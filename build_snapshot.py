#!/usr/bin/env python3
"""
Orbit snapshot builder — l0g.fr style.

Run by a hardened systemd timer. Fetches CoinGecko (markets + global), and
optionally LunarCrush (social) and FRED (macro), server-side, then writes a
single static `orbit.json` plus locally-cached coin logos. The browser only
ever reads same-origin static files: no third-party calls, no API key client-side.

Stdlib only (urllib/json/ssl) — no pip. Hardened: https-only, host allowlist
for logos, per-response size cap, timeouts, atomic writes.
"""
import json, os, re, ssl, sys, time, tempfile, urllib.request, urllib.parse, urllib.error

# ---- config (env) ----
TOP        = int(os.environ.get("ORBIT_TOP", "500"))          # universe size
SPARK_TOP  = int(os.environ.get("ORBIT_SPARK_TOP", "250"))    # coins w/ sparkline
SPARK_PTS  = int(os.environ.get("ORBIT_SPARK_POINTS", "32"))  # downsample target
OUT_DIR    = os.environ.get("ORBIT_OUT_DIR", "/var/lib/orbit")
LOGO_DIR   = os.environ.get("ORBIT_LOGO_DIR", os.path.join(OUT_DIR, "logos"))
LOGO_MAX   = int(os.environ.get("ORBIT_LOGO_MAX", str(TOP)))  # cap logos to download
TIMEOUT    = float(os.environ.get("ORBIT_TIMEOUT", "20"))
MAX_BYTES  = int(os.environ.get("ORBIT_MAX_BYTES", str(40 * 1024 * 1024)))

CG_TIER = os.environ.get("CG_API_TIER", "none").lower()
CG_KEY  = os.environ.get("CG_API_KEY", "").strip()
CG_BASE = "https://pro-api.coingecko.com/api/v3" if CG_TIER == "pro" else "https://api.coingecko.com/api/v3"
LUNAR_KEY = os.environ.get("LUNARCRUSH_API_KEY", "").strip()
FRED_KEY  = os.environ.get("FRED_API_KEY", "").strip()
FRED_SERIES = {"us10y": "DGS10", "usd": "DTWEXBGS"}

LOGO_HOSTS = {"assets.coingecko.com", "coin-images.coingecko.com"}
# coin ids become logo filenames -> validate to block path traversal on write
COIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$", re.I)
KEEP = ("id", "symbol", "name", "current_price", "market_cap", "total_volume",
        "market_cap_rank", "ath", "circulating_supply",
        "price_change_percentage_1h_in_currency", "price_change_percentage_24h_in_currency",
        "price_change_percentage_7d_in_currency", "price_change_percentage_30d_in_currency")

_CTX = ssl.create_default_context()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable redirect following: a 3xx raises instead of being chased.
    Blocks redirect-based SSRF (parity with the proxy's follow_redirects=False)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_CTX))


def fetch(url, headers=None, binary=False):
    """HTTPS-only GET with timeout, size cap, and no redirect following."""
    if not url.lower().startswith("https://"):
        raise ValueError("refusing non-https url")
    req = urllib.request.Request(url, headers={"User-Agent": "orbit-builder/1.0",
                                               "Accept": "*/*" if binary else "application/json",
                                               **(headers or {})})
    with _OPENER.open(req, timeout=TIMEOUT) as r:
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("response too large")
        return data if binary else json.loads(data.decode("utf-8"))


def cg(path, params):
    if CG_KEY and CG_TIER == "demo":
        params = {**params, "x_cg_demo_api_key": CG_KEY}
    headers = {"x-cg-pro-api-key": CG_KEY} if (CG_KEY and CG_TIER == "pro") else None
    return fetch(f"{CG_BASE}/{path}?{urllib.parse.urlencode(params)}", headers=headers)


def downsample(arr, n):
    if not arr or len(arr) <= n:
        return [round(x, 8) for x in (arr or [])]
    step = (len(arr) - 1) / (n - 1)
    return [round(arr[int(round(i * step))], 8) for i in range(n)]


def get_markets():
    coins, page, per = [], 1, 250
    while len(coins) < TOP:
        batch = cg("coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc", "per_page": per, "page": page,
            "price_change_percentage": "1h,24h,7d,30d", "sparkline": "true"})
        if not batch:
            break
        coins.extend(batch)
        if len(batch) < per:
            break
        page += 1
    return coins[:TOP]


