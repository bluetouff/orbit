# Orbit2

Orbit2 is the next iteration of Orbit, a l0g Lab crypto watchlist and heatmap.
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
  orbit.svg                  local favicon + brand mark
  app.css                    styles
  app.js                     logic (reads ./data.json + ./logos/, 30 s refresh + jitter)
  data.json                  local snapshot link (generated, never committed)
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
python3 -m http.server 8765
```

Then open:

```text
http://127.0.0.1:8765/web/
```

Opening `index.html` directly is expected to fail with the strict CSP and
external asset files.

If no snapshot is available, the app displays an unavailable state and retries.
It does not substitute invented prices. Generated snapshots and logos are
ignored by Git.

## Compatibility and licensing

The existing `orbit` service names, paths, public domain and browser watchlist
key are preserved for deployment compatibility. Renaming the product does not
require resetting favorites or changing the production service.

The MIT license covers the repository's software and documentation. Market
data, provider services and third-party cryptocurrency logos remain subject
to their owners' terms; they are not distributed or relicensed by this repository.
See [SECURITY.md](SECURITY.md) for private reporting and contribution checks.
