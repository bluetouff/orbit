"""Offline collection health and conservative local Demo budget projection.

No network calls, credentials or upstream response bodies. The ledger describes
only requests reserved by this installation, not the provider account total.
"""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time


def timestamp(value):
    try:
        date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return date.timestamp() if date.tzinfo is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def budget_projection(path, now):
    date = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    month = date.strftime('%Y-%m')
    result = {'scope': 'local-reservations-only', 'month': month, 'limit': 10000,
              'calls': None, 'projected_calls': None, 'remaining': None, 'state': 'unknown'}
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return result
            raw = stream.read(1025)
        data = json.loads(raw) if len(raw) <= 1024 else None
        if (not isinstance(data, dict) or set(data) != {'month', 'calls'}
                or type(data['calls']) is not int or not 0 <= data['calls'] <= 10000
                or not isinstance(data['month'], str)):
            return result
        ledger_month = dt.datetime.strptime(data['month'], '%Y-%m').strftime('%Y-%m')
        if ledger_month != data['month'] or ledger_month > month:
            return result
        calls = data['calls'] if ledger_month == month else 0
    except (OSError, ValueError, TypeError):
        return result
    end = (date.replace(day=1) + dt.timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    seconds = max(0, end.timestamp() - now)
    # Future scheduled requests, not an extrapolation of an unknown start date.
    projected = calls + math.ceil(seconds / 300) + math.ceil(seconds / 3600)
    result.update(calls=calls, remaining=10000-calls, projected_calls=projected,
                  state='exhausted' if calls >= 10000 else 'at-risk' if projected >= 10000 else 'low-margin' if projected > 9500 else 'ok')
    return result


def assess(snapshot, now=None, budget=None, failure=None):
    now = time.time() if now is None else now
    source = (snapshot.get('status') or {}).get('coingecko_markets') or {}
    demo = source.get('policy') == 'demo-250-v1'
    stamp = source.get('last_success_at') or (source.get('fetched_at') if source.get('ok') else None)
    observed = timestamp(stamp)
    coins = snapshot.get('coins') or []
    coins = [c for c in coins if isinstance(c, dict)] if isinstance(coins, list) else []
    current = lambda c: (timestamp(c.get('last_updated')) is not None
                         and -60 <= now - timestamp(c.get('last_updated')) <= (600 if demo else 180))
    recent = sum(current(c) for c in coins)
    issues = []
    if failure:
        issues.append(failure)
    if source.get('ok') is not True:
        issues.append('market-collection-failed')
    if observed is None or not -60 <= now-observed <= (420 if demo else 180):
        issues.append('market-collection-stale')
    if len(coins) < 20 or recent < math.ceil(len(coins)*.9) or not any(c.get('id') == 'bitcoin' and current(c) for c in coins):
        issues.append('quote-coverage-insufficient')
    state = 'critical' if issues else 'ok'
    for key in ('coingecko_global', 'fred', 'lunarcrush'):
        context = (snapshot.get('status') or {}).get(key) or {}
        if context.get('enabled') is not False and context.get('ok') is False:
            issues.append(key + '-unavailable')
            if state == 'ok':
                state = 'warning'
    if budget and budget['state'] != 'ok':
        issues.append('budget-' + budget['state'])
        if budget['state'] == 'exhausted':
            state = 'critical'
        elif state == 'ok':
            state = 'warning'
    return {'state': state, 'issues': issues, 'checked_at': dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
            'last_success_at': stamp, 'assets': len(coins), 'recent_quotes': recent, 'budget': budget}


def write_private(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.orbit-health-', dir=Path(path).parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record(snapshot, directory, demo=False, failure=None):
    now = time.time()
    budget = budget_projection(Path(directory) / '.coingecko-budget.json', now) if demo else None
    report = assess(snapshot, now, budget, failure)
    path = Path(directory) / '.orbit-health.json'
    previous = None
    try:
        with path.open() as stream:
            previous = json.load(stream)
    except (OSError, ValueError):
        pass
    transition = not isinstance(previous, dict) or (previous.get('state'), previous.get('issues')) != (report['state'], report['issues'])
    write_private(path, report)
    if transition:
        sys.stderr.write('ORBIT_HEALTH state=' + report['state'] + ' issues=' + ','.join(report['issues']) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=Path('/var/lib/orbit/orbit.json'))
    parser.add_argument('--budget', type=Path, default=Path('/var/lib/orbit/.coingecko-budget.json'))
    args = parser.parse_args()
    try:
        with args.snapshot.open() as stream:
            snapshot = json.load(stream)
        demo = (snapshot.get('status') or {}).get('coingecko_markets', {}).get('policy') == 'demo-250-v1'
        report = assess(snapshot, budget=budget_projection(args.budget, time.time()) if demo else None)
        print(json.dumps(report, allow_nan=False))
        sys.exit({'ok': 0, 'warning': 1, 'critical': 2}[report['state']])
    except (OSError, ValueError, TypeError, AttributeError):
        print('{"state":"critical","issues":["snapshot-unreadable"]}')
        sys.exit(2)
