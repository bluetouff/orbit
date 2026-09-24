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
sudo install -o root -g root -m 0755 build_snapshot.py /opt/orbit/build_snapshot.py
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

Without any key, the app already works through CoinGecko's public API.
LunarCrush supplies separate social context (Galaxy Score); FRED supplies macro
observations with publication dates. Neither source changes the market signal
reference or substitutes for missing crypto returns.

---

## 3. First Manual Build

```bash
sudo -u orbit ORBIT_OUT_DIR=/var/lib/orbit /usr/bin/python3 /opt/orbit/build_snapshot.py
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

With the default settings (`ORBIT_TOP=500`, ~30 s timer), one crypto-market
refresh calls CoinGecko for 2 `coins/markets` pages, cached for 60 s by default. CoinGecko `global` is fetched
at most every 120 s, the xStocks category at most every 60 s, LunarCrush at most every 900 s, and FRED at most every
3600 s. That is at most 3.5 CoinGecko calls per minute on average at rest. This is not a
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
- **Crypto TTL**: `ORBIT_MARKETS_REFRESH_SEC` (default 60, bounded 60–180). A failed
  page retains the entire prior crypto universe and its original dates, while
  independent feeds continue. CoinGecko calls are spaced by two seconds.
- **Slow-source TTLs**: `ORBIT_GLOBAL_REFRESH_SEC` (default 120),
  `ORBIT_SOCIAL_REFRESH_SEC` (default 900), `ORBIT_MACRO_REFRESH_SEC`
  (default 3600). Non-due sources are reused from the previous snapshot.
- **xStocks**: `ORBIT_XSTOCKS_REFRESH_SEC` (default 60 seconds) adds one
  bounded category request, up to 250 assets. Check `status.coingecko_xstocks`
  separately from crypto freshness. A failure retains explicitly stale quotes.
  The xStocks map shows the top 50; all collected xStocks are searchable.
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

## Coordinated xStocks and documentation release

This release changes the collector and the frontend. A frontend-only update
does not populate the xStocks catalog. From a clean checkout on the production
host at the full approved SHA, run:

```bash
python3 scripts/deploy_release.py --revision FULL_40_CHARACTER_SHA
sudo python3 scripts/deploy_release.py --revision FULL_40_CHARACTER_SHA --apply
```

The administrator enters sudo personally. The first command is read-only. It
checks the existing `/opt/orbit` collector, service user and hardening, active
timer, exact Git revision, public pages, CSP and market snapshot. A mismatch
blocks activation instead of rewriting the host configuration.

Activation takes the shared deployment lock, checks output paths without
printing credentials, pauses the existing timer and waits for an in-flight
collection to finish. It backs up the collector and validator, then replaces
them atomically. A quiet minute with the timer paused prevents an immediate extra burst after
the preceding production collection. The existing service then collects with
its own provider environment.
The new snapshot must pass the schema validator, contain xStocks and have
current successful crypto and xStocks statuses before the frontend is published.
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
and entry pages, leaving generated data and immutable assets in place. It does
not copy preview snapshots or provider credentials to production.

After activation, verify `/`, `/legal/`, `/docs/` and `/docs/en/` all expose the
approved `orbit-release` SHA; compare the served immutable assets with that
checkout. Verify xStocks quotes and original observation times, independent
source status, mixed favorites, FR/EN navigation, mobile layout, CSP, no cookies
and no third-party browser requests. The guide pages require no JavaScript.

After activation, prove that both feeds actually renew twice (read-only HTTPS,
at most five minutes, no provider API requests):

```bash
python3 scripts/verify_collection.py
```

The check rejects failed/stale collections, regressing timestamps, a frozen
source hidden by new file timestamps, and a top-50 xStocks view where most
quotes are undated or older than ten minutes. That quote-age boundary is the
explicit delayed-display policy, not a real-time guarantee.

The additional category request is TTL-cached independently (60 seconds by
default); existing environment overrides remain effective. Crypto now also has
a 60-second default cache. Timer, macro and social settings are preserved.
Validate both per-minute limits and monthly credits for the actual provider plan.

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
recorded 429. It waits up to three minutes for that retry and never retries an
authentication, service or schema failure. Both market feeds must still pass
validation before the frontend is activated. On failure the previous collector
is restored, and its timer cannot bypass the recorded cooldown. An extended
provider limit remains an operational constraint, not a successful release.
