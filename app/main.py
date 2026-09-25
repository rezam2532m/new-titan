"""TiTaN — single-service multi-protocol proxy panel.

FastAPI app: admin UI + REST API + subscription endpoints. Xray-core does the
actual proxying; nginx fronts both. SQLite for storage.
"""
import asyncio
import functools
import logging
import base64
import gzip
import io
import json
import math
import os
import re
import secrets
import threading
import time
import uuid as uuid_lib
from urllib.parse import quote
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import ipaddress
import psutil
import qrcode
from PIL import Image as PILImage
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import APP_NAME, APP_VERSION, config, db, security, state, xray
from . import nodes as nodesync
from . import reality
from . import routing
from . import tasks as bg
from . import wg
from .colo_map import describe_colo
from .geo import detect_location, flag_from_code
from .links import build_links, subscription_text, volume_text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

DOH_PRIMARY = "https://1.1.1.1/dns-query"
DOH_SECONDARY = "https://8.8.8.8/dns-query"
doh_client = httpx.AsyncClient(timeout=6.0, follow_redirects=True)


# Idempotency for config creation (double-click / network retry after “failed to fetch”).
# Frontend now sends a per-wizard client_nonce; fallback is (name, node_id, protocol).
_recent_creates: dict[str, tuple[float, str]] = {}
_recent_creates_lock = threading.Lock()
_IDEMPOTENCY_TTL = 10.0  # seconds

log = logging.getLogger("titan.main")


# ------------------------------------------------------------------ lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # config._usable_data_dir() already made this writable (or replaced it with a
    # temp dir and said so loudly), so a bad Volume cannot crash the boot.
    os.makedirs(config.DATA_DIR, exist_ok=True)
    if not config.IS_NODE:
        # generate the Reality keypair once (no-op without the Xray binary)
        try:
            reality.ensure_reality_keys()
        except Exception:  # noqa: BLE001
            pass
    try:
        xray.write_xray_config()
        xray.restart_xray()
    except Exception:  # noqa: BLE001
        pass
    # WireGuard (optional): generate this node's keypair + start the server.
    try:
        wg.ensure_keys()
        wg.restart()
    except Exception:  # noqa: BLE001
        pass
    bg.start_background_tasks(app)
    yield
    for t in app.state.titan_tasks:
        t.cancel()
    await doh_client.aclose()


_DOCS_ON = os.environ.get("TITAN_DOCS", "").strip().lower() in ("1", "true", "yes")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
    # Swagger/ReOpenAPI enumerate the whole attack surface; keep them off unless
    # a developer explicitly opts in with TITAN_DOCS=1.
    docs_url="/docs" if _DOCS_ON else None,
    redoc_url="/redoc" if _DOCS_ON else None,
    openapi_url="/openapi.json" if _DOCS_ON else None,
)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Auth is a cookie, so every state-changing endpoint is a CSRF target. JSON
# endpoints are accidentally shielded by the CORS preflight (they call
# request.json(), so a cross-site form cannot reach them) but multipart ones
# like POST /api/gallery are not — hence an explicit Origin check.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Endpoints a browser cannot and must not be the one driving:
#  - /sub/* and /status/* are dialed by VPN clients (no cookie involved)
#  - /api/node/* is service-to-service (authenticated by node token)
#  - /dns-query is a DoH oracle used by Xray clients
_CSRF_EXEMPT_PREFIXES = ("/sub/", "/api/node/", "/dns-query", "/status/")


def _allowed_origins(request: Request) -> set[str]:
    hosts = {request.headers.get("host", "").strip()}
    pd = (db.get_settings().get("public_domain") or "").strip()
    if pd:
        hosts.add(pd.split("//")[-1].strip("/"))
    if _TRUST_PROXY_HEADERS:
        xfh = request.headers.get("x-forwarded-host", "").strip()
        if xfh:
            hosts.add(xfh.split(",")[-1].strip())
    out: set[str] = set()
    for h in hosts:
        if h:
            out |= {f"https://{h}", f"http://{h}"}
    return out


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    if request.method not in _SAFE_METHODS and not request.url.path.startswith(_CSRF_EXEMPT_PREFIXES):
        origin = (request.headers.get("origin") or "").strip()
        referer = (request.headers.get("referer") or "").strip()
        source = origin or referer
        if source:
            allowed = _allowed_origins(request)
            # A cross-site page CAN send this request; the response is unreadable
            # without CORS, but the *write* still happens -> reject it outright.
            root = "/".join(source.split("/")[:3])
            if root.rstrip("/") not in {a.rstrip("/") for a in allowed}:
                return JSONResponse(
                    {"detail": "csrf-origin-rejected"},
                    status_code=403,
                    headers={"X-CSRF-Reason": "origin-not-allowed"},
                )
    return await call_next(request)


# ------------------------------------------------------------------ helpers
# Only trust X-Forwarded-For / X-Forwarded-Proto when the peer that opened the
# TCP connection is a proxy we control. uvicorn binds to 127.0.0.1 and nginx
# (or the platform edge) always fronts it, so without this check ANY client
# could set an arbitrary XFF and defeat the per-IP login throttle.
# Set TITAN_TRUST_PROXY_HEADERS=1 only when the panel is deployed *behind* a
# reverse proxy that sanitizes XFF (nginx does: it overwrites the value).
_TRUST_PROXY_HEADERS = os.environ.get(
    "TITAN_TRUST_PROXY_HEADERS", "1"
).strip().lower() in ("1", "true", "yes")


def _peer_is_trusted_proxy(peer: str) -> bool:
    """True when `peer` is loopback or a private network (nginx / platform edge)."""
    if not peer:
        return False
    if peer in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        return ipaddress.ip_address(peer).is_private
    except ValueError:
        return False


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if _TRUST_PROXY_HEADERS and _peer_is_trusted_proxy(peer):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # take the left-most entry only when it is a syntactically valid IP
            ip = fwd.split(",")[0].strip()
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return peer or "unknown"
            return ip
    return peer or "unknown"


def _throttle_key(request: Request) -> str:
    """Key for the login brute-force guard: the TCP peer, never a header.

    X-Forwarded-For cannot be used here (10 forged values used to be 10 free
    budgets), and neither can a value a middleware derived from it - that is why
    `uvicorn.run` is called with `proxy_headers=False` in `__main__` and
    `--no-proxy-headers` in scripts/dev_run.sh. Behind nginx every request
    arrives from 127.0.0.1, so the guard is intentionally global: one attacker
    slows down every visitor's guesses, which is the safe direction for a panel
    with a single admin account.
    """
    return request.client.host if request.client else "unknown"


def _usable_public_host(host: str) -> bool:
    """Would a client outside this machine be able to dial this host?

    Loopback and unspecified addresses are the trap: opening the panel over
    127.0.0.1 (a health probe, docker -p, or the raw entry's own port) used to
    bake `@127.0.0.1` into every link, i.e. a config that connects to the
    reader's own laptop.
    """
    if not host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True                      # a normal hostname
    return not (ip.is_loopback or ip.is_unspecified)


def _public_host(request: Request) -> str:
    """Get the public host for link generation, preferring the public_domain setting."""
    settings = db.get_settings()
    override = settings.get("public_domain") or ""
    if override:
        return override.strip().split(":")[0].split("/")[0]
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.hostname
        or ""
    )
    # Handle IPv6 literals like [2001:db8::1]:8000 correctly
    if host.startswith("["):
        if "]" in host:
            host = host.split("]")[0].lstrip("[")
        else:
            host = host.strip("[]")
    else:
        host = host.split(":")[0]
    host = host.strip()
    if not _usable_public_host(host):
        # A platform-provided domain beats a request Host that no client can use.
        platform_host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "",
                               os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")).split("/")[0].strip()
        if _usable_public_host(platform_host):
            return platform_host
    return host


def _link_port(settings: dict) -> int:
    """The port written into client links. 443 behind TLS by default; the admin
    can override it from Settings -> Network (e.g. a non-443 exposed port)."""
    try:
        port = int(settings.get("public_port") or 443)
    except (TypeError, ValueError):
        port = 443
    return port if 1 <= port <= 65535 else 443


def _tcp_port(protocol: str, security: str) -> int:
    """Public port a raw-TCP user should dial, per protocol  and  security."""
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


def _user_endpoint(u: dict, request: Request | None, plan: dict | None = None) -> tuple[str, int]:
    """The (host, port) a user's connection link should point at.

    *Who* serves the user is decided once, in `routing.serving`, which is also
    what `nodes.local_users` serves from — a link and the server behind it can
    therefore never disagree. This function only turns that decision into an
    address:

    - **node**: the node's host. Edge transports use the port the node's own
      probe answered on; raw transports use the fleet's raw port for the
      protocol/security, never the port the admin typed in the node's address
      (that one is the node's HTTP edge).
    - **panel**: this process. Raw transports are reachable only through a
      platform TCP proxy; without one they were already remapped by
      `routing.edge_view`, so the edge port is the correct answer.
    - Hysteria2/WireGuard keep their dedicated UDP ports on both.
    """
    settings = db.get_settings()
    plan = plan or routing.serving(u)
    node = plan.get("node")
    proto = (u.get("protocol") or "vless").lower()
    sec = (u.get("security") or "none").lower()
    transport = (u.get("transport") or "ws").lower()

    # The port follows what the link will *advertise* (plan["transport"]), not
    # what the row stores: a raw row remapped to XHTTP/TLS must carry the edge
    # port, otherwise the client dials a raw port the target never opened.
    advertised_t = (plan.get("transport") or transport).lower()
    advertised_s = (plan.get("security") or sec).lower()
    is_raw = routing.is_raw_transport(advertised_t, advertised_s)
    if plan["target"] == "node" and node:
        host = routing.link_host(node)
        port = routing.edge_port(node)
        if is_raw:
            port = plan.get("raw_port") or routing.raw_port(proto, advertised_s)
    else:
        host = _public_host(request)
        port = _link_port(settings)
        proxy = config.tcp_proxy()
        if proxy and is_raw:
            host, port = proxy

    if proto == "wireguard":
        port = config.WG_PORT
    elif proto == "hysteria2":
        # Hysteria2 always dials the QUIC/UDP port (default 443).
        port = config.XRAY_HY2_PORT
    elif proto == "shadowsocks":
        method = (u.get("ss_method") or settings.get("ss_method")
                  or config.DEFAULT_SS_METHOD).lower()
        port = config.XRAY_SS_2022_PORT if method in config.SS_2022_METHODS else config.XRAY_SS_PORT
    return host, port


#: Hosts that are known to be an HTTP-only edge: a Railway public domain is the
#: service's HTTPS edge, and its raw ports answer nothing (measured).
#: Hosts that are known to be an HTTP-only edge live in `routing` (one place,
#: because both the link and the serving decision depend on them).


def _link_explicit_port(node) -> bool:
    """True when a node's address carries a port the admin set on purpose.

    For a Railway node the port in the address is the container's internal one
    (443 in the deploy log), which is not reachable from outside - only its
    HTTPS edge is. A plain VPS address with a port is the opposite: the port is
    the exposed one, so it must be kept.
    """
    if routing.is_edge_only(routing.link_host(node)):
        return False
    return routing.address_port(node) is not None


def _node_for_user(u: dict):
    """The node whose link a user is *supposed* to use (before verification)."""
    return routing.intended_node(u)


def _target_allows_raw_transport(node_id) -> bool:
    """True when a raw transport can be stored for a user on this node.

    The edge constraint belongs to the *target*, not to the panel: a user sent to
    a VPS node that publishes its raw port may absolutely use Reality, and being
    created from a Railway panel must not take that away. A node whose raw port
    the panel has *measured* closed is excluded, so the row never records a
    transport that cannot connect.
    """
    try:
        nid = db.coerce_node_id(node_id)
    except Exception:  # noqa: BLE001
        return False
    if not nid:
        return False
    node = db.get_node(nid)
    if not node or node.get("is_local"):
        return False
    if not (node.get("address") or "").strip():
        return False
    if routing.is_edge_only(routing.link_host(node)):
        return False
    # Only the Reality/TCP family needs a raw port; ask about the strictest one.
    state = routing.raw_state(node["id"], config.XRAY_TCP_VLESS_REALITY_PORT)
    return state is not False


def _node_host_port(node) -> tuple:
    """(host, port) parsed out of a node's stored address (see routing)."""
    return routing.host_port(node)


def _node_link_host(node) -> str:
    """The bare host of a node's address (its stored port, if any, is dropped)."""
    return routing.link_host(node)


def _edge_only_host(host: str) -> bool:
    """True when ``host`` is (almost certainly) an HTTP-only edge."""
    return routing.is_edge_only(host)


def _edge_link_view(u: dict) -> tuple[dict, list]:
    """(user-as-it-must-be-linked, warnings) as decided by `routing`.

    The stored row is never rewritten: the admin's choice stays in the database,
    and the moment the target can serve it again (a node finishes syncing, a TCP
    proxy appears) the original transport is what gets advertised.
    """
    plan = routing.serving(u)
    return _apply_plan(u, plan), list(plan.get("warnings") or [])


def _links_for(u: dict, request: Request | None) -> dict:
    """Build a user's links (handles WireGuard server-pub resolution).

    The target is decided **once** (`routing.serving`) and used for both the
    address and the transport: recomputing it from the remapped row would let a
    link point at a host that refused the mapped transport.
    """
    u = _ensure_wg_user(u)
    settings = db.get_settings()
    plan = routing.serving(u)
    host, port = _user_endpoint(u, request, plan)
    shown = _apply_plan(u, plan)
    # A panel-wide sni_override (e.g. a CDN domain) only makes sense for the
    # main panel's own TLS. A link that dials a remote node must present that
    # node's SNI, so drop the override there.
    if plan["target"] == "node":
        settings = {**settings, "sni_override": ""}
    server_pub = _wg_server_pub(u, plan) if u.get("protocol") == "wireguard" else ""
    return build_links(host, port, shown, settings, server_pub=server_pub)


#: Which transports each protocol is really served on. The Xray config puts
#: every VLESS user into the WS, XHTTP, HTTPUpgrade and gRPC inbounds alike (and
#: every VMess user into its own four), so *one* user genuinely answers on four
#: configs - which is what makes a per-subscription selection meaningful instead
#: of decorative. The stored transport always comes first: that is the row's main
#: config, the one the copy button hands out.
_SUB_TRANSPORT_ORDER = {
    "vless": ("ws", "xhttp", "httpupgrade", "grpc", "tcp"),
    "vmess": ("ws", "xhttp", "httpupgrade", "grpc", "tcp"),
    "trojan": ("ws", "tcp"),
    "shadowsocks": (),
    "hysteria2": (),
    "wireguard": (),
}


def _sub_transport_choices(u: dict) -> list:
    """Transports this user's subscription may carry, the stored one first."""
    proto = (u.get("protocol") or "vless").lower()
    stored = (u.get("transport") or "ws").lower()
    order = _SUB_TRANSPORT_ORDER.get(proto) or ()
    if not order:
        return [stored]                # single-config protocol (SS / Hy2 / WG)
    allowed = _SERVED_TRANSPORTS.get(proto) or set(order)
    if "tcp" in order and not (db.get_meta("reality_pub") or config.tls_ready()):
        order = tuple(t for t in order if t != "tcp")   # no raw config without keys
    rest = [t for t in order if t in allowed and t != stored]
    return [stored] + rest


def _entry_place(plan: dict) -> dict:
    """{place, city, country_code, flag} for one link — node or this panel."""
    node = plan.get("node") or {}
    if plan.get("target") == "node" and node:
        return {
            "place": node.get("name") or "",
            "city": node.get("city") or "",
            "country_code": (node.get("country_code") or "").lower(),
            "flag": node.get("flag") or "",
        }
    local = db.local_node() or {}
    return {
        "place": local.get("name") or "TiTaN",
        "city": local.get("city") or "",
        "country_code": (local.get("country_code") or "").lower(),
        "flag": local.get("flag") or "",
    }


