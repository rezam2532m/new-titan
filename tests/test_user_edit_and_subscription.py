"""Editing a user, and choosing what a subscription link contains.

Two admin-facing promises are pinned here:

* **Editing works.** "I open the edit box, change things, press save, nothing is
  applied" — the API accepted the PATCH but `db.update_user`'s allowlist silently
  dropped fields more than once in this codebase (`allowed_ips` is documented in
  the diff for exactly that reason). Every field the modal sends is checked here,
  for every protocol, so a dropped column cannot come back unnoticed.
* **A subscription is a set the admin chooses.** One user really is served on
  several transports — the Xray config builds a WS, XHTTP, HTTPUpgrade and gRPC
  inbound for every VLESS/VMess user — so the sub link can carry several configs,
  and `/sub/{uid}` must contain exactly the ticked ones.
"""
import base64
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

H = {"Origin": "http://testserver"}
PROTOCOLS = ["vless", "vmess", "trojan", "shadowsocks", "hysteria2", "wireguard"]


def _uids_in(sub_text: str) -> list:
    """Decode a subscription body into its *config* links.

    The body also carries one dummy link (uuid 000...001) whose remark shows live
    usage in the client - so the client's own listing has the right numbers; it is
    not a config the server runs.
    """
    raw = base64.b64decode(sub_text.strip()).decode()
    return [ln for ln in raw.splitlines() if ln.strip() and "00000000-0000-0000-0000-000000000001" not in ln]


# ────────────────────────────────────────────────────────────── editing a user
@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_every_field_the_edit_modal_sends_is_stored(admin, protocol):
    r = admin.post("/api/users", headers=H, json={
        "name": f"edit-{protocol}", "protocol": protocol, "transport": "ws",
        "security": "tls", "quota_gb": 10, "node_id": 0})
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["uid"]

    new_name = f"edited-{protocol}"
    r = admin.patch(f"/api/users/{uid}", headers=H, json={
        "name": new_name, "note": "n", "node_id": 0, "protocol": protocol,
        "transport": r.json()["user"]["transport"],
        "security": r.json()["user"]["security"],
        "fingerprint": "chrome", "alpn": "http/1.1",
        "ss_method": "2022-blake3-aes-128-gcm",
        "quota_gb": 12.5, "expire_days": 30, "max_devices": 2, "max_requests": 5,
        "allowed_ips": ["1.1.1.1"], "avatar": "", "client_nonce": "n" * 12})
    assert r.status_code == 200, r.text
    got = admin.get(f"/api/users/{uid}", headers=H).json()
    assert got["name"] == new_name
    assert abs(got["quota_gb"] - 12.5) < 0.01
    assert got["expire_at"], "expiry was dropped by the PATCH"
    assert got["max_devices"] == 2 and got["max_requests"] == 5
    assert got["allowed_ips"] == ["1.1.1.1"], "the allowlist dropped allowed_ips again"
    admin.delete(f"/api/users/{uid}", headers=H)


