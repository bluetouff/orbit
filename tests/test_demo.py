"""Offline profile, quota and failure-boundary fixtures; no provider access."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from test_builder import b, coin, v


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for attr, value in [('OUT_DIR', str(self.root)), ('CG_TIER', 'demo'), ('CG_KEY', 'synthetic-test-only'), ('_CG_LAST_REQUEST', None)]:
            context = patch.object(b, attr, value)
            context.start()
            self.addCleanup(context.stop)
        self.ledger = self.root / '.coingecko-budget.json'

    def test_every_attempt_reserved_before_network_and_survives_process_restart(self):
        def failed_request(*args, **kwargs):
            self.assertEqual(json.loads(self.ledger.read_text())['calls'], 1)
            raise urllib.error.HTTPError('https://example.invalid', 403, 'forbidden', {}, None)
        with patch.object(b, 'fetch', side_effect=failed_request):
            with self.assertRaises(urllib.error.HTTPError): b.cg('coins/markets', {})
        b.reserve_demo_request()
        self.assertEqual(json.loads(self.ledger.read_text())['calls'], 2)
        self.assertEqual(self.ledger.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('synthetic-test-only', self.ledger.read_text())
        self.assertEqual(set(json.loads(self.ledger.read_text())), {'month', 'calls'})

    def test_limit_month_boundary_and_calendar_rollback(self):
        self.ledger.write_text(json.dumps({'month': '2026-09', 'calls': 9999}))
        september = dt.datetime(2026, 9, 30, 23, 59, tzinfo=dt.timezone.utc).timestamp()
        with patch.object(b.time, 'time', return_value=september), patch.object(b, 'fetch') as fetch:
            b.reserve_demo_request()
            with self.assertRaises(b.CoinGeckoBudgetExceeded) as error: b.cg('global', {})
            self.assertEqual(error.exception.retry_at, september + 60)
            fetch.assert_not_called()
        with patch.object(b.time, 'time', return_value=september + 60): b.reserve_demo_request()
        self.assertEqual(json.loads(self.ledger.read_text()), {'month': '2026-10', 'calls': 1})
        with patch.object(b.time, 'time', return_value=september):
            with self.assertRaisesRegex(ValueError, 'budget state'): b.reserve_demo_request()

    def test_corruption_symlinks_and_missing_key_fail_before_network(self):
        for raw in ['{}', '{bad', 'x' * 1025, '{"month":"2026-01","calls":true}', '{"month":"2026-13","calls":1}']:
            self.ledger.write_text(raw)
            with patch.object(b, 'fetch') as fetch:
                with self.assertRaises(ValueError): b.cg('global', {})
                fetch.assert_not_called()
        self.ledger.unlink()
        target = self.root / 'unchanged'
        target.write_text('unchanged')
        self.ledger.symlink_to(target)
        with self.assertRaises(OSError): b.reserve_demo_request()
        self.assertEqual(target.read_text(), 'unchanged')
        self.ledger.unlink()
        with patch.object(b, 'CG_KEY', ''), patch.object(b, 'fetch') as fetch:
            with self.assertRaisesRegex(ValueError, 'needs a key'): b.cg('global', {})
            fetch.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_parallel_processes_cannot_lose_reservations(self):
        builder = str(Path(b.__file__).resolve())
        code = "import runpy,sys; ns=runpy.run_path(sys.argv[1]); [ns['reserve_demo_request']() for _ in range(25)]"
        env = {'PATH': os.environ['PATH'], 'ORBIT_OUT_DIR': str(self.root), 'CG_API_TIER': 'demo'}
        children = [subprocess.Popen([sys.executable, '-c', code, builder], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(4)]
        for child in children:
            output, error = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, error.decode())
        self.assertEqual(json.loads(self.ledger.read_text())['calls'], 100)

    def test_profile_overrides_only_nonsecret_collection_settings(self):
        builder = self.root / 'build_snapshot.py'
        builder.write_bytes(Path(b.__file__).read_bytes())
        profile = self.root / 'collection.profile'
        profile.write_bytes(b'demo-250-v1\n')
        env = {'PATH': os.environ['PATH'], 'CG_API_TIER': 'none', 'ORBIT_TOP': '500', 'ORBIT_MARKETS_REFRESH_SEC': '60'}
        code = "import runpy,sys,json; n=runpy.run_path(sys.argv[1]); print(json.dumps([n[k] for k in ('CG_TIER','TOP','MARKETS_REFRESH_SEC','GLOBAL_REFRESH_SEC')]))"
        result = subprocess.run([sys.executable, '-c', code, str(builder)], env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['demo', 250, 300, 3600])
        profile.write_bytes(b'unknown\n')
        with self.assertRaisesRegex(ValueError, 'Unknown collection profile'): b.collection_profile(profile)
        profile.unlink()
        profile.symlink_to(builder)
        with self.assertRaises(OSError): b.collection_profile(profile)

    def test_activation_fetches_despite_old_access_refusal_and_publishes_policy(self):
        old = {'coins': [coin()], 'status': {'coingecko_markets': {'ok': False, 'http_status': 403, 'retry_at': '2099-01-01T00:00:00Z'}}}
        markets = [coin('bitcoin' if i == 0 else f'asset-{i}') for i in range(20)]
        with patch.object(b.time, 'time', return_value=1767225601), patch.object(b, 'PROFILE', 'demo-250-v1'), patch.object(b, 'LOGO_DIR', str(self.root)), patch.object(b, 'load_previous', return_value=old), patch.object(b, 'get_markets', return_value=markets) as market, patch.object(b, 'get_social', return_value=({}, {'ok': False})), patch.object(b, 'get_macro', return_value=(None, {'ok': False})), patch.object(b, 'cg', return_value={}), patch.object(b, 'cache_logo', return_value=False):
            b.build()
        market.assert_called_once()
        data = json.loads((self.root / 'orbit.json').read_text())
        self.assertEqual(data['status']['coingecko_markets']['policy'], 'demo-250-v1')
        self.assertTrue(data['status']['coingecko_markets']['ok'])
        self.assertTrue(data['coins'][0]['last_updated'].startswith('2026-01-01T00:00:00'))

    def test_live_quote_coverage_is_separate_from_collection_freshness(self):
        now = dt.datetime.now(dt.timezone.utc)
        coins = [dict(coin('bitcoin' if i == 0 else f'asset-{i}'), last_updated=now.isoformat()) for i in range(20)]
        data = {'coins': coins}
        self.assertTrue(v.demo_quotes_current(data, now.timestamp() + 600))
        self.assertFalse(v.demo_quotes_current(data, now.timestamp() + 601))
        self.assertFalse(v.demo_quotes_current(data, now.timestamp() - 61))
        coins[0].pop('last_updated')
        self.assertFalse(v.demo_quotes_current(data, now.timestamp()))
        coins[0]['last_updated'] = now.isoformat()
        for c in coins[1:4]: c.pop('last_updated')
        self.assertFalse(v.demo_quotes_current(data, now.timestamp()))
        self.assertEqual(v.market_max_age({'ttl': 86400}), 180)
        self.assertEqual(v.market_max_age({'policy': 'demo-250-v1'}), 420)

    def test_demo_cadence_uses_one_page_per_five_minutes_and_global_hourly(self):
        clock = [1767225600]
        requests = []
        def stamp():
            return dt.datetime.fromtimestamp(clock[0], dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        def request(path, params):
            requests.append((path, params))
            if path == 'global': return {'data': {'total_market_cap': {'usd': 1}}}
            return [dict(coin('bitcoin' if i == 0 else f'asset-{i}'), last_updated=stamp()) for i in range(250)]
        with patch.object(b, 'PROFILE', 'demo-250-v1'), patch.object(b, 'TOP', 250), patch.object(b, 'MARKETS_REFRESH_SEC', 300), patch.object(b, 'GLOBAL_REFRESH_SEC', 3600), patch.object(b, 'LOGO_DIR', str(self.root)), patch.object(b, 'LOGO_FETCH_PER_RUN', 0), patch.object(b, 'LUNAR_KEY', ''), patch.object(b, 'FRED_KEY', ''), patch.object(b.time, 'time', side_effect=lambda: clock[0]), patch.object(b, 'utc_now', side_effect=stamp), patch.object(b, 'cg', side_effect=request):
            b.build()
            self.assertEqual([r[0] for r in requests], ['coins/markets', 'global'])
            self.assertEqual(requests[0][1]['page'], 1)
            clock[0] += 299
            b.build()
            self.assertEqual(len(requests), 2)
            clock[0] += 1
            b.build()
            self.assertEqual([r[0] for r in requests], ['coins/markets', 'global', 'coins/markets'])
            clock[0] += 3300
            b.build()
            self.assertEqual([r[0] for r in requests], ['coins/markets', 'global', 'coins/markets', 'coins/markets', 'global'])