def _sub_variant(u: dict, transport: str) -> dict:
    """The same user row as it would look if this transport were its stored one."""
    row = dict(u)
    row["transport"] = transport
    if transport == "tcp":
        proto = (row.get("protocol") or "vless").lower()
        # Trojan is TLS-only; VLESS/VMess prefer Reality when the fleet has keys.
        if proto == "trojan":
            row["security"] = "tls"
        elif db.get_meta("reality_pub"):
            row["security"] = "reality"
        else:
            row["security"] = "tls"
    return row


def _sub_entries(u: dict, request: Request | None) -> list:
    """Every config this user's subscription *can* carry, in a stable order.

    Built through the same decision pipeline as the main link (serving -> endpoint
    -> plan), so every entry is a link a client can really connect to. Duplicates
    are dropped: on an HTTP edge the raw TCP entry maps to the same XHTTP/TLS link
    as the XHTTP entry, and offering it twice would only be noise.
    """
    settings = db.get_settings()
    entries: list = []
    seen: set = set()
    wg_pub = ""
    for t in _sub_transport_choices(u):
        row = _sub_variant(u, t)
        plan = routing.serving(row)
        host, port = _user_endpoint(row, request, plan)
        shown = _apply_plan(row, plan)
        if (row.get("protocol") or "") == "wireguard":
            wg_pub = _wg_server_pub(row, plan)
        local = {**settings}
        if plan["target"] == "node":
            local["sni_override"] = ""
        links = build_links(host, port, shown, local, server_pub=wg_pub)
        link = links.get("main") or ""
        if not link or link in seen:
            continue
        seen.add(link)
        adv_t = (plan.get("transport") or t).lower()
        adv_s = (plan.get("security") or "").lower()
        # A protocol with a single config (SS / Hysteria2 / WireGuard) is named
        # after the protocol: its "transport" column is meaningless and showing
        # "WIREGUARD · WS" in the picker would only confuse the admin.
        single = not (_SUB_TRANSPORT_ORDER.get((row.get("protocol") or "").lower()) or ())
        key = (row.get("protocol") or t).lower() if single else t
        label = key.upper() + (f" · {adv_t.upper()}/{adv_s.upper()}" if (adv_t != key and not single) else "")
        entries.append({
            "key": key,
            "protocol": (row.get("protocol") or "").lower(),
            "transport": adv_t,
            "security": adv_s,
            "label": label,
            "link": link,
            "host": host,
            "port": port,
            "target": plan["target"],
            # Where this config physically is: the node's own location, or this
            # panel's. The subscription page shows it as the flag + city column.
            **_entry_place(plan),
        })
    return entries


def _sub_selection(u: dict) -> list:
    """The transports the admin ticked for this user ([] = all of them)."""
    raw = u.get("sub_transports") or ""
    if isinstance(raw, (list, tuple, set)):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    return [x.strip().lower() for x in str(raw).split(",") if x.strip()]


def _sub_links(u: dict, request: Request | None) -> list:
    """Links that go into this user's subscription, honouring the selection."""
    entries = _sub_entries(u, request)
    want = _sub_selection(u)
    if not want:
        return [e["link"] for e in entries]
    picked = [e["link"] for e in entries if e["key"] in want]
    return picked or [e["link"] for e in entries]      # never hand out an empty sub


def _apply_plan(u: dict, plan: dict) -> dict:
    """The row as the client must see it (stored row + the plan's transport)."""
    shown = dict(u)
    shown["transport"] = plan.get("transport") or u.get("transport") or ""
    shown["security"] = plan.get("security") or u.get("security") or "tls"
    if shown.get("flow") == "__inherit__" and shown["transport"] != (u.get("transport") or ""):
        shown["flow"] = ""
    return shown


def _user_is_remote(u: dict) -> bool:
    """True when the link points at a node instead of this process.

    Same decision the link is built from (`routing.serving`), so a user is never
    "remote" for the link and local for the server, or the other way round.
    """
    return routing.serving(u)["target"] == "node"


def _set_session(response: Response, username: str, remember: bool = False):
    token = security.make_token(db.get_secret_key(), {"u": username})
    # "remember me" extends the session; otherwise it stays short-lived.
    max_age = config.SESSION_MAX_AGE * 4 if remember else config.SESSION_MAX_AGE
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # TLS terminated by the platform/nginx
        path="/",
    )


def _current_username(request: Request) -> Optional[str]:
    admin = db.get_admin()
    if not admin:
        return None
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        return None
    # Accept both normal (7d) and "remember me" (28d) tokens
    for max_age in (config.SESSION_MAX_AGE * 4, config.SESSION_MAX_AGE):
        data = security.read_token(db.get_secret_key(), token, max_age)
        if data and data.get("u") == admin["username"]:
            return admin["username"]
    return None


def _require_auth(request: Request) -> str:
    user = _current_username(request)
    if not user:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def _quota_bytes_from_payload(payload: dict) -> int | None:
    """Volume from a request, in whichever unit the panel was asked for.

    `quota_gb` is what the dashboard has always sent; `quota_mb` (a small test
    config, a 500 MB top-up) and the explicit pair `quota` + `quota_unit=mb|gb`
    are accepted too. Returns None when the request said nothing about volume.
    """
    unit = str(payload.get("quota_unit") or "").strip().lower()
    if "quota_mb" in payload and payload.get("quota_mb") is not None:
        raw, factor = payload.get("quota_mb"), 1024 ** 2
    elif "quota_gb" in payload and payload.get("quota_gb") is not None:
        raw, factor = payload.get("quota_gb"), 1024 ** 3
    elif "quota" in payload and payload.get("quota") is not None:
        raw = payload.get("quota")
        factor = 1024 ** 2 if unit in ("mb", "m", "mib") else 1024 ** 3
    else:
        return None
    qstr = str(raw).strip()
    if qstr in ("", "0", "0.0"):
        return 0
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError
    out = round(value * factor)
    if out < 0 or out > (1 << 63) - 1:
        raise ValueError
    return out


def _renewal_reopens_user(before: dict, after: dict) -> bool:
    """True when an update just renewed a user who was cut off for volume.

    "Until it is renewed, no traffic" — and the other half of that sentence is
    that renewing (raising the volume or resetting the usage) brings the config
    straight back instead of leaving the admin to flip the switch by hand.
    """
    used = int(after.get("used_up") or 0) + int(after.get("used_down") or 0)
    quota = int(after.get("quota_bytes") or 0)
    if not quota or used >= quota:
        return False           # still over (or unlimited-but-empty) — stay off
    was_over = int(before.get("quota_bytes") or 0) > 0 and (
        int(before.get("used_up") or 0) + int(before.get("used_down") or 0)
    ) >= int(before.get("quota_bytes") or 0)
    raised = quota > int(before.get("quota_bytes") or 0)
    if after.get("expire_at") and time.time() >= after["expire_at"]:
        return False           # the clock ran out too: renewal means both
    return bool(was_over or raised)


def _user_status(u: dict) -> dict:
    now = time.time()
    used = (u.get("used_up") or 0) + (u.get("used_down") or 0)
    quota = u.get("quota_bytes") or 0
    quota_exceeded = quota > 0 and used >= quota
    expired = bool(u.get("expire_at")) and now >= u["expire_at"]
    enabled = bool(u["enabled"]) and not quota_exceeded and not expired
    return {
        "used": used,
        "quota_bytes": quota,
        "quota_exceeded": quota_exceeded,
        "expired": expired,
        "live_enabled": enabled,
        "active_connections": state.active_count(u["uid"]),
        "days_left": (
            max(0, int((u["expire_at"] - now) // 86400)) if u.get("expire_at") else None
        ),
    }


def _serialize_user(u: dict, with_links: bool = False, request: Request | None = None) -> dict:
    out = {k: v for k, v in u.items() if k != "password_hash"}
    if "allowed_ips" in out and isinstance(out["allowed_ips"], str):
        try:
            out["allowed_ips"] = json.loads(out["allowed_ips"])
        except (json.JSONDecodeError, TypeError):
            out["allowed_ips"] = []
    out["status"] = _user_status(u)
    out["used_gb"] = round(out["status"]["used"] / (1024 ** 3), 3)
    out["quota_gb"] = round((u.get("quota_bytes") or 0) / (1024 ** 3), 3)
    out["quota_mb"] = round((u.get("quota_bytes") or 0) / (1024 ** 2), 1)
    out["avatar_url"] = _resolve_avatar(u.get("avatar") or "")["url"]
    out["sub_transports"] = _sub_selection(u)
    _, edge_warnings = _edge_link_view(u)
    if edge_warnings:
        out["edge_warnings"] = edge_warnings
    if with_links and request is not None:
        links = _links_for(u, request)
        panel_host = _public_host(request)
        out["links"] = links["all"]
        out["main_link"] = links["main"]
        out["sub_url"] = f"https://{panel_host}/sub/{u['uid']}"
        out["status_url"] = f"https://{panel_host}/status/{u['uid']}"
        out["qr_data"] = links["main"]
        # Where the link actually lands, decided once and reported as such: the
        # dashboard shows this instead of leaving the admin to guess why a raw
        # config went out as XHTTP/TLS (or the other way round).
        plan = routing.serving(u)
        host, port = _user_endpoint(u, request, plan)
        out["endpoint"] = {
            "host": host,
            "port": port,
            "target": plan.get("target") or "panel",
            "node": (plan.get("node") or {}).get("name") or "",
            "transport": plan.get("transport") or u.get("transport") or "",
            "security": plan.get("security") or u.get("security") or "",
            "raw": routing.is_raw_transport(plan.get("transport") or "",
                                            plan.get("security") or ""),
            "reasons": list(plan.get("reasons") or []),
        }
    return out


def _flag_for(code: str) -> str:
    """Regional-indicator emoji from a 2-letter ISO country code."""
    return flag_from_code(code)


# ------------------------------------------------------------------ node status service
_node_status_cache: dict = {}
# local node's measured internet latency (1.1.1.1:443), cached to avoid
# blocking /api/nodes on a TCP probe every 30s
_local_inet_latency: dict = {"ts": 0.0, "ms": None}
_LOCAL_LATENCY_TTL = 60.0
_REMOTE_PROBE_TIMEOUT = 2.0


async def _tcp_latency(host: str, port: int, timeout: float = 2.0) -> int | None:
    try:
        t0 = time.time()
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        lat = (time.time() - t0) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return round(lat)
    except Exception:  # noqa: BLE001
        return None


async def _local_latency() -> int | None:
    """Internet latency of this process, re-probed at most every 60s."""
    now = time.time()
    if now - _local_inet_latency["ts"] < _LOCAL_LATENCY_TTL:
        return _local_inet_latency["ms"]
    ms = await _tcp_latency("1.1.1.1", 443, timeout=1.5)
    _local_inet_latency.update(ts=now, ms=ms)
    return ms


#: A raw port is probed with a TCP connect: a node that does not publish it must
#: never end up in a link (that link is exactly what "the config times out" is).
_RAW_PROBE_TIMEOUT = 1.5


async def _probe_raw_ports(node: dict) -> dict:
    """TCP-connect the raw ports the users of ``node`` actually need.

    Railway's edge accepts TCP on every port and then answers nothing, so a
    connect alone is not proof of a working proxy — but a *refused or timed out*
    connect is proof that the port is not published, and that is the case this
    probe exists to catch (it is also what the panel reports per node).
    """
    host = routing.link_host(node)
    if not host or routing.is_edge_only(host):
        return {}
    ports = set()
    for u in db.list_users():
        if nodesync.user_node_id(u) not in (node["id"], 0):
            continue
        if routing.is_raw_transport(u.get("transport") or "", u.get("security") or ""):
            ports.add(routing.raw_port(u.get("protocol") or "vless", u.get("security") or "none"))
    if not ports:
        return {}

    async def one(port: int):
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=_RAW_PROBE_TIMEOUT)
            writer.close()
            return port, True
        except Exception:  # noqa: BLE001
            return port, False

    results = dict(await asyncio.gather(*[one(p) for p in sorted(ports)]))
    routing.record_raw_probe(node["id"], results)
    return results


async def _node_status(node: dict) -> dict:
    """Compute live status for a node. Cached for 30s. Remote nodes are probed
    with a short timeout; callers should run these concurrently (gather) so a
    dead node never blocks the response for 2s  and  N."""
    now = time.time()
    cached = _node_status_cache.get(node["id"])
    if cached and now - cached["ts"] < 30:
        return cached["data"]

    data = {"online": False, "latency_ms": None, "cpu": None, "ram": None, "disk": None,
            "users_count": None, "reason": ""}
    scheme_used, port_used = "", 0
    if node.get("is_local"):
        data["online"] = True
        data["cpu"] = psutil.cpu_percent(interval=0.1)
        data["ram"] = psutil.virtual_memory().percent
        data["disk"] = psutil.disk_usage(config.DATA_DIR).percent
        data["latency_ms"] = await _local_latency()
        data["users_count"] = len(db.list_users())
    else:
        addr = (node.get("address") or "").strip()
        if not addr:
            # node never registered / no address yet — nothing to probe
            data["reason"] = "no-address"
        else:
            # Try https first, then http, so an address works whether or not the
            # admin typed a scheme (Railway domains are https-only; a bare host
            # must be probed with https, while http-only setups still work too).
            schemes = ["https://", "http://"]
            body = addr
            if addr.startswith("https://"):
                body = addr[len("https://"):]
            elif addr.startswith("http://"):
                schemes = ["http://", "https://"]
                body = addr[len("http://"):]
            body = body.split("/", 1)[0].rsplit("@", 1)[-1].strip().strip("[]")
            for scheme in schemes:
                url = f"{scheme}{body}/health"
                try:
                    async with httpx.AsyncClient(timeout=_REMOTE_PROBE_TIMEOUT, follow_redirects=True) as cl:
                        t0 = time.time()
                        r = await cl.get(url)
                        lat = (time.time() - t0) * 1000
                    data["online"] = r.status_code in (200, 401, 404)
                    data["latency_ms"] = round(lat)
                    host_part = body.rsplit(":", 1)
                    scheme_used = scheme
                    if len(host_part) == 2 and host_part[1].isdigit():
                        port_used = int(host_part[1])
                    else:
                        port_used = 443 if scheme == "https://" else 80
                    if not data["online"]:
                        # e.g. 502/503 while the node app is starting or crashed
                        data["reason"] = f"http-{r.status_code}"
                    # learn the node's WireGuard public key + live user count
                    try:
                        rbody = r.json()
                        remote_pub = (rbody.get("wg_pub") or "").strip()
                        if remote_pub and remote_pub != (node.get("wg_pub") or ""):
                            db.update_node(node["id"], {"wg_pub": remote_pub})
                        if isinstance(rbody.get("users"), int):
                            data["users_count"] = rbody["users"]
                    except Exception:  # noqa: BLE001
                        pass
                    break  # got an HTTP response; no need to try other schemes
                except Exception as e:  # noqa: BLE001
                    data["online"] = False
                    data["reason"] = type(e).__name__ or "error"
            if data["online"]:
                data["reason"] = ""  # reached via a fallback scheme — healthy
        if data["online"] and scheme_used and port_used:
            # Links must carry the edge the node actually answered on, not the one
            # the admin guessed, so the measurement is stored for `routing`.
            routing.record_edge_probe(node["id"], scheme_used, port_used)
        if not node.get("is_local"):
            data["raw_open"] = await _probe_raw_ports(node)
    _node_status_cache[node["id"]] = {"ts": now, "data": data}
    _node_latency_snap[node["id"]] = data["latency_ms"]
    if not node.get("is_local"):
        routing.record_latency(node["id"], data["latency_ms"], data["online"])
    return data


def _serialize_node(node: dict, status: dict) -> dict:
    out = dict(node)
    out.pop("token", None)  # never expose a node credential to the frontend
    out["status"] = status
    out["version"] = APP_VERSION if node.get("is_local") else None
    if not node.get("is_local"):
        # how many users this node should be serving vs how many it actually has,
        # and whether the panel has proof that it received them
        expected = sum(
            1 for u in db.list_users()
            if nodesync.user_node_id(u) in (node["id"], 0)
        )
        sync = routing.sync_state(node["id"])
        out["sync"] = {
            "expected": expected,
            "on_node": status.get("users_count"),
            "has_credential": bool(node.get("token")) or bool(nodesync.panel_secret(create=False)),
            # which credential the node accepted ("token" = the one issued in the
            # dashboard, "shared" = TITAN_NODE_SECRET) - shown on the node card so
            # "the push is refused" is visible instead of implied by a dead link
            "credential": db.get_meta(f"node_secret_kind:{node['id']}") or "",
            "ok": sync["ok"],
            "at": sync["at"] or None,
            "error": sync["err"],
            "serving": sorted(sync["uids"]) if sync["uids"] is not None else None,
        }
        # what `routing` actually trusts when it decides about a raw port
        out["raw_open"] = status.get("raw_open") or routing.raw_report(node["id"])
        measured = routing.measured_edge(node)
        out["edge"] = {
            "scheme": routing.edge_scheme(node),
            "port": routing.edge_port(node),
            "measured": bool(measured),
        }
    return out


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
async def page_root(request: Request):
    # Default admin ("TiTaN") is always present — no setup flow.
    if _current_username(request):
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")


@app.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    # Registration is disabled — the default admin ("TiTaN") is created
    # automatically on first run. Route everything to the login page.
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request):
    if _current_username(request):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "login.html", {"app_version": APP_VERSION})


