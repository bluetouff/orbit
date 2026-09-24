#!/usr/bin/env python3
"""Public Kraken xStocks trades. No credentials, orders or CoinGecko requests."""
import datetime as dt
from email.utils import parsedate_to_datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

OUT_DIR = Path(os.environ.get('ORBIT_OUT_DIR', '/var/lib/orbit'))
CACHE_NAME = '.kraken-xstocks.json'
TTL = 1800
MAX_ASSETS = 250
MAX_BYTES = 4 * 1024 * 1024
ID = re.compile(r'^[a-z0-9][a-z0-9._-]{0,79}$', re.I)
BASE = re.compile(r'^[A-Z0-9.]{1,18}x$')
_last_request = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_json(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd) as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Cache too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid cache')
    return value


def write_cache(data):
    fd, temporary = tempfile.mkstemp(prefix='.kraken-', dir=OUT_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, separators=(',', ':'), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, OUT_DIR / CACHE_NAME)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request(endpoint, params):
    global _last_request
    if endpoint not in ('AssetPairs', 'Trades'):
        raise ValueError('Unexpected Kraken endpoint')
    if _last_request is not None:
        time.sleep(max(0, 1.1 - (time.monotonic() - _last_request)))
    _last_request = time.monotonic()
    url = 'https://api.kraken.com/0/public/' + endpoint + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'orbit-xstocks/1.0'})
    with OPENER.open(req, timeout=8) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Kraken response too large')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('error') != [] or not isinstance(data.get('result'), dict):
        raise ValueError('Invalid Kraken response')
    return data['result']


def catalog(result):
    if not isinstance(result, dict) or len(result) > 5000:
        raise ValueError('Invalid Kraken catalog')
    pairs = {}
    for item in result.values():
        if not isinstance(item, dict) or item.get('aclass_base') != 'tokenized_asset' or item.get('quote') != 'ZUSD':
            continue
        base = item.get('base')
        if not isinstance(base, str) or not BASE.fullmatch(base) or item.get('altname') != base + 'USD':
            raise ValueError('Invalid token market identity')
        pairs[base + 'USD'] = base
    if not 1 <= len(pairs) <= MAX_ASSETS:
        raise ValueError('Unexpected Kraken catalog size')
    return sorted(pairs.items())


def identities(*snapshots):
    """Preserve existing local favorite IDs; never reuse old financial metrics."""
    result = {}
    for snapshot in snapshots:
        seen = set()
        for c in snapshot.get('coins', []):
            if not isinstance(c, dict) or c.get('asset_type') != 'xstock':
                continue
            cid, symbol, name = c.get('id'), c.get('symbol'), c.get('name')
            if not isinstance(cid, str) or not ID.fullmatch(cid) or not isinstance(symbol, str) or not isinstance(name, str):
                continue
            symbol = symbol.lower()
            if not BASE.fullmatch(symbol[:-1].upper() + 'x') or not 1 <= len(name) <= 96 or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
                continue
            if symbol in seen:
                result.pop(symbol, None)
            else:
                result[symbol] = (cid, name)
            seen.add(symbol)
    return result


def trade_coin(pair, base, result, names, now):
    # Kraken may return its internal pair name; the request was for exactly one pair.
    rows = [v for key, v in result.items() if key != 'last']
    if len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) > 1:
        raise ValueError('Invalid trade response')
    if not rows[0]:
        return None  # An untraded listing has no price to publish.
    trade = rows[0][0]
    if not isinstance(trade, list) or len(trade) < 3 or isinstance(trade[0], bool) or isinstance(trade[2], bool):
        raise ValueError('Invalid trade')
    price, observed = float(trade[0]), float(trade[2])
    if not math.isfinite(price) or price <= 0 or not math.isfinite(observed) or not 0 < observed <= now + 60:
        raise ValueError('Invalid trade price or time')
    cid, name = names.get(base.lower(), ('kraken-' + base.lower(), base))
    return {'id': cid, 'symbol': base.lower(), 'name': name, 'asset_type': 'xstock',
            'price_source': 'kraken', 'market_pair': pair, 'current_price': price,
            'last_updated': dt.datetime.fromtimestamp(observed, dt.timezone.utc).isoformat(),
            'fetched_at': stamp(), 'market_cap': None, 'total_volume': None,
            'has_logo': (OUT_DIR / 'logos' / (cid + '.png')).is_file()}


