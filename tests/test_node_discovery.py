"""Adding a node from its domain alone, and claiming it without any variables.

The admin's complaint was concrete: adding a node answered "put the variables in
the node's service", which means every node had to be wired by hand. These tests
pin the replacement: a TiTaN node answers an identity card, the panel fills the
form itself, and a node that holds no credential is claimed over the same channel
so nothing has to be typed. The manual path still exists and copies every
variable at once.
"""
import asyncio
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from app import db, security
from app import main as m
from app import nodes as nodesync
from app import tasks as bg
from app.geo import detect_egress_location, flag_for_location, railway_location


@pytest.fixture()
def panel(monkeypatch):
    """A panel process with its own data dir and a known shared secret."""
    tmp = tempfile.mkdtemp(prefix="titan-discover-")
    monkeypatch.setenv("TITAN_DATA_DIR", tmp)
    monkeypatch.setattr(m.config, "NODE_SECRET", "panel-shared-secret-abcdef123456")
    db.close() if hasattr(db, "close") else None
    db._connect()
    db._ensure_bootstrap()
    hp = security.hash_password("TiTaN")
    db.set_admin("TiTaN", hp["hash"], hp["salt"])
    db.set_meta("auth_is_default", "1")
    db.set_settings({"public_domain": "", "public_port": 443})
    with TestClient(m.app) as client:
        client.post("/api/login", json={"username": "TiTaN", "password": "TiTaN"})
        yield client
    shutil.rmtree(tmp, ignore_errors=True)


ORIGIN = {"Origin": "http://testserver"}


def test_railway_location_matches_region_suffix_and_keeps_unknown_regions_unknown():
    location = railway_location("europe-west4-drams3a")
    assert location["known"] is True
    assert (location["city"], location["country"], location["country_code"], location["flag"]) == (
        "Amsterdam", "Netherlands", "NL", "🇳🇱")

    unknown = railway_location("europe-west9-future")
    assert unknown["known"] is False
    assert unknown["city"] == unknown["country"] == unknown["country_code"] == ""
    assert unknown["flag"] == "🌐"