@app.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    if not _current_username(request):
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        request, "dashboard.html", {"app_version": APP_VERSION, "panel": APP_NAME}
    )


@app.get("/status/{uid}", response_class=HTMLResponse)
async def page_status(request: Request, uid: str):
    user = db.get_user(uid)
    if not user:
        return HTMLResponse("<h1>404</h1><p>Not found.</p>", status_code=404)
    return templates.TemplateResponse(
        request, "status.html",
        {"uid": uid, "app_version": APP_VERSION, "panel": APP_NAME},
    )


# ------------------------------------------------------------------ auth api
@app.get("/api/setup-status")
async def api_setup_status():
    # The default admin is auto-created on first run, so setup is never needed.
    return {"needs_setup": False}


@app.post("/api/setup")
async def api_setup(request: Request):
    payload = await request.json()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if db.get_admin():
        raise HTTPException(400, "already-configured")
    if not re.match(r"^[a-zA-Z0-9_]{3,32}$", username):
        raise HTTPException(400, "invalid-username")
    if len(password) < 6:
        raise HTTPException(400, "weak-password")
    hp = security.hash_password(password)
    db.set_admin(username, hp["hash"], hp["salt"])
    db.add_event("info", "setup", f"admin created: {username}", ip=_client_ip(request))
    resp = JSONResponse({"ok": True})
    _set_session(resp, username)
    return resp


@app.post("/api/login")
async def api_login(request: Request):
    payload = await request.json()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    ip = _client_ip(request)

    # Brute-force guard. The counter is keyed on the *peer* address, never on
    # X-Forwarded-For: a client-supplied header would let an attacker mint a
    # fresh budget per attempt (10 forged IPs used to be 10 free tries).
    key = f"login_attempts:{_throttle_key(request)}"
    raw = db.get_meta(key)
    locked_until = 0.0
    count = 0
    if raw:
        try:
            blob = json.loads(raw)
            locked_until = blob.get("locked_until", 0)
            count = blob.get("count", 0)
        except (json.JSONDecodeError, TypeError):
            pass
    if locked_until > time.time():
        raise HTTPException(429, f"locked:{int(locked_until - time.time())}")
    admin = db.get_admin()
    # Password-only login: username is optional. If not provided, use admin's username.
    # The password is always verified, even in default mode (default pass = TiTaN).
    ok = False
    effective_user = ""
    if admin:
        if not username:
            username = admin["username"]
        if username == admin["username"] and security.verify_password(
            password, admin["salt"], admin["password_hash"]
        ):
            ok = True
            effective_user = admin["username"]

    if ok:
        db.set_meta(key, json.dumps({"count": 0, "locked_until": 0}))
        db.add_event("info", "login", "admin login", ip=ip)
        resp = JSONResponse({"ok": True})
        _set_session(resp, effective_user or username, remember=bool(payload.get("remember")))
        return resp

    count += 1
    # Penalise the *failed* attempt, after authentication has already been
    # checked: delaying before the check would make a legitimate admin who
    # mistyped three times wait on the next correct password too. The delay
    # (rather than a hard lock) is the real defence here, because a
    # single-container deploy shares one counter across every visitor - locking
    # at 8 attempts would let anyone lock the admin out of their own panel.
    if count >= config.LOGIN_SOFT_FAILS:
        await asyncio.sleep(min(
            config.LOGIN_BACKOFF_CAP_SECONDS,
            0.5 * (2 ** min(count - config.LOGIN_SOFT_FAILS, 5)),
        ))
    blob = {"count": count, "locked_until": 0}
    if count >= config.LOGIN_HARD_LOCK_ATTEMPTS:
        blob = {"count": 0, "locked_until": time.time() + config.LOGIN_LOCK_SECONDS}
        db.add_event("warn", "login-locked", f"after {count} attempts", ip=ip)
    db.set_meta(key, json.dumps(blob))
    # never echo the attempted username back into the audit log verbatim: it is
    # attacker-controlled text rendered into the dashboard log table.
    safe_name = re.sub(r"[^A-Za-z0-9_.@-]", "", username)[:32]
    db.add_event("warn", "login-failed", f"username={safe_name}", ip=ip)
    raise HTTPException(401, "invalid-credentials")


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(config.SESSION_COOKIE, path="/")
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    user = _current_username(request)
    settings = db.get_settings()
    return {
        "logged_in": bool(user),
        "username": user,
        "settings": settings,
        "avatar": _resolve_avatar(settings.get("admin_avatar")),
        "app_version": APP_VERSION,
        "default_auth": db.get_meta("auth_is_default") == "1",
    }


@app.post("/api/change-password")
async def api_change_password(request: Request, _: str = Depends(_require_auth)):
    payload = await request.json()
    old = payload.get("old_password") or ""
    new = payload.get("new_password") or ""
    admin = db.get_admin()
    if not admin or not security.verify_password(old, admin["salt"], admin["password_hash"]):
        raise HTTPException(401, "wrong-old-password")
    if len(new) < 6:
        raise HTTPException(400, "weak-password")
    hp = security.hash_password(new)
    db.set_admin(admin["username"], hp["hash"], hp["salt"])
    # A real password is now set -> disable the first-run mode.
    db.set_meta("auth_is_default", "0")
    # Rotate secret to invalidate all old sessions (old password stops working everywhere)
    db.set_meta("secret_key", secrets.token_hex(32))
    db.add_event("warn", "password-change", "admin password changed", ip=_client_ip(request))
    resp = JSONResponse({"ok": True})
    _set_session(resp, admin["username"], remember=True)
    return resp


# ------------------------------------------------------------------ settings
@app.get("/api/settings")
async def api_get_settings(request: Request, _: str = Depends(_require_auth)):
    return db.get_settings()


@app.post("/api/settings")
async def api_set_settings(request: Request, _: str = Depends(_require_auth)):
    payload = await request.json()
    allowed = set(config.DEFAULT_SETTINGS.keys())
    updates = {}
    for k, v in payload.items():
        if k not in allowed:
            continue
        if k == "default_fingerprint" and v not in config.VALID_FINGERPRINTS:
            continue
        if k == "default_alpn" and v not in config.VALID_ALPNS:
            continue
        if k == "public_domain":
            v = str(v or "").strip()[:256]
            if v:
                low = v.lower()
                if low.startswith(("javascript:", "data:", "vbscript:")):
                    continue
                host_part = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", v).split("/")[0].split(":")[0].strip("[]").strip()
                if not host_part or any(c in v for c in ' <>"\''):
                    continue
                if len(host_part) > 253:
                    continue
            updates[k] = v
            continue
        if k == "public_port":
            try:
                pv = int(str(v).strip())
                if not 1 <= pv <= 65535:
                    continue
                v = str(pv)
            except (ValueError, TypeError, AttributeError):
                continue
        if k == "sni_override":
            v = str(v or "").strip()[:256]
            if v and any(c in v for c in ' <>"\''):
                continue
        updates[k] = v
    db.set_settings(updates)
    # routing-affecting flags require an Xray reload
    if any(k in updates for k in ("block_ads", "block_iran_sites", "restrict_ips")):
        try:
            xray.write_xray_config()
            xray.restart_xray()
        except Exception:  # noqa: BLE001
            pass
    db.add_event("info", "settings-update", json.dumps(updates, ensure_ascii=False)[:300])
    return {"ok": True, "settings": db.get_settings()}


# ------------------------------------------------------------------ avatar gallery (profile pictures)
GALLERY_BUILTIN = ("g1", "g2", "g3", "g4", "g5", "g6")


def _gallery_upload_dir() -> str:
    d = os.path.join(config.DATA_DIR, "gallery")
    os.makedirs(d, exist_ok=True)
    return d


def _sanitize_avatar_key(key) -> str:
    """Normalize an avatar key. Returns '' for the default (TiTaN logo)."""
    key = (key or "").strip()[:128]
    if not key or key == "titan":
        return ""
    if key.startswith("gallery:"):
        slug = key.split(":", 1)[1]
        return f"gallery:{slug}" if slug in GALLERY_BUILTIN else ""
    if key.startswith("upload:"):
        fname = os.path.basename(key.split(":", 1)[1])
        return f"upload:{fname}" if fname else ""
    return ""


def _resolve_avatar(key) -> dict:
    """Map an avatar key to {key, url}. Default is the TiTaN logo."""
    key = _sanitize_avatar_key(key)
    if key.startswith("gallery:"):
        slug = key.split(":", 1)[1]
        return {"key": key, "url": f"/static/img/gallery/{slug}.svg"}
    if key.startswith("upload:"):
        fname = key.split(":", 1)[1]
        if os.path.exists(os.path.join(_gallery_upload_dir(), fname)):
            return {"key": key, "url": f"/api/gallery-image/{fname}"}
    return {"key": "titan", "url": "/static/img/titan-avatar.svg"}


def _gallery_items() -> list:
    items = [{"id": f"gallery:{s}", "url": f"/static/img/gallery/{s}.svg",
              "name": s, "builtin": True} for s in GALLERY_BUILTIN]
    for fname in sorted(os.listdir(_gallery_upload_dir())):
        if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            items.append({"id": f"upload:{fname}", "url": f"/api/gallery-image/{fname}",
                          "name": fname, "builtin": False})
    return items


@app.get("/api/gallery")
async def api_gallery(_: str = Depends(_require_auth)):
    return {"items": _gallery_items()}


@app.get("/api/gallery-image/{fname}")
async def api_gallery_image(fname: str, _: str = Depends(_require_auth)):
    fname = os.path.basename(fname)
    path = os.path.join(_gallery_upload_dir(), fname)
    if not os.path.exists(path):
        raise HTTPException(404, "not-found")
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp"}.get(os.path.splitext(fname)[1].lower(), "image/png")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@app.post("/api/gallery")
async def api_gallery_upload(request: Request, _: str = Depends(_require_auth)):
    """Upload a picture into the gallery (persisted in the data dir)."""
    form = await request.form()
    file = form.get("file")
    if file is None or not getattr(file, "filename", None):
        raise HTTPException(400, "no-file")
    data = await file.read()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(400, "too-large")
    try:
        img = PILImage.open(io.BytesIO(data))
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid-image") from None
    img.thumbnail((512, 512))
    fname = f"{secrets.token_hex(8)}.png"
    img.save(os.path.join(_gallery_upload_dir(), fname), "PNG")
    db.add_event("info", "gallery-upload", fname, ip=_client_ip(request))
    return {"ok": True, "item": {"id": f"upload:{fname}", "url": f"/api/gallery-image/{fname}",
                                 "name": fname, "builtin": False}}


@app.delete("/api/gallery/{fname}")
async def api_gallery_delete(fname: str, request: Request, _: str = Depends(_require_auth)):
    fname = os.path.basename(fname)
    path = os.path.join(_gallery_upload_dir(), fname)
    if not os.path.exists(path):
        raise HTTPException(404, "not-found")
    os.remove(path)
    db.add_event("warn", "gallery-delete", fname, ip=_client_ip(request))
    return {"ok": True}


@app.post("/api/admin-avatar")
async def api_set_admin_avatar(request: Request, _: str = Depends(_require_auth)):
    """Set the admin's profile picture (TiTaN logo / gallery image / upload)."""
    payload = await request.json()
    key = _sanitize_avatar_key(payload.get("avatar"))
    if key and not key.startswith(("gallery:", "upload:")):
        raise HTTPException(400, "invalid-avatar")
    if key.startswith("upload:"):
        fname = key.split(":", 1)[1]
        if not os.path.exists(os.path.join(_gallery_upload_dir(), fname)):
            raise HTTPException(400, "invalid-avatar")
    db.set_setting("admin_avatar", key or "titan")
    db.add_event("info", "avatar-set", key or "titan", ip=_client_ip(request))
    return {"ok": True, "avatar": _resolve_avatar(key)}


