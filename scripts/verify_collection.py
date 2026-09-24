#!/usr/bin/env python3
"""Read-only verification of repeated public collection, never provider calls."""
import datetime as dt
import json
import time

from deploy_front import public
from validate_snapshot import is_crypto


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
    for key in ('coingecko_markets',):
        status = data.get('status', {}).get(key, {})
        if status.get('ok') is not True:
            raise CollectionError(f'{key}: collection unavailable')
        stamp = timestamp(status.get('fetched_at'))
        age = now - stamp
        maximum = 180
        if not -60 <= age <= maximum:
            raise CollectionError(f'{key}: collection age {age:.0f}s exceeds the release check')
        result[key] = stamp
    coins = data.get('coins', [])
    if not coins or any(not is_crypto(c) for c in coins):
        raise CollectionError('Expected exclusively crypto assets')
    if any('xstock' in key.lower() for key in data.get('status', {})):
        raise CollectionError('Retired source remains in public feed')
    return result, len(coins)


def verify(timeout=600, interval=30):
    deadline = time.monotonic() + timeout
    previous, advances = {}, {'coingecko_markets': 0}
    while True:
        data = json.loads(public('/data.json')[0])
        current, total = inspect(data, time.time())
        for key, stamp in current.items():
            if key in previous:
                if stamp < previous[key]:
                    raise CollectionError(f'{key}: collection timestamp regressed')
                if stamp > previous[key]:
                    advances[key] += 1
        previous = current
        print(f'Collection updates: crypto={advances["coingecko_markets"]}; {total} crypto assets.', flush=True)
        if advances['coingecko_markets'] >= 2:
            print('PASS: crypto collection renewed twice; crypto-only public feed confirmed.')
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CollectionError('Required collection renewals were not observed within the observation window')
        time.sleep(min(interval, remaining))


if __name__ == '__main__':
    try:
        verify()
    except Exception as error:
        # Only locally authored validation errors may be printed; HTTP exceptions
        # can carry URLs and untrusted upstream response details.
        message = str(error) if type(error) is CollectionError else type(error).__name__
        raise SystemExit('Collection verification failed: ' + message)
