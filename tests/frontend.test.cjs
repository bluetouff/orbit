const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../web/app.js'), 'utf8');
const dataLayer = source.slice(0, source.indexOf('const cv='));

function harness(fetch) {
  const elements = new Map();
  const document = {
    visibilityState: 'visible',
    addEventListener() {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        style: {}, textContent: '', classList: {add() {}, remove() {}},
      });
      return elements.get(id);
    },
  };
  const context = vm.createContext({
    document, fetch, layout() {}, renderStrip() {}, setTimeout, clearTimeout,
  });
  vm.runInContext(dataLayer, context);
  return {elements, run: code => vm.runInContext(code, context)};
}

// Deliberately synthetic unit-test values, never served by the application.
function fixture() {
  return {
    snapshot: '2026-01-01T00:00:00Z',
    coins: [{
      id: 'test-asset', symbol: 'test', name: 'Test asset',
      current_price: 1, market_cap: 100, total_volume: 10,
      price_change_percentage_24h_in_currency: null,
    }],
  };
}

test('missing and nonnumeric inputs cannot turn into financial zeroes', () => {
  const {run} = harness();
  for (const value of ['null', 'undefined', 'true', 'false', '""', '"  "', '[]', '{}', 'NaN', 'Infinity']) {
    assert.equal(run(`safeNum(${value})`), null, value);
  }
  assert.equal(run('safeNum(0)'), 0);
  assert.equal(run('safeNum("1.25")'), 1.25);
  assert.equal(run('safeNum(-1, 0)'), null);
});

test('missing returns and global metrics remain unavailable', () => {
  const {run} = harness();
  const normalized = run(`normalizeSnapshot(${JSON.stringify(fixture())})`);
  assert.equal(normalized.coins[0].price_change_percentage_24h_in_currency, null);
  assert.equal(normalized.coins[0].price_change_percentage_30d_in_currency, null);
  assert.equal(run('normalizeGlobal({}).total_market_cap.usd'), null);
  assert.equal(run('normalizeGlobal({}).market_cap_change_percentage_24h_usd'), null);
});

test('initial outage stays unavailable and the next refresh recovers', async () => {
  let calls = 0;
  const {elements, run} = harness(async () => {
    if (++calls === 1) throw new Error('offline');
    return {ok: true, json: async () => fixture()};
  });
  await run('loadData(true)');
  assert.equal(run('state.universe.length'), 0);
  assert.equal(run('state.global'), null);
  assert.equal(run('state.macroLive'), null);
  assert.match(elements.get('status').textContent, /unavailable/);
  await run('refreshData()');
  assert.equal(calls, 2);
  assert.equal(run('state.universe[0].id'), 'test-asset');
  assert.equal(elements.get('status').style.display, 'none');
});

test('a later outage preserves the last snapshot and its original date', async () => {
  let calls = 0;
  const {run} = harness(async () => {
    if (++calls > 1) throw new Error('offline');
    return {ok: true, json: async () => fixture()};
  });
  await run('loadData(true)');
  const original = run('state.snapshot');
  await run('refreshData()');
  assert.equal(run('state.universe.length'), 1);
  assert.equal(run('state.snapshot'), original);
  assert.equal(run('snapshotFreshness().label'), 'stale');
});
