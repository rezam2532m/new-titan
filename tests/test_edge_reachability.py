"""What a client is handed must be reachable — measured, not assumed.

Why this file exists: a Railway (or any HTTP-edge) deployment *accepts* TCP on
every port of its edge IP and then answers nothing. Measured on the live service:
connect() to 10009 succeeds, zero bytes come back, the client hangs until its own
timeout. The panel used to write exactly such a port into every raw (TCP/Reality/
SS) link, so "the config times out on MCI/IRANCEL" had a server-side cause that
no client setting could fix.

These tests pin the rule: on an HTTP-only edge a link carries only what the edge
can carry, and raw ports come back the moment a TCP proxy (or a real host) exists.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

H = {"Origin": "http://testserver"}
#: Every port that only exists inside the container.
RAW_PORTS = (10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009,
             10010, 10011, 10012, 10013, 10014, 10085, 51820)


@pytest.fixture()
def edge_only(monkeypatch):
    """The Railway shape: an HTTP edge, no TCP proxy."""
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 0)
    yield


def _no_raw_port(link: str) -> bool:
    return not any(f":{p}" in link for p in RAW_PORTS)


def test_a_raw_config_is_stored_as_something_the_edge_can_serve(admin, make_user, edge_only):
    """Reality over raw TCP cannot work here, so it must not be what gets stored.

    The admin asked for the strongest thing they know; handing them a link that
    hangs forever is not respecting that choice.
    """
    u = make_user(protocol="vless", transport="tcp", security="reality")
    assert u["transport"] in config.EDGE_TRANSPORTS, u["transport"]
    assert u["security"] == "tls"
    assert _no_raw_port(u["main_link"]), u["main_link"]
    assert ":443" in u["main_link"] or f":{config.PUBLIC_PORT}" in u["main_link"]


def test_every_served_transport_stays_untouched(admin, make_user, edge_only):
    """The mapping must not touch configs that already work."""
    for transport in ("ws", "xhttp", "httpupgrade", "grpc"):
        u = make_user(protocol="vless", transport=transport, security="tls")
        assert u["transport"] == transport
        assert _no_raw_port(u["main_link"])


def test_a_stored_raw_config_is_link_mapped(admin, make_user, edge_only, monkeypatch):
    """Rows created before this fix (or by a node) still must not hang a client."""
    u = make_user(protocol="vless", transport="ws", security="tls")
    # Force a raw row straight into the DB: that is what an older version stored.
    from app import db
    db.update_user(u["uid"], {"transport": "tcp", "security": "reality"})
    shown = admin.get(f"/api/users/{u['uid']}", headers=H).json()
    link = shown["main_link"]
    assert _no_raw_port(link), link
    assert "type=xhttp" in link or "type=ws" in link, link
    assert "security=tls" in link
    assert shown.get("edge_warnings"), "the admin must be told the link was remapped"


def test_a_tcp_proxy_brings_raw_transports_back(admin, make_user, monkeypatch):
    """Railway injects RAILWAY_TCP_PROXY_* once a TCP proxy exists, including the
    container port it forwards to - that triple is what makes Reality real again."""
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "shuttle.proxy.rlwy.net")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 23456)
    monkeypatch.setattr(config, "TCP_APP_PORT", config.XRAY_TCP_VLESS_REALITY_PORT)
    u = make_user(protocol="vless", transport="tcp", security="reality")
    assert u["transport"] == "tcp" and u["security"] == "reality"
    assert "shuttle.proxy.rlwy.net:23456" in u["main_link"], u["main_link"]


def test_a_tcp_proxy_never_advertises_a_port_it_does_not_carry(admin, make_user, monkeypatch):
    """One proxy carries one port, and the panel has six raw ones.

    The proxy forwards to container port 10009 (VLESS+Reality). A VMess/TCP
    config needs 10010, so the proxy is the last place it may be sent: the client
    would dial Reality with a VMess handshake and hang until it timed out. The
    link falls back to the HTTPS edge, which connects, and the admin is told
    exactly which two ports disagree.
    """
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "shuttle.proxy.rlwy.net")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 23456)
    monkeypatch.setattr(config, "TCP_APP_PORT", config.XRAY_TCP_VLESS_REALITY_PORT)
    assert config.tcp_proxy_carries(config.XRAY_TCP_VLESS_REALITY_PORT) is True
    assert config.tcp_proxy_carries(config.XRAY_TCP_VMESS_PORT) is False

    u = make_user(protocol="vmess", transport="tcp", security="none")
    # vmess links are base64(JSON) - look at what the client would actually read.
    import base64
    import json
    payload = json.loads(base64.b64decode(u["main_link"].split("://", 1)[1] + "=="))
    assert payload["add"] != "shuttle.proxy.rlwy.net", payload
    assert payload["net"] == "xhttp" and payload["tls"] == "tls", payload
    mismatch = " ".join(u.get("edge_warnings") or [])
    assert str(config.XRAY_TCP_VMESS_PORT) in mismatch, mismatch
    assert str(config.XRAY_TCP_VLESS_REALITY_PORT) in mismatch, mismatch

    # ... and a config that needs exactly that port does get the proxy.
    r = make_user(protocol="vless", transport="tcp", security="reality")
    assert "shuttle.proxy.rlwy.net:23456" in r["main_link"], r["main_link"]


def test_an_unknown_proxy_target_is_never_guessed(admin, make_user, monkeypatch):
    """No platform told us which port the proxy carries: never guess.

    Guessing is how a config ends up hanging; falling back is not — the edge
    path always connects. TITAN_TCP_PROXY_APP_PORT is the way to declare it.
    """
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "shuttle.proxy.rlwy.net")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 23456)
    monkeypatch.setattr(config, "TCP_APP_PORT", 0)
    u = make_user(protocol="vless", transport="tcp", security="reality")
    assert "shuttle.proxy.rlwy.net" not in u["main_link"], u["main_link"]
    assert "type=xhttp" in u["main_link"], u["main_link"]
    assert any("TCP proxy" in w and "unknown" in w for w in (u.get("edge_warnings") or [])), \
        u.get("edge_warnings")


def _serving_node(admin, node_id, uid):
    """Record a successful sync - the node now demonstrably has this user."""
    from app import routing
    routing.record_sync(node_id, True, uids=[uid])


def test_a_railway_node_keeps_only_its_edge_port(admin, edge_only):
    """A node's address port is its *internal* port - unreachable from outside.

    The node's link is only advertised once the node is *known* to serve the
    user (a successful sync naming them). Before that the panel keeps the link:
    an unverified node is exactly how "the node config times out" happens.
    """
    r = admin.post("/api/nodes", headers=H, json={
        "name": "edge-node", "address": "titan-node-abc.up.railway.app:443",
        "city": "Frankfurt", "country": "Germany", "country_code": "DE"})
    assert r.status_code == 200, r.text
    node_id = r.json()["node"]["id"]
    r2 = admin.post("/api/users", headers=H, json={
        "name": "node-user", "protocol": "vless", "transport": "tcp",
        "security": "reality", "node_id": node_id})
    assert r2.status_code == 200, r2.text
    u = r2.json()["user"]

    # Not verified yet: the panel serves it (and says so) instead of handing out
    # a link to a node that may have nothing for this user.
    assert "titan-node-abc.up.railway.app" not in u["main_link"], u["main_link"]
    assert any("panel" in w for w in (u.get("edge_warnings") or [])), u.get("edge_warnings")

    _serving_node(admin, node_id, u["uid"])
    u = admin.get(f"/api/users/{u['uid']}", headers=H).json()
    link = u["main_link"]
    assert "titan-node-abc.up.railway.app" in link
    assert ":443" in link, link
    assert _no_raw_port(link), link
    assert "type=xhttp" in link and "security=tls" in link
    admin.delete(f"/api/nodes/{node_id}")


def test_a_vps_node_that_publishes_its_raw_port_keeps_reality(admin, edge_only):
    """The opposite case must keep working: a verified host with an open port.

    A node's raw port is the fleet's port for that transport (every deployment
    runs the same inbound map), not the port in its address - that one is the
    node's HTTP edge, and Reality is not served there.
    """
    from app import config, routing
    r = admin.post("/api/nodes", headers=H, json={
        "name": "vps-node", "address": "203.0.113.9:8443",
        "city": "Tehran", "country": "Iran", "country_code": "IR"})
    node_id = r.json()["node"]["id"]
    r2 = admin.post("/api/users", headers=H, json={
        "name": "vps-user", "protocol": "vless", "transport": "tcp",
        "security": "reality", "node_id": node_id})
    u = r2.json()["user"]
    _serving_node(admin, node_id, u["uid"])
    routing.record_raw_probe(node_id, {config.XRAY_TCP_VLESS_REALITY_PORT: True})
    u = admin.get(f"/api/users/{u['uid']}", headers=H).json()
    assert f":{config.XRAY_TCP_VLESS_REALITY_PORT}" in u["main_link"], u["main_link"]
    assert "security=reality" in u["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_a_node_that_does_not_answer_its_raw_port_never_gets_it_in_a_link(admin, edge_only):
    """Measured closed: the raw port must not reach a client, on any transport.

    This is the node-side twin of the Railway edge problem - the link moves to
    the node's HTTPS edge (so the location is kept) instead of hanging.
    """
    from app import config, routing
    r = admin.post("/api/nodes", headers=H, json={
        "name": "closed-node", "address": "node.example.com",
        "city": "Amsterdam", "country": "Netherlands", "country_code": "NL"})
    node_id = r.json()["node"]["id"]
    r2 = admin.post("/api/users", headers=H, json={
        "name": "closed-user", "protocol": "vless", "transport": "tcp",
        "security": "reality", "node_id": node_id})
    u = r2.json()["user"]
    _serving_node(admin, node_id, u["uid"])
    routing.record_raw_probe(node_id, {config.XRAY_TCP_VLESS_REALITY_PORT: False})
    u = admin.get(f"/api/users/{u['uid']}", headers=H).json()
    assert "node.example.com" in u["main_link"], u["main_link"]
    assert _no_raw_port(u["main_link"]), u["main_link"]
    assert "type=xhttp" in u["main_link"] and "security=tls" in u["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_edge_check_names_the_cause(admin, edge_only):
    """The endpoint an admin runs when a config times out."""
    r = admin.get("/api/edge-check", headers=H)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["edge_http_only"] is True
    assert "proxy_in_front" in data
    assert data["public"]["port"] == config.PUBLIC_PORT or data["public"]["port"] == 443
    assert set(data["transports"]) >= {"vless+ws", "vless+xhttp", "vless+grpc"}
    for _name, info in data["transports"].items():
        assert "status" in info and "alive" in info
    assert data["raw_ports"]["XRAY_TCP_VLESS_REALITY_PORT"] == config.XRAY_TCP_VLESS_REALITY_PORT
    # ... and the TCP proxy block says *which* container port it carries, so the
    # dashboard can tell the admin why a raw config did or did not use it.
    proxy = data["tcp_proxy"]
    if config.tcp_proxy():
        assert proxy["host"] and proxy["port"]
        assert "application_port" in proxy and "carries" in proxy
    else:
        assert proxy is None
    assert "TCP proxy" in data["note"] or "TCP proxy" in data["note"]


def test_the_public_host_used_for_links_is_never_a_raw_port(make_user, edge_only):
    u = make_user(protocol="vless", transport="tcp", security="tls")
    assert _no_raw_port(u["main_link"])
    assert _no_raw_port(u["qr_data"])
    for link in u["links"]:
        assert _no_raw_port(link), link


def test_the_endpoint_shown_to_the_admin_matches_the_link(admin, make_user, monkeypatch):
    """The dashboard line must describe the link that was actually handed out.

    The proxy here carries the *Reality* port and this user needs the plain VLESS
    one, so the row stays raw in the database and the link is remapped at build
    time - which is exactly the case the admin has to be able to see: the modal
    says XHTTP/TLS, on the edge port, with the reason, instead of leaving him to
    infer it from a client that times out.
    """
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "shuttle.proxy.rlwy.net")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 23456)
    monkeypatch.setattr(config, "TCP_APP_PORT", config.XRAY_TCP_VLESS_REALITY_PORT)
    u = make_user(protocol="vless", transport="tcp", security="none")
    got = admin.get(f"/api/users/{u['uid']}", headers=H).json()
    ep = got["endpoint"]
    assert ep["target"] == "panel" and ep["host"]
    assert ep["raw"] is False, ep            # remapped: not raw any more
    assert ep["transport"] == "xhttp" and ep["security"] == "tls", ep
    assert ep["host"] != "shuttle.proxy.rlwy.net", ep
    assert f":{ep['port']}" in got["main_link"], (ep, got["main_link"])
    assert got["edge_warnings"], "the reason must travel with the endpoint"
    assert ep["reasons"], ep

    # ... and with the platform proxy carrying exactly that port, it *is* raw,
    # and the endpoint names the proxy the client will dial.
    monkeypatch.setattr(config, "TCP_APP_PORT", config.XRAY_TCP_VLESS_PORT)
    ep2 = admin.get(f"/api/users/{u['uid']}", headers=H).json()["endpoint"]
    assert ep2["raw"] is True and ep2["transport"] == "tcp", ep2
    assert ep2["host"] == "shuttle.proxy.rlwy.net" and ep2["port"] == 23456, ep2
    assert "tcp-proxy" in ep2["reasons"], ep2
