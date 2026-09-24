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
import calendar, datetime, json, math, os, re, ssl, sys, time, urllib.request, urllib.parse, urllib.error
from collections import Counter
from itertools import zip_longest
from email.utils import parsedate_to_datetime
import tempfile


def env_int(name, default, lo, hi):
    try:
        v = int(os.environ.get(name, str(default)))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def env_float(name, default, lo, hi):
    try:
        v = float(os.environ.get(name, str(default)))
    except ValueError:
        v = default
    return max(lo, min(hi, v))

# ---- config (env) ----
TOP        = env_int("ORBIT_TOP", 500, 1, 1000)               # universe size
SPARK_TOP  = env_int("ORBIT_SPARK_TOP", 250, 0, TOP)          # coins w/ sparkline
SPARK_PTS  = env_int("ORBIT_SPARK_POINTS", 32, 2, 240)        # downsample target
OUT_DIR    = os.environ.get("ORBIT_OUT_DIR", "/var/lib/orbit")
LOGO_DIR   = os.environ.get("ORBIT_LOGO_DIR", os.path.join(OUT_DIR, "logos"))
LOGO_MAX   = env_int("ORBIT_LOGO_MAX", TOP, 0, TOP)           # cap logo universe
LOGO_FETCH_PER_RUN = env_int("ORBIT_LOGO_FETCH_PER_RUN", 60, 0, 250)
GLOBAL_REFRESH_SEC = env_int("ORBIT_GLOBAL_REFRESH_SEC", 120, 30, 3600)
SOCIAL_REFRESH_SEC = env_int("ORBIT_SOCIAL_REFRESH_SEC", 900, 60, 86400)
MACRO_REFRESH_SEC  = env_int("ORBIT_MACRO_REFRESH_SEC", 3600, 300, 86400)
XSTOCKS_REFRESH_SEC = env_int("ORBIT_XSTOCKS_REFRESH_SEC", 120, 60, 180)
XSTOCKS_MAX = 250  # One bounded category request, independent of visitor traffic.
TIMEOUT    = env_float("ORBIT_TIMEOUT", 20, 2, 60)
MAX_BYTES  = env_int("ORBIT_MAX_BYTES", 40 * 1024 * 1024, 1024 * 1024, 80 * 1024 * 1024)

CG_TIER = os.environ.get("CG_API_TIER", "none").lower()
CG_KEY  = os.environ.get("CG_API_KEY", "").strip()
CG_BASE = "https://pro-api.coingecko.com/api/v3" if CG_TIER == "pro" else "https://api.coingecko.com/api/v3"
LUNAR_KEY = os.environ.get("LUNARCRUSH_API_KEY", "").strip()
FRED_KEY  = os.environ.get("FRED_API_KEY", "").strip()
FRED_SERIES = {"us10y": "DGS10", "usd": "DTWEXBGS"}

LOGO_HOSTS = {"assets.coingecko.com", "coin-images.coingecko.com"}
# coin ids become logo filenames -> validate to block path traversal on write
COIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$", re.I)
SYMBOL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,19}$", re.I)
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


class CoinGeckoCooldown(Exception):
    """Expected provider backpressure, containing no request or credential."""
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__('CoinGecko requests deferred')


def rate_limit_path():
    return os.path.join(OUT_DIR, '.coingecko-rate-limit.json')


