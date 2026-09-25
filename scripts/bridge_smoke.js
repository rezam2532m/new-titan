/* Renders the live dashboard in node with a stub DOM.
 *
 * The panel has no build step: `templates/dashboard.html` ships a static shell
 * and `static/js/titan-bridge.js` fills it with real data. A stray quote in the
 * new premium markup is a blank section in production and nothing else in the
 * test suite would notice, so this loads the real bridge, feeds it real API
 * shapes (including the node sync/edge/raw-port fields) and checks what it
 * produced.
 *
 * Usage: node scripts/bridge_smoke.js   (exit 0 = every section rendered)
 */
const fs = require('fs');
const path = require('path');

const REPO = process.env.TITAN_REPO || path.resolve(__dirname, '..');

function makeEl(tag = 'div') {
  const el = {
    tagName: String(tag || 'div').toUpperCase(), innerHTML: '', textContent: '', value: '',
    checked: false, disabled: false, title: '', id: '', href: '',
    dataset: {}, style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    children: [], _q: {}, onclick: null,
    addEventListener() {}, removeEventListener() {}, appendChild(c) { el.children.push(c); return c; },
    setAttribute(k, v) { el[k] = v; }, getAttribute() { return null; }, removeAttribute() {},
    remove() {}, focus() {}, blur() {}, click() {}, insertAdjacentHTML() {}, scrollIntoView() {},
    closest() { return null; }, getBoundingClientRect: () => ({ width: 0, height: 0, top: 0, left: 0 }),
    querySelector(sel) { return el._q[sel] || (el._q[sel] = makeEl('div')); },
    querySelectorAll() { return []; },
  };
  return el;
}

const handlers = {};
const registry = {};
const documentStub = {
  body: makeEl('body'), documentElement: makeEl('html'), head: makeEl('head'), cookie: '',
  createElement: (t) => makeEl(t), createElementNS: (_ns, t) => makeEl(t), createTextNode: (t) => ({ text: String(t) }),
  getElementById(id) { return registry['#' + id] || (registry['#' + id] = makeEl('div')); },
  querySelector(sel) { return registry[sel] || (registry[sel] = makeEl('div')); },
  querySelectorAll() { return []; },
  addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
  removeEventListener() {}, dispatchEvent() {},
};