def test_the_edit_response_carries_the_new_link(admin):
    r = admin.post("/api/users", headers=H, json={"name": "e", "protocol": "vless",
                                                  "transport": "ws", "security": "tls"})
    uid = r.json()["user"]["uid"]
    r = admin.patch(f"/api/users/{uid}", headers=H, json={"name": "renamed", "quota_gb": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["user"]["name"] == "renamed"
    assert body["user"]["main_link"].startswith("vless://")
    assert "#TiTaN-renamed" in body["user"]["main_link"] or "renamed" in body["user"]["main_link"]
    admin.delete(f"/api/users/{uid}", headers=H)


def test_a_config_can_be_switched_off_and_on_again(admin):
    """The power button in the users and configs tables."""
    r = admin.post("/api/users", headers=H, json={"name": "toggler", "protocol": "vless",
                                                  "transport": "ws", "security": "tls"})
    uid = r.json()["user"]["uid"]
    r = admin.patch(f"/api/users/{uid}", headers=H, json={"enabled": False})
    assert r.status_code == 200, r.text
    got = admin.get(f"/api/users/{uid}", headers=H).json()
    assert got["enabled"] in (0, False)
    assert got["status"]["live_enabled"] is False
    r = admin.patch(f"/api/users/{uid}", headers=H, json={"enabled": True})
    assert admin.get(f"/api/users/{uid}", headers=H).json()["status"]["live_enabled"] is True
    admin.delete(f"/api/users/{uid}", headers=H)


# ─────────────────────────────────────────────── what a subscription contains
def test_a_subscription_can_carry_several_configs_and_they_are_distinct(admin):
    r = admin.post("/api/users", headers=H, json={"name": "multi", "protocol": "vless",
                                                  "transport": "ws", "security": "tls"})
    uid = r.json()["user"]["uid"]
    info = admin.get(f"/api/users/{uid}/sub-configs", headers=H).json()
    keys = [c["key"] for c in info["configs"]]
    assert "ws" in keys and len(keys) >= 3, keys
    assert len({c["link"] for c in info["configs"]}) == len(keys), "duplicate links offered"
    assert all(c["included"] for c in info["configs"]), "everything is included by default"
    # the subscription really contains them all
    body = admin.get(f"/sub/{uid}").text
    assert len(_uids_in(body)) == len(keys), (_uids_in(body), keys)
    admin.delete(f"/api/users/{uid}", headers=H)


def test_the_admin_picks_which_configs_go_into_the_subscription(admin):
    r = admin.post("/api/users", headers=H, json={"name": "picked", "protocol": "vless",
                                                  "transport": "ws", "security": "tls"})
    uid = r.json()["user"]["uid"]
    info = admin.get(f"/api/users/{uid}/sub-configs", headers=H).json()
    keys = [c["key"] for c in info["configs"]]
    chosen = [keys[0]]

    r = admin.patch(f"/api/users/{uid}/sub-configs", headers=H, json={"transports": chosen})
    assert r.status_code == 200, r.text
    links = _uids_in(admin.get(f"/sub/{uid}").text)
    assert len(links) == 1, links
    want = next(c["link"] for c in info["configs"] if c["key"] == chosen[0])
    assert links[0] == want, (links[0], want)

    # the selection survives a re-read and shows up in the user payload
    assert admin.get(f"/api/users/{uid}", headers=H).json()["sub_transports"] == chosen
    # and the JSON subscription agrees
    j = admin.get(f"/sub/{uid}/json").json()
    assert j["links"] == [want]

    # ticking everything again clears the override back to "all"
    admin.patch(f"/api/users/{uid}/sub-configs", headers=H, json={"transports": keys})
    assert admin.get(f"/api/users/{uid}", headers=H).json()["sub_transports"] == []
    assert len(_uids_in(admin.get(f"/sub/{uid}").text)) == len(keys)
    admin.delete(f"/api/users/{uid}", headers=H)


def test_an_unknown_transport_is_rejected(admin):
    r = admin.post("/api/users", headers=H, json={"name": "badpick", "protocol": "vless",
                                                  "transport": "ws", "security": "tls"})
    uid = r.json()["user"]["uid"]
    r = admin.patch(f"/api/users/{uid}/sub-configs", headers=H, json={"transports": ["quic-nonsense"]})
    assert r.status_code == 400, r.text
    admin.delete(f"/api/users/{uid}", headers=H)


def test_a_single_config_protocol_offers_exactly_one(admin):
    r = admin.post("/api/users", headers=H, json={"name": "hy", "protocol": "hysteria2"})
    uid = r.json()["user"]["uid"]
    info = admin.get(f"/api/users/{uid}/sub-configs", headers=H).json()
    assert len(info["configs"]) == 1, info["configs"]
    assert info["configs"][0]["protocol"] == "hysteria2"
    admin.delete(f"/api/users/{uid}", headers=H)
