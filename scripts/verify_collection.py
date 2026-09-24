#!/usr/bin/env python3
"""Read-only verification of repeated public collection, never provider calls."""
import datetime as dt
import json
import time

from deploy_front import public


class CollectionError(ValueError):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise CollectionError('Missing collection timestamp')
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise CollectionError('Timestamp has no timezone')
    return stamp.timestamp()


def inspect(data, now):
    result = {}
    for key in ('coingecko_markets', 'coingecko_xstocks'):
        status = data.get('status', {}).get(key, {})
        if status.get('ok') is not True:
            raise CollectionError(f'{key}: collection unavailable')
        stamp = timestamp(status.get('fetched_at'))
        age = now - stamp
        if not -60 <= age <= 180:
            raise CollectionError(f'{key}: collection age {age:.0f}s exceeds the release check')
        result[key] = stamp
    stocks = [c for c in data.get('coins', []) if c.get('asset_type') == 'xstock'][:50]
    if not stocks:
        raise CollectionError('No xStocks in the public feed')
    dated = []
    for coin in stocks:
        try:
            age = now - timestamp(coin.get('last_updated'))
        except (TypeError, ValueError):
            continue
        if -60 <= age <= 600:
            dated.append(age)
    if len(dated) <= len(stocks) / 2:
        raise CollectionError('Most displayed xStocks lack a quote from the last ten minutes')
    return result, len(dated), len(stocks)


def verify(timeout=300, interval=30):
    deadline = time.monotonic() + timeout
    previous, advances = {}, {'coingecko_markets': 0, 'coingecko_xstocks': 0}
    while True:
        data = json.loads(public('/data.json')[0])
        current, recent, total = inspect(data, time.time())
        for key, stamp in current.items():
            if key in previous:
                if stamp < previous[key]:
                    raise CollectionError(f'{key}: collection timestamp regressed')
                if stamp > previous[key]:
                    advances[key] += 1
        previous = current
        print(f'Collection updates: crypto={advances["coingecko_markets"]}, xStocks={advances["coingecko_xstocks"]}; dated token quotes <=10min: {recent}/{total}.', flush=True)
        if min(advances.values()) >= 2:
            print('PASS: both market feeds renewed twice, collection current, original quote dates checked.')
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionError('Both market feeds did not renew twice within five minutes')
        time.sleep(min(interval, remaining))


if __name__ == '__main__':
    try:
        verify()
    except Exception as error:
        # Only locally authored validation errors may be printed; HTTP exceptions
        # can carry URLs and untrusted upstream response details.
        message = str(error) if type(error) is CollectionError else type(error).__name__
        raise SystemExit('Collection verification failed: ' + message)
