"""Who serves a user — and therefore what a link is allowed to say.

Why this module exists: a config can point at the panel itself or at a node, and
the client will dial exactly what the link says. Two shapes of "the config times
out" were traced to the panel building a link it had no evidence for:

1. **A node that never received the user.** The sync pushes users with a token;
   when that push fails (wrong/rotated token, node replaced, node deleted) the
   panel used to advertise the node anyway. The client connects, the node has no
   such user, and the client waits for its own timeout.
2. **A port that is not published by the target.** A Railway-style edge accepts
   TCP on every port of its IP and answers nothing (measured on the live
   service), and a VPS node's raw ports can be firewalled shut. The panel used to
   write those ports into links because an admin *had* typed a host:port.

So the decision is made once, here, from evidence the panel actually has: the
node is enabled, it registered an address, its last sync really included this
user, and the port the link would carry answers a TCP connect. When any of that
is false the link falls back to the panel itself — which serves every user (see
`nodes.local_users`) — so the config keeps working and the admin is told why
through the link warnings.

Nothing here talks to the network. `main._node_status` does the probes and
records what it measured; this module only reads those measurements, which keeps
link building synchronous, cheap and testable.
"""
import json
import time
from urllib.parse import urlsplit

from . import config, db

#: How long a measurement stays trustworthy. Past this it is treated as unknown
#: (unknown is never worse than what the panel did before this module existed).
EDGE_TTL = 900.0
RAW_TTL = 900.0
#: A node whose users have not been pushed for this long is not trusted to have
#: the current user list: the sync loop runs every NODE_SYNC_INTERVAL seconds.
SYNC_TTL = 900.0

#: Hosts that are known to be an HTTP-only edge: a Railway public domain is the
#: service's HTTPS edge, and its raw ports answer nothing (measured).
_EDGE_HOST_SUFFIXES = (".up.railway.app", ".railway.app", ".railway.internal")


# ------------------------------------------------------------------ addresses
def host_port(node) -> tuple:
    """(host, port) parsed out of a node's stored address.

    The address is stored with a scheme ("https://203.0.113.9:8443"), so parsing
    it as a URL is the only reliable way: counting colons gets the scheme's colon
    wrong and silently disables every decision made from it.
    """
    raw = ((node or {}).get("address") or "").strip()
    if not raw:
        return "", None
    if "://" not in raw:
        raw = "//" + raw
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return "", None
    return (parts.hostname or ""), port


def link_host(node) -> str:
    """The bare host of a node's address (its stored port is dropped)."""
    return host_port(node)[0]


def address_port(node):
    """The port the admin wrote in the node's address, if any."""
    return host_port(node)[1]


def is_edge_only(host: str) -> bool:
    """True when ``host`` is (almost certainly) an HTTP-only edge."""
    h = (host or "").strip().lower()
    if not h:
        return False
    return any(h == sfx.lstrip(".") or h.endswith(sfx) for sfx in _EDGE_HOST_SUFFIXES)


def is_ip_literal(host: str) -> bool:
    """A TLS link cannot be validated against a bare IP (no certificate name)."""
    h = (host or "").strip().strip("[]")
    if not h:
        return False
    if ":" in h:  # IPv6
        return True
    parts = h.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def raw_port(protocol: str, security: str) -> int:
    """The fleet port for a raw-TCP transport, per protocol and security.

    Every deployment runs the same image and therefore the same inbound map, so
    a node's raw port is this number on that node's host — *not* whatever port
    the admin typed in the node's address (that one is the node's HTTP edge).
    """
    p = (protocol or "vless").lower()
    s = (security or "none").lower()
    if p == "vless":
        return {
            "none": config.XRAY_TCP_VLESS_PORT,
            "tls": config.XRAY_TCP_VLESS_TLS_PORT,
            "reality": config.XRAY_TCP_VLESS_REALITY_PORT,
        }.get(s, config.XRAY_TCP_VLESS_PORT)
    if p == "vmess":
        return config.XRAY_TCP_VMESS_TLS_PORT if s == "tls" else config.XRAY_TCP_VMESS_PORT
    if p == "trojan":
        return config.XRAY_TCP_TROJAN_PORT
    return config.XRAY_TCP_VLESS_PORT


def is_raw_transport(transport: str, security: str) -> bool:
    """True for the configs that need a dedicated TCP port of their own."""
    t = (transport or "").strip().lower()
    s = (security or "").strip().lower()
    return t == "tcp" or s == "reality"


