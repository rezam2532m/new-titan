"""The premium layer of the *served* dashboard.

`templates/dashboard.html` ships the shell and the styles, `static/js/titan-bridge.js`
fills it with real data — those two files are what the panel actually serves. These
tests pin the parts that were asked for: premium icon actions instead of buttons
carrying a Persian word (users / configs / subscriptions), a luxury server card per
node, and none of it breaking the render.
"""

import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD = (REPO / "templates" / "dashboard.html").read_text(encoding="utf-8")
BRIDGE = (REPO / "static" / "js" / "titan-bridge.js").read_text(encoding="utf-8")
PAGES_JS = (REPO / "static" / "js" / "pages.js").read_text(encoding="utf-8")

PERSIAN = re.compile(r"[\u0600-\u06FF]")


def _section(name: str) -> str:
    start = DASHBOARD.index(f'<section class="section-view" data-section="{name}">')
    end = DASHBOARD.find('<section class="section-view"', start + 10)
    return DASHBOARD[start:end if end > 0 else len(DASHBOARD)]


def _buttons(chunk: str) -> list[str]:
    return re.findall(r"<button\b.*?</button>", chunk, re.S)


def test_the_dashboard_ships_the_premium_layer():
    assert '<style id="titan-premium">' in DASHBOARD
    for cls in (".ico-btn", ".node-lux", ".nl-dial", ".nl-cap", "rg-fg", ".ping.good", ".sr-medal"):
        assert cls in DASHBOARD, f"{cls} is not styled in the served dashboard"


@pytest.mark.parametrize("section", ["users", "configs", "servers"])
def test_the_primary_action_is_a_premium_icon(section):
    """The bridge binds to `.section-btn.primary`, so keep it and drop the word."""
    chunk = _section(section)
    head = chunk[: chunk.index("</div></div>") + 12]
    primary = [b for b in _buttons(head) if "section-btn primary" in b]
    assert primary, f"{section}: no primary action left"
    assert "ico-btn" in primary[0], f"{section}: the primary action is not an icon button"
    label = re.sub(r"<[^>]+>", "", primary[0]).strip()
    assert label == "", f"{section}: the primary action still shows the text {label!r}"
    assert "<svg" in primary[0], f"{section}: the primary action has no icon"


@pytest.mark.parametrize("section", ["users", "configs", "subscriptions"])
def test_no_action_button_in_those_sections_carries_a_persian_word(section):
    for btn in _buttons(_section(section)):
        classes = re.search(r'class="([^"]*)"', btn)
        classes = classes.group(1) if classes else ""
        # Filter chips ("فعال", "منقضی") stay words on purpose: an icon cannot say them.
        if "section-btn" in classes and "ico-btn" not in classes:
            continue
        text = re.sub(r"<[^>]+>", "", btn).strip()
        assert not PERSIAN.search(text), f"{section}: {text!r} is still written on the button"


def test_the_bridge_renders_icon_actions_and_luxury_cards():
    assert "function icoBtn(" in BRIDGE and "function nodeCard(" in BRIDGE
    assert "class=\"mini-btn\"" not in BRIDGE, "a row or modal still renders a text button"
    # the two actions the new tables added: QR and on/off, in both sections
    for act in ('"data-act":"qr"', '"data-act":"power"', '"data-act":"configs"'):
        assert act in BRIDGE, f"{act} is not wired"
    assert "openSubConfigModal" in BRIDGE and "openNodeSetupModal" in BRIDGE
    assert "const ICONS" in BRIDGE and BRIDGE.count("'<path") + BRIDGE.count("'<rect") >= 10


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_node_flag_prefers_country_code_to_a_stale_stored_emoji():
    """Admin node views should show the ISO location, not a stale flag field."""
    script = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.TITAN_PAGES_JS, 'utf8');
