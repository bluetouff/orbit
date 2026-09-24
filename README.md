# Orbit2

Orbit2 is a l0g Lab watchlist and heatmap for crypto assets and xStocks.

[Français](README.fr.md) · [User guide (EN)](https://orbit.l0g.fr/docs/en/) · [Guide utilisateur (FR)](https://orbit.l0g.fr/docs/)
Source: [bluetouff/orbit](https://github.com/bluetouff/orbit).
The project is released under the [MIT License](LICENSE).

Privacy-first crypto and xStocks heatmap, aligned with the other l0g dashboards
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
  orbit-snapshot.timer       trigger (crypto markets about every 30 s + at boot)
  orbit.l0g.fr.conf          Apache vhost (strict CSP, data.json + logos aliases)
scripts/
  validate_snapshot.py       validates the public orbit.json contract
  preview.py                 loopback preview using public or local real snapshots
  deploy_front.py            immutable static release with guarded rollback
  deploy_release.py          coordinated collector + frontend release
RUNBOOK.md                   detailed deployment procedure
```

## Short Version

1. `build_snapshot.py` calls CoinGecko markets server-side on each timer run,
   while CoinGecko global, LunarCrush and FRED are TTL-cached. It downloads
   missing logos in bounded batches and atomically writes `orbit.json` into
   `/var/lib/orbit`.
2. Apache serves `web/` as static files and exposes `/data.json` + `/logos/` as
   read-only aliases outside the web root.
3. The browser only reads same-origin assets. CSP is `default-src 'none'`,
   `script-src 'self'`, `connect-src 'self'`.
4. User traffic never multiplies provider calls: 50,000 visitors read the same
   static snapshot, not the CoinGecko/LunarCrush/FRED APIs.

The snapshot also exposes `status` so the app can distinguish what was really
fed by providers: CoinGecko markets, CoinGecko xStocks, CoinGecko global, LunarCrush, FRED and logo
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
ORBIT_OUT_DIR="$PWD/web" ORBIT_LOGO_DIR="$PWD/web/logos" python3 build_snapshot.py
ln -sf orbit.json web/data.json
```

`index.html` loads `app.css`, `app.js` and `data.json` through relative paths, so
the files must be served together. Run a small static server from the repository
root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory web
```

Then open:

```text
http://127.0.0.1:8765/
```

Opening `index.html` directly is expected to fail with the strict CSP and
external asset files.

If no snapshot is available, the app displays an unavailable state and retries.
It does not substitute invented prices. Generated snapshots and logos are
ignored by Git.

## xStocks

The builder adds CoinGecko's `xstocks-ecosystem` category to the crypto feed,
deduplicated by CoinGecko ID. One request retrieves up to 250 category members
with 1H / 24H / 7D / 30D returns and a seven-day sparkline when supplied.
`ORBIT_XSTOCKS_REFRESH_SEC` defaults to 120 seconds (bounded to 60–180).
The category and endpoint were checked against the public API; see the
[CoinGecko market contract](https://docs.coingecko.com/reference/coins-markets).
This adds at most one request every two minutes with the default setting,
independent of visitors. Check the provider plan's monthly budget before release.

- The **xStocks** market view shows up to 50 category members ordered by token
  market cap; the full collected catalog is searchable under **All assets /
  Crypto / xStocks**. Both classes share the existing 50-favorite limit.
- `asset_type` is `crypto` or `xstock`. `status.coingecko_xstocks` has its own
  `fetched_at`, `last_success_at`, `ok` and `reused`. The category is bounded to
  one page; `capped` is true if that page contains 250 rows.
- Token price is required. Missing token market cap or volume stays null.
  Price observation timestamps are preserved. Malformed timestamps are rejected.
- A failed category refresh keeps only previously collected quotes, with their
  original timestamps and an explicit failed status. No synthetic price or
  equity-underlying substitution is used. Crypto collection continues.
- xStocks never enter the crypto median, breadth, anomaly/activity scores or
  BTC-relative comparisons. They receive no LunarCrush symbol matches.
- Token sheets open directly on token market data, without crypto signal gauges.
  Old quotes are marked, and stale tokens use neutral heatmap colors. These are
  tracker certificates with economic exposure, without shareholder voting rights;
  see [the issuer documentation](https://docs.xstocks.fi/docs/frequently-asked-questions).
- Logos remain same-origin. HTTPS host/port restrictions and disabled redirects
  are retained; the logo budget caps attempts, including failures, and alternates
  between xStocks and crypto. CoinGecko credentials use request headers only.

To preview a real locally generated snapshot, preserving its timestamps:

```bash
python3 scripts/preview.py --port 8767 --snapshot /path/to/orbit.json --logos /path/to/logos
```

Run `node tests/xstocks-browser.cjs` against that preview for the token-specific
browser checks. Visual checks require real xStocks data; synthetic inputs are
used only inside isolated failure/security tests.

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
  not just the visible watchlist. xStocks are excluded. At least 20 valid observations are required.
- Price anomalies use absolute population z-scores above 2. Activity anomalies
  use z-scores above 2 for `log10(1 + 1000 * 24h volume / market cap)`.
  Divergences use an absolute price/activity z-score gap above 1.2, in 24H only.
  These heuristics compare assets cross-sectionally, not against their history.
- Signals stop when market collection age is unknown or exceeds three minutes.
  Supplied asset observation timestamps are checked separately. Old snapshots
  without asset timestamps retain an explicit collection-only limitation.
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
`node tests/xstocks-browser.cjs` and `node tests/docs-browser.cjs` (set `NODE_PATH`
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
favorites, map controls, token-versus-underlying metrics, source age, crypto
formulas and privacy. Their contents are versioned with the app and deploy
with the same `orbit-release` revision marker.

For an existing installation, use `scripts/deploy_release.py` when changing the
collector as well as the frontend. It validates the host contract, pauses only
the timer during activation, saves the previous collector, validates a newly
generated real crypto/xStocks snapshot, then publishes the four entry pages
with immutable assets. Failures restore the collector and affected entry pages.
Provider credentials, Apache configuration and source cadence are preserved.
The precise administrator commands and rollback procedure are in [RUNBOOK.md](RUNBOOK.md).

CoinGecko 429 responses trigger a shared, persistent cooldown across market,
xStocks and global requests. The collector honors `Retry-After`, uses bounded
exponential backoff when the header is absent, and preserves snapshot timestamps.
The private cooldown file contains only numeric transport metadata, is outside
the web root and is ignored by Git. See [HTTP 429 recovery](RUNBOOK.md#coingecko-http-429-recovery)
for deployment waiting and rollback behavior.
