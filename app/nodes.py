"""Multi-node coordination.

Two roles share one codebase (see config.ROLE):

- **main**: owns the database and the dashboard. It pushes each user's config
  to the node the user is assigned to, so that node runs Xray for them.
- **node**: runs Xray for the users the main panel pushed to it, and reports
  their traffic usage back to the main panel.

Authentication is either a shared secret (TITAN_NODE_SECRET, legacy/simple) or
a per-node token issued by the main panel's "Quick node setup" wizard
(TITAN_NODE_TOKEN on the node side). With a token, a node can self-register:
it reports its own public URL to the main panel, so the admin never has to copy
domains around or keep a shared secret in sync.
"""
import hashlib
import json
import logging
import os
import secrets
import time

import httpx

from . import APP_VERSION, config, db, routing

log = logging.getLogger("titan.nodes")

# fields a node needs to build Xray inbounds for a user
SYNC_FIELDS = (
    "uuid", "name", "enabled", "protocol", "transport", "security",
    "fingerprint", "alpn", "public_key", "short_id", "spider_x",
    "max_devices", "quota_bytes", "expire_at", "max_requests", "avatar",
    "ss_method", "wg_ip", "wg_pub",
)


def user_node_id(u: dict) -> int:
    """A user's assigned node id; 0 = auto (nearest online node)."""
    v = u.get("node_id")
    try:
        return int(v) if v not in (None, "") else 1
    except (TypeError, ValueError):
        return 1


def local_users() -> list[dict]:
    """Users whose traffic this process must serve: all of them.

    A node serves everyone the panel pushed to it. The *main panel* used to serve
    only the users assigned to its local node, which made a link and the server
    behind it disagree: a user whose node was disabled, never registered, or whose
    sync had failed got a link pointing at that node while the panel refused to
    serve them — the client connected and waited for its own timeout (traced in
    the field). See ``routing`` for the link-side half of the rule.

    So the panel keeps *every* user ready: the link still points at the node when
    the node is verifiably serving that user, and it falls back to the panel the
    moment it is not. Serving both costs one config entry per user and removes a
    whole class of "config times out".
    """
    return db.list_users()


def _matches(a: str, b: str) -> bool:
    return bool(b) and secrets.compare_digest(str(a or ""), str(b))


def panel_secret(create: bool = True) -> str:
    """The credential this panel uses to talk to its nodes.

    ``TITAN_NODE_SECRET`` when it is set. A panel that has none mints one and
    keeps it in its own database, so the zero-variable flow works end to end: the
    panel hands the minted secret to every node it claims over the node's own
    address, and those nodes accept its pushes from then on. Nothing else in the
    fleet needs to know the value, and nothing has to be typed anywhere.
    """
    env = str(config.NODE_SECRET or "").strip()
    if env:
        return env
    stored = str(db.get_meta("panel_secret") or "").strip()
    if stored or not create:
        return stored
    fresh = secrets.token_urlsafe(24)
    db.set_meta("panel_secret", fresh)
    log.warning("no TITAN_NODE_SECRET set — minted a fleet secret for this panel (%s…) "
                "and will hand it to every node added by domain", fresh[:8])
    return fresh


def node_credential() -> str:
    """The credential this instance would accept a push with ("" = none yet).

    Env first (``TITAN_NODE_SECRET`` / ``TITAN_NODE_TOKEN``), then whatever a
    panel stored through ``/api/node/bootstrap``. A node deployed with no
    variables at all has none, which is exactly the state the panel can fix
    remotely instead of asking the admin to type variables into the service.
    """
    return str(config.NODE_SECRET or config.NODE_TOKEN or db.get_meta("node_secret") or "")


def node_panel_url() -> str:
    """The panel this node belongs to (env, or the URL stored on bootstrap)."""
    return str(config.MAIN_URL or db.get_meta("node_panel_url") or "").rstrip("/")


def store_node_credential(secret: str, panel_url: str = "") -> None:
    """Persist a credential handed over by the panel (bootstrap)."""
    db.set_meta("node_secret", secret)
    if panel_url:
        db.set_meta("node_panel_url", panel_url.rstrip("/"))
    db.set_meta("node_claimed_at", str(time.time()))


def identity() -> dict:
    """Public identity card of this instance — no secret, ever.

    A panel that was handed only a project domain needs to know three things
    before it can usefully add this instance: that it really is TiTaN, where it
    is, and whether it would accept a push. The first two are already visible
    from outside (the URL answers, the edge port is probeable); the third is a
    boolean. Nothing here is worth hiding, and hiding it would only push the
    admin back to typing variables.
    """
    local = db.local_node() or {}
    cred = node_credential()
    kind = ("shared" if config.NODE_SECRET else
            "claimed" if db.get_meta("node_secret") else
            "token" if config.NODE_TOKEN else
            "minted" if db.get_meta("panel_secret") else "")
    edge_scheme, edge_port = routing_host_port(local)
    return {
        "app": "titan",
        "version": APP_VERSION,
        "role": "node" if config.IS_NODE else "main",
        "name": _own_name(local),
        "city": local.get("city") or "",
        "country": local.get("country") or "",
        "country_code": (local.get("country_code") or "").upper(),
        "flag": local.get("flag") or "🌐",
        "url": config.NODE_URL or "",
        "edge": {"scheme": edge_scheme, "port": edge_port},
        "raw_ports": routing.raw_report(1) if config.IS_NODE else {},
        "credential": kind,                 # "" = this node has nothing yet
        "accepts_bootstrap": not cred,
        "claimed_at": float(db.get_meta("node_claimed_at") or 0) or None,
        "panel_url": node_panel_url(),
        "users": len(db.list_users()),
    }


