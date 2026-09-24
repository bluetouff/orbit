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
    for key in ('coingecko_markets', 'kraken_xstocks'):
        status = data.get('status', {}).get(key, {})
        if status.get('ok') is not True:
            raise CollectionError(f'{key}: collection unavailable')
        stamp = timestamp(status.get('fetched_at'))
        age = now - stamp
        maximum = 2100 if key == 'kraken_xstocks' else 180
        if not -60 <= age <= maximum:
            raise CollectionError(f'{key}: collection age {age:.0f}s exceeds the release check')
        result[key] = stamp
    stocks = [c for c in data.get('coins', []) if c.get('asset_type') == 'xstock']
    if not stocks:
        raise CollectionError('No xStocks in the public feed')
    for coin in stocks:
        if coin.get('price_source') != 'kraken':
            raise CollectionError('xStocks source is not Kraken')
        observed = timestamp(coin.get('last_updated'))
        checked = timestamp(coin.get('fetched_at'))
        if not -60 <= now - checked <= 2400 or observed <= 0 or observed > checked + 60:
            raise CollectionError('Invalid or unchecked Kraken trade date')
    return result, len(stocks), len(stocks)


def verify(timeout=600, interval=30, kraken_renewal=False):
    deadline = time.monotonic() + timeout
    previous, advances = {}, {'coingecko_markets': 0, 'kraken_xstocks': 0}
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
        print(f'Collection updates: crypto={advances["coingecko_markets"]}, xStocks={advances["kraken_xstocks"]}; dated Kraken trades: {recent}/{total}.', flush=True)
        if advances['coingecko_markets'] >= 2 and (not kraken_renewal or advances['kraken_xstocks'] >= 1):
            print('PASS: crypto renewed twice; Kraken collection valid, original trade dates checked.' + (' Kraken renewed once.' if kraken_renewal else ' Kraken recurrence needs the extended check.'))
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionError('Required collection renewals were not observed within the observation window')
        time.sleep(min(interval, remaining))


if __name__ == '__main__':
    try:
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--kraken-renewal", action="store_true", help="Also wait for a scheduled Kraken renewal (up to 40 minutes)")
        args = parser.parse_args()
        verify(timeout=2400 if args.kraken_renewal else 600, kraken_renewal=args.kraken_renewal)
    except Exception as error:
        # Only locally authored validation errors may be printed; HTTP exceptions
        # can carry URLs and untrusted upstream response details.
        message = str(error) if type(error) is CollectionError else type(error).__name__
        raise SystemExit('Collection verification failed: ' + message)
