"""Subscription links you build: pick users, pick their configs, get a URL.

The architecture the admin rejected hung the picker off a single user's personal
link. What he wants is the other direction: mint a link, then choose — across
every user — exactly which configs it carries, the way a config is assembled.
These tests pin that: the catalog the builder renders, validation against what
really exists, the public link, and what happens when a user or a config
disappears after the link was built.
"""
import base64
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture()
def panel(admin):
    """The shared admin client, plus cleanup of every link a test mints."""
    created = []

    class _Panel:
        def __init__(self, client):
            self._c = client

        def __getattr__(self, item):
            method = getattr(self._c, item)
            if item not in ("get", "post", "patch", "delete"):
                return method

            def _wrapped(url, **kw):
                r = method(url, **kw)
                if item == "post" and url == "/api/subscriptions" and r.status_code == 200:
                    created.append(r.json()["subscription"]["id"])
                return r

            return _wrapped

        def track(self, sub_id):
            created.append(sub_id)

    try:
        yield _Panel(admin)
    finally:
        for sub_id in created:
            db.delete_subscription(sub_id)


def _user(panel, name, protocol="vless", transport="ws", security="tls", **extra):
    body = {"name": f"{name}-" + base64.b32encode(name.encode()).decode()[:4],
            "protocol": protocol, "transport": transport, "security": security, **extra}
    r = panel.post("/api/users", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["uid"]
    return uid, body["name"]


def _links_in_subscription(panel, token):
    body = panel.get(f"/s/{token}").text
    decoded = base64.b64decode(body).decode()
    return [line for line in decoded.splitlines()
            if line.strip() and "00000000-0000-0000-0000-000000000001" not in line]


def test_the_catalog_offers_every_user_and_the_configs_they_can_carry(panel):
    ali_uid, _ = _user(panel, "ali", "vless", "ws", "tls")
    sara_uid, _ = _user(panel, "sara", "trojan", "tcp", "tls")
    cat = panel.get("/api/subscriptions/catalog").json()
    by_uid = {u["uid"]: u for u in cat["users"]}
    assert ali_uid in by_uid and sara_uid in by_uid
    keys = [c["key"] for c in by_uid[ali_uid]["configs"]]
    assert "ws" in keys and len(keys) >= 4, f"a VLESS user offers several configs: {keys}"
    assert by_uid[ali_uid]["configs"][0]["target"] in ("panel", "node")
    # the stored transport always comes first, so the builder opens on the
    # config the user is actually running today
    assert by_uid[sara_uid]["configs"][0]["key"] == "tcp"
    # identical links are deduped, so a trojan on this edge offers one entry
    assert {c["key"] for c in by_uid[sara_uid]["configs"]} <= {"tcp", "ws"}
    assert all(c["label"] for c in by_uid[ali_uid]["configs"])


def test_a_link_is_built_from_chosen_configs_of_several_users(panel):
    ali, _ = _user(panel, "ali", "vless", "ws", "tls")
    sara, _ = _user(panel, "sara", "trojan", "tcp", "tls")
    r = panel.post("/api/subscriptions", json={
        "name": "پک موبایل",
        "items": [{"uid": ali, "configs": ["ws"]}, {"uid": sara, "configs": ["trojan"]}],
    }, headers=ORIGIN)
    assert r.status_code == 200, r.text
    sub = r.json()["subscription"]
    assert sub["name"] == "پک موبایل" and sub["users"] == 2 and sub["configs"] == 2
    assert sub["url"].endswith("/s/" + sub["token"])
    assert sub["enabled"] is True

    links = _links_in_subscription(panel, sub["token"])
    assert len(links) == 2
    assert any("/vl-ws" in line for line in links), "Ali's WS config is inside"
    assert any(line.startswith("trojan://") for line in links), "Sara's config is inside"
    # the personal link of each user is untouched by the bundle
    assert base64.b64decode(panel.get(f"/sub/{ali}").text).decode().count("\n") >= 4


def test_an_empty_selection_is_refused_and_unknown_entries_are_dropped(panel):
    ali, _ = _user(panel, "ali2", "vless", "ws", "tls")
    assert panel.post("/api/subscriptions", json={"name": "x", "items": []},
                      headers=ORIGIN).status_code == 400
    r = panel.post("/api/subscriptions", json={
        "name": "filtered",
        "items": [{"uid": ali, "configs": ["ws", "does-not-exist"]},
                  {"uid": "ghost", "configs": ["ws"]}],
    }, headers=ORIGIN)
    assert r.status_code == 200
    sub = r.json()["subscription"]
    assert sub["users"] == 1 and sub["configs"] == 1, "only real (user, config) pairs survive"
    assert sub["items"][0]["configs"] == ["ws"]


def test_an_empty_config_list_means_every_config_of_that_user(panel):
    ali, _ = _user(panel, "ali3", "vless", "ws", "tls")
    sub = panel.post("/api/subscriptions", json={"name": "همه", "items": [{"uid": ali, "configs": []}]},
                     headers=ORIGIN).json()["subscription"]
    assert sub["configs"] >= 4, "an empty pick follows the user, new configs included"
    assert len(_links_in_subscription(panel, sub["token"])) == sub["configs"]


def test_editing_a_link_replaces_its_selection(panel):
    ali, _ = _user(panel, "ali4", "vless", "ws", "tls")
    sara, _ = _user(panel, "sara4", "trojan", "tcp", "tls")
    sub = panel.post("/api/subscriptions", json={
        "name": "first", "items": [{"uid": ali, "configs": ["ws"]}]}, headers=ORIGIN).json()["subscription"]
    assert len(_links_in_subscription(panel, sub["token"])) == 1

    r = panel.patch(f"/api/subscriptions/{sub['id']}", json={
        "name": "second",
        "items": [{"uid": sara, "configs": ["trojan"]}, {"uid": ali, "configs": ["ws", "grpc"]}],
    }, headers=ORIGIN)
    assert r.status_code == 200
    edited = r.json()["subscription"]
    assert edited["name"] == "second" and edited["users"] == 2
    assert len(_links_in_subscription(panel, sub["token"])) == 3
    assert panel.get(f"/s/{sub['token']}/json").json()["name"] == "second"


def test_a_disabled_link_is_off_but_keeps_its_token(panel):
    ali, _ = _user(panel, "ali5", "vless", "ws", "tls")
    sub = panel.post("/api/subscriptions", json={
        "name": "off soon", "items": [{"uid": ali, "configs": ["ws"]}]}, headers=ORIGIN).json()["subscription"]
    assert panel.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": False},
                       headers=ORIGIN).json()["subscription"]["enabled"] is False
    assert panel.get(f"/s/{sub['token']}").status_code == 403
    assert panel.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": True},
                       headers=ORIGIN).json()["subscription"]["enabled"] is True
    assert panel.get(f"/s/{sub['token']}").status_code == 200


