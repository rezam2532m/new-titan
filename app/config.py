"""Runtime configuration derived from environment variables."""
import os
import socket

# Directory that holds the SQLite DB and generated Xray config.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("TITAN_DATA_DIR", os.path.join(BASE_DIR, "data"))

def _usable_data_dir(path: str) -> str:
    """A data dir we can actually write to - or a loud downgrade instead of a crash.

    The very first thing boot does is open the SQLite file, so an unwritable
    `TITAN_DATA_DIR` (a Volume mounted at the wrong path, or read-only) used to
    raise before anything could answer the healthcheck: the platform then shows a
    generic "Application failed to respond" and the real reason is only in the
    logs. Boot anyway, say why, and make the persistence loss visible.
    """
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".titan-write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return path
    except OSError as exc:
        import logging
        import tempfile
        fallback = tempfile.mkdtemp(prefix="titan-data-")
        logging.getLogger("titan.config").error(
            "data dir %s is unusable (%s); falling back to %s. The panel will boot and "
            "stay reachable, but users and settings will NOT survive a restart: mount "
            "the Volume at /app/data or point TITAN_DATA_DIR at a writable path.",
            path, exc, fallback)
        return fallback


DATA_DIR = _usable_data_dir(DATA_DIR)
DB_PATH = os.environ.get("TITAN_DB_PATH", os.path.join(DATA_DIR, "titan.db"))
XRAY_CONFIG_PATH = os.environ.get(
    "TITAN_XRAY_CONFIG", "/usr/local/bin/config.json"
)

# Public port of the container (Railway/Render inject PORT). Nginx listens here.
PUBLIC_PORT = int(os.environ.get("PORT", "8000"))

# Ports for the internal services (localhost only).
PANEL_PORT = int(os.environ.get("PANEL_PORT", "10000"))


def _ipv6_available() -> bool:
    """True when this kernel can bind an IPv6 socket at all."""
    try:
        probe = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        probe.bind(("::", 0))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _panel_hosts() -> list:
    """Every address family the panel must answer on.

    Serving one family is invisible from inside the container: a healthcheck on
    127.0.0.1 passes, the logs stay clean, and the admin sees only "Application
    failed to respond" from the platform edge, which may be dialling the other
    family. So the panel binds both whenever the kernel offers both.

    They are two sockets, not one v4-mapped socket: asyncio sets IPV6_V6ONLY on
    the socket it binds, so `uvicorn --host ::` is IPv6-*only* - the trap that
    turns "add IPv6 support" into "IPv4 stops working". See app.main.
    """
    explicit = (os.environ.get("PANEL_HOST") or "").strip()
    if explicit:
        return [explicit]
    return ["0.0.0.0", "::"] if _ipv6_available() else ["0.0.0.0"]


PANEL_BIND_HOSTS = _panel_hosts()
#: The primary address, for logs (the full list is above).
PANEL_HOST = PANEL_BIND_HOSTS[0]
XRAY_VLESS_WS_PORT = int(os.environ.get("XRAY_VLESS_WS_PORT", "10001"))
XRAY_VMESS_WS_PORT = int(os.environ.get("XRAY_VMESS_WS_PORT", "10002"))
XRAY_TROJAN_WS_PORT = int(os.environ.get("XRAY_TROJAN_WS_PORT", "10003"))
XRAY_XHTTP_PORT = int(os.environ.get("XRAY_XHTTP_PORT", "10004"))
XRAY_GRPC_PORT = int(os.environ.get("XRAY_GRPC_PORT", "10005"))
XRAY_SS_PORT = int(os.environ.get("XRAY_SS_PORT", "10006"))
XRAY_SS_2022_PORT = int(os.environ.get("XRAY_SS_2022_PORT", "10014"))
XRAY_API_PORT = int(os.environ.get("XRAY_API_PORT", "10085"))