const start = src.indexOf('function flagFor(cc)');
const end = src.indexOf('function flagHtml', start);
if (start < 0 || end < 0) throw new Error('node flag helper not found');
new Function('globalThis', src.slice(start, end) + '\nglobalThis.resolveNodeFlagEmoji = nodeFlagEmoji;')(globalThis);
const cases = [
  [{ country_code: 'DE', flag: '🇳🇱' }, '🇩🇪'],
  [{ country_code: '', flag: '🇸🇬' }, '🇸🇬'],
  [{ country_code: '', flag: '🏳️' }, '🌐'],
];
for (const [node, expected] of cases) {
  const actual = globalThis.resolveNodeFlagEmoji(node);
  if (actual !== expected) throw new Error(`${JSON.stringify(node)}: expected ${expected}, got ${actual}`);
}
"""
    result = subprocess.run(
        [shutil.which("node"), "-e", script], cwd=str(REPO), capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TITAN_PAGES_JS": str(REPO / "static" / "js" / "pages.js")},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_subscription_builder_and_node_detection_are_wired():
    """The two flows the admin asked for, pinned where they can regress.

    * A subscription link is *built*: the tab lists links, the modal offers every
      user with the configs that user can contribute, and saving posts the pick.
    * A node is added by its project domain: the modal can identify the domain,
      and the setup modal copies every variable with a single button when the
      node could not be claimed automatically.
    """
    assert "async function openSubBuilder(" in BRIDGE
    assert "/api/subscriptions/catalog" in BRIDGE
    for act in ('"data-act":"manage"', '"data-act":"copy"', '"data-act":"configs"'):
        assert act in BRIDGE, f"{act} is not wired into the new tables"
    assert "async function detectNode(" in BRIDGE and "/api/nodes/detect" in BRIDGE
    assert "setupCopyAll" in BRIDGE and "setup.block" in BRIDGE
    assert "'data-act':'claim'" in BRIDGE and "act==='claim'" in BRIDGE, \
        "a node cannot be detected/claimed in one click"
    assert "ساخت لینک اشتراک جدید" in DASHBOARD, "the subscriptions head has no new-link button"
    for cls in (".sub-user", ".sub-chip", ".sub-summary", ".det-card", ".det-ok"):
        assert cls in DASHBOARD, f"{cls} is not styled"


def test_the_latency_advisor_measures_from_the_client():
    """The ping that matters is client -> exit, which only a browser can measure.

    The panel's own node cards show panel -> node latency; that number is not the
    one a user feels. The advisor fires cache-busted no-store requests from the
    admin's browser at the panel edge, every enabled node and Cloudflare's nearest
    PoP, so the panel can tell which exit is actually closest to the admin.
    """
    assert "async function openLatencyAdvisor()" in BRIDGE
    assert "async function rttBest(" in BRIDGE and "'no-store'" in BRIDGE
    assert "cp.cloudflare.com/generate_204" in BRIDGE, "no Cloudflare floor to compare against"
    assert "'no-cors'" in BRIDGE, "node probes must be cross-origin safe"
    assert "x-railway-edge" in BRIDGE, "the serving region is not reported"
    # the header's pulse button is the entry point, and it is not a text button
    assert "data-act','advisor'" in BRIDGE
    assert 'data-tip="پینگ‌سنج' in DASHBOARD
    for cls in (".lat-row", ".lat-ms", ".lat-verdict", ".lat-custom"):
        assert cls in DASHBOARD, f"{cls} is not styled"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_bridge_renders_every_section():
    """Runs the real bridge against a stub DOM and a real API shape."""
    r = subprocess.run([shutil.which("node"), str(REPO / "scripts" / "bridge_smoke.js")],
                       cwd=str(REPO), capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TITAN_REPO": str(REPO)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bridge rendered every section" in r.stdout


# ── the two things that were broken on a phone ───────────────────────────────

def test_no_template_leaks_its_own_source_into_the_page():
    """Nothing may follow `</html>`, and no markup may carry raw CSS.

    A block of CSS was appended to the dashboard *after* `</html>`. A browser has
    nowhere to put it except the body, so it painted thirty-odd lines of source
    code under the panel — and, because one of those lines was a single unbreakable
    string, the document became 521 px wide on a 360 px phone. Chrome then switched
    that phone out of its mobile layout to fit the page, which shrank the whole
    dashboard. One missing `</style>` and a document-wide layout change.
    """
    for template in sorted((REPO / "templates").glob("*.html")):
        text = template.read_text(encoding="utf-8")
        closes = list(re.finditer(r"</html\s*>", text, re.I))
        assert closes, f"{template.name}: not a complete document"
        tail = text[closes[-1].end():]
        assert not tail.strip(), f"{template.name} carries {len(tail)} chars after </html>: {tail.strip()[:80]!r}"

        # no `{prop:value}` pair may be sitting in text the browser would show
        stripped = re.sub(r"<(style|script)\b[^>]*>.*?</\1\s*>", " ", text, flags=re.S | re.I)
        stripped = re.sub(r"<!--.*?-->", " ", stripped, flags=re.S)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        leaks = re.findall(r"\{[^{}\n]{0,120}[:;][^{}\n]{0,120}\}", stripped)
        assert not leaks, f"{template.name}: CSS is visible as body text: {leaks[:2]}"


def test_the_dashboard_has_one_shipped_responsive_block():
    assert '<style id="titan-responsive">' in DASHBOARD
    block = DASHBOARD[DASHBOARD.index('<style id="titan-responsive">'):]
    block = block[: block.index("</style>")]
    for rule in (".header{height:auto", ".data-table,.subscription-table{min-width:0",
                 "overflow-x:auto", "font-size:16px"):
        assert rule in block, f"the phone layout lost {rule!r}"
    # the tablet band between 760 and 1100 px used to fall through every media query
    assert "@media (max-width:1100px)" in block


def test_the_login_page_has_one_shipped_responsive_block():
    login = (REPO / "templates" / "login.html").read_text(encoding="utf-8")
    assert '<style id="titan-responsive">' in login
    block = login[login.index('<style id="titan-responsive">'):]
    block = block[: block.index("</style>")]
    # the two panels are 563 + 542 px wide; between 901 and 1125 px they had no rule
    assert "@media (min-width:901px) and (max-width:1125px)" in block
    assert ".password input{font-size:16px" in block, "a phone must not zoom when the password box is focused"
    assert "grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0" in login
    assert ".left{border-top-right-radius:0;border-bottom-right-radius:0}" in login
    assert ".right{border-top-left-radius:0;border-bottom-left-radius:0;margin-left:-1px}" in login
    assert ".left{border-radius:18px 0 0 18px" in block
    assert ".right{border-radius:0 18px 18px 0" in block


def test_every_page_asks_for_the_notch_area():
    for template in sorted((REPO / "templates").glob("*.html")):
        viewport = re.search(r'<meta name="viewport" content="([^"]+)"', template.read_text(encoding="utf-8"))
        assert viewport, f"{template.name}: no viewport meta"
        assert "width=device-width" in viewport.group(1), template.name