def test_deleting_a_link_kills_its_url(panel):
    ali, _ = _user(panel, "ali6", "vless", "ws", "tls")
    sub = panel.post("/api/subscriptions", json={
        "name": "temp", "items": [{"uid": ali, "configs": ["ws"]}]}, headers=ORIGIN).json()["subscription"]
    assert panel.delete(f"/api/subscriptions/{sub['id']}", headers=ORIGIN).status_code == 200
    assert panel.get(f"/s/{sub['token']}").status_code == 404
    assert panel.delete(f"/api/subscriptions/{sub['id']}", headers=ORIGIN).status_code == 404


def test_a_link_survives_a_user_being_removed_or_switched_off(panel):
    ali, _ = _user(panel, "ali7", "vless", "ws", "tls")
    sara, _ = _user(panel, "sara7", "vless", "ws", "tls")
    sub = panel.post("/api/subscriptions", json={"name": "pair", "items": [
        {"uid": ali, "configs": ["ws"]}, {"uid": sara, "configs": ["ws"]}]},
        headers=ORIGIN).json()["subscription"]
    assert len(_links_in_subscription(panel, sub["token"])) == 2
    panel.patch(f"/api/users/{sara}", json={"enabled": False}, headers=ORIGIN)
    assert len(_links_in_subscription(panel, sub["token"])) == 1, "a disabled user stops being served"
    panel.delete(f"/api/users/{ali}", headers=ORIGIN)
    listing = next(s for s in panel.get("/api/subscriptions").json()["subscriptions"]
                   if s["id"] == sub["id"])
    assert listing["configs"] == 0, "neither user can be served any more"
    assert listing["missing"] == [ali], "the link says which user disappeared"


def test_the_listing_shows_what_the_admin_needs_on_the_row(panel):
    ali, _ = _user(panel, "ali8", "vless", "ws", "tls")
    created = panel.post("/api/subscriptions", json={"name": "row", "items": [{"uid": ali, "configs": ["ws"]}]},
                         headers=ORIGIN).json()["subscription"]
    row = next(s for s in panel.get("/api/subscriptions").json()["subscriptions"]
               if s["id"] == created["id"])
    for key in ("id", "name", "url", "configs", "users", "hits", "enabled", "items"):
        assert key in row
    assert row["hits"] == 0
    _links_in_subscription(panel, row["token"])
    again = next(s for s in panel.get("/api/subscriptions").json()["subscriptions"]
                 if s["id"] == created["id"])
    assert again["hits"] == 1 and again["last_used"] > 0, "a fetched link counts as used"


def test_the_payload_header_aggregates_the_included_users(panel):
    ali, _ = _user(panel, "ali9", "vless", "ws", "tls", quota_gb=10)
    db.add_user_usage(ali, 1024 ** 3, 2 * 1024 ** 3)
    sub = panel.post("/api/subscriptions", json={"name": "usage", "items": [{"uid": ali, "configs": ["ws"]}]},
                     headers=ORIGIN).json()["subscription"]
    info = panel.get(f"/s/{sub['token']}").headers["subscription-userinfo"]
    assert "total=10737418240" in info and "download=2147483648" in info


def test_subscriptions_need_a_session(panel):
    from fastapi.testclient import TestClient
    from app import main as m
    anon = TestClient(m.app)
    assert anon.get("/api/subscriptions").status_code == 401
    assert anon.post("/api/subscriptions", json={"name": "x", "items": []}).status_code == 401
    unknown = panel.get("/s/not-a-real-token")
    assert unknown.status_code == 404
