# Orbit - l0g.fr snapshot architecture

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
  legal/index.html           legal, privacy and GDPR notice for Orbit / l0g Lab
  orbit.svg                  local favicon + brand mark
  app.css                    styles
  app.js                     logic (reads ./data.json + ./logos/, 30 s refresh + jitter)
  data.json                  DEMO SAMPLE (do not deploy)
deploy/
  orbit-snapshot.service     hardened systemd oneshot unit
  orbit-snapshot.timer       trigger (crypto markets about every 30 s + at boot)
  orbit.l0g.fr.conf          Apache vhost (strict CSP, data.json + logos aliases)
scripts/
  validate_snapshot.py       validates the public orbit.json contract
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
fed by providers: CoinGecko markets, CoinGecko global, LunarCrush, FRED and logo
warmup.

Step-by-step deployment: see **RUNBOOK.md**.

## Local Preview

`index.html` loads `app.css`, `app.js` and `data.json` through relative paths, so
the files must be served together. Run a small static server from the repository
root:

```bash
python3 -m http.server 8765
```

Then open:

```text
http://127.0.0.1:8765/web/
```

Opening `index.html` directly is expected to fail with the strict CSP and
external asset files.
