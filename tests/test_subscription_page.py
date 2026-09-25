"""The page behind a subscription link (/p/<token>).

The admin uploaded a design (profile, usage ring, subscription box, add-to-client
grid, config list, downloads, contact menu) and asked for exactly one thing to
happen to it: fill it with the real data of the link. These tests pin that — the
page is served as-is, the data comes from the panel, the profile set in the
dashboard is what shows up, and a switched-off link still opens but hands out
nothing. The subscription link itself carries the page too: a browser opening
/s/<token> sees it, while a client at the same address still gets its configs.
"""
import base64
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

ORIGIN = {"Origin": "http://testserver"}
#: a person opening the link in a browser
BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
#: a client importing a subscription
CLIENT = {"Accept": "*/*", "User-Agent": "v2rayNG/1.9.16"}


def _is_html(r) -> bool:
    return "text/html" in r.headers.get("content-type", "")


def _is_payload(r) -> bool:
    return r.headers.get("content-type", "").startswith("text/plain")
UID_ZERO = "00000000-0000-0000-0000-000000000001"


@pytest.fixture()
def panel(admin):
    created: list = []

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

    try:
        yield _Panel(admin)
    finally:
        for sub_id in created:
            db.delete_subscription(sub_id)


def _user(panel, name, **extra):
    body = {"name": f"{name}-{base64.b32encode(name.encode()).decode()[:4]}",
            "protocol": "vless", "transport": "ws", "security": "tls", **extra}
    r = panel.post("/api/users", json=body, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["user"]["uid"], body["name"]


def _link(panel, uids, name="pack", **extra):
    r = panel.post("/api/subscriptions", json={
        "name": name, "items": [{"uid": u, "configs": []} for u in uids], **extra},
        headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["subscription"]


def test_the_page_is_served_with_the_uploaded_design_intact(panel):
    uid, _ = _user(panel, "page")
    sub = _link(panel, [uid])
    r = panel.get(f"/p/{sub['token']}")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    html = r.text
    # the design the admin uploaded: every section, id and behaviour still there
    for anchor in ('id="subLink"', 'id="addClients"', 'id="addTabs"', 'id="downloadTabs"',
                   'id="downloads"', 'id="latest"', 'id="allConfigs"', 'id="modal"',
                   'id="toast"', 'id="supportMenu"', 'id="supportButton"', 'id="langSwitch"',
                   'class="ring"', 'class="profile-halo"', 'class="crown"'):
        assert anchor in html, anchor
    # ... and the page is wired, not a mock-up
    assert "v2rayng://install-sub" in html and "v2box://install-sub" in html
    assert "hiddify://install-sub" in html and "streisand://import/" in html
    assert "/p/'+encodeURIComponent(state.token)+'/data" in html, "reads the panel"
    assert "کلاینت مورد نظر روی سیستم عامل شما نصب نیست" in html
    assert r.headers.get("cache-control", "").startswith("no-store")


def test_the_page_carries_the_contact_links_the_admin_gave(panel):
    uid, _ = _user(panel, "contact")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    assert "https://github.com/mr-rashidi" in html
    assert "https://t.me/Code_Shield" in html


def test_the_page_data_is_the_real_subscription(panel):
    ali, ali_name = _user(panel, "pageali", expire_days=7, quota_gb=50)
    sara, _ = _user(panel, "pagesara", expire_days=30, quota_gb=50)
    sub = _link(panel, [ali, sara], name="پک خانواده")
    d = panel.get(f"/p/{sub['token']}/data").json()

    assert d["profile"]["name"] == "پک خانواده"
    assert d["subscription"]["enabled"] is True and d["subscription"]["serves_links"] is True
    assert d["subscription"]["url"].endswith("/s/" + sub["token"])
    assert d["subscription"]["page_url"].endswith("/p/" + sub["token"])
    assert d["counts"]["users"] == 2
    assert d["counts"]["configs"] == len(d["configs"]) > 0
    for c in d["configs"]:
        assert c["link"].startswith(("vless://", "vmess://", "trojan://", "ss://"))
        assert c["name"].startswith("TiTaN-") and c["name"][-3] == "-"
        assert c["target"] in ("panel", "node")
        assert "city" in c and "country_code" in c
    # the numbers are the users' numbers, summed
    u = d["usage"]
    assert u["total_bytes"] == sum(int(db.get_user(x)["quota_bytes"] or 0) for x in (ali, sara))
    assert u["used_bytes"] == sum(int(db.get_user(x)["used_up"] or 0)
                                  + int(db.get_user(x)["used_down"] or 0) for x in (ali, sara))
    assert u["active"] is True and u["expire_at"] > 0 and u["days_left"] is not None
    assert ali_name.split("-")[0] in {v["name"].split("-")[0] for v in d["users"]}


def test_the_profile_set_in_the_dashboard_is_the_one_shown(panel):
    uid, _ = _user(panel, "prof", avatar="gallery:g1")
    sub = _link(panel, [uid])
    # no picture on the link yet: the user's own one stands in
    d = panel.get(f"/p/{sub['token']}/data").json()
    assert d["profile"]["kind"] == "user" and d["profile"]["avatar"] == f"/s/{sub['token']}/avatar"
    r = panel.get(f"/s/{sub['token']}/avatar")
    assert r.status_code == 200 and r.content, "the picture is served without a session"

    # set on the link: it wins, and it is what the API reports back
    upd = panel.patch(f"/api/subscriptions/{sub['id']}",
                      json={"avatar": "gallery:g1", "plan": "Ultra 100GB"},
                      headers=ORIGIN).json()["subscription"]
    assert upd["avatar"] == "gallery:g1" and upd["plan"] == "Ultra 100GB"
    assert upd["page_url"].endswith("/p/" + sub["token"])
    assert upd["avatar_url"].endswith("g1.svg")
    d2 = panel.get(f"/p/{sub['token']}/data").json()
    assert d2["profile"]["kind"] == "subscription" and d2["plan"] == "Ultra 100GB"


def test_a_switched_off_link_opens_but_serves_nothing(panel):
    uid, _ = _user(panel, "off")
    sub = _link(panel, [uid])
    panel.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": False}, headers=ORIGIN)

    # the client face stays exactly as it was: 403, no payload
    assert panel.get(f"/s/{sub['token']}").status_code == 403
    assert panel.get(f"/s/{sub['token']}/json").status_code == 403

    # the human page still opens and tells the truth
    assert panel.get(f"/p/{sub['token']}").status_code == 200
    d = panel.get(f"/p/{sub['token']}/data").json()
    assert d["subscription"]["enabled"] is False
    assert d["subscription"]["serves_links"] is False
    assert d["configs"] == [] and d["subscription"]["url"] == ""
    assert d["profile"]["name"], "the profile is still shown when the link is off"


def test_the_raw_subscription_is_unchanged_for_clients(panel):
    uid, _ = _user(panel, "raw")
    sub = _link(panel, [uid])
    body = panel.get(f"/s/{sub['token']}").text
    lines = [ln for ln in base64.b64decode(body).decode().splitlines()
             if ln.strip() and UID_ZERO not in ln]
    assert lines, "the client still gets the base64 payload"
    j = panel.get(f"/s/{sub['token']}/json").json()
    assert j["name"] and j["users"] and j["links"], "the debug view keeps its old fields"
    assert j["profile"]["name"] and j["usage"]["total_bytes"] >= 0
    assert j["subscription"]["url"].endswith("/s/" + sub["token"])


def test_an_unknown_token_is_a_404_everywhere(panel):
    for path in ("/p/nope", "/p/nope/data", "/s/nope/avatar"):
        assert panel.get(path).status_code == 404, path

def test_the_subscription_link_itself_opens_the_panel_in_a_browser(panel):
    """One address, two faces — and never the wrong one."""
    uid, _ = _user(panel, "both")
    sub = _link(panel, [uid])

    r = panel.get(f"/s/{sub['token']}", headers=BROWSER)
    assert r.status_code == 200 and _is_html(r)
    assert 'id="addClients"' in r.text and 'id="subLink"' in r.text
    assert r.headers.get("cache-control", "").startswith("no-store")

    # the very same address still hands the client its configs
    raw = panel.get(f"/s/{sub['token']}", headers=CLIENT)
    assert raw.status_code == 200 and _is_payload(raw)
    assert base64.b64decode(raw.text)

    # ?raw=1 is always the payload, whatever asks
    assert _is_payload(panel.get(f"/s/{sub['token']}?raw=1", headers=BROWSER))

    # the debug and base64 faces never turn into html
    assert panel.get(f"/s/{sub['token']}/json", headers=BROWSER).json()["counts"]["users"] == 1
    assert _is_payload(panel.get(f"/s/{sub['token']}/base64", headers=BROWSER))

    # a switched-off link: the person still gets the page, the client gets 403
    panel.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": False}, headers=ORIGIN)
    assert panel.get(f"/s/{sub['token']}", headers=BROWSER).status_code == 200
    assert panel.get(f"/s/{sub['token']}", headers=CLIENT).status_code == 403
    assert panel.get(f"/s/{sub['token']}?raw=1", headers=BROWSER).status_code == 403

def test_the_builder_knows_each_users_picture(panel):
    """The subscriptions section sets pictures exactly like users/configs do."""
    uid, _ = _user(panel, "catpic", avatar="gallery:g4")
    cat = panel.get("/api/subscriptions/catalog").json()
    row = next(u for u in cat["users"] if u["uid"] == uid)
    assert row["avatar"] == "gallery:g4", "the catalog carries the key"
    assert row["avatar_url"].endswith("g4.svg"), "and a URL the picker can show"

    # changing it from the builder is the plain users endpoint
    r = panel.patch(f"/api/users/{uid}", json={"avatar": "gallery:g2"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    cat2 = panel.get("/api/subscriptions/catalog").json()
    row2 = next(u for u in cat2["users"] if u["uid"] == uid)
    assert row2["avatar"] == "gallery:g2" and row2["avatar_url"].endswith("g2.svg")

    # the link itself carries a picture too, and it wins over the user's on the page
    sub = _link(panel, [uid], avatar="gallery:g6", plan="Pro")
    link_pic = panel.get(f"/s/{sub['token']}/avatar")
    assert link_pic.status_code == 200 and link_pic.content
    d = panel.get(f"/p/{sub['token']}/data").json()
    assert d["subscription"]["url"].endswith("/s/" + sub["token"])
    assert d["profile"]["kind"] == "subscription" and d["plan"] == "Pro"

    # ... and the row can take it away again: back to the user's own face
    panel.patch(f"/api/subscriptions/{sub['id']}", json={"avatar": ""}, headers=ORIGIN)
    d2 = panel.get(f"/p/{sub['token']}/data").json()
    assert d2["profile"]["kind"] == "user"

def test_every_config_row_carries_a_flag_and_the_name_of_its_place(panel):
    """The config list shows the server's flag and where it lands, by name."""
    from app.main import _entry_place

    # a node carries the place a config lands in; the panel carries its own
    node_place = _entry_place({"target": "node", "node": {"name": "Dubai-Edge", "city": "Dubai",
                                                          "country_code": "AE", "flag": "🇦🇪"}})
    assert node_place == {"place": "Dubai-Edge", "city": "Dubai",
                          "country_code": "ae", "flag": "🇦🇪"}
    local_place = _entry_place({"target": "panel"})
    assert local_place["country_code"] and local_place["place"]

    uid, _ = _user(panel, "flagcity")
    sub = _link(panel, [uid])
    d = panel.get(f"/p/{sub['token']}/data").json()
    for cfg in d["configs"]:
        assert cfg["country_code"], "the page is told which country the config is in"
        assert cfg["flag"] or cfg["country_code"], "so it can draw that country's flag"
        assert cfg["city"] or cfg["place"], "and where the config really lands"
        assert cfg["name"].startswith("TiTaN-")

    # the page turns that into a flag image plus a named location, in both languages
    html = panel.get(f"/p/{sub['token']}").text
    assert "function flagUri" in html and "function locationLabel" in html
    assert "CC_NAMES" in html and "آمریکا" in html and "United States" in html
    assert "flagUri(c[0])" in html, "the row draws the flag of that country"
    assert "esc(place)" in html and "esc(c[2])" in html, "and prints the place, not the code"
    # the design's own flag artwork is reused for the countries it ships
    assert '"us":"data:image/' in html and '"nl":"data:image/' in html and '"de":"data:image/' in html


def test_the_page_never_paints_a_light_layer_over_the_uploaded_background(panel):
    """The design's artwork is the background — nothing may wash it out."""
    uid, _ = _user(panel, "bg")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    # the design's own darkening gradient is gone: it read as a grey veil over
    # the whole page, and repeated past the body box as a seam under the content
    assert "linear-gradient(180deg,rgba(2,3,12,.08)" not in html
    assert "rgba(2,3,12,.42)" not in html
    # the artwork is painted on its own fixed backdrop, at the design's position
    assert "body::before{" in html
    assert "position:fixed;inset:0;z-index:-1" in html
    assert "center top / cover no-repeat" in html
    # the artwork is declared as what it is: a JPEG (it was labelled image/png,
    # which strict browsers refuse — the art vanished and only the veil stayed)
    assert 'url("data:image/jpeg;base64,/9j/' in html
    assert 'url("data:image/png;base64,/9j/' not in html
    # and the page's base colour is the design's own --bg, never a white wash
    assert "getPropertyValue('--bg')" in html
    assert "background:#fff" not in html.lower().replace(" ", "")

def test_a_volume_may_be_set_in_megabytes(panel):
    """A config can be metered in MB — and the renewal reopens it."""
    # create with megabytes
    r = panel.post("/api/users", json={"name": "mbuser", "protocol": "vless", "transport": "ws",
                                       "security": "tls", "quota_mb": 500}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["quota_gb"] == round(500 / 1024, 3)
    assert user["quota_mb"] == 500.0
    uid = user["uid"]

    # ... and change it from GB to MB again
    upd = panel.patch(f"/api/users/{uid}", json={"quota_mb": 1500}, headers=ORIGIN).json()["user"]
    assert upd["quota_mb"] == 1500.0
    assert int(db.get_user(uid)["quota_bytes"]) == 1500 * 1024 ** 2

    # the explicit pair works too
    panel.patch(f"/api/users/{uid}", json={"quota": 2, "quota_unit": "mb"}, headers=ORIGIN)
    assert db.get_user(uid)["quota_bytes"] == 2 * 1024 ** 2
    panel.patch(f"/api/users/{uid}", json={"quota": 3, "quota_unit": "gb"}, headers=ORIGIN)
    assert db.get_user(uid)["quota_bytes"] == 3 * 1024 ** 3

    # bad input is a 400, never a 500
    assert panel.patch(f"/api/users/{uid}", json={"quota_mb": "abc"}, headers=ORIGIN).status_code == 400


def test_a_spent_volume_really_cuts_the_config_off(panel):
    """Quota reached → disabled + Xray reloaded; renewing brings it back."""
    from app import main as app_main
    from app import tasks

    uid, _ = _user(panel, "cutoff", quota_mb=1)
    quota = int(db.get_user(uid)["quota_bytes"])
    db.set_user_usage(uid, quota, 0)          # the whole volume is spent
    reloads = []
    app_main._reload_xray = lambda *a, **k: reloads.append(1)   # spy (patched below too)

    assert tasks._check_quota(uid) is True, "the user was cut off"
    assert not db.get_user(uid)["enabled"], "and the row is disabled"

    # the helper writes the config and restarts Xray — that is what makes the
    # client actually stop, instead of keeping a live credential
    calls = []
    tasks.xray.write_xray_config = lambda *a, **k: calls.append("write")
    tasks.xray.restart_xray = lambda *a, **k: calls.append("restart")

    import asyncio
    asyncio.run(tasks._apply_cutoffs([uid]))
    assert calls == ["write", "restart"], calls

    # a second call is a no-op: no endless restart loop
    assert tasks._check_quota(uid) is False

    # renewing the volume reopens it ...
    upd = panel.patch(f"/api/users/{uid}", json={"quota_mb": 500}, headers=ORIGIN).json()["user"]
    assert bool(upd["enabled"]) is True, "raising the volume brought the config back"

    # ... and so does resetting the usage
    quota = int(db.get_user(uid)["quota_bytes"])
    db.set_user_usage(uid, quota, 0)
    tasks._check_quota(uid)
    assert not db.get_user(uid)["enabled"]
    r = panel.post(f"/api/users/{uid}/reset", headers=ORIGIN).json()
    assert r["reopened"] is True and bool(db.get_user(uid)["enabled"])


def test_nothing_opaque_can_end_up_in_front_of_the_artwork(panel):
    """The art lives on `body::before` with z-index:-1 — behind every background.

    So neither the body's own rule nor the page's script may paint an opaque
    colour on the body: a background there is drawn *over* a negative-z-index
    layer, which is how the artwork once vanished behind a flat navy page while
    every HTML-level check still looked right.
    """
    uid, _ = _user(panel, "layer")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    import re
    body_rules = re.findall(r"body\{([^}]*)\}", html)
    assert body_rules, "the page has no body rule at all"
    assert any("background:transparent" in r for r in body_rules)
    for rule in body_rules:
        assert not re.search(r"background(-color)?:\s*(?!transparent)[^;}]+;?", rule), rule
    # the navy lives on the root element, where it is only ever the canvas colour
    assert re.search(r"html\{[^}]*background:var\(--bg\)", html)
    assert "document.body.style.backgroundColor" not in html, \
        "the script must not give the body an opaque background"
    # the base colour is the canvas colour, on the root element
    assert "document.documentElement.style.backgroundColor" in html


def test_the_page_script_would_actually_run(panel):
    """A parse error in the inline script silently kills every fix on the page.

    That already happened once: a comment holding a line break between `async`
    and `function` makes the parser read a bare `async` identifier, the script
    dies with "async is not defined" before boot() ever runs — and the page just
    keeps showing the design's sample numbers. `node --check` catches it.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    uid, _ = _user(panel, "parse")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    blocks = [m.group(2) for m in re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", html, re.S)
              if "application/json" not in m.group(1) and m.group(2).strip()]
    assert blocks, "the page has no inline script at all"
    assert "boot();" in "".join(blocks), "nothing boots the page"
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    for body in blocks:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(body)
            path = fh.name
        proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
        pathlib.Path(path).unlink()
        assert proc.returncode == 0, proc.stderr[:500]


def test_a_small_volume_is_written_in_megabytes_everywhere_the_client_looks():
    """A 250 MB plan must not be described to the client as "0.24GB".

    The info line is the first thing a user sees in the client's config list, so
    it has to speak the same unit the plan was sold in.
    """
    from app.links import volume_text

    assert volume_text(0, 250 * 1024 ** 2) == "0.00/250MB"
    assert volume_text(1024 ** 2, 512 * 1024 ** 2) == "1.00/512MB"
    assert volume_text(0, 10 * 1024 ** 3) == "0.00/10GB"                 # GB is untouched
    assert volume_text(int(3.5 * 1024 ** 3), 10 * 1024 ** 3) == "3.50/10GB"
    assert volume_text(0, 0) == "0.00/0GB"                              # unlimited stays as it was


def test_the_page_declares_itself_dark_so_no_browser_filter_is_added(panel):
    """Chrome on Android auto-darkens pages that do not say what they are.

    That filter is applied by the browser on top of the page — no CSS inside the
    page can remove it — which is a "layer" the admin can see on his phone while
    nothing is wrong in the HTML. Declaring `color-scheme: dark` makes the
    browser leave the page alone, and the page is dark anyway.
    """
    uid, _ = _user(panel, "scheme")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    assert '<meta name="color-scheme" content="dark">' in html
    assert "color-scheme:dark" in html
    # and the canvas colour is the design's own navy, so the band a phone shows
    # while the page is still loading cannot flash white either
    assert '<meta name="theme-color" content="#03040d">' in html


def test_the_admin_s_own_background_is_the_top_layer(panel):
    """A file in the repo is the page's background; the design stays as a fallback.

    The admin replaces the picture by uploading `static/img/backm.png` — no code
    change. The design's own artwork is kept underneath it on purpose: a file that
    is missing, half-uploaded or unreadable makes the browser drop that layer and
    paint the one below, so the page can never go blank while he swaps pictures.
    """
    import re

    uid, _ = _user(panel, "bgorder")
    sub = _link(panel, [uid])
    html = panel.get(f"/p/{sub['token']}").text
    block = html[html.index("body::before"): html.index("}", html.index("body::before"))]
    urls = re.findall(r'url\("([^"]+)"\)', block)
    assert urls, block
    assert urls[0] == "/static/img/backm.png", urls[0]
    assert urls[1].startswith("data:image/jpeg;base64,/9j/"), "the fallback layer went missing"
    # both layers sized and placed the same way, so a swap changes nothing else
    assert block.count("center top / cover no-repeat") == 2
    # and the file the page points at is part of the repo that serves it
    assert pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "static", "img", "backm.png").exists(), "the background file is missing from the repo"