const RAW_OPEN = 10009;
const NODES = [
  { id: 1, name: 'سرور اصلی', is_local: true, enabled: true, address: 'http://panel.up.railway.app', flag: '🇺🇸',
    city: 'San Jose', country_code: 'US', country: 'United States', last_seen: 1789000000,
    status: { online: true, latency_ms: 62, cpu: 21, ram: 44, disk: 38, version: '1.0.0', uptime: '3d',
      reason: '', edge_port: 8080 },
    sync: { expected: 2, on_node: 2, has_credential: true, ok: true, at: 1789000000, error: '', serving: ['u1', 'u2'] },
    edge: { scheme: 'http', port: 8080, measured: true }, raw_open: { [RAW_OPEN]: false } },
  { id: 2, name: 'Amsterdam-01', is_local: false, enabled: true, address: 'https://amsterdam-01.up.railway.app', flag: '🇳🇱',
    city: 'Amsterdam', country_code: 'NL', country: 'Netherlands', last_seen: 1789000000,
    status: { online: true, latency_ms: 118, cpu: 34, ram: 52, disk: 91, version: '1.0.0', uptime: '2d', reason: '' },
    sync: { expected: 3, on_node: 3, has_credential: true, credential: 'shared', ok: true, at: 1789000000, error: '', serving: ['u1', 'u2', 'u3'] },
    edge: { scheme: 'https', port: 443, measured: true }, raw_open: { [RAW_OPEN]: false } },
  // Deliberately stale: the country code must win over the stored emoji.
  { id: 3, name: 'Frankfurt-VPS', is_local: false, enabled: true, address: 'https://fra.example.com:8443', flag: '🇳🇱',
    city: 'Frankfurt', country_code: 'DE', country: 'Germany', last_seen: 1789000000,
    status: { online: true, latency_ms: 310, cpu: 12, ram: 28, disk: 33, version: '1.0.0', uptime: '9d', reason: '' },
    sync: { expected: 2, on_node: 2, has_credential: true, ok: true, at: 1789000000, error: '', serving: ['u1', 'u2'] },
    edge: { scheme: 'https', port: 8443, measured: true }, raw_open: { [RAW_OPEN]: true } },
  { id: 4, name: 'Dubai-Edge', is_local: false, enabled: true, address: 'https://dubai.example.net', flag: '🇦🇪',
    city: 'Dubai', country_code: 'AE', country: 'United Arab Emirates', last_seen: 0,
    status: { online: false, latency_ms: null, cpu: null, ram: null, disk: null, reason: 'ConnectError' },
    sync: { expected: 2, on_node: null, has_credential: true, ok: false, at: 1789000000, error: 'HTTP 401', serving: null },
    edge: { scheme: 'https', port: 443, measured: false }, raw_open: {} },
  { id: 5, name: 'Istanbul-02', is_local: false, enabled: false, address: 'istanbul-02.up.railway.app', flag: '🇹🇷',
    city: 'Istanbul', country_code: 'TR', country: 'Turkey', last_seen: 1788000000,
    status: { online: false, latency_ms: null, cpu: null, ram: null, disk: null, reason: '' },
    sync: { expected: 1, on_node: null, has_credential: false, ok: null, at: null, error: '', serving: null },
    edge: { scheme: 'https', port: 443, measured: false }, raw_open: {} },
];
const USERS = [
  { uid: 'u1', name: 'reza', protocol: 'vless', node_id: 2, enabled: true, expire_at: 1790000000, created_at: 1788000000,
    sub_transports: ['ws', 'grpc'], main_link: 'vless://x@node.up.railway.app:443?type=ws',
    status: { used: 12 * 1024 ** 3, expired: false, live_enabled: true, active_connections: 1 } },
  { uid: 'u2', name: 'sara', protocol: 'vmess', node_id: 0, enabled: false, created_at: 1788000000,
    status: { used: 0, expired: false, live_enabled: false, active_connections: 0 } },
];
const PAYLOADS = {
  '/api/stats': { app_version: '1.0.0', total_up: 1024, total_down: 4096, enabled_count: 2 },
  '/api/nodes': { nodes: NODES },
  '/api/users': { users: USERS },
  '/api/reports': { daily: [], totals: {}, protocols: [] },
  '/api/settings': { default_transport: 'ws' },
  '/api/me': { username: 'TiTaN', avatar: null },
  // two links the admin built: one carrying configs of two users, one disabled
  '/api/subscriptions': { ok: true, count: 2, subscriptions: [
    { id: 1, name: 'پک موبایل', enabled: true, token: 'tok-abcdef123456',
      url: 'https://panel.test/s/tok-abcdef123456', users: 2, configs: 3, hits: 7,
      last_used: 1789600000, missing: [], note: '',
      items: [{ uid: 'u1', name: 'Ali', configs: ['ws', 'grpc'] },
              { uid: 'u2', name: 'Sara', configs: ['tcp'] }] },
    { id: 2, name: 'پک دسکتاپ', enabled: false, token: 'tok-998877665544',
      url: 'https://panel.test/s/tok-998877665544', users: 1, configs: 4, hits: 0,
      last_used: 0, missing: [], note: '',
      items: [{ uid: 'u1', name: 'Ali', configs: [] }] },
  ] },
  '/api/subscriptions/catalog': { ok: true, users: USERS.map((u) => ({
    uid: u.uid, name: u.name, protocol: u.protocol, enabled: u.enabled !== false,
    node_id: u.node_id, expired: false,
    configs: [{ key: 'ws', label: 'WS · TLS', transport: 'ws', security: 'tls', target: 'panel', host: 'panel.test' },
              { key: 'grpc', label: 'GRPC', transport: 'grpc', security: 'tls', target: 'panel', host: 'panel.test' }],
    personal_pick: u.sub_transports || [],
  })), subscriptions: [] },
};
const fetchStub = async (url) => {
  const key = String(url).split('?')[0].replace(/\/+$/, '');
  const body = PAYLOADS[key] !== undefined ? PAYLOADS[key] : { ok: true };
  return { ok: true, status: 200, headers: { get: () => 'application/json' },
    json: async () => body, text: async () => JSON.stringify(body) };
};