def read_rate_limit():
    try:
        fd = os.open(rate_limit_path(), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {'retry_at': 0, 'failures': 0}
    with os.fdopen(fd, encoding='utf-8') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('Invalid CoinGecko cooldown state')
    state = json.loads(raw)
    if not isinstance(state, dict) or type(state.get('retry_at')) is not int or not 0 <= state['retry_at'] <= 253402300799 or type(state.get('failures')) is not int or not 0 <= state['failures'] <= 5:
        raise ValueError('Invalid CoinGecko cooldown state')
    return state


def retry_delay(header, failures, now):
    # Conservative fallback: 120s, 240s, 480s, 960s, then 1800s.
    delay = min(1800, 120 * 2 ** (min(5, max(1, failures)) - 1))
    if isinstance(header, str) and len(header) <= 128:
        value = header.strip()
        try:
            if re.fullmatch(r'[0-9]+', value):
                supplied = int(value)
            else:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    return delay
                supplied = math.ceil(parsed.timestamp() - now)
            delay = max(delay, supplied)
        except (ValueError, TypeError, OverflowError):
            pass
    # Values outside datetime's range remain effectively blocked, never overflow.
    return min(delay, max(0, 253402300799 - math.ceil(now)))


def record_rate_limit(header, previous):
    now = time.time()
    failures = min(5, previous['failures'] + 1)
    retry_at = math.ceil(now) + retry_delay(header, failures, now)
    state = {'retry_at': retry_at, 'failures': failures}
    fd, temporary = tempfile.mkstemp(prefix='.coingecko-', dir=OUT_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, rate_limit_path())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return retry_at


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_ts(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0


def load_previous():
    path = os.path.join(OUT_DIR, "orbit.json")
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def status_due(prev, key, ttl):
    st = ((prev.get("status") or {}).get(key) or {})
    fetched = parse_ts(st.get("fetched_at"))
    return not fetched or fetched > time.time() or (time.time() - fetched) >= ttl


def mark_reused(status, ttl):
    status = dict(status or {})
    fetched = parse_ts(status.get("fetched_at"))
    status["reused"] = True
    status["ttl"] = ttl
    if fetched:
        status["age_seconds"] = max(0, int(time.time() - fetched))
    return status


def previous_social(prev):
    out = {}
    counts = Counter((c.get("symbol") or "").upper() for c in prev.get("coins") or [])
    for c in prev.get("coins") or []:
        sym = (c.get("symbol") or "").upper()
        if sym and counts[sym] == 1 and c.get("galaxy_score") is not None:
            out[sym] = {"galaxy_score": c.get("galaxy_score"), "sentiment": c.get("sentiment"),
                        "social_dominance": c.get("social_dominance")}
    return out


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
    state = read_rate_limit()
    if state['retry_at'] > time.time():
        raise CoinGeckoCooldown(state['retry_at'])
    headers = {f"x-cg-{CG_TIER}-api-key": CG_KEY} if CG_KEY and CG_TIER in ("demo", "pro") else None
    try:
        return fetch(f"{CG_BASE}/{path}?{urllib.parse.urlencode(params)}", headers=headers)
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise
        header = error.headers.get('Retry-After') if error.headers else None
        error.close()
        raise CoinGeckoCooldown(record_rate_limit(header, state)) from None


def downsample(arr, n):
    if not arr or len(arr) <= n:
        return [round(x, 8) for x in (arr or [])]
    step = (len(arr) - 1) / (n - 1)
    return [round(arr[int(round(i * step))], 8) for i in range(n)]


def finite_num(v, *, lo=None, hi=None):
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n):
        return None
    if lo is not None and n < lo:
        return None
    if hi is not None and n > hi:
        return None
    return n


def bounded_text(v, max_len):
    s = str(v or "").strip()
    return s[:max_len] if s else None


def normalize_social(s):
    out = {}
    gs = finite_num(s.get("galaxy_score"), lo=0, hi=100)
    sentiment = finite_num(s.get("sentiment"), lo=-100, hi=100)
    dominance = finite_num(s.get("social_dominance"), lo=0, hi=100)
    if gs is not None:
        out["galaxy_score"] = round(gs, 2)
    if sentiment is not None:
        out["sentiment"] = round(sentiment, 2)
    if dominance is not None:
        out["social_dominance"] = round(dominance, 4)
    if out:
        out["social_source"] = "lunarcrush_symbol"
    return out


def normalize_coin(c, social_by_symbol, include_spark):
    if not isinstance(c, dict):
        return None
    cid = bounded_text(c.get("id"), 80)
    sym = bounded_text(c.get("symbol"), 20)
    name = bounded_text(c.get("name"), 96)
    if not cid or not sym or not name or cid != c.get("id") or sym != c.get("symbol") or not COIN_ID_RE.fullmatch(cid) or not SYMBOL_RE.fullmatch(sym):
        return None
    kind = "xstock" if c.get("asset_type") == "xstock" else "crypto"
    o = {"id": cid, "symbol": sym.lower(), "name": re.sub(r"[\x00-\x1f\x7f]", "", name), "asset_type": kind}
    if not o["name"]:
        return None
    observed = c.get("last_updated")
    if isinstance(observed, str) and len(observed) <= 40:
        try:
            stamp = datetime.datetime.fromisoformat(observed.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                o["last_updated"] = stamp.isoformat()
        except ValueError:
            pass
    if observed is not None and "last_updated" not in o:
        return None  # Never turn a malformed observation into an undated quote.
    required = ("current_price", "market_cap", "total_volume")
    for k in required:
        n = finite_num(c.get(k), lo=0)
        if n is None:
            if kind != "xstock" or k == "current_price":
                return None
        o[k] = n
    for k in ("ath", "circulating_supply"):
        n = finite_num(c.get(k), lo=0)
        if n is not None:
            o[k] = n
    rank = finite_num(c.get("market_cap_rank"), lo=1)
    if rank is not None:
        o["market_cap_rank"] = int(rank)
    for k in ("price_change_percentage_1h_in_currency", "price_change_percentage_24h_in_currency",
              "price_change_percentage_7d_in_currency", "price_change_percentage_30d_in_currency"):
        n = finite_num(c.get(k), lo=-100, hi=100000)
        o[k] = round(n, 6) if n is not None else None
    s = social_by_symbol.get(sym.upper()) if kind == "crypto" else None
    if s:
        o.update(normalize_social(s))
    if include_spark:
        source = c.get("sparkline_in_7d")
        sp = source.get("price") if isinstance(source, dict) else None
        sp = sp[:10000] if isinstance(sp, list) else []
        vals = [x for x in (finite_num(p, lo=0) for p in (sp or [])) if x is not None]
        if len(vals) >= 2:
            o["spark"] = downsample(vals, SPARK_PTS)
    return o


def get_markets():
    coins, page, per = [], 1, 250
    while len(coins) < TOP:
        batch = cg("coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc", "per_page": per, "page": page,
            "price_change_percentage": "1h,24h,7d,30d", "sparkline": "true"})
        if not isinstance(batch, list) or len(batch) > per:
            raise ValueError("invalid market response")
        if not batch:
            break
        coins.extend(batch)
        if len(batch) < per:
            break
        page += 1
    return coins[:TOP]


def get_xstocks(previous):
    """A separate, bounded feed. Reuse real observations without redating them."""
    old_status = (previous.get("status") or {}).get("coingecko_xstocks") or {}
    old_coins = [c for c in previous.get("coins", []) if isinstance(c, dict) and c.get("asset_type") == "xstock"][:XSTOCKS_MAX]
    if not status_due(previous, "coingecko_xstocks", XSTOCKS_REFRESH_SEC):
        return old_coins, [], mark_reused(old_status, XSTOCKS_REFRESH_SEC)
    try:
        rows = cg("coins/markets", {"vs_currency": "usd", "category": "xstocks-ecosystem",
            "order": "market_cap_desc", "per_page": XSTOCKS_MAX, "page": 1,
            "price_change_percentage": "1h,24h,7d,30d", "sparkline": "true"})
        if not isinstance(rows, list) or not rows or len(rows) > XSTOCKS_MAX:
            raise ValueError("invalid xStocks response")
        coins, seen = [], set()
        for row in rows:
            coin = normalize_coin({**row, "asset_type": "xstock"}, {}, True) if isinstance(row, dict) else None
            if coin and coin["id"] not in seen:
                coins.append(coin)
                seen.add(coin["id"])
        if not coins:
            raise ValueError("no valid xStocks")
        stamp = utc_now()
        return coins, [r for r in rows if isinstance(r, dict) and r.get("id") in seen], {
            "ok": True, "fetched_at": stamp, "last_success_at": stamp, "ttl": XSTOCKS_REFRESH_SEC,
            "valid": len(coins), "invalid": len(rows) - len(coins), "capped": len(rows) == XSTOCKS_MAX}
    except Exception as error:
        # Class only: never publish URLs, credentials or upstream response bodies.
        return old_coins, [], {"ok": False, "error": type(error).__name__, "fetched_at": utc_now(),
            "last_success_at": old_status.get("last_success_at") or (old_status.get("fetched_at") if old_status.get("ok") else None),
            "reused": bool(old_coins), "ttl": XSTOCKS_REFRESH_SEC}


def get_social():
    if not LUNAR_KEY:
        return {}, {"enabled": False, "ok": False, "count": 0}
    try:
        d = fetch(f"https://lunarcrush.com/api4/public/coins/list/v1",
                  headers={"Authorization": f"Bearer {LUNAR_KEY}"})
    except Exception as e:
        sys.stderr.write(f"social skip: {type(e).__name__}\n")
        return {}, {"enabled": True, "ok": False, "error": type(e).__name__, "count": 0, "fetched_at": utc_now()}
    out = {}
    rows = d.get("data", [])
    counts = Counter((it.get("symbol") or "").upper() for it in rows)
    for it in rows:
        sym = (it.get("symbol") or "").upper()
        if sym and counts[sym] == 1:
            out[sym] = {"galaxy_score": it.get("galaxy_score"), "sentiment": it.get("sentiment"),
                        "social_dominance": it.get("social_dominance")}
    return out, {"enabled": True, "ok": True, "count": len(out), "match": "symbol", "fetched_at": utc_now()}


def get_macro():
    if not FRED_KEY:
        return None, {"enabled": False, "ok": False, "series": 0}
    out = {}
    errors = []
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
            errors.append({"series": sid, "error": type(e).__name__})
    if out:
        out["asof"] = out.get("us10y", {}).get("date") or out.get("usd", {}).get("date")
    series_count = len([k for k in FRED_SERIES if k in out])
    return out or None, {"enabled": True, "ok": bool(out), "series": series_count, "errors": errors, "fetched_at": utc_now()}


def cache_logo(coin):
    """Download the coin logo once into LOGO_DIR/<id>.png (host-allowlisted)."""
    url = coin.get("image") or ""
    cid = coin.get("id") or ""
    if not isinstance(url, str) or not isinstance(cid, str) or not url or not COIN_ID_RE.fullmatch(cid):
        return False
    dest = os.path.join(LOGO_DIR, cid + ".png")
    if os.path.exists(dest):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in LOGO_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        body = fetch(url.split("?")[0], binary=True)
        if len(body) > 2_000_000:
            return False
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, dest)
        os.chmod(dest, 0o644)
        return True
    except Exception as e:
        sys.stderr.write(f"logo {cid} skip: {type(e).__name__}\n")
        return False


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(LOGO_DIR, exist_ok=True)
    previous = load_previous()
    markets = get_markets()
    markets_fetched_at = utc_now()
    if not markets:
        sys.stderr.write("no market data; aborting (keeping previous snapshot)\n")
        sys.exit(1)

    prev_status = previous.get("status") or {}
    xstocks, xstock_logos, xstocks_status = get_xstocks(previous)
    xstock_ids = {c["id"] for c in xstocks}
    # Category membership is authoritative. Exclude recognizable xStocks from
    # the crypto feed even if category discovery is temporarily unavailable.
    markets = [{**c, "asset_type": "crypto"} for c in markets if isinstance(c, dict)
               and c.get("id") not in xstock_ids
               and not re.search(r"xstocks?$", str(c.get("id", "")), re.I)
               and not re.search(r"\bxstocks?\b", str(c.get("name", "")), re.I)]

    if status_due(previous, "lunarcrush", SOCIAL_REFRESH_SEC):
        social, social_status = get_social()
    else:
        social = previous_social(previous)
        social_status = mark_reused(prev_status.get("lunarcrush"), SOCIAL_REFRESH_SEC)

    glob = None
    if status_due(previous, "coingecko_global", GLOBAL_REFRESH_SEC):
        try:
            glob = cg("global", {}).get("data")
            global_status = {"ok": bool(glob), "fetched_at": utc_now()}
        except Exception as e:
            sys.stderr.write(f"global skip: {type(e).__name__}\n")
            glob = previous.get("global")
            global_status = {"ok": bool(glob), "error": type(e).__name__, "reused": bool(glob),
                             "fetched_at": (prev_status.get("coingecko_global") or {}).get("fetched_at")}
    else:
        glob = previous.get("global")
        global_status = mark_reused(prev_status.get("coingecko_global"), GLOBAL_REFRESH_SEC)

    if status_due(previous, "fred", MACRO_REFRESH_SEC):
        macro, macro_status = get_macro()
        if macro is None and previous.get("macro"):
            macro = previous.get("macro")
            macro_status["reused"] = True
            old = prev_status.get("fred") or {}
            macro_status["last_success_at"] = old.get("last_success_at") or (old.get("fetched_at") if old.get("ok") else None)
        elif macro:
            macro_status["last_success_at"] = macro_status.get("fetched_at")
    else:
        macro = previous.get("macro")
        macro_status = mark_reused(prev_status.get("fred"), MACRO_REFRESH_SEC)

    coins = []
    symbols = Counter((c.get("symbol") or "").upper() for c in markets)
    social = {sym: value for sym, value in social.items() if symbols[sym] == 1}
    seen_ids = set()
    invalid = 0
    for i, c in enumerate(markets):
        o = normalize_coin(c, social, i < SPARK_TOP)
        if not o or o["id"] in seen_ids:
            invalid += 1
            continue
        seen_ids.add(o["id"])
        coins.append(o)
    crypto_count = len(coins)
    coins.extend(xstocks)
    if not coins:
        sys.stderr.write("no valid market data; aborting (keeping previous snapshot)\n")
        sys.exit(1)

    logo_fetches, logo_attempts = 0, 0
    logo_candidates = [c for pair in zip_longest(xstock_logos, markets[:LOGO_MAX]) for c in pair if c is not None]
    for c in logo_candidates:
        if logo_attempts >= LOGO_FETCH_PER_RUN:
            break
        cid = c.get("id")
        if not isinstance(cid, str) or not COIN_ID_RE.fullmatch(cid) or os.path.exists(os.path.join(LOGO_DIR, cid + ".png")):
            continue
        logo_attempts += 1
        if cache_logo(c):
            logo_fetches += 1
    for c in coins:
        c["has_logo"] = os.path.exists(os.path.join(LOGO_DIR, c["id"] + ".png"))

    # Reset only after all CoinGecko feeds recovered, never between market pages.
    if crypto_count and xstocks_status.get('ok') and global_status.get('ok') and not global_status.get('error') and read_rate_limit()['retry_at'] <= time.time():
        try:
            os.unlink(rate_limit_path())
        except FileNotFoundError:
            pass
    snapshot = {
        "snapshot": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(coins),
        "global": glob,
        "macro": macro,
        "social_enabled": bool(LUNAR_KEY),
        "status": {
            "coingecko_markets": {"ok": bool(crypto_count), "raw": len(markets), "valid": crypto_count,
                                  "invalid": invalid, "fetched_at": markets_fetched_at},
            "coingecko_xstocks": xstocks_status,
            "coingecko_global": global_status,
            "lunarcrush": social_status,
            "fred": macro_status,
            "logos": {"fetched": logo_fetches, "attempted": logo_attempts, "limit": LOGO_FETCH_PER_RUN},
        },
        "coins": coins,
    }
    tmp = os.path.join(OUT_DIR, "orbit.json.tmp")
    with open(tmp, "w") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    os.replace(tmp, os.path.join(OUT_DIR, "orbit.json"))
    os.chmod(os.path.join(OUT_DIR, "orbit.json"), 0o644)
    sys.stderr.write(f"snapshot ok: {len(coins)} coins, social={bool(social)}, macro={bool(macro)}, logos={logo_fetches}\n")


if __name__ == "__main__":
    try:
        build()
    except CoinGeckoCooldown as error:
        stamp = datetime.datetime.fromtimestamp(error.retry_at, datetime.timezone.utc).isoformat()
        sys.stderr.write(f'CoinGecko cooldown until {stamp}; previous snapshot retained, no retry this run.\n')
    except Exception as error:
        # No URL, upstream response or credential in the journal.
        sys.stderr.write(f'snapshot failed: {type(error).__name__}; previous snapshot retained.\n')
        sys.exit(1)
