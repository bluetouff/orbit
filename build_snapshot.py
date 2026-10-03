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
from email.utils import parsedate_to_datetime
import tempfile
import fcntl
import stat
import orbit_health


def collection_profile(path):
    """Optional administrator-owned profile beside the installed collector; no keys."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Invalid collection profile')
        body = stream.read(64)
    if body != b'demo-250-v1\n':
        raise ValueError('Unknown collection profile')
    return 'demo-250-v1'


PROFILE = collection_profile(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collection.profile'))


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
MARKETS_REFRESH_SEC = env_int("ORBIT_MARKETS_REFRESH_SEC", 60, 60, 180)
SOCIAL_REFRESH_SEC = env_int("ORBIT_SOCIAL_REFRESH_SEC", 900, 60, 86400)
MACRO_REFRESH_SEC  = env_int("ORBIT_MACRO_REFRESH_SEC", 3600, 300, 86400)
TIMEOUT    = env_float("ORBIT_TIMEOUT", 20, 2, 60)
MAX_BYTES  = env_int("ORBIT_MAX_BYTES", 40 * 1024 * 1024, 1024 * 1024, 80 * 1024 * 1024)

CG_TIER = os.environ.get("CG_API_TIER", "none").lower()
CG_KEY  = os.environ.get("CG_API_KEY", "").strip()
CG_BASE = "https://pro-api.coingecko.com/api/v3" if CG_TIER == "pro" else "https://api.coingecko.com/api/v3"
if PROFILE == 'demo-250-v1':
    # Explicit deployment choice, overriding old non-secret cadence settings.
    CG_TIER, CG_BASE = 'demo', 'https://api.coingecko.com/api/v3'
    TOP, SPARK_TOP, LOGO_MAX = 250, min(SPARK_TOP, 250), min(LOGO_MAX, 250)
    MARKETS_REFRESH_SEC, GLOBAL_REFRESH_SEC = 300, 3600
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
_CG_LAST_REQUEST = None


class CoinGeckoCooldown(Exception):
    """Expected provider backpressure, containing no request or credential."""
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__('CoinGecko requests deferred')


class CoinGeckoBudgetExceeded(CoinGeckoCooldown):
    """Local Demo request budget exhausted until the next UTC calendar month."""


def reserve_demo_request():
    """Reserve before sending, including failed requests; serialize all processes.

    Only Orbit's requests since activation are known, not other key consumers.
    A corrupt ledger blocks requests instead of silently resetting the budget.
    """
    if CG_TIER != 'demo':
        return
    lock_path = os.path.join(OUT_DIR, '.coingecko-budget.lock')
    path = os.path.join(OUT_DIR, '.coingecko-budget.json')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid CoinGecko budget lock')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        now = datetime.datetime.fromtimestamp(time.time(), datetime.timezone.utc)
        month = now.strftime('%Y-%m')
        state = {'month': month, 'calls': 0}
        try:
            source = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(source) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError('Invalid CoinGecko budget state')
                raw = stream.read(1025)
            try:
                state = json.loads(raw) if len(raw) <= 1024 else None
            except ValueError:
                state = None
            if (not isinstance(state, dict) or set(state) != {'month', 'calls'}
                    or not isinstance(state['month'], str)
                    or not re.fullmatch(r'[0-9]{4}-(?:0[1-9]|1[0-2])', state['month'])
                    or state['month'] > month or type(state['calls']) is not int
                    or not 0 <= state['calls'] <= 10000):
                raise ValueError('Invalid CoinGecko budget state')
            if state['month'] != month:
                state = {'month': month, 'calls': 0}
        if state['calls'] >= 10000:
            next_month = (now.replace(day=1) + datetime.timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            raise CoinGeckoBudgetExceeded(int(next_month.timestamp()))
        state['calls'] += 1
        target, temporary = tempfile.mkstemp(prefix='.coingecko-budget-', dir=OUT_DIR)
        try:
            with os.fdopen(target, 'w') as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(OUT_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


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
    # Access refusals need an operator/provider fix, not one retry per minute.
    if st.get('ok') is False and st.get('http_status') in (401, 403):
        if parse_ts(st.get('retry_at')) > time.time():
            return False
    fetched = parse_ts(st.get("attempted_at") or st.get("fetched_at"))
    return not fetched or fetched > time.time() or (time.time() - fetched) >= ttl


def mark_reused(status, ttl):
    status = dict(status or {})
    fetched = parse_ts(status.get("fetched_at"))
    status["reused"] = True
    status["ttl"] = ttl
    if fetched:
        status["age_seconds"] = max(0, int(time.time() - fetched))
    return status


def failed_status(previous, error, ttl, retained):
    """A failed attempt never replaces the last successful collection date."""
    successful = previous.get('last_success_at') or (previous.get('fetched_at') if previous.get('ok') else None)
    status = {'ok': False, 'attempted_at': utc_now(), 'fetched_at': successful,
              'last_success_at': successful, 'error': type(error).__name__,
              'reused': bool(retained), 'ttl': ttl}
    if isinstance(error, CoinGeckoCooldown):
        status['retry_at'] = datetime.datetime.fromtimestamp(error.retry_at, datetime.timezone.utc).isoformat()
    elif isinstance(error, urllib.error.HTTPError):
        status['http_status'] = error.code
        if error.code in (401, 403):
            now = time.time()
            header = error.headers.get('Retry-After') if error.headers else None
            delay = max(900, retry_delay(header, 1, now))
            deadline = min(253402300799, math.ceil(now) + delay)
            status['retry_at'] = datetime.datetime.fromtimestamp(deadline, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        error.close()
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
        def invalid_constant(_):
            raise ValueError('Non-finite JSON number')
        def finite_float(value):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Non-finite JSON number')
            return number
        return data if binary else json.loads(data.decode("utf-8"), parse_constant=invalid_constant, parse_float=finite_float)


def cg(path, params):
    global _CG_LAST_REQUEST
    state = read_rate_limit()
    if state['retry_at'] > time.time():
        raise CoinGeckoCooldown(state['retry_at'])
    if CG_TIER in ('demo', 'pro') and not CG_KEY:
        raise ValueError('Authenticated CoinGecko mode needs a key')
    # Page and global calls used to arrive in the same burst.
    # This never retries a request and does not bypass the shared 429 deadline.
    if _CG_LAST_REQUEST is not None:
        time.sleep(max(0, 2 - (time.monotonic() - _CG_LAST_REQUEST)))
    _CG_LAST_REQUEST = time.monotonic()
    headers = {f"x-cg-{CG_TIER}-api-key": CG_KEY} if CG_KEY and CG_TIER in ("demo", "pro") else None
    reserve_demo_request()
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


def is_removed_asset(c):
    return (c.get('asset_type', 'crypto') != 'crypto' or c.get('price_source') == 'kraken'
            or bool(re.search(r'(?:^kraken-|xstocks?$)', str(c.get('id', '')), re.I))
            or bool(re.search(r'\bxstocks?\b', str(c.get('name', '')), re.I)))


def normalize_coin(c, social_by_symbol, include_spark):
    if not isinstance(c, dict):
        return None
    cid = bounded_text(c.get("id"), 80)
    sym = bounded_text(c.get("symbol"), 20)
    name = bounded_text(c.get("name"), 96)
    if not cid or not sym or not name or cid != c.get("id") or sym != c.get("symbol") or not COIN_ID_RE.fullmatch(cid) or not SYMBOL_RE.fullmatch(sym):
        return None
    if is_removed_asset(c):
        return None
    o = {"id": cid, "symbol": sym.lower(), "name": re.sub(r"[\x00-\x1f\x7f]", "", name), "asset_type": "crypto"}
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
    s = social_by_symbol.get(sym.upper())
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


def get_social():
    if not LUNAR_KEY:
        return {}, {"enabled": False, "ok": False, "count": 0}
    try:
        d = fetch(f"https://lunarcrush.com/api4/public/coins/list/v1",
                  headers={"Authorization": f"Bearer {LUNAR_KEY}"})
        if not isinstance(d, dict) or not isinstance(d.get('data'), list):
            raise ValueError('Invalid social response')
        rows = d['data']
        if any(not isinstance(row, dict) or not isinstance(row.get('symbol'), str)
               or not SYMBOL_RE.fullmatch(row['symbol']) for row in rows):
            raise ValueError('Invalid social row')
        out = {}
        counts = Counter(row['symbol'].upper() for row in rows)
        for row in rows:
            symbol = row['symbol'].upper()
            if counts[symbol] == 1:
                values = normalize_social(row)
                if values:
                    out[symbol] = values
    except Exception as e:
        sys.stderr.write(f"social skip: {type(e).__name__}\n")
        return {}, {"enabled": True, "ok": False, "error": type(e).__name__, "count": 0, "fetched_at": utc_now()}
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
            if not isinstance(d, dict) or not isinstance(d.get('observations'), list):
                raise ValueError('Invalid macro response')
            vals = []
            for row in d['observations']:
                if not isinstance(row, dict):
                    raise ValueError('Invalid macro observation')
                if row.get('value') in (None, '.', ''):
                    continue
                value = finite_num(row.get('value'), lo=-100000, hi=100000)
                date = row.get('date')
                if value is None or not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                    raise ValueError('Invalid macro value')
                if datetime.date.fromisoformat(date) > datetime.datetime.now(datetime.timezone.utc).date():
                    raise ValueError('Future macro observation')
                vals.append((date, value))
            if any(vals[i][0] <= vals[i+1][0] for i in range(len(vals)-1)):
                raise ValueError('Unordered macro observations')
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
    return out or None, {"enabled": True, "ok": series_count == len(FRED_SERIES), "series": series_count, "errors": errors, "fetched_at": utc_now()}


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


def publish_snapshot(snapshot):
    """Readers see either complete snapshot; provider dates are never rewritten."""
    if PROFILE:
        for key in ('coingecko_markets', 'coingecko_global'):
            snapshot['status'][key]['policy'] = PROFILE
    body = json.dumps(snapshot, separators=(",", ":"), allow_nan=False)
    tmp = os.path.join(OUT_DIR, "orbit.json.tmp")
    with open(tmp, "w") as f:
        f.write(body)
    os.replace(tmp, os.path.join(OUT_DIR, "orbit.json"))
    os.chmod(os.path.join(OUT_DIR, "orbit.json"), 0o644)


def publish_crypto_first(markets, status, previous):
    """Make complete crypto pages available before optional network work."""
    social = previous_social(previous)
    symbols = Counter(c['symbol'].upper() for c in markets if isinstance(c, dict) and isinstance(c.get('symbol'), str))
    social = {symbol: value for symbol, value in social.items() if symbols[symbol] == 1}
    coins, seen = [], set()
    for i, row in enumerate(markets):
        c = normalize_coin(row, social, i < SPARK_TOP)
        if not c or c['id'] in seen or c['asset_type'] != 'crypto':
            continue
        c['has_logo'] = os.path.exists(os.path.join(LOGO_DIR, c['id'] + '.png'))
        seen.add(c['id'])
        coins.append(c)
    if not coins:
        return
    status.update(raw=len(markets), valid=len(coins), invalid=len(markets)-len(coins))
    prior_status = previous.get('status') or {}
    source_status = {key: dict(prior_status.get(key) or {'ok': False})
                     for key in ('coingecko_global', 'lunarcrush', 'fred')}
    source_status['coingecko_markets'] = dict(status)
    publish_snapshot({'snapshot': utc_now(), 'count': len(coins), 'coins': coins,
                      'status': source_status, 'global': previous.get('global'),
                      'macro': previous.get('macro'), 'social_enabled': bool(LUNAR_KEY)})


class MarketCoverageError(ValueError):
    """A response cannot replace a substantially larger healthy universe."""


def check_market_coverage(markets, previous):
    valid = {}
    for row in markets:
        coin = normalize_coin(row, {}, False)
        if coin:
            valid[coin['id']] = coin
    old_count = len({c['id'] for c in previous if isinstance(c, dict) and isinstance(c.get('id'), str)})
    minimum = max(min(20, TOP), math.ceil(min(old_count, TOP)*.9))
    if len(valid) < minimum:
        raise MarketCoverageError('Insufficient crypto universe')
    if PROFILE == 'demo-250-v1':
        now = time.time()
        def recent(coin):
            stamp = orbit_health.timestamp(coin.get('last_updated'))
            return stamp is not None and -60 <= now-stamp <= 600
        if len(valid) < 20 or sum(recent(c) for c in valid.values()) < math.ceil(len(valid)*.9) or not recent(valid.get('bitcoin', {})):
            raise MarketCoverageError('Insufficient current crypto quotes')


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(LOGO_DIR, exist_ok=True)
    previous = load_previous()
    prev_status = previous.get("status") or {}
    old_crypto = [dict(c) for c in previous.get('coins', []) if isinstance(c, dict) and not is_removed_asset(c)]
    markets, retained_crypto = [], []
    same_profile = (prev_status.get('coingecko_markets') or {}).get('policy') == PROFILE
    if old_crypto and same_profile and not status_due(previous, 'coingecko_markets', MARKETS_REFRESH_SEC):
        retained_crypto = old_crypto
        markets_status = mark_reused(prev_status.get('coingecko_markets'), MARKETS_REFRESH_SEC)
    else:
        try:
            markets = get_markets()
            check_market_coverage(markets, old_crypto)
            markets_status = {'ok': True, 'fetched_at': utc_now(), 'ttl': MARKETS_REFRESH_SEC}
            markets_status['last_success_at'] = markets_status['fetched_at']
        except Exception as error:
            markets = []
            retained_crypto = old_crypto
            markets_status = failed_status(prev_status.get('coingecko_markets') or {}, error, MARKETS_REFRESH_SEC, retained_crypto)

    if markets and markets_status.get('ok'):
        publish_crypto_first(markets, markets_status, previous)

    # Optional context can update independently from crypto market failures.
    markets = [c for c in markets if isinstance(c, dict) and not is_removed_asset(c)]

    if status_due(previous, "lunarcrush", SOCIAL_REFRESH_SEC):
        social, social_status = get_social()
    else:
        social = previous_social(previous)
        social_status = mark_reused(prev_status.get("lunarcrush"), SOCIAL_REFRESH_SEC)

    glob = None
    if (prev_status.get('coingecko_global') or {}).get('policy') != PROFILE or status_due(previous, "coingecko_global", GLOBAL_REFRESH_SEC):
        try:
            glob = cg("global", {}).get("data")
            global_status = {"ok": bool(glob), "fetched_at": utc_now(), "ttl": GLOBAL_REFRESH_SEC}
        except Exception as e:
            sys.stderr.write(f"global skip: {type(e).__name__}\n")
            glob = previous.get("global")
            global_status = failed_status(prev_status.get('coingecko_global') or {}, e, GLOBAL_REFRESH_SEC, glob)
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
        elif macro and macro_status.get('ok'):
            macro_status["last_success_at"] = macro_status.get("fetched_at")
        elif macro:
            # Preserve each missing series and its original observation date.
            for key in FRED_SERIES:
                if key not in macro and key in (previous.get('macro') or {}):
                    macro[key] = previous['macro'][key]
            old = prev_status.get('fred') or {}
            macro_status['last_success_at'] = old.get('last_success_at') or (old.get('fetched_at') if old.get('ok') else None)
            macro_status['reused'] = True
    else:
        macro = previous.get("macro")
        macro_status = mark_reused(prev_status.get("fred"), MACRO_REFRESH_SEC)

    coins = []
    symbols = Counter(c['symbol'].upper() for c in (markets or retained_crypto) if isinstance(c, dict) and isinstance(c.get('symbol'), str))
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
    if retained_crypto:
        coins = retained_crypto
        for c in coins:
            for key in ('galaxy_score', 'sentiment', 'social_dominance', 'social_source'):
                c.pop(key, None)
            if c.get('symbol', '').upper() in social:
                c.update(normalize_social(social[c['symbol'].upper()]))
    else:
        markets_status.update(raw=len(markets), valid=len(coins), invalid=invalid)
    crypto_count = len(coins)
    if not coins:
        sys.stderr.write("no valid market data; aborting (keeping previous snapshot)\n")
        sys.exit(1)

    logo_fetches, logo_attempts = 0, 0
    logo_candidates = markets[:LOGO_MAX]
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
    if crypto_count and markets_status.get('ok') and global_status.get('ok') and not global_status.get('error') and read_rate_limit()['retry_at'] <= time.time():
        try:
            os.unlink(rate_limit_path())
        except FileNotFoundError:
            pass
    snapshot = {
        "snapshot": utc_now(),
        "count": len(coins),
        "global": glob,
        "macro": macro,
        "social_enabled": bool(LUNAR_KEY),
        "status": {
            "coingecko_markets": markets_status,
            "coingecko_global": global_status,
            "lunarcrush": social_status,
            "fred": macro_status,
            "logos": {"fetched": logo_fetches, "attempted": logo_attempts, "limit": LOGO_FETCH_PER_RUN},
        },
        "coins": coins,
    }
    publish_snapshot(snapshot)
    try:
        orbit_health.record(snapshot, OUT_DIR, demo=PROFILE == 'demo-250-v1')
    except (OSError, ValueError, TypeError):
        # Publication succeeded; a private health-report failure must not claim
        # that the old public snapshot was retained.
        sys.stderr.write('ORBIT_HEALTH state=critical issues=health-report-failed\n')
    health = 'ok' if markets_status.get('ok') else 'degraded'
    sys.stderr.write(f"snapshot {health}: {len(coins)} coins, crypto={markets_status.get('error', 'ok')}, social={bool(social)}, macro={bool(macro)}, logos={logo_fetches}\n")


if __name__ == "__main__":
    try:
        build()
    except CoinGeckoCooldown as error:
        stamp = datetime.datetime.fromtimestamp(error.retry_at, datetime.timezone.utc).isoformat()
        sys.stderr.write(f'CoinGecko cooldown until {stamp}; previous snapshot retained, no retry this run.\n')
    except Exception as error:
        # No URL, upstream response or credential in the journal.
        sys.stderr.write(f'snapshot failed: {type(error).__name__}; previous snapshot retained.\n')
        try:
            orbit_health.record(load_previous(), OUT_DIR, demo=PROFILE == 'demo-250-v1', failure='collector-failed')
        except Exception:
            sys.stderr.write('ORBIT_HEALTH state=critical issues=health-report-failed\n')
        sys.exit(1)