# ------------------------------------------------------------------ readings
def _meta_json(key: str) -> dict:
    raw = db.get_meta(key)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fresh(data: dict, ttl: float) -> bool:
    try:
        at = float(data.get("at") or 0)
    except (TypeError, ValueError):
        return False
    return bool(at) and (time.time() - at) <= ttl


def measured_edge(node) -> dict:
    """What the panel measured for a node's HTTP edge.

    ``{"scheme": "https"|"http", "port": int, "at": ts}`` — written by
    ``main._node_status`` from the probe that actually got an answer, so the link
    carries the port that answered instead of a guess.
    """
    data = _meta_json(f"node_edge:{node['id']}")
    if not _fresh(data, EDGE_TTL):
        return {}
    return data


def edge_port(node) -> int:
    """The port a link to this node's HTTP edge should carry."""
    measured = measured_edge(node)
    if measured.get("port"):
        return int(measured["port"])
    return address_port(node) or 443


def edge_scheme(node) -> str:
    measured = measured_edge(node)
    scheme = str(measured.get("scheme") or "").lower()
    if scheme in ("http", "https"):
        return scheme
    return "https"


def raw_state(node_id: int, port: int):
    """True/False when measured, None when unknown (never measured / stale)."""
    data = _meta_json(f"node_raw:{node_id}")
    if not _fresh(data, RAW_TTL):
        return None
    value = (data.get("open") or {}).get(str(port))
    return None if value is None else bool(value)


def raw_report(node_id: int) -> dict:
    """Stored port→reachable map (empty when the panel never measured it)."""
    data = _meta_json(f"node_raw:{node_id}")
    if not data:
        return {}
    return {str(k): bool(v) for k, v in (data.get("open") or {}).items()}


def record_raw_probe(node_id: int, open_ports: dict):
    """Store which raw ports answered a TCP connect on this node."""
    db.set_meta(f"node_raw:{node_id}", json.dumps({
        "open": {str(k): bool(v) for k, v in open_ports.items()},
        "at": time.time(),
    }))


def record_edge_probe(node_id: int, scheme: str, port: int):
    """Store which (scheme, port) the node's own HTTP probe answered on."""
    if not scheme or not port:
        return
    db.set_meta(f"node_edge:{node_id}", json.dumps({
        "scheme": scheme, "port": int(port), "at": time.time(),
    }))


def record_latency(node_id: int, ms, online: bool):
    """Latency + liveness snapshot used by the automatic node pick."""
    db.set_meta(f"node_latency:{node_id}", json.dumps(
        {"ms": ms, "online": bool(online), "at": time.time()}))


def latency(node_id: int):
    """(latency_ms, online) as last measured; None when never measured."""
    data = _meta_json(f"node_latency:{node_id}")
    if not data or not _fresh(data, SYNC_TTL):
        return None
    return data.get("ms"), bool(data.get("online"))


# ------------------------------------------------------------------ sync state
def record_sync(node_id: int, ok: bool, uids=None, err: str = ""):
    """Remember the outcome of a sync push, including *who* the node now has.

    The uid set is what makes "this node has this user" a fact instead of a
    hope: it is written only when the node answered 200 to the push.
    """
    db.set_meta(f"node_sync_ok:{node_id}", "1" if ok else "0")
    db.set_meta(f"node_sync_at:{node_id}", str(time.time()))
    db.set_meta(f"node_sync_err:{node_id}", (err or "")[:200])
    if ok and uids is not None:
        db.set_meta(f"node_sync_uids:{node_id}", json.dumps(sorted(uids)))


def sync_state(node_id: int) -> dict:
    """``{"ok": bool|None, "at": float, "err": str, "uids": set|None}``."""
    raw_ok = db.get_meta(f"node_sync_ok:{node_id}")
    try:
        at = float(db.get_meta(f"node_sync_at:{node_id}") or 0)
    except (TypeError, ValueError):
        at = 0.0
    uids = None
    stored = db.get_meta(f"node_sync_uids:{node_id}")
    if stored:
        try:
            parsed = json.loads(stored)
            if isinstance(parsed, list):
                uids = set(str(x) for x in parsed)
        except (ValueError, TypeError):
            uids = None
    return {
        "ok": None if raw_ok is None else raw_ok == "1",
        "at": at,
        "err": db.get_meta(f"node_sync_err:{node_id}") or "",
        "uids": uids,
    }