def test_egress_geoip_uses_the_process_address_and_returns_a_matching_flag(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {"status": "success", "city": "Singapore", "country": "Singapore", "countryCode": "SG"}

    def _get(url, timeout):
        calls.append((url, timeout))
        return Response()

    monkeypatch.setattr("app.geo.httpx.get", _get)
    location = detect_egress_location(timeout=1.5)
    assert location == {
        "city": "Singapore", "country": "Singapore", "country_code": "SG", "flag": "🇸🇬"
    }
    assert calls == [("http://ip-api.com/json/?fields=status,country,countryCode,city", 1.5)]


def test_location_refresh_does_not_use_cloudflare_colo_as_the_node_location(monkeypatch):
    monkeypatch.delenv("RAILWAY_REPLICA_REGION", raising=False)
    monkeypatch.setitem(bg.LOCATION, "colo", "?")
    updates = []

    class TraceResponse:
        text = "colo=AMS\n"

    class TraceClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return TraceResponse()

    class StopRefresh(Exception):
        pass

    async def _stop(_seconds):
        raise StopRefresh

    monkeypatch.setattr(bg.httpx, "AsyncClient", TraceClient)
    monkeypatch.setattr("app.geo.detect_egress_location", lambda: {
        "city": "Singapore", "country": "Singapore", "country_code": "SG", "flag": "🇸🇬"
    })
    monkeypatch.setattr(bg.db, "set_local_node_location", lambda *args, **_kwargs: updates.append(args))
    monkeypatch.setattr(bg.asyncio, "sleep", _stop)

    with pytest.raises(StopRefresh):
        asyncio.run(bg._refresh_location())

    assert bg.LOCATION["colo"] == "AMS", "Cloudflare colo should still feed the edge widget"
    assert updates == [
        ("", "", "", "🌐"),
        ("Amsterdam", "Netherlands", "NL", "🇳🇱"),
        ("Singapore", "Singapore", "SG", "🇸🇬"),
    ]

def test_country_code_overrides_stale_flags_and_known_countries_fill_missing_codes():
    assert flag_for_location("DE", "Netherlands", "Amsterdam", "🇳🇱") == ("DE", "🇩🇪")
    assert flag_for_location("", "Netherlands", "Amsterdam", "🇺🇸") == ("NL", "🇳🇱")
    assert flag_for_location("Germany", "Germany", "Berlin", "🇺🇸") == ("DE", "🇩🇪")
    assert flag_for_location("UK", "", "", "🇳🇱") == ("GB", "🇬🇧")
    serialized = m._serialize_node({
        "id": 7, "name": "node", "city": "Berlin", "country": "Germany",
        "country_code": "Germany", "flag": "🇳🇱", "token": "secret",
    }, {})
    assert serialized["flag"] == "🇩🇪" and serialized["country_code"] == "DE"
    assert "token" not in serialized


def _me(panel):
    return panel.get("/api/me").json() if panel.get("/api/me").status_code == 200 else {}


# ─────────────────────────────────────────────────────── node-side endpoints
def test_node_identity_prefers_railway_region_over_stale_edge_location(panel, monkeypatch):
    monkeypatch.setenv("RAILWAY_REPLICA_REGION", "europe-west4-drams3a")
    monkeypatch.setattr(m.config, "IS_NODE", True)
    db.set_local_node_location("San Jose", "United States", "US", "🇺🇸")

    identity = nodesync.identity()
    assert (identity["city"], identity["country"], identity["country_code"], identity["flag"]) == (
        "Amsterdam", "Netherlands", "NL", "🇳🇱")


def test_unknown_railway_region_does_not_inherit_stale_edge_location(panel, monkeypatch):
    monkeypatch.setenv("RAILWAY_REPLICA_REGION", "europe-west9-future")
    monkeypatch.setattr(m.config, "IS_NODE", True)
    db.set_local_node_location("Frankfurt", "Germany", "DE", "🇩🇪")

    identity = nodesync.identity()
    assert identity["city"] == identity["country"] == identity["country_code"] == ""
    assert identity["flag"] == "🌐"


def test_cloudflare_fallback_remains_a_panel_place_not_the_node_location(panel, monkeypatch):
    monkeypatch.delenv("RAILWAY_REPLICA_REGION", raising=False)
    monkeypatch.setattr(bg, "NODE_LOCATION", {})
    monkeypatch.setattr(bg, "EDGE_FALLBACK_LOCATION", {
        "city": "Amsterdam", "country": "Netherlands", "country_code": "NL", "flag": "🇳🇱"
    })
    db.set_local_node_location("Amsterdam", "Netherlands", "NL", "🇳🇱")

    identity = nodesync.identity()
    assert identity["city"] == identity["country"] == identity["country_code"] == ""
    assert identity["flag"] == "🌐"
    serialized = m._serialize_node({**db.local_node(), "is_local": 1}, {})
    assert serialized["city"] == serialized["country"] == serialized["country_code"] == ""
    assert serialized["flag"] == "🌐"


def test_a_node_answers_an_identity_card_without_leaking_anything(panel, monkeypatch):
    """The panel calls this before it can add anything, so it must not need a session."""
    monkeypatch.setattr(m.config, "IS_NODE", True)
    monkeypatch.setattr(m.config, "NODE_SECRET", "")   # nothing configured yet
    monkeypatch.setattr(m.config, "NODE_TOKEN", "")
    db.set_meta("node_secret", "")
    db.set_meta("panel_secret", "")          # the panel may have minted one by now
    db.set_local_node_location("Frankfurt", "Germany", "DE", "🇩🇪")
    r = panel.get("/api/node/discover")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["app"] == "titan" and card["role"] == "node"
    assert card["city"] == "Frankfurt" and card["country_code"] == "DE"
    assert card["accepts_bootstrap"] is True and card["credential"] == ""
    assert "secret" not in str(card).lower() or "credential" in card
    # the private bits stay private unless the caller proves it holds the secret
    assert "users" not in card and "panel_url" not in card
    db.set_meta("node_secret", "panel-shared-secret-abcdef123456")
    authed = panel.get("/api/node/discover",
                       headers={"X-TiTaN-Node-Secret": "panel-shared-secret-abcdef123456"}).json()
    assert "users" in authed and authed["credential"] == "claimed", \
        "an authenticated caller sees the fuller card, including a claimed secret"


def test_a_fresh_node_accepts_one_claim_and_then_locks(panel, monkeypatch):
    """Trust on first use: the first panel to reach a fresh node owns it."""
    monkeypatch.setattr(m.config, "IS_NODE", True)
    monkeypatch.setattr(m.config, "NODE_SECRET", "")
    monkeypatch.setattr(m.config, "NODE_TOKEN", "")
    db.set_meta("node_secret", "")
    db.set_meta("panel_secret", "")

    first = panel.post("/api/node/bootstrap",
                       json={"secret": "owner-secret-0123456789", "panel_url": "https://panel.example"})
    assert first.status_code == 200 and first.json()["claimed"] is True
    assert db.get_meta("node_secret") == "owner-secret-0123456789"
    assert db.get_meta("node_panel_url") == "https://panel.example"
    # the stored credential is now what this node accepts for pushes
    assert nodesync.secret_valid_for_node("owner-secret-0123456789") is True
    assert nodesync.secret_valid_for_node("someone-else-secret-0123456789") is False
    assert nodesync.node_credential() == "owner-secret-0123456789"

    # a second panel cannot take the node over
    second = panel.post("/api/node/bootstrap",
                        json={"secret": "attacker-secret-0123456789"})
    assert second.status_code == 409
    # ... and re-claiming with the same secret is idempotent
    again = panel.post("/api/node/bootstrap", json={"secret": "owner-secret-0123456789"})
    assert again.status_code == 200 and again.json().get("already") is True
    # a short secret is refused outright
    assert panel.post("/api/node/bootstrap", json={"secret": "short"}).status_code == 400


def test_an_env_credential_is_never_replaced_by_a_claim(panel, monkeypatch):
    """A node that was deployed with variables keeps them, claim or not."""
    monkeypatch.setattr(m.config, "IS_NODE", True)
    monkeypatch.setattr(m.config, "NODE_SECRET", "already-set-secret-0123456789")
    r = panel.post("/api/node/bootstrap", json={"secret": "other-secret-0123456789"})
    assert r.status_code == 409
    assert m.config.NODE_SECRET == "already-set-secret-0123456789"


# ──────────────────────────────────────────────────── panel-side detect/claim
class _FakeProbe:
    """Stands in for the network: a live TiTaN node that holds nothing yet."""

    def __init__(self, *, kind="titan", accepts=True):
        self.kind = kind
        self.accepts = accepts
        self.claims = 0

    async def __call__(self, addr, timeout=6.0):
        if self.kind != "titan":
            return {"kind": self.kind, "url": "", "identity": {}, "error": "HTTP 502"}
        return {"kind": "titan", "url": addr, "identity": {
            "app": "titan", "version": "1.0.0", "role": "node", "name": "fra-node",
            "city": "Frankfurt", "country": "Germany", "country_code": "DE", "flag": "🇩🇪",
            "edge": {"scheme": "https", "port": 443}, "credential": "",
            "accepts_bootstrap": self.accepts,
        }, "error": ""}

    async def claim(self, url, panel_url, timeout=8.0):
        self.claims += 1
        if not self.accepts:
            return {"ok": False, "error": "node-already-claimed"}
        return {"ok": True, "claimed": True}


def test_a_domain_alone_is_enough_to_add_a_node(panel, monkeypatch):
    """POST /api/nodes with only an address: detected, claimed, and pushed."""
    probe = _FakeProbe()
    monkeypatch.setattr(m, "_probe_node_identity", probe)

    async def _fake_claim(url, panel_url, timeout=8.0):
        return await probe.claim(url, panel_url)

    monkeypatch.setattr(m, "_claim_node", _fake_claim)

    pushed = []

    async def _fake_sync(node_id, timeout=6.0):
        pushed.append(node_id)
        return {"node_id": node_id, "ok": True, "error": "", "served_by": ["nobody"]}

    monkeypatch.setattr(m, "_sync_node_now", _fake_sync)

    r = panel.post("/api/nodes", json={"address": "https://fra-node.up.railway.app"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body = r.json()
    node = body["node"]
    assert node["name"] == "fra-node", "the name came from the node itself"
    assert node["city"] == "Frankfurt" and node["country_code"] == "DE"
    assert node["flag"] == "🇩🇪"
    assert body["discovery"]["kind"] == "titan"
    assert body["discovery"]["claim"]["ok"] is True, "the fresh node was claimed automatically"
    assert probe.claims == 1
    assert body["sync_now"]["ok"] is True and pushed, "the users were pushed right away"
    # the manual recipe is still there, and now copies as one block
    assert body["setup"]["block"].startswith("TITAN_ROLE=node")
    assert "TITAN_NODE_TOKEN=" in body["setup"]["block"]
    assert body["setup"]["lines"] == body["setup"]["block"].splitlines()


def test_a_detect_call_fills_the_form_without_storing_anything(panel, monkeypatch):
    monkeypatch.setattr(m, "_probe_node_identity", _FakeProbe())
    before = len(db.list_nodes())
    r = panel.post("/api/nodes/detect", json={"address": "fra-node.example.com"}, headers=ORIGIN)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["kind"] == "titan"
    assert d["fields"]["city"] == "Frankfurt" and d["fields"]["country_code"] == "DE"
    assert d["needs_credentials"] is True and d["can_claim"] is True
    assert len(db.list_nodes()) == before, "detect must not add a node"


def test_when_detection_fails_the_manual_path_still_works(panel, monkeypatch):
    """An older node (or a typo) must not block the admin: manual entry stays."""
    monkeypatch.setattr(m, "_probe_node_identity", _FakeProbe(kind="unreachable"))

    async def _fake_sync(node_id, timeout=6.0):
        return {"node_id": node_id, "ok": False, "error": "HTTP 401 (credential rejected)"}

    monkeypatch.setattr(m, "_sync_node_now", _fake_sync)
    r = panel.post("/api/nodes",
                   json={"name": "manual-node", "address": "old-node.example.com",
                         "city": "Dubai", "country_code": "AE", "flag": "🇦🇪"},
                   headers=ORIGIN)
    assert r.status_code == 200
    body = r.json()
    assert body["discovery"]["kind"] == "unreachable"
    assert body["node"]["name"] == "manual-node" and body["node"]["city"] == "Dubai"
    assert body["sync_now"]["ok"] is False
    assert body["setup"]["block"].splitlines()[0].startswith("TITAN_ROLE=")


def test_unreachable_titan_node_stays_unknown_instead_of_using_edge_geoip(panel, monkeypatch):
    async def _unreachable(_addr, timeout=6.0):
        return {"kind": "unreachable", "url": "", "identity": {}, "error": "timeout"}

    async def _fake_status(_node):
        return {"online": False}

    async def _fake_sync(node_id, timeout=6.0):
        return {"node_id": node_id, "ok": False, "error": "timeout"}

    geo_calls = []
    monkeypatch.setattr(m, "_probe_node_identity", _unreachable)
    monkeypatch.setattr(m, "_node_status", _fake_status)
    monkeypatch.setattr(m, "_sync_node_now", _fake_sync)
    monkeypatch.setattr(m, "detect_location", lambda addr: geo_calls.append(addr) or {
        "city": "Ashburn", "country": "United States", "country_code": "US", "flag": "🇺🇸"})

    response = panel.post("/api/nodes", json={
        "name": "unknown-node", "address": "edge.example.com", "flag": "🌐"}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    node = response.json()["node"]
    assert node["city"] == node["country"] == node["country_code"] == ""
    assert node["flag"] == "🌐" and geo_calls == []


def test_foreign_host_with_neutral_flag_can_still_use_domain_geoip(panel, monkeypatch):
    async def _foreign(_addr, timeout=6.0):
        return {"kind": "foreign", "url": "https://example.com", "identity": {}, "error": "not-a-titan-node"}

    async def _fake_status(_node):
        return {"online": False}

    async def _fake_sync(node_id, timeout=6.0):
        return {"node_id": node_id, "ok": False, "error": "not-a-titan-node"}

    geo_calls = []
    monkeypatch.setattr(m, "_probe_node_identity", _foreign)
    monkeypatch.setattr(m, "_node_status", _fake_status)
    monkeypatch.setattr(m, "_sync_node_now", _fake_sync)

    def _geo(addr):
        geo_calls.append(addr)
        return {"city": "Amsterdam", "country": "Netherlands", "country_code": "NL", "flag": "🇳🇱"}

    monkeypatch.setattr(m, "detect_location", _geo)
    response = panel.post("/api/nodes", json={
        "name": "foreign-node", "address": "foreign.example.com", "flag": "🌐"}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    node = response.json()["node"]
    assert geo_calls and node["city"] == "Amsterdam" and node["country_code"] == "NL"
    assert node["flag"] == "🇳🇱"


def test_ping_fills_and_persists_the_node_identity_location(panel, monkeypatch):
    node = db.create_node({"name": "auto-node", "address": "https://auto.example.com", "flag": "🌐"})

    async def _identity(_addr, timeout=6.0):
        return {"kind": "titan", "url": "https://auto.example.com", "identity": {
            "app": "titan", "name": "amsterdam-node", "city": "Amsterdam",
            "country": "Netherlands", "country_code": "NL", "flag": "🇺🇸",
        }, "error": ""}

    async def _fake_status(_node):
        return {"online": True, "latency_ms": 20}

    monkeypatch.setattr(m, "_probe_node_identity", _identity)
    monkeypatch.setattr(m, "_node_status", _fake_status)

    response = panel.post(f"/api/nodes/{node['id']}/ping")
    assert response.status_code == 200, response.text
    reported = response.json()["node"]
    stored = db.get_node(node["id"])
    for value in (reported, stored):
        assert value["city"] == "Amsterdam" and value["country_code"] == "NL"
        assert value["flag"] == "🇳🇱"


def test_claiming_an_existing_node_reports_every_step(panel, monkeypatch):
    node = db.create_node({"name": "late-node", "address": "https://late.example.com",
                           "token": "tok", "enabled": True})
    probe = _FakeProbe()
    monkeypatch.setattr(m, "_probe_node_identity", probe)

    async def _fake_claim(url, panel_url, timeout=8.0):
        return await probe.claim(url, panel_url)

    monkeypatch.setattr(m, "_claim_node", _fake_claim)

    async def _fake_sync(node_id, timeout=6.0):
        return {"node_id": node_id, "ok": True, "error": "", "served_by": []}

    monkeypatch.setattr(m, "_sync_node_now", _fake_sync)
    r = panel.post(f"/api/nodes/{node['id']}/claim", headers=ORIGIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "titan" and body["claim"]["ok"] is True
    assert body["node_sync"]["ok"] is True
    assert db.get_node(node["id"])["city"] == "Frankfurt", "the card was written onto the node"


def test_the_shared_secret_is_what_gets_handed_over(panel, monkeypatch):
    """The claim carries the panel's own credential, never a made-up one."""
    sent = {}

    class _Resp:
        status_code = 200
        text = '{"ok": true, "claimed": true}'

        @staticmethod
        def json():
            return {"ok": True, "claimed": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent["url"] = url
            sent["json"] = json
            return _Resp()

    monkeypatch.setattr(m.httpx, "AsyncClient", lambda **kw: _Client())
    out = __import__("asyncio").run(m._claim_node("https://node.example.com", "https://panel.example"))
    assert out["ok"] is True
    assert sent["url"] == "https://node.example.com/api/node/bootstrap"
    assert sent["json"]["secret"] == "panel-shared-secret-abcdef123456"
    assert sent["json"]["panel_url"] == "https://panel.example"

def test_a_panel_with_no_secret_mints_one_and_uses_it(panel, monkeypatch):
    """Nobody typed a variable anywhere, and the node still gets users.

    A panel deployed without TITAN_NODE_SECRET used to have nothing to hand over,
    so "claim this node" could not work: the claim carries the panel's secret.
    The panel now mints one on first need, keeps it in its own database, offers it
    to nodes and accepts what they report back with it.
    """
    monkeypatch.setattr(m.config, "NODE_SECRET", "")
    db.set_meta("panel_secret", "")
    minted = nodesync.panel_secret()
    assert len(minted) >= 24, "the minted secret is long enough to be one"
    assert nodesync.panel_secret() == minted, "it is stable, not regenerated per call"
    assert db.get_meta("panel_secret") == minted
    # it is offered to nodes as the shared credential ...
    pairs = dict((kind, sec) for sec, kind in nodesync._sync_secrets({"id": 2, "token": "per-node"}))
    assert pairs["shared"] == minted and pairs["token"] == "per-node"
    # ... and reports signed with it are accepted back
    assert nodesync.secret_valid_for_main(minted) is True
    assert nodesync.secret_valid_for_main("nope") is False
    # an explicit env value always wins and is never replaced by the minted one
    monkeypatch.setattr(m.config, "NODE_SECRET", "typed-secret-0123456789")
    assert nodesync.panel_secret() == "typed-secret-0123456789"
    assert db.get_meta("panel_secret") == minted, "minting does not overwrite anything"


def test_claiming_carries_the_minted_secret_when_no_env_is_set(panel, monkeypatch):
    monkeypatch.setattr(m.config, "NODE_SECRET", "")
    db.set_meta("panel_secret", "")
    sent = {}

    class _Resp:
        status_code = 200
        text = '{"ok": true}'

        @staticmethod
        def json():
            return {"ok": True, "claimed": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            sent["json"] = json
            return _Resp()

    monkeypatch.setattr(m.httpx, "AsyncClient", lambda **kw: _Client())
    out = __import__("asyncio").run(m._claim_node("https://node.example.com", "https://panel.example"))
    assert out["ok"] is True
    assert sent["json"]["secret"] == db.get_meta("panel_secret") != ""