# ------------------------------------------------------------------ raw TCP
# Raw-TCP inbounds bind on the public interface (they own the socket — no TLS
# termination at the edge). Each protocol × security combo gets its own port.
XRAY_TCP_VLESS_PORT = int(os.environ.get("XRAY_TCP_VLESS_PORT", "10007"))            # none
XRAY_TCP_VLESS_TLS_PORT = int(os.environ.get("XRAY_TCP_VLESS_TLS_PORT", "10008"))    # tls
XRAY_TCP_VLESS_REALITY_PORT = int(os.environ.get("XRAY_TCP_VLESS_REALITY_PORT", "10009"))  # reality
XRAY_TCP_VMESS_PORT = int(os.environ.get("XRAY_TCP_VMESS_PORT", "10010"))            # none
XRAY_TCP_VMESS_TLS_PORT = int(os.environ.get("XRAY_TCP_VMESS_TLS_PORT", "10011"))    # tls
XRAY_TCP_TROJAN_PORT = int(os.environ.get("XRAY_TCP_TROJAN_PORT", "10012"))          # tls

# Xray terminates TLS itself for the TCP-TLS inbounds; point these at a cert.
TLS_CERT_FILE = os.environ.get("TITAN_TLS_CERT", "")
TLS_KEY_FILE = os.environ.get("TITAN_TLS_KEY", "")

# Who to contact from the public subscription page and from the client
# (clients show `support-url` in their own UI when it is present).
SUPPORT_URL = os.environ.get("TITAN_SUPPORT_URL", "https://t.me/Code_Shield").strip()
GITHUB_URL = os.environ.get("TITAN_GITHUB_URL", "https://github.com/mr-rashidi").strip()

IS_RAILWAY = bool(os.environ.get("RAILWAY_SERVICE_ID") or os.environ.get("RAILWAY_PROJECT_ID"))

# ---------------------------------------------------------------- edge exposure
# Platforms like Railway expose exactly one HTTP(S) edge and nothing else. TCP to
# any other port is *accepted* by the edge and then never answered - we measured
# it: connect() succeeds, zero bytes come back, the client hangs until its own
# timeout. A link pointing at such a port is not "blocked", it is unreachable by
# construction, and no client setting can fix it. So the panel must never emit
# one: when the edge is HTTP-only, only transports the edge can carry (WS, XHTTP,
# HTTPUpgrade, gRPC over 443) may appear in a link.
def _flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


EDGE_HTTP_ONLY = _flag("TITAN_EDGE_HTTP_ONLY",
                       bool(os.environ.get("RAILWAY_PUBLIC_DOMAIN")
                            or os.environ.get("RAILWAY_TCP_PROXY_DOMAIN")))

# The one way raw TCP (Reality / SS / Hy2) becomes reachable: a platform TCP
# proxy. Railway injects these two variables as soon as the proxy exists
# (Settings -> Networking -> TCP Proxy), so no manual configuration is needed.
TCP_PROXY_DOMAIN = (os.environ.get("TITAN_TCP_PROXY_DOMAIN")
                    or os.environ.get("RAILWAY_TCP_PROXY_DOMAIN") or "").strip()
try:
    TCP_PROXY_PORT = int(os.environ.get("TITAN_TCP_PROXY_PORT")
                         or os.environ.get("RAILWAY_TCP_PROXY_PORT") or 0)
except ValueError:
    TCP_PROXY_PORT = 0

#: The container port the proxy actually forwards to. Platforms inject it
#: (Railway: RAILWAY_TCP_APPLICATION_PORT); anywhere else it can be declared
#: with TITAN_TCP_PROXY_APP_PORT. 0 means "nobody told us".
try:
    TCP_APP_PORT = int(os.environ.get("TITAN_TCP_PROXY_APP_PORT")
                       or os.environ.get("RAILWAY_TCP_APPLICATION_PORT") or 0)
except ValueError:
    TCP_APP_PORT = 0


def tcp_proxy() -> tuple | None:
    """(host, port) of the platform TCP proxy, or None when there is none."""
    if TCP_PROXY_DOMAIN and 1 <= TCP_PROXY_PORT <= 65535:
        return TCP_PROXY_DOMAIN, TCP_PROXY_PORT
    return None


