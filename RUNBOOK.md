# Deploying Orbit2 on l0g.fr (snapshot architecture)

Orbit2 retains the existing `orbit` service names and filesystem paths.
Changing the repository or product name does not deploy anything by itself.

Same pattern as yct/us/euro/energy: a systemd timer regenerates a static JSON
snapshot outside the web root, Apache serves static files, the browser contacts
**no third party**, and **no secret** is exposed client-side. Logos are fetched
once server-side and served locally, so there is no browser request to the
CoinGecko CDN.

```text
  systemd timer (crypto markets about every 30 s)
        |
        v
  build_snapshot.py --(HTTPS)--> CoinGecko markets every run
        |                          + TTL-cached global/social/macro/logos
        v
  /var/lib/orbit/orbit.json   (atomic write, outside web root)
  /var/lib/orbit/logos/*.png
        ^   ^
        |   | Alias /logos  (read-only, long cache)
        | Alias /data.json (read-only, 20 s cache + stale)
  Apache 443 --> /var/www/html/orbit/{index.html,app.css,app.js}
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
sudo install -o root -g root -m 0644 web/app.js     /var/www/html/orbit/app.js
sudo install -o root -g root -m 0644 web/orbit.svg  /var/www/html/orbit/orbit.svg
sudo install -d -m 755 /var/www/html/orbit/legal
sudo install -o root -g root -m 0644 web/legal/index.html /var/www/html/orbit/legal/index.html
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
LunarCrush enables the real social axis (Galaxy Score); FRED enables the real
macro strip.

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
build calls CoinGecko for 2 `coins/markets` pages. CoinGecko `global` is fetched
at most every 120 s, LunarCrush at most every 900 s, and FRED at most every
3600 s. That is roughly 4-5 CoinGecko calls per minute at rest, well below the
documented public/demo order of magnitude, and the browser population does not
change that number. Missing logos are downloaded in bounded batches
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

- **Provider cadence**: `OnUnitActiveSec` in the timer (default 30 s for crypto
  markets). The front rereads the JSON roughly every 30 s, with jitter and a
  pause in hidden tabs
  (`REFRESH_MS` / `REFRESH_JITTER_MS` in `app.js`).
- **Slow-source TTLs**: `ORBIT_GLOBAL_REFRESH_SEC` (default 120),
  `ORBIT_SOCIAL_REFRESH_SEC` (default 900), `ORBIT_MACRO_REFRESH_SEC`
  (default 3600). Non-due sources are reused from the previous snapshot.
- **Depth**: `ORBIT_TOP` (universe) and `ORBIT_SPARK_TOP` (coins with sparkline)
  in `orbit.env`. The larger it is, the heavier `orbit.json` gets.
- **Logo warmup**: `ORBIT_LOGO_FETCH_PER_RUN` caps new logo downloads per build.
  Logos already present do not trigger a provider call.
- **Watchlist / view** in `app.js`: `MAX_FAV` (default 50, favorite cap),
  `TOP_N` (default 100, market view size). The default screen is the watchlist.
  Favorites are persisted in the browser through `localStorage`
  (`orbit.favs.v1`): no account, no login, nothing is sent to the server.

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