def retry_at(error):
    if not isinstance(error, urllib.error.HTTPError) or error.code not in (429, 503):
        return None
    header = error.headers.get('Retry-After', '') if error.headers else ''
    try:
        seconds = int(header)
        deadline = time.time() + max(60, seconds)
    except (ValueError, OverflowError):
        try:
            value = parsedate_to_datetime(header)
            deadline = max(time.time() + 60, value.timestamp())
        except (TypeError, ValueError, OverflowError):
            deadline = time.time() + TTL
    return dt.datetime.fromtimestamp(min(253402300799, math.ceil(deadline)), dt.timezone.utc).isoformat()


def collect():
    previous = read_json(OUT_DIR / CACHE_NAME)
    old_status = previous.get('status', {})
    if old_status.get('retry_at'):
        deadline = dt.datetime.fromisoformat(old_status['retry_at'].replace('Z', '+00:00')).timestamp()
        if deadline > time.time():
            print('Kraken provider cooldown active; no request made.', flush=True)
            return False
    # A newly enabled OnBootSec timer can fire immediately after warmup.
    # Suppress only that duplicate; do not skip the next 30-minute cycle.
    if old_status.get('ok') is True and old_status.get('fetched_at'):
        checked = dt.datetime.fromisoformat(old_status['fetched_at'].replace('Z', '+00:00')).timestamp()
        if 0 <= time.time() - checked <= 60:
            print('Kraken collection just completed; no duplicate requests.', flush=True)
            return True
    attempted = stamp()
    try:
        names = identities(read_json(OUT_DIR / 'orbit.json'), previous)
        pairs = catalog(request('AssetPairs', {'aclass_base': 'tokenized_asset'}))
        coins, started = [], time.monotonic()
        for index, (pair, base) in enumerate(pairs):
            if time.monotonic() - started > 480:
                raise TimeoutError('Collection budget exhausted')
            result = request('Trades', {'pair': pair, 'asset_class': 'tokenized_asset', 'count': 1})
            c = trade_coin(pair, base, result, names, time.time())
            if c:
                coins.append(c)
            if (index + 1) % 25 == 0:
                print(f'Kraken markets checked: {index + 1}/{len(pairs)}', flush=True)
        if not coins or len({c['id'] for c in coins}) != len(coins):
            raise ValueError('No valid unique Kraken trades')
        completed = stamp()
        status = {'ok': True, 'attempted_at': attempted, 'fetched_at': completed,
                  'last_success_at': completed, 'ttl': TTL, 'valid': len(coins),
                  'markets': len(pairs), 'untraded': len(pairs) - len(coins)}
        write_cache({'coins': coins, 'status': status})
        print(f'Kraken collection complete: {len(coins)} dated token prices, no credentials.', flush=True)
        return True
    except Exception as error:
        successful = old_status.get('last_success_at') or (old_status.get('fetched_at') if old_status.get('ok') else None)
        status = {'ok': False, 'attempted_at': attempted, 'fetched_at': successful,
                  'last_success_at': successful, 'ttl': TTL, 'error': type(error).__name__}
        retry = retry_at(error)
        if retry:
            status['retry_at'] = retry
        write_cache({'coins': previous.get('coins', []), 'status': status})
        print(f'Kraken collection unavailable: {type(error).__name__}; previous trade dates retained.', file=sys.stderr, flush=True)
        return False


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUT_DIR / '.kraken-xstocks.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Kraken collection already running; no duplicate requests.')
            return
        if not collect():
            raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never log request URLs, bodies, environment or external exception text.
        raise SystemExit('Kraken collector failed: ' + type(error).__name__)