def tcp_proxy_carries(port: int) -> bool:
    """Does the public TCP proxy forward to exactly ``port``?

    One proxy carries one port. Writing its host:port into a config that needs a
    *different* port sends the client into whichever inbound the proxy really
    points at, where its handshake is meaningless and the connection hangs until
    the client times out — so this only ever says yes about a proven match.

    Unknown means no: the fallback (XHTTP/TLS over the HTTPS edge) connects
    everywhere, and the admin is told both ports, so a wrong guess can never
    turn into a dead config. TITAN_TCP_PROXY_APP_PORT declares it by hand on a
    platform that does not inject one.
    """
    if not tcp_proxy():
        return False
    try:
        return int(port) > 0 and int(port) == int(TCP_APP_PORT)
    except (TypeError, ValueError):
        return False


#: Transports the HTTP edge can carry end to end (the container's nginx proxies
#: each of these to the matching Xray inbound).
EDGE_TRANSPORTS = {"ws", "xhttp", "httpupgrade", "grpc"}

# Reality (VLESS) — destination to masquerade as + SNI to present.
REALITY_DEST = os.environ.get("TITAN_REALITY_DEST", "1.1.1.1:443")
REALITY_SNI = os.environ.get("TITAN_REALITY_SNI", "www.microsoft.com")

# ------------------------------------------------------------------ Hysteria2
# Hysteria2 runs over QUIC (UDP). The inbound binds on the public interface and
# terminates TLS itself (needs TITAN_TLS_CERT / TITAN_TLS_KEY).
XRAY_HY2_PORT = int(os.environ.get("XRAY_HY2_PORT", "443"))            # UDP
# Salamander obfuscation password ("" = off). Requires a recent Xray-core.
HY2_OBFS = os.environ.get("TITAN_HY2_OBFS", "")
# HTTP/3 masquerade for unauthenticated probes ("" = off): proxy mode only.
HY2_MASQUERADE_URL = os.environ.get("TITAN_HY2_MASQUERADE_URL", "")

# ------------------------------------------------------------------ HTTPUpgrade
# HTTPUpgrade transport (like XHTTP) — served through nginx on the public port.
XRAY_HTTPUPGRADE_PORT = int(os.environ.get("XRAY_HTTPUPGRADE_PORT", "10013"))

# ------------------------------------------------------------------ Fallback
# Single-port fallback: VLESS(TCP+TLS) + WebSocket paths served on one port.
# 0 = disabled. On a VPS/Docker set it to 443; on Railway pick a TCP-proxied
# port (443 is reserved for the HTTPS edge). Needs TITAN_TLS_CERT/_KEY.
FALLBACK_PORT = int(os.environ.get("TITAN_FALLBACK_PORT", "0") or 0)

# ------------------------------------------------------------------ Shadowsocks 2022
# 2022 methods use a pre-shared key (like WireGuard); the PSK is derived
# deterministically from the user uuid so main and nodes always agree.
SS_METHODS = [
    "aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
    "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
]
SS_2022_METHODS = {
    "2022-blake3-aes-128-gcm",
    "2022-blake3-aes-256-gcm",
    "2022-blake3-chacha20-poly1305",
}
DEFAULT_SS_METHOD = os.environ.get("XRAY_SS_METHOD", "2022-blake3-aes-128-gcm")

# ------------------------------------------------------------------ WireGuard
# Optional userspace WireGuard/AmneziaWG server (VPS/Docker only — needs a TUN
# device + NET_ADMIN). The panel generates keypairs and the client config, and
# manages a userspace WG process. Skipped gracefully when the binary is absent.
WG_PORT = int(os.environ.get("TITAN_WG_PORT", "51820"))            # UDP
WG_SUBNET = os.environ.get("TITAN_WG_SUBNET", "10.200.0.0/24")
WG_BIN = os.environ.get("TITAN_WG_BIN", "/usr/local/bin/amnezia-wg-go")
WG_CONFIG_PATH = os.environ.get(
    "TITAN_WG_CONFIG", "/usr/local/bin/wg0.conf"
)


def tls_ready() -> bool:
    """True when a certificate pair is configured and present on disk."""
    return bool(
        TLS_CERT_FILE and TLS_KEY_FILE
        and os.path.exists(TLS_CERT_FILE) and os.path.exists(TLS_KEY_FILE)
    )


def fallback_active() -> bool:
    """True when the single-port fallback inbound should be generated."""
    return bool(FALLBACK_PORT) and tls_ready()

# Xray binary location + feature flag (dev mode runs the panel without Xray).
XRAY_BIN = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")