def _own_name(local: dict) -> str:
    """A name the admin can recognise in the panel.

    The local row is seeded as "سرور اصلی" on every boot, so that generic label
    is never what a freshly added node should be called: an explicit
    ``TITAN_NODE_NAME`` wins, then the Railway service name, then a name built
    from the detected city, and only then the address.
    """
    explicit = str(getattr(config, "NODE_NAME", "") or "").strip()
    if explicit:
        return explicit[:64]
    service = (os.environ.get("RAILWAY_SERVICE_NAME") or "").strip()
    if service:
        return service[:64]
    stored = (local.get("name") or "").strip()
    if stored and stored not in ("سرور اصلی", "TiTaN node"):
        return stored[:64]
    city = (local.get("city") or "").strip()
    if city and city not in ("—", "Unknown"):
        return f"TiTaN · {city}"[:64]
    host = config.NODE_URL.replace("https://", "").replace("http://", "").split("/")[0]
    return (host or ("TiTaN node" if config.IS_NODE else "TiTaN panel"))[:64]


def routing_host_port(node: dict) -> tuple:
    """Edge this instance answers on, tolerating an empty/partial node row."""
    try:
        from . import routing as _r
        return _r.edge_scheme(node), _r.edge_port(node)
    except Exception:  # noqa: BLE001
        return ("https" if config.EDGE_HTTP_ONLY is False else "http"), config.PUBLIC_PORT


def secret_valid_for_node(secret: str) -> bool:
    """Node side: accept a sync push from the main panel.

    The stored credential counts too: a node that was claimed through
    ``/api/node/bootstrap`` holds the secret in its database, not in its env.
    """
    if _matches(secret, config.NODE_SECRET):
        return True
    if _matches(secret, config.NODE_TOKEN):
        return True
    return _matches(secret, db.get_meta("node_secret"))


def secret_valid_for_main(secret: str) -> bool:
    """Main side: accept a report/registration from a node."""
    if _matches(secret, config.NODE_SECRET):
        return True
    if _matches(secret, panel_secret(create=False)):
        return True
    return db.get_node_by_token(secret) is not None


def user_sync_payload(u: dict) -> dict:
    """Trim a user dict down to what a node needs."""
    out = {k: u.get(k) for k in ("uid",) + SYNC_FIELDS}
    out["uid"] = u["uid"]
    return out


def _node_url(node: dict) -> str | None:
    addr = (node.get("address") or "").strip()
    if not addr:
        return None
    if not addr.startswith(("http://", "https://")):
        addr = "https://" + addr
    return addr.rstrip("/")


def _sync_secrets(node: dict) -> list[tuple[str, str]]:
    """Credentials to present to a node, best first — [(secret, kind)].

    A node added by hand in the dashboard is issued a per-node token by the
    panel, but a node deployed with only ``TITAN_NODE_SECRET`` knows the shared
    secret and rejects that token (its own ``secret_valid_for_node`` accepts the
    shared secret or its own configured token, nothing else). The panel used to
    send exactly one credential, get HTTP 401 and give up — which is why "add a
    node, assign a user" left the config on the main domain: the node never
    received the user, so the link fell back to the panel.

    Both are tried here, and whichever worked is remembered
    (``node_secret_kind:`` meta) and offered first next time.
    """
    token = (node.get("token") or "").strip()
    shared = panel_secret(create=False).strip()
    pairs = [("token", token), ("shared", shared)]
    if db.get_meta(f"node_secret_kind:{node['id']}") == "shared":
        pairs.reverse()
    return [(secret, kind) for kind, secret in pairs if secret]


def _payload_hash(users: list[dict]) -> str:
    canon = json.dumps(
        [{k: u.get(k) for k in ("uid",) + SYNC_FIELDS} for u in users],
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canon.encode()).hexdigest()


def _reality_payload() -> dict | None:
    """Reality keypair to hand to nodes so their Reality inbound matches links."""
    priv = db.get_meta("reality_priv")
    if not priv:
        return None
    return {
        "priv": priv,
        "pub": db.get_meta("reality_pub") or "",
        "sid": db.get_meta("reality_sid") or "",
    }