def node_has_user(node, uid: str) -> tuple:
    """(bool, reason) — is this user really being served by that node right now?"""
    st = sync_state(node["id"])
    if st["ok"] is None:
        return False, "never-synced"
    if not st["ok"]:
        return False, "sync-failed"
    if st["at"] and (time.time() - st["at"]) > SYNC_TTL:
        return False, "sync-stale"
    if uid and st["uids"] is not None and uid not in st["uids"]:
        return False, "user-not-synced"
    return True, "ok"


def has_credential(node) -> bool:
    from . import nodes as nodesync      # local import: nodes imports this module
    return bool((node or {}).get("token")) or bool(nodesync.panel_secret(create=False))


def raw_allowed(node, protocol: str, security: str) -> tuple:
    """(bool, port, reason) — may a raw transport be advertised on this node?

    Unknown counts as yes: the panel keeps the fleet's standard port map for a
    node it has never managed to probe, which is exactly what it did before this
    module existed. Only a *measured* refusal (connect refused or timed out)
    downgrades the link.
    """
    port = raw_port(protocol, security)
    host = link_host(node)
    if is_edge_only(host):
        return False, port, "edge-only-host"
    state = raw_state(node["id"], port)
    if state is False:
        return False, port, f"port-{port}-closed"
    return True, port, "ok"


# ------------------------------------------------------------------ decisions
def _enabled_remote_nodes() -> list:
    return [n for n in db.list_nodes()
            if not n.get("is_local") and n.get("enabled") and (n.get("address") or "").strip()]


def auto_node():
    """Fastest node that is online *and* currently trusted to serve.

    The previous version picked the lowest measured latency and ignored whether
    the node was online, synced or even enabled — a user on "auto" could be sent
    to a node that had none of their config.
    """
    best = None
    for node in _enabled_remote_nodes():
        measured = latency(node["id"])
        if not measured or not measured[1]:
            continue
        ok, _reason = node_has_user(node, "")
        if not ok:
            continue
        if best is None or (measured[0] or 10 ** 9) < (best[0] or 10 ** 9):
            best = (measured[0], node)
    return best[1] if best else None


def intended_node(u: dict):
    """The node a user is *meant* to be served by (before any verification)."""
    if config.IS_NODE:
        return None
    from . import nodes as nodesync  # local import: nodes imports this module
    nid = nodesync.user_node_id(u)
    if nid == 0:
        return auto_node()
    if not u.get("node_id"):
        return None
    node = db.get_node(nid)
    if node and node.get("is_local"):
        return None          # the panel itself: not a remote target
    return node


def serving(u: dict) -> dict:
    """Where this user's link must point, and why.

    ``{"target": "panel"|"node", "node": node|None, "transport": t, "security": s,
       "warnings": [...], "reasons": [...]}``

    ``transport``/``security`` are what the link must advertise: they differ from
    the stored row whenever the chosen target cannot carry the stored transport
    (a raw config on an HTTP edge, or on a node whose raw port is shut).
    """
    stored_t = (u.get("transport") or "").lower()
    stored_s = (u.get("security") or "tls").lower()
    node = intended_node(u)
    warnings: list = []

    if node is None:
        return _panel_target(u, stored_t, stored_s, warnings, reason="no-node")

    if not node.get("enabled"):
        warnings.append(_why(node, "disabled"))
        return _panel_target(u, stored_t, stored_s, warnings, reason="node-disabled")
    if not has_credential(node):
        warnings.append(_why(node, "no-credential"))
        return _panel_target(u, stored_t, stored_s, warnings, reason="node-no-credential")

    has_user, reason = node_has_user(node, u.get("uid") or "")
    if not has_user:
        warnings.append(_why(node, reason))
        return _panel_target(u, stored_t, stored_s, warnings, reason=f"node-{reason}")

    # The node really is serving this user; the remaining question is which
    # transport the link may carry to it.
    if is_raw_transport(stored_t, stored_s):
        allowed, port, why = raw_allowed(node, u.get("protocol") or "vless", stored_s)
        if allowed:
            return {"target": "node", "node": node, "transport": "tcp",
                    "security": stored_s, "raw_port": port,
                    "warnings": warnings, "reasons": ["node-raw-ok"]}
        warnings.append(
            f"{node.get('name') or 'node'}: {why} — "
            f"the raw port is not reachable on this node, so the link uses its "
            f"HTTPS edge instead (XHTTP/TLS)."
        )
        if edge_scheme(node) != "https" or is_ip_literal(link_host(node)):
            warnings.append(
                f"{node.get('name') or 'node'}: no usable TLS edge either "
                f"({link_host(node) or 'no address'}); the config is served by the panel."
            )
            return _panel_target(u, stored_t, stored_s, warnings, reason="node-no-tls-edge")
        return {"target": "node", "node": node, "transport": "xhttp", "security": "tls",
                "warnings": warnings, "reasons": ["node-raw-mapped"]}

    if str(stored_s).lower() == "tls" and edge_scheme(node) == "http":
        warnings.append(
            f"{node.get('name') or 'node'}: its edge answers over plain http, so a TLS "
            f"link cannot complete — put TLS in front of the node or use a raw transport there."
        )
    if str(stored_s).lower() == "tls" and is_ip_literal(link_host(node)):
        warnings.append(
            f"{node.get('name') or 'node'}: the address is an IP literal, so a TLS "
            f"certificate has no name to match — use the node's domain."
        )
    return {"target": "node", "node": node, "transport": stored_t, "security": stored_s,
            "raw_port": None, "warnings": warnings, "reasons": ["node-ok"]}