const windowStub = {
  document: documentStub, addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  location: { hash: '', href: '', origin: 'http://panel.test' },
  matchMedia: () => ({ matches: false, addListener() {}, addEventListener() {} }),
  navigator: { language: 'fa', clipboard: { writeText: async () => {} } },
};

const src = fs.readFileSync(path.join(REPO, 'static/js/titan-bridge.js'), 'utf8');
new Function('window', 'document', 'location', 'navigator', 'localStorage', 'fetch', 'confirm', 'alert',
  'console', 'setTimeout', 'clearTimeout', 'requestAnimationFrame', 'Event', 'CustomEvent', src)(
  windowStub, documentStub, windowStub.location, windowStub.navigator,
  { getItem: () => null, setItem() {}, removeItem() {} }, fetchStub, () => true, () => {},
  console, setTimeout, clearTimeout, (fn) => setTimeout(fn, 0), class {}, class {});

const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); };

(async () => {
  const boot = handlers['DOMContentLoaded'] || [];
  check(boot.length > 0, 'the bridge never registered a DOMContentLoaded handler');
  for (const fn of boot) fn();
  // the bridge defers wireDetails() by 400ms after DOMContentLoaded
  await new Promise((r) => setTimeout(r, 1200));

  const el = (sel) => registry[sel];
  const section = (name) => el(`.section-view[data-section="${name}"]`);
  const inSection = (name, sel) => { const s = section(name); return s ? s._q[sel] : undefined; };
  const html = (node) => (node && typeof node.innerHTML === 'string' ? node.innerHTML : '');

  // ── servers: luxury cards, every state ───────────────────────────────────
  const grid = html(inSection('servers', '.node-grid'));
  check(grid.length > 600, 'the server grid stayed empty');
  check((grid.match(/class="node-lux/g) || []).length === NODES.length,
    `expected ${NODES.length} luxury cards, got ${(grid.match(/class="node-lux/g) || []).length}`);
  for (const needle of ['nl-medal', 'nl-dial', 'nl-metric', 'nl-caps', 'rg-fg', 'ico-btn', 'nl-orb']) {
    check(grid.includes(needle), `server cards are missing ${needle}`);
  }
  check(grid.includes('🇩🇪'), 'the node country code did not override its stale stored flag');
  check(!grid.includes('undefined'), 'server cards contain the string "undefined"');
  check(grid.includes(`raw ${RAW_OPEN} ✓`), 'an open raw port is not shown as open');
  check(grid.includes(`raw ${RAW_OPEN} ✕`), 'a closed raw port is not shown as closed');
  check(grid.includes('sync 3/3 ✓'), 'a healthy sync does not show its served count');
  check(grid.includes('HTTP 401'), 'a failed sync does not show its error');
  check(grid.includes('حالت نگهداری'), 'a disabled node is not flagged as maintenance');
  check(grid.includes('data-act="sync"') && grid.includes('data-act="ping"') && grid.includes('data-act="toggle"'),
    'the per-node actions are not wired');
  check(!grid.includes('>ویرایش<') && !grid.includes('>حذف<'), 'a server action still shows a Persian word');

  // ── users / configs / subscriptions: premium icon actions ────────────────
  for (const [name, acts] of [['users', ['edit', 'detail', 'del', 'qr', 'power', 'configs']],
                              ['configs', ['edit', 'links', 'del', 'qr', 'power']],
                              ['subscriptions', ['manage', 'copy', 'qr', 'power', 'del']]]) {
    const tbody = html(inSection(name, '.data-table tbody'));
    check(tbody.length > 40, `${name}: the table stayed empty`);
    check(!tbody.includes('mini-btn'), `${name}: a text button is still rendered`);
    check((tbody.match(/ico-btn/g) || []).length >= USERS.length, `${name}: rows have no icon actions`);
    for (const act of acts) check(tbody.includes(`data-act="${act}"`), `${name}: missing the ${act} action`);
  }

  // the subscription rows are *links*: name, how many users, how many configs
  const subs = html(inSection('subscriptions', '.data-table tbody'));
  check(subs.includes('sub-count'), 'the subscription rows do not show their counts');
  check(/sub-count[^>]*>2</.test(subs), 'the user count is not rendered');
  check(/sub-count[^>]*>3</.test(subs), 'the config count is not rendered');
  check(subs.includes('پک موبایل') && subs.includes('پک دسکتاپ'), 'the built links are not listed');
  check(!subs.includes('هنوز لینک اشتراکی'), 'the empty state is shown although links exist');

  // a node that can serve shows *which* credential it accepted
  check(grid.includes('shared secret'), 'the node card does not name the accepted credential');
  check(grid.includes('حالت نگهداری'), 'the maintenance state is missing');

  // ── latency advisor (client-side ping, not the panel->node probe) ────────
  const bridgeSrc = src;                       // the real bridge, as loaded above
  const dashboardSrc = fs.readFileSync(path.join(REPO, 'templates/dashboard.html'), 'utf8');
  // ── subscription builder + node auto-detect ──────────────────────────────
  check(/async function openSubBuilder/.test(bridgeSrc), 'the subscription builder is not in the bridge');
  check(/\/api\/subscriptions'/.test(bridgeSrc) && /\/api\/subscriptions\//.test(bridgeSrc),
    'the builder does not talk to the subscription API');
  check(/\.sub-chip/.test(bridgeSrc) && /\.sub-chip/.test(dashboardSrc || ''),
    'the builder chips are not rendered/styled');
  check(/detectNode/.test(bridgeSrc) && /\/api\/nodes\/detect/.test(bridgeSrc),
    'the add-node modal cannot identify a domain');
  check(/setupCopyAll/.test(bridgeSrc) && /setup\.block/.test(bridgeSrc),
    'the setup modal has no copy-every-variable button');
  check(grid.includes('data-act="claim"'), 'the node card has no one-click detect/connect action');
  check(dashboardSrc.includes('ساخت لینک اشتراک جدید'), 'the subscriptions header has no new-link button');

  check(/openLatencyAdvisor/.test(bridgeSrc), 'the latency advisor is not in the bridge');
  check(/data-act','advisor'/.test(bridgeSrc), 'the section-head pulse button is not bound to the advisor');
  check(/cp\.cloudflare\.com\/generate_204/.test(bridgeSrc), 'the advisor does not measure the Cloudflare floor');
  check(/no-cors/.test(bridgeSrc) && /cache:'no-store'/.test(bridgeSrc),
    'the advisor probes are not cache-busted cross-origin requests');
  check(/x-railway-edge/.test(bridgeSrc), 'the advisor does not read the serving region header');
  check(/\.lat-row/.test(dashboardSrc || '') && /\.lat-verdict/.test(dashboardSrc || ''),
    'the advisor rows are not styled in the dashboard');
  const advisorBtn = html(el('.section-view[data-section="servers"] .section-head'));
  check(/data-tip="پینگ‌سنج/.test(dashboardSrc || ''), 'the section head does not offer the ping tool');

  // ── dashboard strip ──────────────────────────────────────────────────────
  const strip = html(el('.server-content'));
  check(strip.includes('sr-medal'), 'the dashboard server strip has no flag medal');
  check(strip.includes('ping good') && strip.includes('ping bad'), 'the strip has no latency colour bands');

  if (failures.length) {
    console.error('FAILURES:\n- ' + failures.join('\n- '));
    process.exit(1);
  }
  console.log(`ok  servers     ${(grid.match(/class="node-lux/g) || []).length} luxury cards, states covered`);
  console.log('ok  users       premium icon actions');
  console.log('ok  configs     premium icon actions');
  console.log('ok  subscriptions built links + builder wired');
  console.log('ok  nodes       domain-only add + copy-all variables');
  console.log('ok  dashboard   latency bands + medals');
  console.log('bridge rendered every section');
})();
