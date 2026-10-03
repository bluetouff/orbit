# Deploying Orbit2 on l0g.fr (snapshot architecture)

Orbit2 retains the existing `orbit` service names and filesystem paths.
Changing the repository or product name does not deploy anything by itself.

Same pattern as yct/us/euro/energy: a systemd timer regenerates a static JSON
snapshot outside the web root, Apache serves static files, the browser contacts
**no third party**, and **no secret** is exposed client-side. Logos are fetched
once server-side and served locally, so there is no browser request to the
CoinGecko CDN.

```text
  systemd timer (wake about every 30 s)
        |
        v
  build_snapshot.py --(HTTPS)--> CoinGecko markets, 60 s cache
        |                          + TTL-cached global/social/macro/logos
        v
  /var/lib/orbit/orbit.json   (atomic write, outside web root)
  /var/lib/orbit/logos/*.png
        ^   ^
        |   | Alias /logos  (read-only, long cache)
        | Alias /data.json (read-only, 20 s cache + stale)
  Apache 443 --> /var/www/html/orbit/{index.html,app.css,core.js,app.js,icons/}
```

Repository layout: `web/` (static front), `deploy/` (service, timer, vhost),
`build_snapshot.py` and `env.example` at the root.

---

## 0. Requirements

- DNS `A`/`AAAA`: `orbit.l0g.fr` -> zen IP.
- Apache modules: `sudo a2enmod ssl headers rewrite`
- Python 3. The builder only uses the standard library, no pip dependency.

---

## 1. System User And Directory Layout

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin orbit

sudo install -d -o orbit -g orbit -m 755 /var/lib/orbit /var/lib/orbit/logos
sudo install -d -m 755 /opt/orbit
sudo install -o root -g root -m 0755 build_snapshot.py /opt/orbit/
sudo install -o root -g root -m 0644 orbit_health.py /opt/orbit/
sudo install -o root -g root -m 0755 scripts/validate_snapshot.py /opt/orbit/validate_snapshot.py

