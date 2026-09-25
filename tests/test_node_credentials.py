"""Which credential the panel presents to a node — and why that mattered.

A node deployed with only ``TITAN_NODE_SECRET`` rejects the per-node token the
dashboard issues when a node is added by hand (its ``secret_valid_for_node``
accepts the shared secret or its own configured token, nothing else). The panel
used to send that one credential, get HTTP 401, and give up: the node never got
the user, so the link fell back to the main domain. That is one of the ways "I
added the node, picked it, and the client still shows the main domain" happened.

These tests drive the real push path with a stubbed HTTP layer that behaves like
such a node: 401 for the token, 200 for the shared secret.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

H = {"Origin": "http://testserver"}
SHARED = "shared-secret-for-tests-0123456789"


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _FakeClient:
    """Stands in for httpx.AsyncClient: accepts the shared secret only."""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        secret = (json or {}).get("secret") or ""
        _FakeClient.seen.append(secret)
        return _Resp(200 if secret == SHARED else 401)


_FakeClient.seen = []


@pytest.fixture()
def node_wants_shared_secret(monkeypatch):
    from app import config
    from app import nodes as nodesync
    monkeypatch.setattr(config, "NODE_SECRET", SHARED)
    monkeypatch.setattr(nodesync.httpx, "AsyncClient", _FakeClient)
    _FakeClient.seen = []
    yield _FakeClient.seen


def test_the_panel_falls_back_to_the_shared_secret(admin, node_wants_shared_secret):
    from app import db

    r = admin.post("/api/nodes", headers=H, json={
        "name": "shared-secret-node", "address": "https://shared.example.com",
        "country_code": "NL"})
    assert r.status_code == 200, r.text
    node_id = r.json()["node"]["id"]
    # creating a node verifies the upload path right away
    assert r.json()["sync_now"]["ok"] is True, r.json()["sync_now"]

    r = admin.post("/api/users", headers=H, json={
        "name": "on-shared-node", "protocol": "vless", "transport": "ws",
        "security": "tls", "node_id": node_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["node_sync"]["ok"] is True, body["node_sync"]
    assert "shared.example.com" in body["user"]["main_link"], body["user"]["main_link"]
    # both credentials were tried, the shared one won and was remembered
    assert _FakeClient.seen[-1] == SHARED, _FakeClient.seen
    assert db.get_meta(f"node_secret_kind:{node_id}") == "shared"

    # the next push starts with the winner instead of re-trying the loser
    _FakeClient.seen = []
    r = admin.post(f"/api/nodes/{node_id}/sync", headers=H)
    assert r.status_code == 200, r.text
    assert _FakeClient.seen and _FakeClient.seen[0] == SHARED, _FakeClient.seen
    admin.delete(f"/api/nodes/{node_id}", headers=H)


def test_a_node_that_rejects_everything_says_why(admin, node_wants_shared_secret, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "NODE_SECRET", "some-other-secret")
    r = admin.post("/api/nodes", headers=H, json={
        "name": "refusing-node", "address": "https://refusing.example.com",
        "country_code": "DE"})
    node_id = r.json()["node"]["id"]
    r = admin.post("/api/users", headers=H, json={
        "name": "refused", "protocol": "vless", "transport": "ws", "security": "tls",
        "node_id": node_id})
    body = r.json()
    assert body["node_sync"]["ok"] is False
    assert "credential rejected" in body["node_sync"]["error"], body["node_sync"]
    assert "refusing.example.com" not in body["user"]["main_link"]
    assert body["user"]["edge_warnings"], "the admin must be told the link fell back"
    admin.delete(f"/api/users/{body['user']['uid']}", headers=H)
    admin.delete(f"/api/nodes/{node_id}", headers=H)


def test_the_node_cards_report_which_credential_works(admin, node_wants_shared_secret):
    r = admin.post("/api/nodes", headers=H, json={"name": "cred-node",
                                                  "address": "https://cred.example.com"})
    node_id = r.json()["node"]["id"]
    node = next(n for n in admin.get("/api/nodes", headers=H).json()["nodes"] if n["id"] == node_id)
    assert node["sync"]["ok"] is True, node["sync"]
    assert node["sync"]["has_credential"] is True
    assert node["sync"].get("credential") == "shared", node["sync"]
    admin.delete(f"/api/nodes/{node_id}", headers=H)
