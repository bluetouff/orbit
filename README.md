# Orbit2

Orbit2 is a l0g Lab watchlist and heatmap for crypto assets.

[Français](README.fr.md) · [User guide (EN)](https://orbit.l0g.fr/docs/en/) · [Guide utilisateur (FR)](https://orbit.l0g.fr/docs/)
Source: [bluetouff/orbit](https://github.com/bluetouff/orbit).
The project is released under the [MIT License](LICENSE).

Privacy-first crypto heatmap, aligned with the other l0g dashboards
(yct/us/euro/energy): a static subdomain served by Apache and fed by a Python
builder running under a systemd timer. **No third-party call from the browser,
no client-side secret, self-hosted logos.**

## Repository Layout

```text
build_snapshot.py            builder (stdlib only): APIs -> /var/lib/orbit/orbit.json + logos
env.example                  template for /etc/orbit/orbit.env
web/
  index.html                 page shell (external assets, strict CSP, no inline JS)
  legal/index.html           legal, privacy and GDPR notice for Orbit2 / l0g Lab
  docs/index.html            French user guide (static, no JavaScript required)
  docs/en/index.html         English user guide
  orbit.svg                  local favicon + brand mark
  app.css                    styles
  core.js                    normalization, source freshness, signal math, import and layout
  app.js                     UI (reads ./data.json + ./logos/, 30-45 s refresh)
  icons/                     locally vendored Lucide icons and upstream license
  data.json                  local snapshot link (generated, never committed)
deploy/
  orbit-snapshot.service     hardened systemd oneshot unit
  orbit-snapshot.timer       trigger (about every 30 s; each feed has its own cache)
  orbit.l0g.fr.conf          Apache vhost (strict CSP, data.json + logos aliases)
scripts/
  validate_snapshot.py       validates the public orbit.json contract
  preview.py                 loopback preview using public or local real snapshots
  verify_collection.py       read-only proof of two crypto collection renewals
  deploy_front.py            immutable static release with guarded rollback
  deploy_release.py          coordinated collector + frontend release
RUNBOOK.md                   detailed deployment procedure
```

## Short Version

1. The production Demo profile collects up to 250 cryptos every 5 minutes,
   plus CoinGecko global context hourly. Without a profile, the legacy defaults
   remain 500 assets and a 60-second market cache.
   Global, LunarCrush and FRED have longer caches. It downloads
   missing logos in bounded batches and atomically writes `orbit.json` into
   `/var/lib/orbit`.
2. Apache serves `web/` as static files and exposes `/data.json` + `/logos/` as
   read-only aliases outside the web root.
3. The browser only reads same-origin assets. CSP is `default-src 'none'`,
   `script-src 'self'`, `connect-src 'self'`.
4. User traffic never multiplies provider calls: 50,000 visitors read the same
   static snapshot, not the CoinGecko/LunarCrush/FRED APIs.

The snapshot also exposes `status` so the app can distinguish what was really
fed by providers: CoinGecko markets, CoinGecko global, LunarCrush, FRED and logo
warmup.

Step-by-step deployment: see **RUNBOOK.md**.

## Local Preview

For UI development without provider credentials or additional provider API calls:

```bash
python3 scripts/preview.py --port 8767
```

Open <http://127.0.0.1:8767/web/>. The local server reads the existing public
`orbit.l0g.fr` snapshot, cached for 30 seconds, and its public logos. It preserves
source timestamps; failures never generate substitute values. Only web assets
are exposed, not the repository or environment files. It binds to loopback only.

### Build Your Own Snapshot

Clone the repository, then generate a real snapshot. No provider keys are
required for the public CoinGecko endpoint; availability and quotas depend on
the provider. Optional credentials must be supplied through your environment.

```bash
git clone https://github.com/bluetouff/orbit.git ORBIT2
cd ORBIT2
mkdir -p /tmp/orbit-preview
ORBIT_OUT_DIR=/tmp/orbit-preview python3 build_snapshot.py
```

Serve this real snapshot through the loopback-only preview, keeping private
collector caches outside the web root:

```bash
python3 scripts/preview.py --port 8767 --snapshot /tmp/orbit-preview/orbit.json --logos /tmp/orbit-preview/logos
```

Open <http://127.0.0.1:8767/web/>. Opening `index.html` directly is unsupported.

If no snapshot is available, the app displays an unavailable state and retries.
It does not substitute invented prices. Generated snapshots and logos are
ignored by Git.

Crypto pages are published atomically as soon as the complete crypto collection
is ready, before social, macro and logo requests. A second publication
adds that context without changing the crypto collection or price timestamps.

## Watchlists and Signals

- New visitors see the home introduction, a real-data market preview, FAQ and
  visible l0g/support links. Preview coins are not added to favorites. Existing
  watchlists open directly; the Orbit logo returns home without clearing them.
  `?view=home` opens that home explicitly. Favorites retain the `orbit.favs.v1`
  key and are capped at 50.
- French and English cover the app, FAQ, methodology and legal page. The browser
  language is used initially; explicit choices use `orbit.locale.v1` locally.
- Tiles show logos and returns, scaled from each tile's dimensions. Areas follow
  performance by default, or market cap / volume. Selection order stays stable.
- The Signals panel lists anomalies and divergences. Each entry opens its inputs,
  threshold, reference size, source, collection time and methodology.
  Crypto asset dialogs open on signed signal gauges; market history and social context
  remain in a separate keyboard-accessible tab. Existing anomaly thresholds
  and formulas are unchanged.
- Snapshot context adds the median return and rising / unchanged / falling
  asset counts for the selected period, across the usable reference universe.
  The displayed coverage includes the denominator and dated-observation count.
  Stale data or fewer than 20 usable returns produce an unavailable state.
- Each eligible crypto asset shows its relative return against Bitcoin (CoinGecko ID `bitcoin`):
  `100 * ((100 + asset return %) / (100 + BTC return %) - 1)`.
  This is not the simple difference of returns. The market-median comparison
  **is** a difference, labelled in percentage points, not percent.
  Missing BTC, invalid returns, a BTC return of -100%, or stale observations
  suppress the BTC comparison. Two supplied timestamps must be at most 60
  seconds apart. Missing observation times remain explicitly collection-only;
  they do not establish synchronous quotes. These are context, not new alerts.
- The crypto reference includes valid crypto assets in the snapshot, including stablecoins,
  not just the visible watchlist. At least 20 valid observations are required.
- Price anomalies use absolute population z-scores above 2. Activity anomalies
  use z-scores above 2 for `log10(1 + 1000 * 24h volume / market cap)`.
  Divergences use an absolute price/activity z-score gap above 1.2, in 24H only.
  These heuristics compare assets cross-sectionally, not against their history.
- Prices, returns, performance colors and signals are suppressed when market
  collection fails or its age is unknown. The Demo profile allows 7 minutes
  for collection (5-minute cadence plus scheduling tolerance), and requires
  individual prices dated within 10 minutes. Legacy profiles keep the strict
  3-minute boundary and label undated prices as collection-only.
  A malformed supplied timestamp is rejected, not treated as missing.
- LunarCrush is separate context, never a substitute activity axis. Ambiguous
  symbols are discarded by the builder; remaining symbol matches are indicative.
  FRED observation dates are separate from collection times.
- Display preferences use `orbit.settings.v2`. JSON import/export stays local;
  imports are bounded to 16 KB / 50 coins and require merge or replace confirmation.
- No signal history, visitor identifier or analytics is stored. Calculations
  use only the current snapshot in memory; local storage remains limited to
  favorites, display settings and language. No cookies are introduced.
- Asset buttons support keyboard focus, arrow navigation, Enter and native
  dialog dismissal. The UI respects zoom and does not run continuous animation.

No signal is a probability, a trading recommendation or evidence of accumulation.
Browser polling does not change provider cadence. Production timer and provider
plan limits must be checked independently before changing collection frequency.
CoinGecko's [market endpoint contract](https://docs.coingecko.com/reference/coins-markets)
documents the return horizons and `last_updated` field. This field is an upstream
update timestamp, not proof that every constituent exchange traded at that moment.
There is no backtest or independently calibrated predictive-confidence score.

## Checks

```bash
node --test tests/*.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
node --check web/core.js
node --check web/app.js
node --check web/i18n.js
```

Optional end-to-end checks use an existing Playwright installation:
`node tests/browser.cjs`, `node tests/experience-browser.cjs`,
`node tests/crypto-only-browser.cjs` and `node tests/docs-browser.cjs` (set `NODE_PATH`
when it is installed outside this repo).
Start the preview on port 8767 first, or set `ORBIT_PREVIEW_URL` to its loopback
origin. Real-data screenshots cover 320px / 390px mobile, desktop and 4K. Failure
tests use isolated synthetic fixtures, never production or preview data.

## Compatibility and licensing

The existing `orbit` service names, paths, public domain and browser watchlist
key are preserved for deployment compatibility. Renaming the product does not
require resetting favorites or changing the production service.

The MIT license covers the repository's software and documentation. Market
data, provider services and third-party cryptocurrency logos remain subject
to their owners' terms; they are not distributed or relicensed by this repository.
See [SECURITY.md](SECURITY.md) for private reporting and contribution checks.

## Documentation and release

The app and legal page link to the user guide in the selected language. The
guides have independent FR/EN URLs, work with JavaScript disabled, and cover
favorites, map controls, source age, crypto
formulas and privacy. Their contents are versioned with the app and deploy
with the same `orbit-release` revision marker.

For an existing installation, use `scripts/deploy_release.py` when changing the
collector as well as the frontend. It validates the host contract and backs up
code and any legacy xStocks units. During activation it stops and disables the
legacy Kraken timer, removes its worker and units, and installs the crypto-only
builder. It validates a new crypto-only snapshot before publishing the four
entry pages with immutable assets. Failures restore the previous code, units,
timer state and affected entry pages. Provider credentials, Apache configuration
and crypto timer configuration are preserved. Unused private token caches stay
outside the web root and are never read by the builder.
The precise administrator commands and rollback procedure are in [RUNBOOK.md](RUNBOOK.md).

CoinGecko 429 responses trigger a shared, persistent cooldown across crypto market
and global requests. The collector honors `Retry-After`, uses bounded
exponential backoff when the header is absent, and preserves quote and successful
collection timestamps. A new snapshot may report a failed attempt and refresh
independent sources. Requests are spaced by at least two seconds within a run.
A failed crypto page never publishes a partial universe or prevents macro
collection.
The private cooldown file contains only numeric transport metadata, is outside
the web root and is ignored by Git. See [HTTP 429 recovery](RUNBOOK.md#coingecko-http-429-recovery)
for deployment waiting and rollback behavior.

## Free Demo collection profile

Activate an existing installation with `deploy_release.py --demo-250 --apply`
plus the exact `--revision` (see [runbook](RUNBOOK.md#free-demo-profile-and-outage-recovery)).
This selects the existing Demo key without changing or copying the secret file.
The root-owned `/opt/orbit/collection.profile` contains only `demo-250-v1`.
Subsequent releases preserve it; the activation backup can restore its absence.

One market request per 5 minutes and one global request per hour represent
9,672 calls over 31 days, before extra/manual calls, against the
[Demo allowance of 10,000 monthly calls](https://www.coingecko.com/en/api/pricing).
The private, locked monthly ledger reserves every Demo request before sending it,
including failed requests. It stops at 10,000 until the next UTC calendar month.
It counts only this installation since activation; usage elsewhere or earlier
with the same key is unknown. Corrupt state blocks requests and requires repair,
never an automatic budget reset. Provider limits and availability still apply.

Favorites outside the smaller universe remain saved and are labelled unavailable.
No price is fabricated or redated. Release validation requires a new successful
collection and at least 90% of the returned prices dated within 10 minutes,
including Bitcoin, with at least 20 assets. Each older or undated price remains
unavailable in the interface even when that coverage check passes.

## List view and optional statistical reference

Map/List preserves the current watchlist, horizon and filter. List search is
local to the displayed selection; sorting is explicit, unavailable values sort
last, and mobile rows retain price, cap and volume. Divergence filtering is
disabled outside 24H and resets to all assets when the horizon changes.

The optional screened reference excludes a reviewed, partial list of stablecoin
and tokenized-asset IDs. Unknown IDs stay unclassified. The sources, review date,
excluded assets and signal counts under both references are visible in the
composition details. All assets remains the default; neither method has
predictive validation. See the bilingual user guide for the primary sources.

The collector validates coverage before each market publication and rejects
non-finite JSON. Local operational health and budget projections are described
in [the runbook](RUNBOOK.md#runtime-health-coverage-and-budget-alerts).

The deterministic CI browser suite requires only a loopback preview and isolated
fixtures, with no provider traffic:

```bash
npm ci --ignore-scripts
npx --no-install playwright install chromium
npm run test:browser
```

Playwright is a pinned development dependency only. No dependency is added to
the browser application or production collector. Failure screenshots are kept
as CI artifacts for seven days.