# Where Xray's own stdout/stderr goes (diagnostics).
XRAY_LOG_PATH = os.environ.get("TITAN_XRAY_LOG", os.path.join(DATA_DIR, "xray.log"))

# Session cookie.
SESSION_COOKIE = "titan_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
# Progressive backoff starts after this many failed logins (see api_login);
# the delay, not a hard lock, is the primary defence because a single-container
# deploy shares one counter across every visitor.
LOGIN_SOFT_FAILS = 3
LOGIN_BACKOFF_CAP_SECONDS = 15
# Hard lock only after this many consecutive failures.
LOGIN_MAX_ATTEMPTS = 8
LOGIN_HARD_LOCK_ATTEMPTS = 30
LOGIN_LOCK_SECONDS = 10 * 60  # 10 minutes

# ------------------------------------------------------------------ multi-node
# TITAN_ROLE=main  -> the control panel (dashboard + DB). Syncs users to nodes.
# TITAN_ROLE=node  -> a pure proxy node: runs Xray for the users the main panel
#                     assigns to it and reports their usage back.
ROLE = os.environ.get("TITAN_ROLE", "main").strip().lower() or "main"
IS_NODE = ROLE == "node"

# Shared secret that lets the main panel talk to its nodes (and vice versa).
# Must be identical on every service. If empty, node sync is disabled.
NODE_SECRET = os.environ.get("TITAN_NODE_SECRET", "")

# Per-node credential issued by the main panel's "Quick node setup" wizard.
# When set, the node uses it to authenticate itself (register + usage report)
# and to verify the main panel's sync pushes. Replaces the shared secret.
NODE_TOKEN = os.environ.get("TITAN_NODE_TOKEN", "")

# Optional human name for this instance; otherwise the Railway service name is
# used, and failing that a name built from the detected city.
NODE_NAME = os.environ.get("TITAN_NODE_NAME", "").strip()

# The node's own public URL (used to self-register with the main panel).
# Auto-derived from Railway's injected RAILWAY_PUBLIC_DOMAIN when available.
def _node_public_url() -> str:
    d = os.environ.get("TITAN_NODE_URL", "").strip()
    if d:
        return d
    d = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if not d:
        return ""
    if d.startswith(("http://", "https://")):
        return d
    return "https://" + d


NODE_URL = _node_public_url()

# On a node: the public URL of the main panel, e.g. https://panel.example.com
MAIN_URL = os.environ.get("TITAN_MAIN_URL", "").strip().rstrip("/")

# How often (seconds) the main panel re-pushes users to its nodes.
NODE_SYNC_INTERVAL = int(os.environ.get("TITAN_NODE_SYNC_INTERVAL", "60"))


# Default settings for newly created users / generated links.
DEFAULT_SETTINGS = {
    "public_domain": "",
    "public_port": 443,
    "admin_avatar": "titan",
    "default_transport": "ws",
    "default_fingerprint": "chrome",
    "default_alpn": "http/1.1",
    "sni_override": "",
    "fragment_enabled": False,
    "fragment_length": "10-30",
    "fragment_interval": "10-20",
    "restrict_ips": True,
    "block_ads": True,
    "block_iran_sites": False,
    "backup_enabled": True,
    "backup_interval_hours": 24,
    # reality (VLESS) — public values, filled when the keypair is generated
    "reality_pub": "",
    "reality_sid": "",
    "reality_sni": "",
    "reality_dest": "",
}

# Which Xray outbound tags are counted as "blocked" domains (for the routing
# feature). Must match the tag names emitted in xray.py::generate_xray_config.
BLOCKED_TAGS = {"block-ads", "block-iran", "block-adult", "block-custom"}

VALID_FINGERPRINTS = {"chrome", "firefox", "safari", "ios", "android", "edge", "360", "qq", "random", "randomized"}
VALID_ALPNS = {"http/1.1", "h2,http/1.1", "h3,h2,http/1.1", ""}
VALID_TRANSPORTS = {"ws", "xhttp", "grpc", "tcp", "httpupgrade"}
VALID_SECURITY = {"none", "tls", "reality"}
VALID_PROTOCOLS = {"vless", "vmess", "trojan", "shadowsocks", "hysteria2", "wireguard"}