# ------------------------------------------------------------------ connection diagnostics
@app.get("/api/connection-test")
async def api_connection_test(_: str = Depends(_require_auth)):
    """Self-test that explains why generated configs may not connect."""
    settings = db.get_settings()
    domain = (settings.get("public_domain") or "").strip()
    port = _link_port(settings)
    result = {
        "xray_installed": xray.xray_available(),
        "xray_running": xray.xray_running(),
        "config_exists": os.path.exists(config.XRAY_CONFIG_PATH),
        "domain": domain,
        "port": port,
        "public_domain_configured": bool(domain),
    }

    # are the local Xray inbound ports actually accepting connections?
    internal = {}
    for name, p in (
        ("vless-ws", config.XRAY_VLESS_WS_PORT),
        ("vmess-ws", config.XRAY_VMESS_WS_PORT),
        ("trojan-ws", config.XRAY_TROJAN_WS_PORT),
        ("xhttp", config.XRAY_XHTTP_PORT),
    ):
        internal[name] = await _tcp_latency("127.0.0.1", p, timeout=1.5) is not None
    result["internal_ports_open"] = internal

    # validate the generated Xray config (only if binary present)
    result["config_valid"] = None
    if xray.xray_available() and result["config_exists"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                config.XRAY_BIN, "run", "-test", "-c", config.XRAY_CONFIG_PATH,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _out, _err = await proc.communicate()
            result["config_valid"] = proc.returncode == 0
        except Exception as e:  # noqa: BLE001
            result["config_valid"] = False
            result["config_error"] = str(e)[:200]

    # reach the public domain + WS path (only when a domain is configured)
    public = {"checked": False}
    if domain:
        public["checked"] = True
        try:
            async with httpx.AsyncClient(timeout=6, follow_redirects=True, verify=True) as client:
                r = await client.get(f"https://{domain}:{port}/health")
                public["panel_http_status"] = r.status_code
                r2 = await client.get(f"https://{domain}:{port}/vl-ws")
                public["ws_status"] = r2.status_code
                public["ws_path_routed"] = r2.status_code not in (404, 502, 503)
        except Exception as e:  # noqa: BLE001
            public["error"] = str(e)[:200]
    result["public"] = public
    return result


# ------------------------------------------------------------------ users api
@app.get("/api/users")
async def api_list_users(_: str = Depends(_require_auth)):
    return {"users": [ _serialize_user(u) for u in db.list_users() ]}


@app.post("/api/users")
async def api_create_user(request: Request, _: str = Depends(_require_auth)):
    payload = await request.json()
    # --- idempotency guard: second quick retry with same nonce/payload returns first user ---
    raw_nonce = (payload.get("client_nonce") or payload.get("_nonce") or "").strip()[:64]
    now = time.time()
    # prune expired entries
    with _recent_creates_lock:
        for k in list(_recent_creates.keys()):
            ts, _ = _recent_creates[k]
            if now - ts > _IDEMPOTENCY_TTL:
                _recent_creates.pop(k, None)
        dedup_key = None
        if raw_nonce:
            dedup_key = f"nonce:{raw_nonce}"
        else:
            # fallback key from stable fields (prevents double-click w/o nonce)
            try:
                nm = (payload.get("name") or "User").strip()[:64]
                nid = db.coerce_node_id(payload.get("node_id"))
                proto = (payload.get("protocol") or "vless").strip().lower()
                dedup_key = f"fallback:{nm}\x1f{nid}\x1f{proto}\x1f{request.client.host if request.client else ''}"
            except Exception:
                dedup_key = None
        if dedup_key and dedup_key in _recent_creates:
            ts, prev_uid = _recent_creates[dedup_key]
            if now - ts < _IDEMPOTENCY_TTL:
                prev = db.get_user(prev_uid)
                if prev:
                    return {"ok": True, "user": _serialize_user(prev, with_links=True, request=request), "deduped": True}
    settings = db.get_settings()
    uid = secrets.token_hex(8)
    protocol = payload.get("protocol", "vless")
    if protocol not in config.VALID_PROTOCOLS:
        raise HTTPException(400, "invalid-protocol")
    transport, security = _normalize_protocol_fields(
        protocol,
        payload.get("transport") or settings.get("default_transport", "ws"),
        payload.get("security", "tls"),
        raw_ok=_target_allows_raw_transport(payload.get("node_id")),
    )
    ss_method = (
        payload.get("ss_method")
        or settings.get("ss_method")
        or config.DEFAULT_SS_METHOD
    )
    if ss_method not in config.SS_METHODS:
        ss_method = config.DEFAULT_SS_METHOD
    fingerprint = payload.get("fingerprint") or settings.get("default_fingerprint", "chrome")
    if fingerprint not in config.VALID_FINGERPRINTS:
        fingerprint = "chrome"
    alpn = payload.get("alpn") if payload.get("alpn") is not None else settings.get("default_alpn", "http/1.1")
    if alpn not in config.VALID_ALPNS:
        alpn = "http/1.1"
    # Validate numeric fields — invalid values should be 400, not 500
    try:
        max_devices = int(payload.get("max_devices") or 0)
        max_requests = int(payload.get("max_requests") or 0)
        # GB or MB, whichever the dashboard asked for
        quota_bytes = _quota_bytes_from_payload(payload)
        if quota_bytes is None:
            quota_bytes = 0
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(400, "invalid-quota") from None
    try:
        expire_at = _expire_from_days(payload.get("expire_days"))
    except (ValueError, TypeError):
        raise HTTPException(400, "invalid-expire") from None
    if max_devices < 0 or max_requests < 0:
        raise HTTPException(400, "invalid-limit")
    # Validate allowed_ips on create (same as PATCH)
    raw_allowed = payload.get("allowed_ips") or []
    if raw_allowed:
        if not isinstance(raw_allowed, list):
            raise HTTPException(400, "invalid-allowed_ips") from None
        cleaned_allowed = []
        for ip in raw_allowed[:20]:
            ip = str(ip).strip()
            if ip:
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    raise HTTPException(400, "invalid-allowed_ips") from None
                cleaned_allowed.append(ip)
        raw_allowed = cleaned_allowed
    else:
        raw_allowed = []
    data = {
        "uid": uid,
        "uuid": str(uuid_lib.uuid4()),
        "name": (payload.get("name") or "User").strip()[:64],
        "note": (payload.get("note") or "")[:200],
        "protocol": protocol,
        "transport": transport,
        "security": security,
        "fingerprint": fingerprint,
        "alpn": alpn,
        "public_key": payload.get("public_key", ""),
        "short_id": payload.get("short_id", ""),
        "spider_x": payload.get("spider_x", ""),
        "max_devices": max_devices,
        "allowed_ips": raw_allowed,
        "quota_bytes": quota_bytes,
        "expire_at": expire_at,
        "max_requests": max_requests,
        "node_id": db.coerce_node_id(payload.get("node_id")),
        "avatar": _sanitize_avatar_key(payload.get("avatar")),
        "ss_method": ss_method,
    }
    user = db.create_user(data)
    if protocol == "wireguard":
        user = wg.ensure_user_keys(user)
    # remember for dedup window so an immediate retry returns this user
    if dedup_key:
        with _recent_creates_lock:
            _recent_creates[dedup_key] = (time.time(), uid)
    _reload_xray()
    node_sync = await _sync_node_now(user.get("node_id"))
    _trigger_node_sync()
    db.add_event("info", "user-create", f"{user['name']} ({protocol})", ip=_client_ip(request))
    return {"ok": True, "user": _serialize_user(user, with_links=True, request=request),
            "node_sync": node_sync}


@app.get("/api/users/{uid}")
async def api_get_user(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    return _serialize_user(user, with_links=True, request=request)


@app.patch("/api/users/{uid}")
async def api_update_user(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    payload = await request.json()
    fields = {}
    for k in ("name", "note", "enabled", "protocol", "transport", "security",
              "fingerprint", "alpn", "public_key", "short_id", "spider_x",
              "max_devices", "allowed_ips", "max_requests", "node_id", "ss_method"):
        if k in payload:
            fields[k] = payload[k]
    if "avatar" in payload:
        fields["avatar"] = _sanitize_avatar_key(payload.get("avatar"))
    if "node_id" in fields:
        fields["node_id"] = db.coerce_node_id(fields["node_id"])
    if "ss_method" in fields and fields["ss_method"] not in config.SS_METHODS:
        fields["ss_method"] = config.DEFAULT_SS_METHOD
    # Validate numeric limits for PATCH — invalid should be 400 not 500
    for k in ("max_devices", "max_requests"):
        if k in fields:
            try:
                v = int(fields[k] or 0)
                if v < 0:
                    raise ValueError
                fields[k] = v
            except (ValueError, TypeError):
                raise HTTPException(400, f"invalid-{k}") from None
    if "allowed_ips" in fields:
        # Ensure list of strings, drop empty, max 20 entries
        if not isinstance(fields["allowed_ips"], list):
            raise HTTPException(400, "invalid-allowed_ips") from None
        cleaned = []
        for ip in fields["allowed_ips"][:20]:
            ip = str(ip).strip()
            if ip:
                # Validate IP/CIDR syntax
                try:
                    ipaddress.ip_network(ip, strict=False)
                except ValueError:
                    raise HTTPException(400, "invalid-allowed_ips") from None
                cleaned.append(ip)
        fields["allowed_ips"] = cleaned
    proto = fields.get("protocol", user.get("protocol", "vless"))
    if proto not in config.VALID_PROTOCOLS:
        raise HTTPException(400, "invalid-protocol")
    if ("transport" in fields or "security" in fields
            or proto in ("hysteria2", "wireguard")):
        t, s = _normalize_protocol_fields(
            proto,
            fields.get("transport", user.get("transport", "ws")),
            fields.get("security", user.get("security", "tls")),
            raw_ok=_target_allows_raw_transport(fields.get("node_id", user.get("node_id"))),
        )
        fields["transport"], fields["security"] = t, s
    if "fingerprint" in fields and fields["fingerprint"] not in config.VALID_FINGERPRINTS:
        fields["fingerprint"] = "chrome"
    if "alpn" in fields and fields["alpn"] not in config.VALID_ALPNS:
        fields["alpn"] = "http/1.1"
    if any(k in payload for k in ("quota_gb", "quota_mb", "quota")):
        try:
            quota_bytes = _quota_bytes_from_payload(payload)
            if quota_bytes is None:
                raise ValueError
            fields["quota_bytes"] = quota_bytes
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(400, "invalid-quota") from None
    if "expire_days" in payload:
        try:
            fields["expire_at"] = _expire_from_days(payload.get("expire_days"))
        except (ValueError, TypeError):
            raise HTTPException(400, "invalid-expire") from None
    updated = db.update_user(uid, fields)
    if updated and updated.get("protocol") == "wireguard":
        updated = wg.ensure_user_keys(updated)
    # renewing the volume (or resetting the usage) brings the config back
    if updated and not updated.get("enabled") and _renewal_reopens_user(user, updated):
        updated = db.update_user(uid, {"enabled": True}) or updated
        db.add_event("info", "renewed", f"quota renewed, config re-enabled: {uid}", user_id=user.get("id"))
    _reload_xray()
    node_sync = await _sync_node_now((updated or {}).get("node_id"))
    _trigger_node_sync()
    db.add_event("info", "user-update", f"{uid}", ip=_client_ip(request))
    return {"ok": True, "user": _serialize_user(updated, with_links=True, request=request),
            "node_sync": node_sync}


@app.get("/api/users/{uid}/sub-configs")
async def api_sub_configs(uid: str, request: Request, _: str = Depends(_require_auth)):
    """The configs this user's subscription can carry, and which are ticked.

    One user is genuinely served on several transports (the Xray config builds a
    WS, XHTTP, HTTPUpgrade and gRPC inbound for every VLESS/VMess user), so the
    subscription link is a *set* the admin chooses — not a single fixed link.
    """
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    entries = _sub_entries(user, request)
    picked = _sub_selection(user)
    for e in entries:
        e["included"] = (not picked) or (e["key"] in picked)
    return {
        "uid": uid,
        "protocol": user.get("protocol"),
        "stored_transport": user.get("transport") or "",
        "sub_url": f"https://{_public_host(request)}/sub/{uid}",
        "selected": picked,
        "configs": entries,
    }


@app.patch("/api/users/{uid}/sub-configs")
async def api_set_sub_configs(uid: str, request: Request, _: str = Depends(_require_auth)):
    """Pick which configs appear in this user's subscription link."""
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    payload = await request.json()
    raw = payload.get("transports")
    if raw is None:
        raise HTTPException(400, "transports-required")
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x.strip()]
    if not isinstance(raw, list):
        raise HTTPException(400, "transports-required")
    # "Everything" means every config the admin could actually tick — which is the
    # deduped entry list, not the raw candidate list: on an HTTP edge the raw-TCP
    # candidate resolves to the same XHTTP link, so it is never offered twice.
    entries = _sub_entries(user, request)
    valid = {e["key"] for e in entries}
    picked = [str(x).strip().lower() for x in raw if str(x).strip()]
    if any(x not in valid for x in picked):
        raise HTTPException(400, "unknown-transport")
    # An empty selection (or everything) is stored as "" = all, so a user added
    # later still gets every config without the admin touching this again.
    stored = "" if (not picked or set(picked) == valid) else ",".join(sorted(set(picked)))
    db.update_user(uid, {"sub_transports": stored})
    entries = _sub_entries(db.get_user(uid), request)
    for e in entries:
        e["included"] = (not picked) or (e["key"] in picked)
    db.add_event("info", "sub-configs", f"{uid}: {stored or 'all'}", ip=_client_ip(request))
    return {"ok": True, "selected": picked, "configs": entries}


@app.delete("/api/users/{uid}")
async def api_delete_user(uid: str, request: Request, _: str = Depends(_require_auth)):
    if not db.delete_user(uid):
        raise HTTPException(404, "not-found")
    state.ACTIVE.pop(uid, None)
    _reload_xray()
    _trigger_node_sync()
    db.add_event("warn", "user-delete", f"{uid}", ip=_client_ip(request))
    return {"ok": True}


@app.post("/api/users/{uid}/reset")
async def api_reset_user(uid: str, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    db.reset_user_usage(uid)
    # a reset is a renewal too: the volume is free again, so the config goes back
    fresh = db.get_user(uid)
    reopened = False
    if fresh and not fresh.get("enabled") and _renewal_reopens_user(user, fresh):
        db.update_user(uid, {"enabled": True})
        reopened = True
    _reload_xray()
    _trigger_node_sync()
    return {"ok": True, "reopened": reopened}


@app.post("/api/users/{uid}/regenerate")
async def api_regenerate(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    db.update_user(uid, {"uuid": str(uuid_lib.uuid4())})
    state.ACTIVE.pop(uid, None)
    _reload_xray()
    _trigger_node_sync()
    db.add_event("warn", "uuid-rotate", f"{uid}", ip=_client_ip(request))
    return {"ok": True, "user": _serialize_user(db.get_user(uid), with_links=True, request=request)}


@app.post("/api/users/{uid}/toggle")
async def api_toggle(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    new_state = not bool(user["enabled"])
    db.update_user(uid, {"enabled": new_state})
    _reload_xray()
    _trigger_node_sync()
    db.add_event("info", "user-toggle", f"{uid} -> {new_state}", ip=_client_ip(request))
    return {"ok": True, "enabled": new_state}


@app.get("/api/users/{uid}/links")
async def api_user_links(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    return _serialize_user(user, with_links=True, request=request)


@app.get("/api/users/{uid}/qr")
async def api_user_qr(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    link = _links_for(user, request)["main"]
    img = qrcode.make(link, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/api/users/{uid}/wireguard")
async def api_user_wireguard(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user or user.get("protocol") != "wireguard":
        raise HTTPException(404, "not-found")
    user = _ensure_wg_user(user)
    host, port = _user_endpoint(user, request)
    server_pub = _wg_server_pub(user)
    conf = wg.client_conf(user, host, port, server_pub)
    link = _links_for(user, request)["main"]
    return {"ok": True, "conf": conf, "link": link, "endpoint": f"{host}:{port}"}


@app.get("/api/users/{uid}/wireguard.conf")
async def api_user_wireguard_conf(uid: str, request: Request, _: str = Depends(_require_auth)):
    user = db.get_user(uid)
    if not user or user.get("protocol") != "wireguard":
        raise HTTPException(404, "not-found")
    user = _ensure_wg_user(user)
    host, port = _user_endpoint(user, request)
    server_pub = _wg_server_pub(user)
    conf = wg.client_conf(user, host, port, server_pub)
    return Response(
        content=conf,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="titan-{uid}.conf"'},
    )


@app.get("/api/edge-check")
async def api_edge_check(request: Request, _: str = Depends(_require_auth)):
    """Prove which transports this deployment can actually serve.

    The panel asks *itself* through nginx (the same path a client's packet takes
    after the edge), per transport, and reports what came back. On an HTTP-only
    edge the raw ports are dead by construction, and that verdict is included -
    this is the check that turns "the config times out" into a named cause.
    """
    import httpx

    settings = db.get_settings()
    host = _public_host(request)
    port = _link_port(settings)
    checks = {
        "vless+ws": ("/vl-ws", {"Connection": "Upgrade", "Upgrade": "websocket",
                                "Sec-WebSocket-Version": "13",
                                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}),
        "vmess+ws": ("/vm-ws", {"Connection": "Upgrade", "Upgrade": "websocket",
                                "Sec-WebSocket-Version": "13",
                                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}),
        "trojan+ws": ("/tr-ws", {"Connection": "Upgrade", "Upgrade": "websocket",
                                 "Sec-WebSocket-Version": "13",
                                 "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}),
        "vless+xhttp": ("/xhttp", {"Content-Type": "application/octet-stream"}),
        "vless+httpupgrade": ("/hup", {"Connection": "Upgrade", "Upgrade": "websocket"}),
        "vless+grpc": ("/titan", {"Content-Type": "application/grpc"}),
    }
    results = {}

    def _nginx_in_front() -> bool:
        """True when something in front of the panel forwards to us (nginx does:
        it adds X-TiTaN-Listen-Port, which the panel echoes as edge_port)."""
        for port in (config.PUBLIC_PORT, config.PANEL_PORT):
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=3.0)
                if r.status_code == 200 and r.json().get("edge_port"):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _probe(path: str, headers: dict) -> tuple:
        # Local nginx is the same hop the edge forwards to; when nginx is absent
        # the panel serves the port itself, so the same URL still works.
        for url in (f"http://127.0.0.1:{config.PUBLIC_PORT}{path}",
                    f"http://127.0.0.1:{config.PANEL_PORT}{path}"):
            try:
                method = "POST" if path == "/xhttp" else "GET"
                r = httpx.request(method, url, headers=headers, timeout=4.0,
                                  content=b"\x00" if method == "POST" else None)
                # Xray answers 400/415 to a bogus handshake: that is *alive*.
                return r.status_code, len(r.content)
            except Exception as exc:  # noqa: BLE001
                last = str(exc)[:80]
        return 0, last

    in_front = _nginx_in_front()
    for name, (path, headers) in checks.items():
        code, _extra = _probe(path, headers)
        alive = code in (200, 400, 415, 426, 101)
        detail = ""
        if code == 0:
            detail = ("nothing answered: the proxy in front of the panel is not "
                      "running, so these paths cannot be served at all"
                      if not in_front else "no answer from the upstream (inbound down?)")
        results[name] = {"path": path, "status": code, "alive": alive, "detail": detail}
    raw_ports = {name: getattr(config, name) for name in (
        "XRAY_TCP_VLESS_PORT", "XRAY_TCP_VLESS_TLS_PORT", "XRAY_TCP_VLESS_REALITY_PORT",
        "XRAY_TCP_VMESS_PORT", "XRAY_TCP_VMESS_TLS_PORT", "XRAY_TCP_TROJAN_PORT",
        "XRAY_SS_PORT", "XRAY_SS_2022_PORT", "XRAY_HY2_PORT", "WG_PORT")}
    return {
        "ok": True,
        "edge_http_only": config.EDGE_HTTP_ONLY,
        "proxy_in_front": in_front,
        "tcp_proxy": (lambda p: {"host": p[0], "port": p[1],
                                 "application_port": getattr(config, "TCP_APP_PORT", 0) or None,
                                 "carries": sorted(
                                     f"{name}={getattr(config, name)}"
                                     for name in (
                                         "XRAY_TCP_VLESS_PORT", "XRAY_TCP_VLESS_TLS_PORT",
                                         "XRAY_TCP_VLESS_REALITY_PORT", "XRAY_TCP_VMESS_PORT",
                                         "XRAY_TCP_VMESS_TLS_PORT", "XRAY_TCP_TROJAN_PORT")
                                     if config.tcp_proxy_carries(getattr(config, name))),
                                 } if p else None)(config.tcp_proxy()),
        "public": {"host": host, "port": port},
        "transports": results,
        "raw_ports": raw_ports,
        "note": ("an HTTP-only edge answers nothing on the raw ports; raw TCP needs "
                 "a platform TCP proxy or a node that exposes them"),
    }


def _expire_from_days(days) -> float | None:
    d = int(days or 0)
    return (time.time() + d * 86400) if d > 0 else None


_SERVED_TRANSPORTS = {
    "vless": {"ws", "xhttp", "grpc", "tcp", "httpupgrade"},
    "vmess": {"ws", "xhttp", "grpc", "tcp", "httpupgrade"},
    "trojan": {"ws", "tcp"},
    "shadowsocks": set(),
    "hysteria2": set(),
}


def _normalize_protocol_fields(protocol: str, transport, security,
                               raw_ok: bool = False) -> tuple[str, str]:
    """Coerce transport/security to values the server can actually serve."""
    if protocol == "hysteria2":
        # Hysteria2 has no transport and is always TLS (QUIC).
        return "", "tls"
    if protocol == "wireguard":
        # WireGuard is a UDP VPN: no transport/security concepts.
        return "", ""
    t = (transport or "ws").lower()
    s = (security or "tls").lower()
    allowed = _SERVED_TRANSPORTS.get(protocol, {"ws"})
    if t not in allowed:
        t = "ws" if "ws" in allowed else next(iter(allowed), "ws")
    if s not in ("tls", "none", "reality"):
        s = "tls"
    if protocol == "trojan":
        # Trojan requires TLS regardless of transport
        s = "tls"
    elif protocol == "vmess" and s == "reality":
        # VMess has no Reality support
        s = "tls"
    if s == "reality" and t != "tcp":
        # Reality is only served over raw TCP
        s = "tls"
    if (t == "tcp" or s == "reality") and not raw_ok \
            and config.EDGE_HTTP_ONLY and not config.tcp_proxy():
        # The deployment has an HTTP-only edge and no TCP proxy: a raw transport
        # here is a config that can never connect. Store a servable one instead
        # of handing out a dead link (the admin sees the switch in the response).
        t = "xhttp" if "xhttp" in allowed else ("ws" if "ws" in allowed else t)
        s = "tls"
    return t, s


_reload_running = False
_reload_wanted = 0
# Strong references to background tasks. asyncio only keeps a weak reference to
# a bare create_task() result, so a task scheduled from a request handler can be
# garbage-collected while it is still pending ("Task was destroyed but it is
# pending") - which silently drops a node sync or an Xray reload.
_pending_tasks: set = set()


def _spawn(coro, name: str = ""):
    """Create a task and keep it alive until it finishes."""
    task = asyncio.create_task(coro, name=name or None)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return task


def _do_reload():
    """Rewrite the Xray config and restart Xray + WireGuard. Synchronous and
    heavy (subprocess shutdown can take seconds), so it must never run inside
    a request handler."""
    try:
        xray.write_xray_config()
        xray.restart_xray()
    except Exception:  # noqa: BLE001
        pass
    try:
        wg.restart()
    except Exception:  # noqa: BLE001
        pass


def _reload_xray():
    """Schedule a config reload in the background.

    The response to a create/update/delete/toggle never depends on the new
    Xray config (links are built from the DB), so we coalesce bursts and run
    the heavy work off the request path. This keeps POST /api/users fast even
    when Xray is slow to shut down.
    """
    global _reload_wanted, _reload_running
    _reload_wanted += 1
    try:
        # called from request handlers, so a loop exists; the node-sync path can
        # also fire from a background task, where there may be none - bail out
        # (the counter stays set and the next reload picks the work up).
        asyncio.get_running_loop()
    except RuntimeError:
        return
    if _reload_running:
        return

    async def _loop():
        global _reload_running, _reload_wanted
        _reload_running = True
        try:
            while _reload_wanted > 0:
                _reload_wanted = 0
                await asyncio.to_thread(_do_reload)
                if _reload_wanted > 0:
                    await asyncio.sleep(0.2)
        finally:
            _reload_running = False

    _spawn(_loop(), name="xray-reload-loop")


def _node_setup(node: dict, token: str, request: Request | None) -> dict:
    """What the freshly created node must be told to accept this panel's pushes.

    A node added by URL alone cannot take users until it knows a credential: its
    ``secret_valid_for_node`` accepts ``TITAN_NODE_SECRET`` or its own
    ``TITAN_NODE_TOKEN``, nothing else. The dashboard used to print the token in a
    toast that disappeared after two seconds, so a node deployed without it
    silently refused every push and every config fell back to the main domain.
    These are the variables to paste into the node service.
    """
    panel_host = ""
    if request is not None:
        try:
            panel_host = _public_host(request)
        except Exception:  # noqa: BLE001
            panel_host = ""
    scheme = "http" if panel_host.startswith(("127.", "localhost")) else "https"
    env = {
        "TITAN_ROLE": "node",
        "TITAN_NODE_TOKEN": token,
        "TITAN_NODE_URL": (node.get("address") or "").strip(),
    }
    if panel_host:
        env["TITAN_MAIN_URL"] = f"{scheme}://{panel_host}"
    return {
        "token": token,
        "env": env,
        "lines": [f"{k}={v}" for k, v in env.items()],
        "block": "\n".join(f"{k}={v}" for k, v in env.items()),
        "note": ("این متغیرها را روی سرویسِ نود بگذار و دوباره دیپلوی کن؛ "
                 "یا به‌جای توکن، TITAN_NODE_SECRET را روی پنل و نود یکسان تنظیم کن."),
    }


async def _sync_node_now(node_id) -> dict:
    """Push one node *during* the request that assigned it.

    The background push (`_trigger_node_sync`) is fire-and-forget, so the response
    to "create/patch this user" used to carry links built from the state *before*
    the node had the user: the admin copied a panel link, the node got the user a
    moment later, and the client kept dialling the main domain. Waiting for the
    node here (bounded, ~6s) means the returned links already point at the server
    that will answer them — and if the node refuses, the response says why instead
    of silently falling back.
    """
    try:
        nid = db.coerce_node_id(node_id)
    except Exception:  # noqa: BLE001
        return {}
    node = db.get_node(nid) if nid else None
    if not node or node.get("is_local") or not (node.get("address") or "").strip():
        return {}
    ok = await nodesync.sync_one(nid)
    st = routing.sync_state(nid)
    return {
        "node_id": nid,
        "node_name": node.get("name") or "",
        "ok": bool(ok),
        "error": "" if ok else (st.get("err") or "sync-failed"),
        "served_by": "node" if ok else "panel",
    }


def _trigger_node_sync():
    """Push user changes to remote nodes without blocking the request."""
    try:
        _spawn(nodesync.sync_all(), name="node-sync")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ smart routing
# Snapshot of per-node latency (ms), refreshed by _node_status whenever it runs.
_node_latency_snap: dict = {}


def _auto_node() -> dict | None:
    """Fastest node that is online *and* currently trusted to serve this user set.

    Latency alone used to be the whole rule, which could send an "auto" user to a
    node that was offline, disabled or had never received the config. `routing`
    owns the verified version.
    """
    return routing.auto_node()


def _wg_server_pub(u: dict, plan: dict | None = None) -> str:
    """The WG server public key for the node that will actually serve `u`."""
    plan = plan or routing.serving(u)
    node = plan.get("node")
    if plan["target"] == "node" and node:
        return (node.get("wg_pub") or "").strip()
    return wg.server_public_key()


def _ensure_wg_user(u: dict) -> dict:
    if u.get("protocol") == "wireguard":
        u = wg.ensure_user_keys(u)
    return u


# ------------------------------------------------------------------ nodes api
@app.get("/api/nodes")
async def api_list_nodes(_: str = Depends(_require_auth)):
    db_nodes = db.list_nodes()
    # probe every node concurrently so a dead/slow node never serializes the
    # response (this endpoint feeds the dashboard, users and config pages)
    statuses = await asyncio.gather(*[_node_status(n) for n in db_nodes])
    return {"nodes": [_serialize_node(n, s) for n, s in zip(db_nodes, statuses, strict=True)]}


def _normalize_node_address(raw: str) -> str:
    """Canonicalize a node address to 'https://host[:port]'.

    Accepts any of: 'domain', 'https://domain/', 'https://domain/path',
    'domain:8443', 'http://user@domain', '[IPv6]:port', … and stores a clean origin
    so the health probe, sync and link building all agree. Explicit 'http://' is
    preserved; everything else defaults to 'https://'.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://"):
        scheme, raw = "http://", raw[len("http://"):]
    elif raw.startswith("https://"):
        scheme, raw = "https://", raw[len("https://"):]
    else:
        scheme = "https://"
    raw = raw.split("/", 1)[0]      # drop path / query / fragment
    raw = raw.rsplit("@", 1)[-1]    # drop any userinfo
    # Strip brackets for IPv6: [::1] or [::1]:port -> ::1 or ::1:port
    # Handle cases like [::1]:port or [::1]
    while raw.startswith("[") and "]" in raw:
        i = raw.index("]")
        raw = raw[1:i] + raw[i+1:]
    raw = raw.strip("[]")
    if not raw:
        return ""
    return scheme + raw


@app.post("/api/nodes")
async def api_create_node(request: Request, _: str = Depends(_require_auth)):
    payload = await request.json()
    name = (payload.get("name") or "").strip()[:64]
    # No name yet? The domain can supply one (see the detection block below) —
    # asking for both is what made adding a node feel like manual work.
    address = _normalize_node_address(payload.get("address") or "")
    cc = (payload.get("country_code") or "").strip()[:2].upper()
    city = (payload.get("city") or "").strip()[:64]
    country = (payload.get("country") or "").strip()[:64]
    flag = (payload.get("flag") or "").strip()[:8]
    # Domain alone is enough: ask the address what it is and take everything it
    # can tell us (name, city, flag, edge, raw ports, whether it holds a
    # credential yet). Only `name` is required at the end of this block.
    probe: dict = {"kind": "skipped", "identity": {}}
    claim: dict = {}
    if address and payload.get("detect", True) is not False:
        probe = await _probe_node_identity(address)
        identity = probe.get("identity") or {}
        found = _discovery_fields(identity)
        name = name or (found.get("name") or "")
        city = city or (found.get("city") or "")
        country = country or (found.get("country") or "")
        cc = cc or (found.get("country_code") or "")
        flag = flag or (found.get("flag") or "")
        if not name:
            raise HTTPException(400, "name-required")
    # Auto-detect location from the normalized address when admin hasn't set it manually.
    # Never overwrite an explicit city/country/country_code/flag provided in the payload.
    if address and not cc and not flag:
        try:
            loc = await asyncio.to_thread(detect_location, address)
        except Exception:
            loc = None
        if loc:
            city = city or loc.get("city", "")[:64]
            country = country or loc.get("country", "")[:64]
            cc = cc or (loc.get("country_code") or "")[:2].upper()
            flag = flag or loc.get("flag") or _flag_for(cc)
    if not flag:
        flag = _flag_for(cc)
    # Manual nodes get a per-node token so sync works without a shared
    # TITAN_NODE_SECRET; the token is returned once (never re-serialized).
    token = secrets.token_hex(16)
    node = db.create_node({
        "name": name,
        "address": address,
        "city": city,
        "country": country,
        "country_code": cc,
        "flag": flag,
        "token": token,
    })
    # A fresh TiTaN node holds no credential: hand it the fleet secret over the
    # same channel we discovered it on, so the admin never pastes variables.
    if probe.get("kind") == "titan" and (probe.get("identity") or {}).get("accepts_bootstrap"):
        panel_url = ""
        try:
            panel_url = f"https://{_public_host(request)}"
        except Exception:  # noqa: BLE001
            panel_url = ""
        claim = await _claim_node(probe.get("url") or address, panel_url)
        if claim.get("ok"):
            node = db.get_node(node["id"]) or node
    db.add_event("info", "node-create", name, ip=_client_ip(request))
    # Prove the upload path right now: the admin learns whether this node can
    # really take users, instead of finding out when a config later falls back.
    node_sync = await _sync_node_now(node["id"])
    return {
        "ok": True,
        "token": token,
        "node": _serialize_node(node, await _node_status(node)),
        "sync_now": node_sync,
        "node_sync": node_sync,
        "discovery": {
            "kind": probe.get("kind"),
            "error": probe.get("error") or "",
            "identity": probe.get("identity") or {},
            "claim": claim,
        },
        "setup": _node_setup(node, token, request),
    }


@app.patch("/api/nodes/{node_id}")
async def api_update_node(node_id: int, request: Request, _: str = Depends(_require_auth)):
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(404, "not-found")
    payload = await request.json()
    fields = {}
    for k in ("name", "address", "city", "country", "country_code", "flag", "enabled"):
        if k in payload:
            fields[k] = payload[k]
    if "address" in fields:
        fields["address"] = _normalize_node_address(fields.get("address") or "")
    # auto-detect country/flag if an address is given and none is known
    # Never overwrite explicit manual values — only fill missing fields.
    effective_addr = fields.get("address") if "address" in fields else node.get("address")
    if effective_addr and not fields.get("country_code") and not fields.get("flag") and not node.get("country_code"):
        # Only auto-detect if neither the payload nor the stored node has a country code.
        # This prevents overwriting a manual selection on re-edits, but fills on first set.
        addr_for_geo = fields.get("address") or effective_addr
        try:
            loc = await asyncio.to_thread(detect_location, addr_for_geo)
        except Exception:
            loc = None
        if loc:
            fields.setdefault("city", loc.get("city", "")[:64])
            fields.setdefault("country", loc.get("country", "")[:64])
            fields.setdefault("country_code", (loc.get("country_code") or "")[:2].upper())
            fields.setdefault("flag", loc.get("flag") or _flag_for(fields.get("country_code") or ""))
    if "country_code" in fields and not fields.get("flag") and not payload.get("flag"):
        fields["flag"] = _flag_for(fields["country_code"])
    updated = db.update_node(node_id, fields)
    db.add_event("info", "node-update", str(node_id), ip=_client_ip(request))
    if any(k in fields for k in ("address", "enabled")):
        await _sync_node_now(node_id)      # re-verify after an address/enable change
    return {"ok": True, "node": _serialize_node(updated, await _node_status(updated))}


@app.delete("/api/nodes/{node_id}")
async def api_delete_node(node_id: int, request: Request, _: str = Depends(_require_auth)):
    if not db.delete_node(node_id):
        raise HTTPException(404, "not-found")
    db.add_event("warn", "node-delete", str(node_id), ip=_client_ip(request))
    return {"ok": True}


@app.post("/api/nodes/{node_id}/ping")
async def api_ping_node(node_id: int, _: str = Depends(_require_auth)):
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(404, "not-found")
    _node_status_cache.pop(node_id, None)
    db.touch_node(node_id)
    status = await _node_status(node)
    # "بررسی نود" — auto-fill city/country/country_code/flag from the node's domain
    # if the stored node is missing them. Normalize to https://host[:port] first,
    # never overwrite a manually set value.
    addr = (node.get("address") or "").strip()
    need_geo = addr and (not node.get("country_code") or not node.get("city") or not node.get("flag") or node.get("flag") == "🏳️")
    if need_geo:
        norm = _normalize_node_address(addr)
        if norm and norm != addr:
            # Persist normalized address as well (https://host[:port])
            try:
                db.update_node(node_id, {"address": norm})
                node["address"] = norm
                addr = norm
            except Exception:
                pass
        try:
            loc = await asyncio.to_thread(detect_location, addr)
        except Exception:
            loc = None
        if loc:
            patch = {}
            if not node.get("city") and loc.get("city"):
                patch["city"] = loc["city"][:64]
            if not node.get("country") and loc.get("country"):
                patch["country"] = loc["country"][:64]
            if not node.get("country_code") and loc.get("country_code"):
                patch["country_code"] = (loc["country_code"] or "")[:2].upper()
                patch["flag"] = loc.get("flag") or _flag_for(patch["country_code"])
            elif not node.get("flag") or node.get("flag") == "🏳️":
                # Fill flag if missing but country_code already known
                cc = node.get("country_code") or patch.get("country_code") or ""
                if cc:
                    patch["flag"] = _flag_for(cc)
                elif loc.get("flag"):
                    patch["flag"] = loc["flag"]
                    if not patch.get("country_code") and loc.get("country_code"):
                        patch["country_code"] = (loc["country_code"] or "")[:2].upper()
            if patch:
                try:
                    updated = db.update_node(node_id, patch)
                    if updated:
                        node = updated
                except Exception:
                    pass
    return {"ok": True, "status": status, "node": _serialize_node(node, status)}


@app.post("/api/nodes/{node_id}/sync")
async def api_sync_node_now(node_id: int, _: str = Depends(_require_auth)):
    """Push this node's users to it immediately and report the result."""
    node = db.get_node(node_id)
    if not node or node.get("is_local"):
        raise HTTPException(404, "not-found")
    if not (node.get("token") or nodesync.panel_secret(create=False)):
        raise HTTPException(400, "no-credential")
    users = db.list_users()
    node_users = sorted(
        [u for u in users if nodesync.user_node_id(u) in (node_id, 0)],
        key=lambda x: x["uid"],
    )
    ok = await nodesync.sync_node(node, node_users)
    _node_status_cache.pop(node_id, None)
    return {"ok": ok, "pushed": len(node_users) if ok else 0}


# ------------------------------------------------------------------ reports
@app.get("/api/reports")
async def api_reports(days: int = 7, _: str = Depends(_require_auth)):
    days = min(max(int(days or 7), 1), 30)
    users = db.list_users()
    totals = {"users": len(users), "active": 0, "expired": 0, "disabled": 0,
              "total_up": 0, "total_down": 0}
    protocols: dict = {}
    for u in users:
        st = _user_status(u)
        if not u["enabled"]:
            totals["disabled"] += 1
        elif st["expired"]:
            totals["expired"] += 1
        else:
            totals["active"] += 1
        totals["total_up"] += u.get("used_up") or 0
        totals["total_down"] += u.get("used_down") or 0
        protocols[u["protocol"]] = protocols.get(u["protocol"], 0) + 1

    top = sorted(users, key=lambda u: (u.get("used_up") or 0) + (u.get("used_down") or 0), reverse=True)[:6]

    day_bucket = int(time.time() // 86400) * 86400
    raw = {r["bucket"]: r for r in db.get_traffic(day_bucket - (days - 1) * 86400)}
    daily = []
    for i in range(days - 1, -1, -1):
        d = day_bucket - i * 86400
        up = down = 0
        for h in range(24):
            row = raw.get(d + h * 3600)
            if row:
                up += row["up"]
                down += row["down"]
        daily.append({"t": d, "up": up, "down": down})

    return {
        "totals": totals,
        "protocols": [{"protocol": k, "count": v} for k, v in protocols.items()],
        "daily": daily,
        "top_users": [
            {"uid": u["uid"], "name": u["name"],
             "used": (u.get("used_up") or 0) + (u.get("used_down") or 0)}
            for u in top
        ],
    }


# ------------------------------------------------------------------ admin info
@app.get("/api/admin-info")
async def api_admin_info(_: str = Depends(_require_auth)):
    admin = db.get_admin()
    last_login = None
    for e in db.list_events(limit=1000):
        if e["action"] == "login":
            last_login = e["ts"]
            break
    return {
        "username": admin["username"] if admin else None,
        "role": "ادمین کل",
        "avatar": _resolve_avatar(db.get_settings().get("admin_avatar")),
        "created_at": admin["created_at"] if admin else None,
        "last_login": last_login,
        "last_login_ip": next(
            (e["ip"] for e in db.list_events(limit=1000) if e["action"] == "login"), ""
        ),
    }


# ------------------------------------------------------------------ node coordination
@app.post("/api/node/sync")
async def api_node_sync(request: Request):
    """Node side: receive the full list of users assigned to this node and
    reconcile the local database + Xray config to match. Secret protected."""
    payload = await request.json()
    if not nodesync.secret_valid_for_node(payload.get("secret")):
        raise HTTPException(401, "bad-secret")
    if payload.get("reality"):
        reality.apply_reality_config(payload["reality"])
    users = payload.get("users") or []
    seen: set[str] = set()
    for data in users:
        uid = (data.get("uid") or "").strip()
        if not uid or not data.get("uuid"):
            continue
        seen.add(uid)
        fields = {k: data.get(k) for k in nodesync.SYNC_FIELDS if data.get(k) is not None}
        fields["uuid"] = data["uuid"]
        existing = db.get_user(uid)
        if existing:
            db.update_user(uid, fields)
        else:
            db.create_user({
                **fields,
                "uid": uid,
                "node_id": 1,  # every synced user is local to this node
                "created_at": time.time(),
            })
    # drop users that are no longer assigned to this node
    for u in db.list_users():
        if u["uid"] not in seen:
            db.delete_user(u["uid"])
            state.ACTIVE.pop(u["uid"], None)
    _reload_xray()
    return {"ok": True, "count": len(seen)}


@app.post("/api/node/usage")
async def api_node_usage(request: Request):
    """Main side: receive traffic deltas reported by a node and merge them."""
    payload = await request.json()
    if not nodesync.secret_valid_for_main(payload.get("secret")):
        raise HTTPException(401, "bad-secret")
    usage = payload.get("usage") or {}
    count = 0
    for uid, d in usage.items():
        if not isinstance(d, dict):
            continue
        up = max(0, int(d.get("up") or 0))
        down = max(0, int(d.get("down") or 0))
        if up or down:
            db.add_user_usage(uid, up, down)
            db.touch_last_seen(uid)
            count += 1
    return {"ok": True, "merged": count}


@app.post("/api/node/register")
async def api_node_register(request: Request):
    """Main side: a node self-registers with its token, announcing its public
    URL. The main panel fills the node's address and auto-detects country."""
    payload = await request.json()
    token = str(payload.get("token") or "")
    url = str(payload.get("url") or "")
    node = db.get_node_by_token(token)
    if not node:
        raise HTTPException(401, "bad-token")
    url = _clean_public_url(url)
    if not url:
        raise HTTPException(400, "missing-url")
    fields = {"address": url}
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url)
    host = host.split("/", 1)[0].rsplit("@", 1)[-1].split(":")[0].strip("[]")
    if host:
        loc = await asyncio.to_thread(detect_location, host)
        if loc:
            fields["city"] = loc.get("city", "")[:64]
            fields["country"] = loc.get("country", "")[:64]
            fields["country_code"] = loc.get("country_code", "")[:2]
            fields["flag"] = loc.get("flag", "🏳️")
    db.update_node(node["id"], fields)
    _trigger_node_sync()
    db.add_event("info", "node-register", f"{node['name']} -> {url}", ip=_client_ip(request))
    return {"ok": True, "node": _serialize_node(db.get_node(node["id"]), await _node_status(node))}


@app.get("/api/node/discover")
async def api_node_discover(request: Request):
    """Node side: identity card, so a panel can add this instance from a domain.

    Public, because the *panel* (not a browser) is the caller: it has no session
    on this service, and it has to be able to ask "what are you?" before it can
    add the node. Nothing sensitive is in the answer — app/version/role, where it
    is, how it is reachable, and whether a credential is configured yet (a boolean
    the panel must know to decide between pushing and claiming). The user count,
    the panel URL and the claim time are only returned when the caller proves it
    already holds this node's credential.
    """
    data = nodesync.identity()
    presented = (request.headers.get("x-titan-node-secret")
                 or request.query_params.get("secret") or "")
    if not nodesync.secret_valid_for_node(presented):
        for key in ("users", "panel_url", "claimed_at"):
            data.pop(key, None)
    return data


@app.post("/api/node/bootstrap")
async def api_node_bootstrap(request: Request):
    """Node side: accept the fleet secret from the panel that claims this node.

    Allowed only while this instance holds no credential at all, so the first
    panel to reach a fresh node owns it and nobody can re-claim it afterwards
    without already knowing the secret. Storing the secret here is what makes
    "give me the project domain and the node is configured" possible without
    typing variables into the node's service.
    """
    payload = await request.json()
    secret = str(payload.get("secret") or "").strip()
    panel_url = str(payload.get("panel_url") or "").strip()
    if len(secret) < 16:
        raise HTTPException(400, "secret-too-short")
    current = nodesync.node_credential()
    if current:
        if secrets.compare_digest(current, secret):
            return {"ok": True, "already": True}
        raise HTTPException(409, "node-already-claimed")
    nodesync.store_node_credential(secret, panel_url)
    db.add_event("warn", "node-claimed", f"panel={(panel_url or 'unknown')}", ip=_client_ip(request))
    log.warning("this node was claimed by %s through /api/node/bootstrap",
                panel_url or "an unknown panel")
    return {"ok": True, "claimed": True, "panel_url": panel_url}


@app.post("/api/nodes/detect")
async def api_detect_node(request: Request, _: str = Depends(_require_auth)):
    """What is behind this domain? Fills the add-node form, nothing is stored."""
    payload = await request.json()
    addr = (payload.get("address") or "").strip()
    if not addr:
        raise HTTPException(400, "address-required")
    probe = await _probe_node_identity(addr)
    identity = probe.get("identity") or {}
    return {
        "ok": probe["kind"] == "titan",
        "kind": probe["kind"],
        "url": probe.get("url") or "",
        "error": probe.get("error") or "",
        "fields": _discovery_fields(identity),
        "identity": identity,
        "needs_credentials": bool(identity) and not identity.get("credential"),
        "can_claim": bool(identity.get("accepts_bootstrap")),
    }


@app.post("/api/nodes/{node_id}/claim")
async def api_claim_node(node_id: int, request: Request, _: str = Depends(_require_auth)):
    """Discover + claim + verify an already-added node, in one call."""
    node = db.get_node(node_id)
    if not node or node.get("is_local"):
        raise HTTPException(404, "not-found")
    addr = (node.get("address") or "").strip()
    if not addr:
        raise HTTPException(400, "address-required")
    probe = await _probe_node_identity(addr)
    identity = probe.get("identity") or {}
    claim: dict = {}
    if probe["kind"] == "titan":
        fields = _discovery_fields(identity)
        if fields:
            db.update_node(node_id, fields)
        if identity.get("accepts_bootstrap"):
            panel_url = ""
            try:
                panel_url = f"https://{_public_host(request)}"
            except Exception:  # noqa: BLE001
                panel_url = ""
            claim = await _claim_node(probe.get("url") or addr, panel_url)
    node = db.get_node(node_id)
    node_sync = await _sync_node_now(node_id)
    _node_status_cache.pop(node_id, None)
    db.add_event("info", "node-claim", f"{node_id}: {probe['kind']}", ip=_client_ip(request))
    return {
        "ok": node_sync.get("ok", False),
        "kind": probe["kind"],
        "identity": identity,
        "claim": claim,
        "node_sync": node_sync,
        "node": _serialize_node(node, await _node_status(node)),
    }

@app.post("/api/nodes/invite")
async def api_invite_node(request: Request, _: str = Depends(_require_auth)):
    """Main side: issue a one-time credential for a new node (quick setup)."""
    payload = await request.json()
    name = (payload.get("name") or "Node").strip()[:64] or "Node"
    token = secrets.token_hex(16)
    node = db.create_node({"name": name, "token": token, "enabled": True})
    db.add_event("info", "node-invite", name, ip=_client_ip(request))
    return {"ok": True, "token": token, "node": _serialize_node(node, await _node_status(node))}


def _clean_public_url(raw: str) -> str:
    return _normalize_node_address(raw)


# ------------------------------------------------------- node auto-detection
def _discover_candidates(addr: str) -> list[str]:
    """URLs to try, most likely first, for a node handed over as a domain."""
    raw = (addr or "").strip().rstrip("/")
    if not raw:
        return []
    if raw.startswith("http://"):
        return [raw]
    if raw.startswith("https://"):
        return [raw, "http://" + raw[len("https://"):]]
    return ["https://" + raw, "http://" + raw]


async def _probe_node_identity(addr: str, timeout: float = 6.0) -> dict:
    """Ask a domain what it is. Never raises: returns a verdict instead.

    ``kind`` is ``titan`` (it answered with our own identity card), ``foreign``
    (something answered, but not a TiTaN instance) or ``unreachable``.
    """
    out = {"kind": "unreachable", "url": "", "identity": {}, "error": ""}
    tried = []
    for base in _discover_candidates(addr):
        url = base + "/api/node/discover"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cl:
                r = await cl.get(url, headers={"User-Agent": "TiTaN-panel",
                                               "X-TiTaN-Node-Secret": nodesync.panel_secret(create=False)})
            tried.append(f"{base} -> HTTP {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and (data.get("app") == "titan" or data.get("role")):
                    out.update({"kind": "titan", "url": base, "identity": data})
                    return out
                out.update({"kind": "foreign", "url": base, "error": "not-a-titan-node"})
                return out
        except Exception as e:  # noqa: BLE001
            tried.append(f"{base} -> {type(e).__name__}")
    out["error"] = "; ".join(tried[-3:]) or "unreachable"
    return out


async def _claim_node(addr_url: str, panel_url: str, timeout: float = 8.0) -> dict:
    """Hand this node the fleet secret so it can serve users right away.

    Trust on first use: only a node that holds *no* credential accepts a claim,
    so the first panel to reach a fresh node owns it. A node that already has
    one answers 409 and the panel falls back to showing the variables instead.
    """
    secret = nodesync.panel_secret()      # minted on first need
    if not secret:
        return {"ok": False, "error": "panel-has-no-shared-secret"}
    payload = {"secret": secret, "panel_url": (panel_url or "").rstrip("/")}
    url = addr_url.rstrip("/") + "/api/node/bootstrap"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as cl:
            r = await cl.post(url, json=payload, headers={"User-Agent": "TiTaN-panel"})
        if r.status_code == 200:
            data = r.json() if r.text else {}
            return {"ok": True, "claimed": bool(data.get("claimed")), "already": bool(data.get("already"))}
        if r.status_code == 409:
            return {"ok": False, "error": "node-already-claimed"}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__}


def _discovery_fields(identity: dict) -> dict:
    """Node columns the identity card can fill in (never overwrites with blanks)."""
    fields = {}
    for key in ("name", "city", "country", "flag"):
        value = (identity.get(key) or "").strip()
        if value and value not in ("—", "🏳️"):
            fields[key] = value[:64]
    cc = (identity.get("country_code") or "").strip().upper()
    if len(cc) == 2:
        fields["country_code"] = cc
        fields.setdefault("flag", _flag_for(cc))
    return fields


# ------------------------------------------------------------- subscriptions
def _sub_items(raw) -> list:
    """Normalise stored items to ``[{"uid": ..., "configs": [...]}]``."""
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("uid") or "").strip()
        if not uid:
            continue
        configs = [str(c).strip().lower() for c in (entry.get("configs") or []) if str(c).strip()]
        out.append({"uid": uid, "configs": configs})
    return out


def _sub_status_of(user: dict) -> dict:
    try:
        return _user_status(user)
    except Exception:  # noqa: BLE001
        return {}


def _sub_catalog(request: Request, users: list | None = None) -> list:
    """Every user and every config that user could contribute to a link.

    One call renders the whole builder: users, their live state, and the configs
    the server would really hand out for each of them (same pipeline as the
    links themselves, so the builder can never offer something that does not
    exist).
    """
    out = []
    for u in (users if users is not None else db.list_users()):
        st = _sub_status_of(u)
        entries = _sub_entries(u, request)
        picked = set(_sub_selection(u))
        out.append({
            "uid": u["uid"],
            "name": u["name"],
            "protocol": u["protocol"],
            "enabled": bool(u.get("enabled")),
            "node_id": u.get("node_id"),
            "expired": bool(st.get("expired")),
            # the picture, so the builder shows who is who (and can change it)
            "avatar": u.get("avatar") or "",
            "avatar_url": _resolve_avatar(u.get("avatar") or "")["url"],
            "configs": [{
                "key": e["key"],
                "label": e["label"],
                "transport": e["transport"],
                "security": e["security"],
                "target": e["target"],
                "host": e["host"],
            } for e in entries],
            "personal_pick": sorted(picked),
        })
    return out


def _sub_included(sub: dict, users_by_uid: dict, request: Request) -> list:
    """The concrete links a subscription link serves, after every filter."""
    items = _sub_items(sub.get("items"))
    links: list = []
    seen: set = set()
    for item in items:
        user = users_by_uid.get(item["uid"])
        if not user or not user.get("enabled"):
            continue
        entries = _sub_entries(user, request)
        if item["configs"]:
            chosen = [e for e in entries if e["key"] in set(item["configs"])]
        else:
            chosen = entries
        for e in chosen:
            if e["link"] not in seen:
                seen.add(e["link"])
                links.append(e["link"])
    return links


def _sub_link_url(sub: dict, request: Request) -> str:
    host = _public_host(request)
    scheme = "http" if host.startswith(("127.", "localhost")) else "https"
    return f"{scheme}://{host}/s/{sub['token']}"


@functools.lru_cache(maxsize=1)
def _subscription_page_html() -> str:
    """The uploaded design, read once (4.5 MB of inlined assets)."""
    with open(os.path.join(BASE_DIR, "templates", "subscription.html"), encoding="utf-8") as fh:
        return fh.read()


def _avatar_path(key: str) -> str:
    """Filesystem path of an avatar key — the public page cannot use /api/..."""
    key = _sanitize_avatar_key(key)
    if not key:
        return ""
    kind, _, name = key.partition(":")
    if kind == "gallery":
        return os.path.join(BASE_DIR, "static", "img", "gallery", f"{name}.svg")
    if kind == "upload":
        return os.path.join(_gallery_upload_dir(), os.path.basename(name))
    return ""


def _looks_like_browser(request: Request) -> bool:
    """True when a *person* opened the subscription link in a browser.

    Clients importing a subscription send `Accept: */*` (never `text/html`) and
    none of the `Sec-Fetch-*` headers, so the Accept check alone already splits
    the two audiences; `Sec-Fetch-Mode/Dest` — sent by every current browser —
    makes it exact where they are available. `?raw=1` forces the plain payload.
    """
    if (request.query_params.get("raw") or "").strip().lower() in ("1", "true", "raw"):
        return False
    if "text/html" not in (request.headers.get("accept") or ""):
        return False
    mode = (request.headers.get("sec-fetch-mode") or "").lower()
    dest = (request.headers.get("sec-fetch-dest") or "").lower()
    if mode or dest:
        return mode == "navigate" or dest == "document"
    return "mozilla" in (request.headers.get("user-agent") or "").lower()


def _sub_page_url(sub: dict, request: Request) -> str:
    """The human link: the page a user opens (the raw link stays /s/<token>)."""
    host = _public_host(request)
    scheme = "http" if host.startswith(("127.", "localhost")) else "https"
    return f"{scheme}://{host}/p/{sub['token']}"


def _serialize_subscription(sub: dict, request: Request, users: list | None = None) -> dict:
    users = users if users is not None else db.list_users()
    by_uid = {u["uid"]: u for u in users}
    items = _sub_items(sub.get("items"))
    links = _sub_included(sub, by_uid, request)
    named = [{"uid": i["uid"],
              "name": (by_uid.get(i["uid"]) or {}).get("name") or i["uid"],
              "configs": i["configs"]} for i in items]
    return {
        "id": sub["id"],
        "name": sub.get("name") or f"Subscription {sub['id']}",
        "enabled": bool(sub.get("enabled")),
        "token": sub["token"],
        "url": _sub_link_url(sub, request),
        "items": named,
        "users": len(named),
        "configs": len(links),
        "missing": [i["uid"] for i in items if i["uid"] not in by_uid],
        "note": sub.get("note") or "",
        "plan": sub.get("plan") or "",
        "avatar": sub.get("avatar") or "",
        "avatar_url": _resolve_avatar(sub.get("avatar") or "")["url"],
        "page_url": _sub_page_url(sub, request),
        "hits": int(sub.get("hits") or 0),
        "last_used": sub.get("last_used") or 0,
        "created_at": sub.get("created_at") or 0,
    }


def _sub_payload_items(payload: dict, users_by_uid: dict, request: Request) -> list:
    """Validate the builder's selection against what each user can really offer."""
    raw = payload.get("items")
    if raw is None:
        return []
    out = []
    for entry in _sub_items(raw):
        user = users_by_uid.get(entry["uid"])
        if not user:
            continue
        available = {e["key"] for e in _sub_entries(user, request)}
        picked = [c for c in entry["configs"] if c in available]
        out.append({"uid": entry["uid"], "configs": picked})
    return out


def _sub_headers_multi(name: str, users: list) -> dict:
    used_up = sum(int(u.get("used_up") or 0) for u in users)
    used_down = sum(int(u.get("used_down") or 0) for u in users)
    total = sum(int(u.get("quota_bytes") or 0) for u in users)
    expire = max([int(u.get("expire_at") or 0) for u in users] or [0])
    info = f"upload={used_up}; download={used_down}; total={total}; expire={expire}"
    return {
        "Content-Type": "text/plain; charset=utf-8",
        "Subscription-Userinfo": info,
        "subscription-userinfo": info,
        "Profile-Update-Interval": "1",
        "profile-update-interval": "1",
        "Profile-Title": "base64:" + base64.b64encode(name.encode()).decode(),
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Powered-By": "TiTaN",
    }


def _sub_status_link(name: str, users: list) -> str:
    used_bytes = sum((u.get("used_up") or 0) + (u.get("used_down") or 0) for u in users)
    quota_bytes = sum(u.get("quota_bytes") or 0 for u in users)
    remark = f"TiTaN {name} | {volume_text(used_bytes, quota_bytes)} | {len(users)} users"
    return ("vless://00000000-0000-0000-0000-000000000001@127.0.0.1:10001?"
            f"encryption=none&security=none&type=tcp&headerType=none#{quote(remark)}")


def _sub_body(sub: dict, request: Request) -> tuple:
    """(base64 body, included users) for one subscription link."""
    users = db.list_users()
    by_uid = {u["uid"]: u for u in users}
    included = [by_uid[i["uid"]] for i in _sub_items(sub.get("items")) if i["uid"] in by_uid]
    links = [_sub_status_link(sub.get("name") or "TiTaN", included)] + _sub_included(
        sub, by_uid, request)
    return subscription_text(links), included


async def _dispatch_subscription(token: str, request: Request, fmt: str):
    sub = db.get_subscription_by_token(token)
    if not sub:
        raise HTTPException(404, "not-found")
    if not sub.get("enabled"):
        raise HTTPException(403, "subscription-disabled")
    db.touch_subscription(sub["id"])
    body, users = _sub_body(sub, request)
    headers = _sub_headers_multi(sub.get("name") or "TiTaN", users)
    headers["Profile-Web-Page-Url"] = _sub_page_url(sub, request)
    headers["profile-web-page-url"] = headers["Profile-Web-Page-Url"]
    if fmt == "json":
        payload = _sub_page_data(sub, request, users)
        payload["users"] = [{"uid": u["uid"], "name": u["name"]} for u in users]
        payload["links"] = _sub_included(sub, {u["uid"]: u for u in users}, request)
        return JSONResponse(payload, headers=headers)
    # Same shape as the personal link (/sub/{uid}): the plain path answers with
    # the base64 payload every client already parses, /json is for debugging.
    return Response(content=body, media_type="text/plain", headers=headers)


# ------------------------------------------------------------------ subscriptions
@app.get("/api/subscriptions")
async def api_list_subscriptions(request: Request, _: str = Depends(_require_auth)):
    users = db.list_users()
    subs = [_serialize_subscription(s, request, users) for s in db.list_subscriptions()]
    return {"ok": True, "subscriptions": subs, "count": len(subs)}


@app.get("/api/subscriptions/catalog")
async def api_subscriptions_catalog(request: Request, _: str = Depends(_require_auth)):
    """Everything the builder needs: users x the configs each one can contribute."""
    return {"ok": True, "users": _sub_catalog(request), "subscriptions": [
        _serialize_subscription(s, request) for s in db.list_subscriptions()]}


@app.post("/api/subscriptions")
async def api_create_subscription(request: Request, _: str = Depends(_require_auth)):
    payload = await request.json()
    name = (payload.get("name") or "").strip()[:64] or "Subscription"
    users_by_uid = {u["uid"]: u for u in db.list_users()}
    items = _sub_payload_items(payload, users_by_uid, request)
    if not items:
        raise HTTPException(400, "no-configs-selected")
    token = secrets.token_urlsafe(18)
    sub = db.create_subscription(name, token, items,
                                 note=(payload.get("note") or "")[:200],
                                 enabled=payload.get("enabled", True) is not False,
                                 avatar=_sanitize_avatar_key(payload.get("avatar") or ""),
                                 plan=(payload.get("plan") or "").strip()[:48])
    db.add_event("info", "sub-create", f"{name} ({len(items)} users)", ip=_client_ip(request))
    return {"ok": True, "subscription": _serialize_subscription(sub, request, list(users_by_uid.values()))}


@app.patch("/api/subscriptions/{sub_id}")
async def api_update_subscription(sub_id: int, request: Request, _: str = Depends(_require_auth)):
    sub = db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, "not-found")
    payload = await request.json()
    fields: dict = {}
    if "name" in payload:
        fields["name"] = (payload.get("name") or "").strip()[:64] or sub["name"]
    if "note" in payload:
        fields["note"] = (payload.get("note") or "")[:200]
    if "plan" in payload:
        fields["plan"] = (payload.get("plan") or "").strip()[:48]
    if "avatar" in payload:
        fields["avatar"] = _sanitize_avatar_key(payload.get("avatar") or "")
    if "enabled" in payload:
        fields["enabled"] = bool(payload["enabled"])
    if "items" in payload:
        users_by_uid = {u["uid"]: u for u in db.list_users()}
        fields["items"] = _sub_payload_items(payload, users_by_uid, request)
    updated = db.update_subscription(sub_id, fields)
    db.add_event("info", "sub-update", f"{sub_id}: {sub.get('name')}", ip=_client_ip(request))
    return {"ok": True, "subscription": _serialize_subscription(updated, request)}


@app.delete("/api/subscriptions/{sub_id}")
async def api_delete_subscription(sub_id: int, request: Request, _: str = Depends(_require_auth)):
    if not db.delete_subscription(sub_id):
        raise HTTPException(404, "not-found")
    db.add_event("warn", "sub-delete", str(sub_id), ip=_client_ip(request))
    return {"ok": True}


@app.get("/api/subscriptions/{sub_id}/qr")
async def api_subscription_qr(sub_id: int, request: Request, _: str = Depends(_require_auth)):
    sub = db.get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, "not-found")
    img = qrcode.make(_sub_link_url(sub, request), border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/s/{token}")
async def sub_link(token: str, request: Request):
    """One address, two faces: raw configs for a client, the page for a person."""
    if _looks_like_browser(request):
        return await sub_page(token, request)
    return await _dispatch_subscription(token, request, "plain")


@app.get("/s/{token}/base64")
async def sub_link_base64(token: str, request: Request):
    return await _dispatch_subscription(token, request, "base64")


def _sub_page_data(sub: dict, request: Request, users: list, include_links: bool = True) -> dict:
    """Everything the public page shows, for one subscription link.

    One call, one shape: the profile the admin set for this link (its own picture
    and label, falling back to the user's), the usage/expiry carried by the users
    inside it, and the exact configs it serves — each with the place it lands in
    and the link a client would connect with.
    """
    items = _sub_items(sub.get("items"))
    by_uid = {u["uid"]: u for u in users}
    ordered = [by_uid[i["uid"]] for i in items if i["uid"] in by_uid]
    links = _sub_included(sub, by_uid, request)
    per_user = {u["uid"]: _sub_entries(u, request) for u in ordered}

    configs = []
    for item in items:
        user = by_uid.get(item["uid"])
        if not user or not user.get("enabled"):
            continue
        entries = per_user.get(item["uid"]) or []
        chosen = [e for e in entries if e["key"] in set(item["configs"])] if item["configs"] else entries
        for e in chosen:
            if e["link"] not in links:
                continue
            configs.append(e)
    counter: dict = {}
    shown = []
    for e in configs:
        cc = (e.get("country_code") or "").lower()
        counter[cc] = counter.get(cc, 0) + 1
        shown.append({
            "country_code": cc or "un",
            "flag": e.get("flag") or "",
            "city": e.get("city") or "",
            "place": e.get("place") or "",
            "name": f"TiTaN-{(cc or 'UN').upper()}-{counter[cc]:02d}",
            "protocol": e.get("protocol") or "",
            "transport": e.get("transport") or "",
            "security": e.get("security") or "",
            "target": e.get("target") or "panel",
            "label": e.get("label") or "",
            "link": e["link"],
        })

    # Usage of the whole link: the users it carries, summed. The expiry is the
    # soonest one — the moment the link stops working for the client.
    used = sum(int(u.get("used_up") or 0) + int(u.get("used_down") or 0) for u in ordered)
    total = sum(int(u.get("quota_bytes") or 0) for u in ordered)
    expiries = [int(u.get("expire_at") or 0) for u in ordered if u.get("expire_at")]
    expire_at = min(expiries) if expiries else 0
    now = time.time()
    days_left = max(0, int((expire_at - now) // 86400)) if expire_at else None
    live = [u for u in ordered if _user_status(u)["live_enabled"]]
    remaining = max(0, total - used) if total > 0 else 0

    avatar_key = (sub.get("avatar") or "").strip()
    if not avatar_key and len(ordered) == 1:
        avatar_key = (ordered[0].get("avatar") or "").strip()
    profile_name = (sub.get("name") or "").strip()
    if not profile_name or profile_name.lower() == "subscription":
        profile_name = (ordered[0].get("name") if ordered else "") or "TiTaN"

    if not include_links:
        # A switched-off link: the profile and the numbers are still the truth
        # about it, the configs and the subscription URL are not handed over.
        shown = []
    return {
        "name": sub.get("name"),
        "plan": sub.get("plan") or "",
        "profile": {
            "name": profile_name,
            "avatar": f"/s/{sub['token']}/avatar" if avatar_key else "",
            "key": avatar_key,
            "kind": "subscription" if (sub.get("avatar") or "").strip() else "user",
        },
        "subscription": {
            "name": sub.get("name") or "",
            "enabled": bool(sub.get("enabled")),
            "token": sub["token"],
            "url": _sub_link_url(sub, request) if include_links else "",
            "page_url": _sub_page_url(sub, request),
            "serves_links": include_links,
            "created_at": sub.get("created_at") or 0,
            "hits": int(sub.get("hits") or 0),
        },
        "usage": {
            "used_bytes": used,
            "used_up": sum(int(u.get("used_up") or 0) for u in ordered),
            "used_down": sum(int(u.get("used_down") or 0) for u in ordered),
            "total_bytes": total,
            "remaining_bytes": remaining,
            "used_pct": round((used / total) * 100, 2) if total > 0 else 0,
            "remaining_pct": round((remaining / total) * 100, 2) if total > 0 else 0,
            "expire_at": expire_at,
            "days_left": days_left,
            "active": bool(live),
            "users": len(ordered),
            "live_users": len(live),
        },
        "configs": shown,
        "users": [{"uid": u["uid"], "name": u["name"], "enabled": bool(u.get("enabled"))}
                  for u in ordered],
        "counts": {"configs": len(shown), "users": len(ordered)},
        "support": {"github": config.GITHUB_URL, "telegram": config.SUPPORT_URL},
    }


@app.get("/p/{token}")
@app.get("/p/{token}/")
async def sub_page(token: str, request: Request):
    """The subscription *page* — what the admin sends a user to open."""
    sub = db.get_subscription_by_token(token)
    if not sub:
        raise HTTPException(404, "not-found")
    return HTMLResponse(
        _subscription_page_html(),
        headers={"Cache-Control": "no-store, must-revalidate", "X-Powered-By": "TiTaN"},
    )


@app.get("/p/{token}/data")
async def sub_page_data(token: str, request: Request):
    """What the page shows for this link — works before it is switched on, too."""
    sub = db.get_subscription_by_token(token)
    if not sub:
        raise HTTPException(404, "not-found")
    items = _sub_items(sub.get("items"))
    wanted = {i["uid"] for i in items}
    users = [u for u in db.list_users() if u["uid"] in wanted]
    if sub.get("enabled"):
        db.touch_subscription(sub["id"])
    return JSONResponse(
        _sub_page_data(sub, request, users, include_links=bool(sub.get("enabled"))),
        headers={"Cache-Control": "no-store, must-revalidate", "X-Powered-By": "TiTaN"},
    )


@app.get("/s/{token}/avatar")
async def sub_avatar(token: str, request: Request):
    """The profile picture of a link, on a path a client-less browser can load."""
    sub = db.get_subscription_by_token(token)
    if not sub:
        raise HTTPException(404, "not-found")
    key = (sub.get("avatar") or "").strip()
    if not key:
        users = [u for u in db.list_users() if u.get("uid") in {i["uid"] for i in _sub_items(sub.get("items"))}]
        if len(users) == 1:
            key = (users[0].get("avatar") or "").strip()
    path = _avatar_path(key)
    if not path or not os.path.exists(path):
        path = os.path.join(BASE_DIR, "static", "img", "titan-avatar.svg")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})


@app.get("/s/{token}/json")
async def sub_link_json(token: str, request: Request):
    return await _dispatch_subscription(token, request, "json")


@app.get("/sub/{uid}")
async def sub_plain(uid: str, request: Request):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    links = _links_for(user, request)
    combined = [c["link"] for c in links["info"]] + _sub_links(user, request)
    body = subscription_text(combined)
    headers = _sub_headers(user)
    return Response(content=body, media_type="text/plain", headers=headers)


@app.get("/sub/{uid}/json")
async def sub_json(uid: str, request: Request):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    links = _links_for(user, request)
    st = _user_status(user)
    return JSONResponse({
        "name": user["name"],
        "uid": uid,
        "enabled": st["live_enabled"],
        "protocol": user["protocol"],
        "quota_gb": round((user.get("quota_bytes") or 0) / (1024 ** 3), 3),
        "used_gb": round(st["used"] / (1024 ** 3), 3),
        "days_left": st["days_left"],
        "active_connections": st["active_connections"],
        "links": _sub_links(user, request),
        "main_link": links["main"],
    }, headers=_sub_headers(user))


@app.get("/sub/{uid}/base64")
async def sub_base64(uid: str, request: Request):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    links = _links_for(user, request)
    combined = [c["link"] for c in links["info"]] + _sub_links(user, request)
    return PlainTextResponse(subscription_text(combined), headers=_sub_headers(user))


def _sub_headers(user: dict) -> dict:
    used_up = int(user.get("used_up") or 0)
    used_down = int(user.get("used_down") or 0)
    total = int(user.get("quota_bytes") or 0)
    expire = int(user.get("expire_at") or 0)
    info = f"upload={used_up}; download={used_down}; total={total}; expire={expire}"
    return {
        "Content-Type": "text/plain; charset=utf-8",
        "Subscription-Userinfo": info,
        "subscription-userinfo": info,
        "Profile-Update-Interval": "1",
        "profile-update-interval": "1",
        "Profile-Title": "base64:" + base64.b64encode(user["name"].encode()).decode(),
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Powered-By": "TiTaN",
    }


# ------------------------------------------------------------------ public status
@app.get("/api/status/{uid}")
async def api_public_status(uid: str):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "not-found")
    st = _user_status(user)
    return {
        "name": user["name"],
        "enabled": st["live_enabled"],
        "protocol": user["protocol"],
        "quota_gb": round((user.get("quota_bytes") or 0) / (1024 ** 3), 4),
        "used_gb": round(st["used"] / (1024 ** 3), 4),
        "days_left": st["days_left"],
        "active_connections": st["active_connections"],
    }


# ------------------------------------------------------------------ system
@app.get("/healthz")
async def healthz(request: Request):
    """Ultra-fast liveness probe for Railway healthcheck - no DB, no WG.

    `listen_host`/`listen_port` are the panel's own socket. `edge_port` is the
    port nginx received the connection on (nginx forwards it as a request header
    - `proxy_set_header` does not touch the client response, so the panel has to
    echo it). Because the panel only answers if the whole chain worked, that one
    number is what makes "the platform edge reached us on a port nobody expected"
    visible from a single curl instead of a support round-trip.
    """
    return {"status": "ok", "ts": time.time(), "version": APP_VERSION,
            "listen_host": config.PANEL_HOST, "listen_port": config.PANEL_PORT,
            "edge_port": request.headers.get("x-titan-listen-port") or ""}

@app.get("/health")
async def health():
    # keep DB-backed for node sync verification, but never block healthz
    try:
        users = len(db.list_users())
    except Exception:
        users = -1
    try:
        wg_pub = wg.server_public_key()
    except Exception:
        wg_pub = ""
    return {
        "status": "ok",
        "ts": time.time(),
        "version": APP_VERSION,
        "wg_pub": wg_pub,
        "users": users,
    }


@app.get("/api/stats")
async def api_stats(_: str = Depends(_require_auth)):
    cpu = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(config.DATA_DIR)
    totals = db.get_totals()
    started = float(db.get_meta("created_at") or time.time())
    active_now = state.total_active()
    recent = db.count_recently_seen(60)

    now_bucket = int(time.time() // 3600) * 3600
    raw = {r["bucket"]: r for r in db.get_traffic(now_bucket - 23 * 3600)}
    hourly = []
    for i in range(23, -1, -1):
        b = now_bucket - i * 3600
        row = raw.get(b)
        hourly.append({
            "t": b,
            "up": row["up"] if row else 0,
            "down": row["down"] if row else 0,
        })

    # count events in the last 24h (for the header notification badge)
    day_ago = time.time() - 86400
    events_today = sum(1 for e in db.list_events(limit=1000) if e["ts"] >= day_ago)
    nodes = db.list_nodes()

    return {
        "cpu_percent": cpu,
        "mem_percent": mem.percent,
        "mem_used_mb": round(mem.used / 1048576, 1),
        "mem_total_mb": round(mem.total / 1048576, 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "uptime_seconds": time.time() - started,
        "total_up": totals["up"],
        "total_down": totals["down"],
        "users_count": totals["count"],
        "enabled_count": sum(1 for u in db.list_users() if u["enabled"]),
        "active_connections": active_now,
        "recently_active": recent,
        "nodes_count": len(nodes),
        "events_today": events_today,
        "hourly": hourly,
        "location": describe_colo(bg.LOCATION.get("colo")),
        "xray_installed": xray.xray_available(),
        "xray_running": xray.xray_running(),
        "app_version": APP_VERSION,
    }


@app.get("/api/events")
async def api_events(level: str | None = None, limit: int = 200,
                     _: str = Depends(_require_auth)):
    return {"events": db.list_events(limit=min(limit, 1000), level=level)}


@app.delete("/api/events")
async def api_clear_events(_: str = Depends(_require_auth)):
    db.clear_events()
    return {"ok": True}


@app.get("/api/backup")
async def api_backup_download(_: str = Depends(_require_auth)):
    raw = db.backup_bytes()
    payload = gzip.compress(raw)
    b64 = base64.b64encode(payload).decode()
    return PlainTextResponse(b64, headers={
        "Content-Disposition": f'attachment; filename="titan-backup-{time.strftime("%Y%m%d-%H%M%S")}.db.gz.b64"',
        "Content-Type": "application/octet-stream",
    })


@app.post("/api/backup/restore")
async def api_backup_restore(file: UploadFile, _: str = Depends(_require_auth)):
    content = await file.read()
    try:
        text = content.decode("ascii").strip()
        payload = base64.b64decode(text)
        raw = gzip.decompress(payload)
    except Exception:  # noqa: BLE001
        # maybe it was uploaded as a raw sqlite file
        raw = content
    if not raw.startswith(b"SQLite"):
        raise HTTPException(400, "invalid-backup")
    db.replace_db(raw)
    _reload_xray()
    db.add_event("warn", "restore", "database restored from backup")
    return {"ok": True}


@app.post("/api/restart")
async def api_restart(_: str = Depends(_require_auth)):
    async def _delayed():
        await asyncio.sleep(1.5)
        os._exit(87)

    _spawn(_delayed(), name="restart")
    return {"ok": True, "restarting": True}


@app.api_route("/dns-query", methods=["GET", "POST", "OPTIONS"])
async def doh_endpoint(request: Request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_cors_headers())
    try:
        if request.method == "POST":
            body = await request.body()
            ct = request.headers.get("content-type", "application/dns-message")
            try:
                r = await doh_client.post(DOH_PRIMARY, content=body, headers={"content-type": ct})
            except Exception:  # noqa: BLE001
                r = await doh_client.post(DOH_SECONDARY, content=body, headers={"content-type": ct})
        else:
            params = dict(request.query_params)
            try:
                r = await doh_client.get(DOH_PRIMARY, params=params)
            except Exception:  # noqa: BLE001
                r = await doh_client.get(DOH_SECONDARY, params=params)
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/dns-message"),
            headers=_cors_headers(),
        )
    except Exception:  # noqa: BLE001
        return Response(content=b"", status_code=502)


def _cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept",
    }


# ------------------------------------------------------------------ entrypoint
def _listen_sockets(hosts, port):
    """Open one listening socket per address, or explain why not.

    Not loopback-only: whoever routes to us may sit in another netns (a platform
    proxy) or be a VPS client hitting the panel port directly. Not one family
    either: a platform edge that dials a family the panel does not serve is
    indistinguishable from a dead app ("Application failed to respond" with a
    healthy container behind it) - uvicorn's own `--host ::` would not help,
    because asyncio sets IPV6_V6ONLY on the socket it binds.
    """
    import socket as _socket

    opened = []
    for host in hosts:
        family = _socket.AF_INET6 if ":" in host else _socket.AF_INET
        sock = _socket.socket(family, _socket.SOCK_STREAM)
        if family == _socket.AF_INET6:
            try:
                sock.setsockopt(_socket.IPPROTO_IPV6, _socket.IPV6_V6ONLY, 1)
            except OSError:  # pragma: no cover - platform dependent
                pass
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(2048)
        except OSError as exc:
            sock.close()
            log.warning("routing: cannot bind %s:%s (%s) - continuing without it",
                        host, port, exc)
            continue
        opened.append(sock)
    if not opened:
        log.error("routing: nothing bound on port %s - exiting so the platform restarts us",
                  port)
        raise SystemExit(1)
    log.info("routing: panel bound on %s (port %s, platform PORT=%s)",
             ", ".join(sorted(s.getsockname()[0] for s in opened)), port, config.PUBLIC_PORT)
    return opened


if __name__ == "__main__":
    import uvicorn

    # The *port* stays PANEL_PORT: entrypoint.sh puts nginx on $PORT and forwards
    # it here, or - with no nginx in the image - exports PANEL_PORT=$PORT itself.
    log.info("routing: panel=%s:%s (platform PORT=%s)",
             ",".join(config.PANEL_BIND_HOSTS), config.PANEL_PORT, config.PUBLIC_PORT)
    uvicorn.Server(uvicorn.Config(
        "app.main:app",
        host=config.PANEL_HOST,
        port=config.PANEL_PORT,
        log_level="info",
        # uvicorn defaults to proxy_headers=True with forwarded_allow_ips
        # "127.0.0.1", which rewrites request.client from X-Forwarded-For. Since
        # nginx is the only peer, that made the *raw* peer address attacker
        # controlled too - the panel parses XFF itself (see _client_ip), so the
        # middleware must not do it a second time.
        proxy_headers=False,
    )).run(sockets=_listen_sockets(config.PANEL_BIND_HOSTS, config.PANEL_PORT))
