"""A node link must point at a node that provably has the user.

Why this file exists: "I add a node, pick it (and its location) for the config,
and the config times out" had a panel-side cause. The panel advertised whatever
node the user was assigned to, whether or not that node had ever received them —
and it also served *only* the users assigned to itself, so the two halves of the
system could disagree. Every test here pins one half of the rule that replaced
that: the link follows the evidence, and the panel is always able to serve.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

H = {"Origin": "http://testserver"}


@pytest.fixture()
def edge_only(monkeypatch):
    """The Railway shape: an HTTP edge for the panel, no TCP proxy."""
    from app import config
    monkeypatch.setattr(config, "EDGE_HTTP_ONLY", True)
    monkeypatch.setattr(config, "TCP_PROXY_DOMAIN", "")
    monkeypatch.setattr(config, "TCP_PROXY_PORT", 0)
    yield


def _node(admin, **fields):
    payload = {"name": "n-" + fields.get("address", "x")[:8], **fields}
    r = admin.post("/api/nodes", headers=H, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["node"]["id"]


def _user(admin, node_id, **fields):
    payload = {"name": "u-" + str(node_id), "protocol": "vless",
               "transport": "ws", "security": "tls", "node_id": node_id, **fields}
    r = admin.post("/api/users", headers=H, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["user"]


def _shown(admin, uid):
    return admin.get(f"/api/users/{uid}", headers=H).json()


def test_the_panel_can_serve_every_user_however_they_are_assigned(admin, edge_only):
    """A link that falls back to the panel only works if the panel serves it.

    The panel used to serve *only* its own node's users, so a fallback link (or a
    user on "auto" before any node measurement) pointed at a server that had no
    such user at all — the client connected and waited for its timeout.
    """
    from app import nodes as nodesync
    node_id = _node(admin, address="node-a.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    assert u["uid"] in {x["uid"] for x in nodesync.local_users()}
    admin.delete(f"/api/nodes/{node_id}")


def test_a_node_that_never_received_the_user_is_not_advertised(admin, edge_only):
    """The exact field case: the node exists but the sync never named this user."""
    node_id = _node(admin, address="node-b.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    assert "node-b.up.railway.app" not in u["main_link"], u["main_link"]
    assert u["edge_warnings"], "the admin must be told the link fell back to the panel"
    admin.delete(f"/api/nodes/{node_id}")


def test_once_the_node_has_the_user_the_link_points_at_it(admin, edge_only):
    from app import routing
    node_id = _node(admin, address="node-c.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    routing.record_sync(node_id, True, uids=[u["uid"]])
    link = _shown(admin, u["uid"])["main_link"]
    assert "node-c.up.railway.app" in link, link
    admin.delete(f"/api/nodes/{node_id}")


def test_assigning_a_user_pushes_it_to_the_node_and_the_returned_link_says_so(
        admin, edge_only, reachable_node):
    """The exact complaint: "I pick the node for the config but the client gets the
    main domain".

    Creating the user must push to that node *inside the request* (bounded), so the
    links in the very response already point at the node — otherwise the admin
    copies a panel link while the background push is still in flight, which is
    exactly how the client ended up dialling the main domain.
    """
    node_id = _node(admin, address="node-g.up.railway.app", country_code="DE")
    r = admin.post("/api/users", headers=H, json={
        "name": "assigned", "protocol": "vless", "transport": "ws", "security": "tls",
        "node_id": node_id})
    assert r.status_code == 200, r.text
    body = r.json()
    uid = body["user"]["uid"]
    assert body["node_sync"]["ok"] is True, body["node_sync"]
    assert body["node_sync"]["served_by"] == "node"
    # the background sync_all() may push other nodes too, so look at *this* node
    mine = [p for p in reachable_node["pushes"] if p["node"] == node_id]
    assert mine and uid in mine[-1]["uids"], reachable_node["pushes"]
    from app import routing as _routing
    assert uid in (_routing.sync_state(node_id)["uids"] or set()), "the node's uid set is not recorded"
    assert "node-g.up.railway.app" in body["user"]["main_link"], body["user"]["main_link"]
    # and it stays that way when the admin re-reads the row
    assert "node-g.up.railway.app" in _shown(admin, uid)["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_a_stale_list_is_never_claimed_but_the_panel_still_serves(admin, edge_only, reachable_node):
    """A sync is a complete list: whoever is not in it is not on that node.

    When the push that follows an assignment fails, *nothing* may be advertised
    from that node — an earlier successful sync is stale by definition, and the
    panel (which serves everyone) answers instead.
    """
    node_id = _node(admin, address="node-h.up.railway.app", country_code="DE")
    first = _user(admin, node_id, name="first")
    reachable_node["fail"] = "HTTP 401"
    second_r = admin.post("/api/users", headers=H, json={
        "name": "second", "protocol": "vless", "transport": "ws", "security": "tls",
        "node_id": node_id})
    assert second_r.status_code == 200, second_r.text
    second = second_r.json()["user"]
    assert second_r.json()["node_sync"]["ok"] is False
    assert "node-h.up.railway.app" not in second["main_link"], second["main_link"]
    assert second["edge_warnings"], "the admin has to be told why it fell back"
    # the earlier user is not claimed either: the node has just refused the push
    assert "node-h.up.railway.app" not in _shown(admin, first["uid"])["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_the_sync_loop_refreshes_its_evidence_even_when_nothing_changed(
        admin, edge_only, reachable_node):
    """"The node works, then the configs move back to the main domain after a while."

    The uid set the panel trusts has a TTL, and the loop used to skip re-pushing
    whenever the payload hash was unchanged — so an idle fleet (nobody edited a
    user for 15 minutes) stopped refreshing the stamp and every node link fell
    back to the panel. The payload must be re-pushed before the evidence expires.
    """
    import asyncio
    import time as _time

    from app import db
    from app import nodes as nodesync
    from app import routing

    node_id = _node(admin, address="node-i.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    assert "node-i.up.railway.app" in _shown(admin, u["uid"])["main_link"]

    # nothing changes: while the stamp is fresh the loop may skip the push
    pushes = len(reachable_node["pushes"])
    asyncio.run(nodesync.sync_all())
    assert len(reachable_node["pushes"]) == pushes, "the loop re-pushed an unchanged, fresh payload"

    # age the stamp past its TTL — now the loop must re-push even though the
    # payload is identical, because the panel can no longer vouch for the node
    db.set_meta(f"node_sync_at:{node_id}", str(_time.time() - routing.SYNC_TTL - 5))
    asyncio.run(nodesync.sync_all())
    assert len(reachable_node["pushes"]) == pushes + 1, "the loop skipped a push it needed"
    st = routing.sync_state(node_id)
    assert st["ok"] is True and (_time.time() - st["at"]) < 60, st
    assert "node-i.up.railway.app" in _shown(admin, u["uid"])["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_a_failed_sync_falls_back_and_names_the_reason(admin, edge_only):
    from app import routing
    node_id = _node(admin, address="node-e.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    routing.record_sync(node_id, True, uids=[u["uid"]])
    assert "node-e.up.railway.app" in _shown(admin, u["uid"])["main_link"]
    routing.record_sync(node_id, False, err="HTTP 401")
    shown = _shown(admin, u["uid"])
    assert "node-e.up.railway.app" not in shown["main_link"], shown["main_link"]
    assert any("sync" in w and "panel" in w for w in shown["edge_warnings"]), shown["edge_warnings"]
    admin.delete(f"/api/nodes/{node_id}")


def test_a_disabled_node_never_takes_the_link(admin, edge_only):
    node_id = _node(admin, address="node-f.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    from app import routing
    routing.record_sync(node_id, True, uids=[u["uid"]])
    admin.patch(f"/api/nodes/{node_id}", headers=H, json={"enabled": False})
    assert "node-f.up.railway.app" not in _shown(admin, u["uid"])["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_auto_never_picks_a_node_that_is_not_serving(admin, edge_only):
    """"auto" used to mean "lowest measured latency" — online, synced or not."""
    from app import routing
    node_id = _node(admin, address="node-g.up.railway.app", country_code="DE")
    u = _user(admin, 0, name="auto-user")
    routing.record_latency(node_id, 42, True)          # measured, but nothing synced
    assert "node-g.up.railway.app" not in _shown(admin, u["uid"])["main_link"]
    routing.record_sync(node_id, True, uids=[u["uid"]])
    assert "node-g.up.railway.app" in _shown(admin, u["uid"])["main_link"]
    admin.delete(f"/api/nodes/{node_id}")


def test_the_node_api_reports_what_the_panel_knows(admin, edge_only):
    """The dashboard must be able to explain a fallback without guessing."""
    from app import config, routing
    node_id = _node(admin, address="node-h.up.railway.app", country_code="DE")
    u = _user(admin, node_id)
    routing.record_sync(node_id, True, uids=[u["uid"]])
    routing.record_raw_probe(node_id, {config.XRAY_TCP_VLESS_REALITY_PORT: False})
    routing.record_edge_probe(node_id, "https", 443)
    node = next(n for n in admin.get("/api/nodes", headers=H).json()["nodes"] if n["id"] == node_id)
    assert node["sync"]["ok"] is True
    assert node["sync"]["serving"] == [u["uid"]]
    assert node["raw_open"][str(config.XRAY_TCP_VLESS_REALITY_PORT)] is False
    assert node["edge"]["scheme"] == "https" and node["edge"]["measured"] is True
    admin.delete(f"/api/nodes/{node_id}")