sudo install -d -m 755 /var/www/html/orbit
sudo install -o root -g root -m 0644 web/index.html /var/www/html/orbit/index.html
sudo install -o root -g root -m 0644 web/app.css    /var/www/html/orbit/app.css
sudo install -o root -g root -m 0644 web/core.js    /var/www/html/orbit/core.js
sudo install -o root -g root -m 0644 web/i18n.js    /var/www/html/orbit/i18n.js
sudo install -o root -g root -m 0644 web/app.js     /var/www/html/orbit/app.js
sudo install -d -m 755 /var/www/html/orbit/icons
sudo install -o root -g root -m 0644 web/icons/*.svg web/icons/LICENSE /var/www/html/orbit/icons/
sudo install -o root -g root -m 0644 web/orbit.svg  /var/www/html/orbit/orbit.svg
sudo install -d -m 755 /var/www/html/orbit/legal
sudo install -o root -g root -m 0644 web/legal/index.html /var/www/html/orbit/legal/index.html
sudo install -d -m 755 /var/www/html/orbit/docs/en
sudo install -o root -g root -m 0644 web/docs/index.html /var/www/html/orbit/docs/index.html
sudo install -o root -g root -m 0644 web/docs/en/index.html /var/www/html/orbit/docs/en/index.html
# Do NOT copy local web/data.json to prod: use the server-generated snapshot.
```

---

## 2. Configuration (Server-Side Keys Only)

```bash
sudo install -d -o orbit -g orbit -m 750 /etc/orbit
sudo cp env.example /etc/orbit/orbit.env
sudo chown orbit:orbit /etc/orbit/orbit.env && sudo chmod 640 /etc/orbit/orbit.env
sudoedit /etc/orbit/orbit.env       # CG_API_TIER/CG_API_KEY, LUNARCRUSH_API_KEY, FRED_API_KEY
```

Choose the provider tier and supported profile before the first collection.
For a Demo key, create the profile before starting the service or timer:

```bash
printf 'demo-250-v1\n' | sudo tee /opt/orbit/collection.profile >/dev/null
sudo chown root:root /opt/orbit/collection.profile
sudo chmod 644 /opt/orbit/collection.profile
```

Unauthenticated CoinGecko availability is provider-dependent. Do not assume
that the legacy one-minute settings fit a Demo budget.
LunarCrush supplies separate social context (Galaxy Score); FRED supplies macro
observations with publication dates. Neither source changes the market signal
reference or substitutes for missing crypto returns.

---

## 3. First Manual Build

```bash
sudo install -o root -g root -m 0644 deploy/orbit-snapshot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start orbit-snapshot.service
ls -lh /var/lib/orbit/orbit.json /var/lib/orbit/logos | head
/usr/bin/python3 /opt/orbit/validate_snapshot.py /var/lib/orbit/orbit.json
```

---

## 4. systemd Timer

```bash
sudo cp deploy/orbit-snapshot.service deploy/orbit-snapshot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now orbit-snapshot.timer
systemctl list-timers orbit-snapshot.timer
journalctl -u orbit-snapshot.service -n 20 --no-pager
```

---

## 5. Apache And Certificate

```bash
sudo cp deploy/orbit.l0g.fr.conf /etc/apache2/sites-available/orbit.l0g.fr.conf
sudo a2ensite orbit.l0g.fr
sudo apache2ctl configtest && sudo systemctl reload apache2
# certificate (webroot):
sudo certbot --apache -d orbit.l0g.fr      # or certonly --webroot -w /var/www/html/orbit
sudo systemctl reload apache2
```

---

## 6. Verify The Privacy Promise

On the deployed site, open the Network tab in devtools: **every** request must
target `orbit.l0g.fr` (HTML, `app.css`, `app.js`, `/data.json`, `/logos/*.png`).
There must be no request to `coingecko.com`, `coin-images.coingecko.com`,
`lunarcrush.com`, `googleapis.com`, or any other third party. The CSP
`connect-src 'self'` enforces this anyway.

---

## 7. Capacity And API Limits

User traffic is decoupled from data providers:

- Browsers never contact CoinGecko, LunarCrush or FRED.
- 50,000 concurrent users read the same static `/data.json` and the same
  self-hosted `/logos/*.png`.
- Provider call volume depends only on the systemd timer, not on traffic.

Without a collection profile, the legacy settings (`ORBIT_TOP=500`, ~30 s timer) apply. Then one crypto-market
refresh calls CoinGecko for 2 `coins/markets` pages, cached for 60 s by default. CoinGecko `global` is fetched
at most every 120 s, LunarCrush at most every 900 s, and FRED at most every
3600 s. That is at most 2.5 CoinGecko calls per minute on average at rest
(108,000 calls per 30 days at that upper bound). The Demo monthly allowance
cannot sustain that upper bound; do not enable a Demo key assuming minute limits
alone are sufficient. This is not a
guarantee against rate limits: check both minute limits and monthly credits on
the actual provider plan. Browser population does not change that number.
Missing logos are downloaded in bounded batches
(`ORBIT_LOGO_FETCH_PER_RUN`, default 60) to avoid a CDN spike at first start.

For 50,000 concurrent connections, the capacity point is therefore the static
serving layer, not provider API limits:

```bash
curl -I https://orbit.l0g.fr/data.json
curl -I https://orbit.l0g.fr/app.js
curl -I https://orbit.l0g.fr/legal/
curl -I https://orbit.l0g.fr/logos/bitcoin.png
```

Check: `Cache-Control` is present, gzip/deflate is active on JSON/JS/CSS, Apache
logs show no 5xx, and network throughput is sufficient. If traffic really
becomes massive, put Cloudflare/Fastly/nginx cache in front of Apache to absorb
`/data.json`, `app.js`, `app.css` and `/logos/*` without changing the builder.

---

## 8. Useful Settings

- **Provider cadence**: `OnUnitActiveSec` in the timer (default 30 s wakeup; per-feed caches determine provider calls). The front rereads the JSON roughly every 30 s, with jitter and a
  pause in hidden tabs
  (30-45 seconds in `app.js`).
- **Production Demo profile**: up to 250 assets / 300 s market cache / 3600 s global cache. The explicit profile overrides the legacy non-secret settings below.
- **Legacy crypto TTL**: `ORBIT_MARKETS_REFRESH_SEC` (default 60, bounded 60–180). A failed
  page retains the entire prior crypto universe and its original dates, while
  independent feeds continue. CoinGecko calls are spaced by two seconds.
- **Publication priority**: new complete crypto pages are published before optional
  feeds and logo downloads. Existing context keeps its original source dates until
  its own refresh completes; an interrupted enrichment stage cannot hide the new
  crypto prices. This adds no provider request and leaves the crypto TTL unchanged.
- **Slow-source TTLs**: `ORBIT_GLOBAL_REFRESH_SEC` (default 120),
  `ORBIT_SOCIAL_REFRESH_SEC` (default 900), `ORBIT_MACRO_REFRESH_SEC`
  (default 3600). Non-due sources are reused from the previous snapshot.
- **Depth**: `ORBIT_TOP` (universe) and `ORBIT_SPARK_TOP` (coins with sparkline)
  in `orbit.env`. The larger it is, the heavier `orbit.json` gets.
- **Logo warmup**: `ORBIT_LOGO_FETCH_PER_RUN` caps new logo downloads per build.
  Logos already present do not trigger a provider call.
- **Watchlist / view**: 50 favorites maximum (`core.js`), 100 coins in the market
  view (`app.js`). Existing selections open the watchlist; new visitors see the
  bilingual home and an unselected real-data preview, then choose their coins.
  Favorites are persisted in the browser through `localStorage`
  (`orbit.favs.v1`): no account, no login, nothing is sent to the server.

## Upgrading an Existing Front

The installation sections above describe a new instance, not an unattended
upgrade. Before changing an existing production installation, inspect its real
vhost, aliases, service paths and timer. Back up the served front and record the
exact deployed revision. Do not change API cadence as part of a UI release.

This front requires `core.js` and `icons/` in addition to `app.js`, `app.css`,
`index.html`, `orbit.svg` and `legal/index.html`. Deploy these as one tested
release, not an `app.js`-only update. Use matching asset versions/cache busting
for activation so cached old scripts cannot run against the new HTML. Never
overwrite production `data.json`, logos or provider configuration with local
preview files. Keep rollback available and verify the served revision, CSP,
watchlist, source ages, asset dialog and legal scrolling before declaring success.

### Guarded Activation

`scripts/deploy_front.py` is for the existing `/var/www/html/orbit` installation.
Run it on the production host from a clean checkout at the exact approved SHA:

```bash
python3 scripts/deploy_front.py --revision FULL_40_CHARACTER_SHA
sudo python3 scripts/deploy_front.py --revision FULL_40_CHARACTER_SHA --apply
```

The first command is read-only. It checks that existing public entry pages match the
local web root, that the expected CSP is present and that the public snapshot is
current. Activation prepares `/releases/<SHA>/` containing only allowlisted
static assets, then checks every asset's HTTPS body and MIME type before swapping
the four entry pages (app, legal, FR guide, EN guide) with atomic file replacements. Each page references one
complete immutable asset version. A public `orbit-release` meta tag identifies
the exact source SHA. Existing `app.js`, `app.css`, logos and data stay untouched.

A new documentation page must return HTTP 404 before its first deployment.
Rollback removes newly created pages and restores existing ones. Earlier
two-page backups remain usable.

Original entry pages and a hash manifest are saved under `/var/backups/orbit/`.
The command prints the exact rollback instruction before activating. A failed
post-activation public check automatically restores the original pages. Manual
rollback refuses to overwrite a subsequently modified or newer release:

```bash
sudo python3 scripts/deploy_front.py --rollback BACKUP_DIRECTORY_NAME
```

No Apache reload, service restart or provider request is made. Changes to the
Python collector in the repository are **not** installed by this front-only
release. Plan a separate collector update after inspecting the current service
and environment on the host. Do not delete immutable release assets while old
tabs or rollback entry pages may still refer to them.

## Security Summary

- No key in the browser, no client-side third-party call, no user IP leak to data
  providers.
- CSP `default-src 'none'`; `script-src 'self'` (external app.js, no inline);
  `connect-src 'self'`. Logos and data are same-origin.
- Unprivileged and strongly sandboxed builder (ProtectSystem=strict,
  MemoryDenyWriteExecute, SystemCallFilter, a single writable path), HTTPS-only,
  logo host allowlist, bounded response size, atomic writes.
- FRED/LunarCrush/CoinGecko keys live in `/etc/orbit/orbit.env` (640), injected
  by systemd, never on disk where the front can access them.

## Coordinated collector and documentation release

This release changes the collector and the frontend. A frontend-only update
does not update the collection process. From a clean checkout on the production
host at the full approved SHA, run:

```bash
python3 scripts/deploy_release.py --revision FULL_40_CHARACTER_SHA
sudo python3 scripts/deploy_release.py --revision FULL_40_CHARACTER_SHA --apply
```

The administrator enters sudo personally. The first command is read-only. It
checks the existing `/opt/orbit` collector, service user and hardening, active
timer, exact Git revision, public pages, CSP and market snapshot. A mismatch
blocks activation instead of rewriting the host configuration.

Activation takes the shared deployment lock and checks output paths without
printing credentials. It saves the collector, validator and any legacy Kraken
worker and units. Activation pauses the crypto timer and waits for an in-flight
collection. It stops and disables `orbit-xstocks.timer`, stops its service,
removes both unit files and `collect_xstocks.py`, reloads systemd, then installs
the crypto-only builder and validator. The previous unit state is recorded before
any change so failures can restore it. Private token caches and logos remain
outside the web root; the builder never reads the token caches.
A quiet minute prevents an immediate extra burst after the preceding production
collection. The existing service collects with its own provider environment.
The new snapshot must pass the schema validator, contain only crypto assets and
have a successful crypto collection within its supported freshness bound before publication (3 minutes for legacy, 7 minutes for Demo). Demo additionally requires at least 90% of prices dated within 10 minutes, including Bitcoin, and at least 20 assets.
The timer configuration remains unchanged. Before resuming it, including after
a rollback to a legacy collector, the script honors a recorded provider cooldown.
It waits at most 30 minutes at this recovery step. A longer or malformed cooldown
leaves the timer paused with an explicit message for the administrator; it never
shortens the provider deadline or silently forces another request.

The command prints one full rollback command **before replacing the collector**:

```bash
sudo python3 scripts/deploy_release.py --rollback COLLECTOR_BACKUP_NAME
```

Backups live under `/var/backups/orbit/`. Rollback checks file hashes and refuses
to overwrite a newer collector or frontend. It restores the previous collector
and entry pages, restores/removes Kraken units to their previous state, and
restores the prior timer enablement, leaving generated data and immutable assets in place. It does
not copy preview snapshots or provider credentials to production.

After activation, verify `/`, `/legal/`, `/docs/` and `/docs/en/` all expose the
approved `orbit-release` SHA; compare the served immutable assets with that
checkout. Verify crypto quotes and original observation times, source status,
favorites, FR/EN navigation, mobile layout, CSP, no cookies
and no third-party browser requests. The guide pages require no JavaScript.

After activation, the public check requires two crypto collection renewals
(up to fifteen minutes, no provider API calls):

```bash
python3 scripts/verify_collection.py
```

It rejects failed collections, regressing source dates, collections beyond their supported freshness bound and any remaining token or xStocks source. Demo also checks original quote dates and coverage. A new file date alone
cannot pass. Check the retired units are inactive and disabled on the host:

```bash
systemctl is-active orbit-xstocks.service orbit-xstocks.timer
systemctl is-enabled orbit-xstocks.timer
```

`inactive` / `not-found` are expected, with a nonzero command exit status.
The crypto timer, provider environment, macro and social settings are preserved.
Validate both minute limits and monthly credits for the actual CoinGecko plan.

## CoinGecko HTTP 429 recovery

A 429 is provider backpressure, not evidence of bad authentication.
[CoinGecko documents](https://docs.coingecko.com/docs/errors-and-rate-limits)
that unsuccessful requests also count toward minute limits, so immediate
retries can extend the problem. Do not loop over manual service starts.

The collector saves only `retry_at` (a UTC epoch second) and `failures`
(a bounded integer) in `/var/lib/orbit/.coingecko-rate-limit.json`, mode 0600.
The file is outside the web root and ignored by Git; it contains no URL,
provider response, key or environment value. All CoinGecko endpoints share
this cooldown, which survives timer invocations.

`Retry-After` accepts seconds or an HTTP date, following
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after).
Without a usable header, waits progress through 120, 240, 480, 960 and
1800 seconds. A supplied longer delay is preserved. Success on one market page
does not reset the counter; a completed recovered collection does. During a
market cooldown, previous quote and successful-collection timestamps remain
untouched. The published snapshot reports a failed attempt and its retry date;
non-CoinGecko sources can still update. A new snapshot timestamp is not proof
that a market source succeeded.
The journal contains a bounded status message rather than request details.

Release activation allows at most one delayed retry, exclusively after a
recorded 429. It waits up to three minutes (six for Demo, covering its cache) for that retry and never retries an
authentication, service or schema failure. Crypto collection and dated quote coverage must still pass
validation before the frontend is activated. On failure the previous collector
is restored, and its timer cannot bypass the recorded cooldown. An extended
provider limit remains an operational constraint, not a successful release.

## CoinGecko access refusal (HTTP 401/403)

A recent `snapshot` timestamp does not prove that prices were refreshed. Inspect
`status.coingecko_markets.ok`, `http_status` and `last_success_at`. A 403 is an
access refusal, distinct from a 429 rate limit. The UI shows the HTTP code and
suppresses stale prices, returns and performance colors; original observations
remain unchanged in the snapshot.

After a 401 or 403, only the failed feed pauses for at least 15 minutes, honoring
a longer `Retry-After`. Other feeds continue. Successful market collection keeps
its configured cadence. Do not repeatedly restart the service or bypass the
provider's access control. Test the configured authentication without printing
keys, request headers, environment contents or upstream response bodies.

A working Demo key does not make a one-minute 500-asset schedule sustainable:
check monthly credits as well as per-minute limits before activating it. The
administrator must choose a supported cadence or plan; credentials must stay in
the existing protected environment file.

## Free Demo profile and outage recovery

The confirmed incident was `CG_API_TIER=none` with an existing working Demo key:
unauthenticated market calls returned HTTP 403; the authenticated diagnostic
returned HTTP 200. The release can activate that key without changing its value:

```bash
cd /home/bluetouff/orbit
git pull --ff-only
sudo python3 scripts/deploy_release.py --revision FULL_40_CHARACTER_SHA --demo-250 --apply
python3 scripts/verify_collection.py
```

Run the activation in the existing Zen session. The administrator enters sudo
personally. Use `&&` between these commands to stop on any failure.
`--demo-250` allows an unavailable market feed during the initial recovery
preflight only: the generated public file must still be recent, served entry
pages must match disk, and all service, path, CSP and revision checks remain.
Postflight is strict: the market collection must succeed after activation starts,
with the Demo policy and sufficient recent original price timestamps. A recent
file alone cannot pass. A failure restores the collector, profile and frontend
before the timer resumes.

The new root-owned `/opt/orbit/collection.profile` contains only `demo-250-v1`.
It selects Demo authentication, at most 250 assets, a 300-second market interval
and a 3600-second global interval. `/etc/orbit/orbit.env` is neither rewritten
nor copied into the backup; the API key remains there. Other provider settings
are preserved. Later releases preserve the profile even without `--demo-250`.
Use the printed activation rollback to remove it and restore prior behavior;
older rollback manifests that do not track the profile are refused while it exists.

The schedule uses approximately 9,672 calls in 31 days (8,928 market + 744 global),
before manual/additional calls. [CoinGecko lists 10,000 monthly Demo calls](https://www.coingecko.com/en/api/pricing).
All Demo requests reserve one entry before the network call in
`/var/lib/orbit/.coingecko-budget.json`, protected by a process lock. The private
ledger contains only the UTC month and request count. Failed requests count
conservatively. At 10,000, CoinGecko requests stop until the next UTC month;
the interface reports the budget and data unavailability.

The ledger starts when enabled and cannot know previous consumption or usage
by other applications using this key. Check the provider dashboard for the
account total. Never delete the ledger to retry: corrupt, future-dated or unsafe
state blocks requests. Keep it when deploying or rolling back. The guard limits
Orbit requests; it does not guarantee upstream availability or remaining credits.

Demo collection becomes stale after 420 seconds (300-second cadence plus
120 seconds of scheduling tolerance). Individual prices require provider dates
within 600 seconds. Global context expires after 3720 seconds. Arbitrary `ttl`
values in a snapshot cannot extend these fixed policy limits. Failed feeds
remain unavailable immediately, regardless of age. Old quotes keep their dates
and are never used for colors, returns, filters or signals.

## Runtime health, coverage and budget alerts

Every market refresh checks distinct normalized assets before either public
write. The minimum is 20 (or a smaller explicitly configured legacy universe),
and at least 90% of the previous universe, bounded by the configured target.
Demo also requires at least 90% recent quotes and current Bitcoin. A failed
check retains the previous full universe with its original dates and marks the
market feed unavailable. Never clear the previous snapshot to bypass this guard;
investigate the provider response or an intentional universe change.

The collector writes `/var/lib/orbit/.orbit-health.json` with mode 0600. It
contains operational counts, times and fixed issue codes. `ORBIT_HEALTH`
journal entries appear on state/issue changes and recovery. This provides local
alerts; no email, webhook or third-party notification is configured.

```bash
sudo -u orbit python3 /opt/orbit/orbit_health.py
journalctl -u orbit-snapshot.service --grep=ORBIT_HEALTH --since=today --no-pager
```

The offline command recomputes freshness at invocation time and exits 0 for
healthy, 1 for warning, 2 for critical. An existing monitor can poll it without
provider requests. A stored report alone does not prove that a stopped collector
is healthy; use this command or public freshness checks.

Budget projection adds scheduled requests remaining in the current UTC month
to recorded reservations. Above 9,500 projected requests it warns about low
margin; at 10,000 projected requests it warns of exhaustion risk. The hard cap
remains 10,000. Missing, corrupt or future-dated ledgers are unknown, never zero.
The projection excludes manual future requests and cannot know requests made
elsewhere or before ledger creation. The five-minute cadence is unchanged.

`orbit_health.py` is backed up and restored with the collector. Private ledger
and health reports are not copied into public release assets.