def get_social():
    if not LUNAR_KEY:
        return {}
    try:
        d = fetch(f"https://lunarcrush.com/api4/public/coins/list/v1",
                  headers={"Authorization": f"Bearer {LUNAR_KEY}"})
    except Exception as e:
        sys.stderr.write(f"social skip: {type(e).__name__}\n")
        return {}
    out = {}
    for it in d.get("data", []):
        sym = (it.get("symbol") or "").upper()
        if sym:
            out[sym] = {"galaxy_score": it.get("galaxy_score"), "sentiment": it.get("sentiment"),
                        "social_dominance": it.get("social_dominance")}
    return out


def get_macro():
    if not FRED_KEY:
        return None
    out = {}
    for key, sid in FRED_SERIES.items():
        try:
            d = fetch("https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(
                {"series_id": sid, "api_key": FRED_KEY, "file_type": "json", "sort_order": "desc", "limit": 12}))
            vals = [(o["date"], float(o["value"])) for o in d.get("observations", [])
                    if o.get("value") not in (None, ".", "")]
            if vals:
                cur, prev = vals[0], (vals[1] if len(vals) > 1 else None)
                out[key] = {"value": round(cur[1], 3), "date": cur[0],
                            "change": round(cur[1] - prev[1], 3) if prev else None}
        except Exception as e:
            sys.stderr.write(f"macro {sid} skip: {type(e).__name__}\n")
    if out:
        out["asof"] = out.get("us10y", {}).get("date") or out.get("usd", {}).get("date")
    return out or None


def cache_logo(coin):
    """Download the coin logo once into LOGO_DIR/<id>.png (host-allowlisted)."""
    url = coin.get("image") or ""
    cid = coin.get("id") or ""
    if not url or not cid or not COIN_ID_RE.match(cid):
        return
    dest = os.path.join(LOGO_DIR, cid + ".png")
    if os.path.exists(dest):
        return
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        if host not in LOGO_HOSTS:
            return
        body = fetch(url.split("?")[0], binary=True)
        if len(body) > 2_000_000:
            return
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dest)
        os.chmod(dest, 0o644)
    except Exception as e:
        sys.stderr.write(f"logo {cid} skip: {type(e).__name__}\n")


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(LOGO_DIR, exist_ok=True)
    markets = get_markets()
    if not markets:
        sys.stderr.write("no market data; aborting (keeping previous snapshot)\n")
        sys.exit(1)
    social = get_social()
    glob = None
    try:
        glob = cg("global", {}).get("data")
    except Exception as e:
        sys.stderr.write(f"global skip: {type(e).__name__}\n")
    macro = get_macro()

    coins = []
    for i, c in enumerate(markets):
        o = {k: c.get(k) for k in KEEP}
        s = social.get((c.get("symbol") or "").upper())
        if s:
            o.update({k: v for k, v in s.items() if v is not None})
        if i < SPARK_TOP:
            sp = (c.get("sparkline_in_7d") or {}).get("price")
            if sp:
                o["spark"] = downsample(sp, SPARK_PTS)
        coins.append(o)

    for c in markets[:LOGO_MAX]:
        cache_logo(c)

    snapshot = {
        "snapshot": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(coins),
        "global": glob,
        "macro": macro,
        "social_enabled": bool(LUNAR_KEY),
        "coins": coins,
    }
    tmp = os.path.join(OUT_DIR, "orbit.json.tmp")
    with open(tmp, "w") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(OUT_DIR, "orbit.json"))
    os.chmod(os.path.join(OUT_DIR, "orbit.json"), 0o644)
    sys.stderr.write(f"snapshot ok: {len(coins)} coins, social={bool(social)}, macro={bool(macro)}\n")


if __name__ == "__main__":
    build()