async def sync_node(node: dict, users: list[dict], timeout: float = 8.0) -> bool:
    """Push a node's full user list to it. Returns True on success.

    The outcome (and, on success, the exact uid set the node now has) is recorded
    so link building can tell "this node really has this user" from "we hoped it
    did" — that difference is the whole reason a node config used to time out.

    Every credential the node might accept is tried (see ``_sync_secrets``); the
    first one that answers 200 is remembered for next time.
    """
    url = _node_url(node)
    candidates = _sync_secrets(node)
    if not url or not candidates:
        routing.record_sync(node["id"], False, err="no-address-or-credential")
        return False
    uids = [u["uid"] for u in users]
    body = {
        "users": [user_sync_payload(u) for u in users],
        "reality": _reality_payload(),
    }
    last_err = ""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cl:
            for secret, kind in candidates:
                r = await cl.post(f"{url}/api/node/sync", json={"secret": secret, **body})
                if r.status_code == 200:
                    db.set_meta(f"node_secret_kind:{node['id']}", kind)
                    routing.record_sync(node["id"], True, uids=uids)
                    return True
                last_err = f"HTTP {r.status_code}"
                log.warning("node sync failed for %s (%s credential): HTTP %s",
                            url, kind, r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("node sync error for %s: %s", url, e)
        last_err = type(e).__name__
    # 401/403 with every credential means the node does not know this panel: say
    # so instead of a bare HTTP code, because that is what the admin must fix.
    if last_err.startswith("HTTP 40"):
        last_err += " (credential rejected — set TITAN_NODE_SECRET on the node, or "\
                    "deploy it with the token from the node's setup command)"
    routing.record_sync(node["id"], False, err=last_err)
    return False


def node_user_list(node: dict) -> list[dict]:
    """The users this node must run: its own plus the auto-routed (node_id=0)."""
    users = db.list_users()
    return sorted([u for u in users if user_node_id(u) in (node["id"], 0)],
                  key=lambda x: x["uid"])


async def sync_one(node_id: int, timeout: float = 6.0) -> bool:
    """Push one node right now, and return whether it took the users.

    Called when the admin assigns a node (to a user or while creating the node):
    the response of that very request then carries a link that already points at
    a node which has the user, instead of the panel link the admin used to copy
    while the background sync was still in flight.
    """
    node = db.get_node(node_id)
    if not node or node.get("is_local") or not node.get("enabled"):
        return False
    node_users = node_user_list(node)
    ok = await sync_node(node, node_users, timeout=timeout)
    if ok:
        db.set_meta(f"node_sync_hash:{node_id}", _payload_hash(node_users))
    return ok


async def sync_all() -> dict[str, bool]:
    """Push users to every remote node (main role). Returns {node_name: ok}.

    A user assigned to node N goes to node N; a user with node_id=0 ("auto")
    goes to *every* enabled remote node so whichever is fastest can serve it.
    """
    results: dict[str, bool] = {}
    users = db.list_users()
    for node in db.list_nodes():
        if node.get("is_local") or not node.get("enabled"):
            continue
        if not _sync_secrets(node):
            routing.record_sync(node["id"], False, err="no-credential")
            continue
        node_users = sorted(
            [u for u in users if user_node_id(u) in (node["id"], 0)],
            key=lambda x: x["uid"],
        )  # same rule as node_user_list(), computed from the shared snapshot
        # Skip a re-push only while the node still counts as freshly verified.
        #
        # The uid set the panel pushed is only trusted for `routing.SYNC_TTL`; the
        # payload hash alone used to be enough to skip the push, so an idle fleet
        # (nobody edited a user for 15 minutes) stopped refreshing that stamp and
        # every node link silently fell back to the panel. Re-pushing an unchanged
        # payload at least every SYNC_TTL/3 keeps the stamp honest, and if the node
        # is down the push fails — which is exactly the signal the link needs.
        h = _payload_hash(node_users)
        st = routing.sync_state(node["id"])
        still_fresh = bool(
            st["ok"] is True and st["at"] and (time.time() - st["at"]) < routing.SYNC_TTL / 3
        )
        if still_fresh and db.get_meta(f"node_sync_hash:{node['id']}") == h:
            results[node["name"]] = True
            continue
        if await sync_node(node, node_users):
            db.set_meta(f"node_sync_hash:{node['id']}", h)
            results[node["name"]] = True
        else:
            results[node["name"]] = False
    return results


async def report_usage(usage: dict[str, dict], timeout: float = 8.0) -> bool:
    """Send per-user traffic deltas back to the main panel (node role)."""
    secret = node_credential()
    main_url = node_panel_url()
    if not main_url or not secret or not usage:
        return False
    payload = {"secret": secret, "usage": usage}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cl:
            r = await cl.post(f"{main_url}/api/node/usage", json=payload)
            return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        log.warning("usage report failed: %s", e)
        return False


async def register(main_url: str, token: str, url: str, timeout: float = 8.0) -> bool:
    """Node side: self-register with the main panel using its token + URL."""
    if not main_url or not token or not url:
        return False
    payload = {"token": token, "url": url}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cl:
            r = await cl.post(f"{main_url}/api/node/register", json=payload)
            return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        log.warning("node register failed: %s", e)
        return False