def _why(node, reason: str) -> str:
    name = node.get("name") or "node"
    explain = {
        "disabled": "the node is disabled (maintenance) — the config is served by the panel",
        "no-credential": "the node has no sync token, so it never received its users — "
                         "the config is served by the panel",
        "never-synced": "no successful sync to this node yet — the config is served by the panel",
        "sync-failed": "the last sync to this node failed, so it does not have this user — "
                       "the config is served by the panel",
        "sync-stale": "the node has not been synced recently — the config is served by the panel",
        "user-not-synced": "this user was not part of the last successful sync to this node — "
                           "the config is served by the panel",
    }.get(reason, f"{reason} — the config is served by the panel")
    return f"{name}: {explain}"


def _panel_target(u: dict, stored_t: str, stored_s: str, warnings: list, reason: str) -> dict:
    """The panel's own edge holds the link — see main._edge_link_view for the map."""
    if config.tcp_proxy() and is_raw_transport(stored_t, stored_s):
        # A platform TCP proxy is the one route a raw port has on an HTTP-only
        # deployment — but it forwards to a single container port, so it may only
        # advertise configs that need *that* port. Handing it to any other raw
        # transport points the client at an inbound its handshake does not belong
        # to, which is a guaranteed timeout.
        proxy_host, proxy_port = config.tcp_proxy()
        wanted = raw_port(u.get("protocol") or "vless", stored_s)
        if config.tcp_proxy_carries(wanted):
            return {"target": "panel", "node": None, "transport": "tcp", "security": stored_s,
                    "raw_port": proxy_port, "warnings": warnings,
                    "reasons": [reason, "tcp-proxy"]}
        carries = getattr(config, "TCP_APP_PORT", 0) or "unknown"
        warnings.append(
            f"the platform TCP proxy ({proxy_host}:{proxy_port}) forwards to container port "
            f"{carries}, but this config needs port {wanted}: the link goes over the HTTPS edge "
            f"instead ({'xhttp' if (u.get('protocol') or 'vless') in ('vless', 'vmess') else 'ws'}"
            f"+TLS), which always connects. Move the TCP proxy to {wanted} to keep it raw."
        )
    mapped_t, mapped_s, extra = edge_view(stored_t, stored_s, u.get("protocol") or "vless")
    warnings.extend(extra)
    return {"target": "panel", "node": None, "transport": mapped_t, "security": mapped_s,
            "raw_port": None, "warnings": warnings, "reasons": [reason]}


def edge_view(transport: str, security: str, protocol: str) -> tuple:
    """(transport, security, warnings) for a link the panel's HTTP edge must carry.

    A raw transport cannot cross an HTTP edge at all; XHTTP/TLS is the closest
    thing to a "raw" feel that still works (a normal POST stream, and it survives
    DPI better than WS).
    """
    t = (transport or "ws").lower()
    s = (security or "tls").lower()
    warnings: list = []
    if t in config.EDGE_TRANSPORTS and s in ("tls", "none"):
        return t, s, warnings
    if s == "reality" and t == "tcp":
        mapped_t, mapped_s = ("xhttp" if protocol in ("vless", "vmess") else "ws"), "tls"
    elif t not in config.EDGE_TRANSPORTS:
        mapped_t = "xhttp" if protocol in ("vless", "vmess") else "ws"
        mapped_s = "tls"
    else:
        return t, s, warnings
    warnings.append(
        f"{t or 'raw'}+{s} is unreachable through the HTTP edge; the link was mapped to "
        f"{mapped_t}+{mapped_s} on the edge port so it can actually connect "
        f"(the stored config is unchanged)."
    )
    return mapped_t, mapped_s, warnings
