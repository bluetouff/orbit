"""Isolated transport fixtures only; never real credentials or market data."""
import datetime as dt
from email.utils import format_datetime
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

from test_builder import b, coin


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        context = patch.object(b, 'OUT_DIR', str(self.directory))
        context.start()
        self.addCleanup(context.stop)
        for name, value in [('_CG_LAST_REQUEST', None)]:
            context = patch.object(b, name, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(b.time, 'sleep')
        context.start()
        self.addCleanup(context.stop)

    def limited(self, header=None):
        return urllib.error.HTTPError('https://api.coingecko.com/api/v3/coins/markets', 429, 'Too Many Requests', {'Retry-After': header} if header is not None else {}, None)

    def test_retry_after_seconds_and_http_dates_never_shorten_fallback(self):
        now = 1700000000
        self.assertEqual(b.retry_delay('300', 1, now), 300)
        header = format_datetime(dt.datetime.fromtimestamp(now + 900, dt.timezone.utc), usegmt=True)
        self.assertEqual(b.retry_delay(header, 1, now), 900)
        for invalid in [None, '', '0', '-1', '1.5', 'NaN', 'Infinity', '<invalid>', 'x' * 129]:
            self.assertEqual(b.retry_delay(invalid, 1, now), 120)
        self.assertEqual(b.retry_delay(format_datetime(dt.datetime.fromtimestamp(now - 10, dt.timezone.utc), usegmt=True), 1, now), 120)
        self.assertEqual(b.retry_delay('9' * 100, 1, now), 253402300799 - now)
        self.assertEqual([b.retry_delay(None, n, now) for n in range(1, 7)], [120, 240, 480, 960, 1800, 1800])

    def test_429_persists_only_private_numeric_state_and_redacts_error(self):
        with patch.object(b.time, 'time', return_value=1000.25), patch.object(b, 'fetch', side_effect=self.limited('180')), patch.object(b, 'CG_KEY', 'synthetic-test-only'):
            with self.assertRaises(b.CoinGeckoCooldown) as caught:
                b.cg('coins/markets', {})
        state = self.directory / '.coingecko-rate-limit.json'
        self.assertEqual(json.loads(state.read_text()), {'retry_at': 1181, 'failures': 1})
        self.assertEqual(os.stat(state).st_mode & 0o777, 0o600)
        self.assertEqual(str(caught.exception), 'CoinGecko requests deferred')
        self.assertNotIn('synthetic-test-only', state.read_text())
        self.assertNotIn('https', state.read_text())

    def test_cooldown_survives_a_new_invocation_and_blocks_all_coingecko_endpoints(self):
        with patch.object(b.time, 'time', return_value=1000), patch.object(b, 'fetch', side_effect=self.limited()):
            with self.assertRaises(b.CoinGeckoCooldown):
                b.cg('coins/markets', {})
        # No in-memory state is reused: every invocation rereads the private file.
        for endpoint in ('coins/markets', 'global'):
            with patch.object(b.time, 'time', return_value=1119), patch.object(b, 'fetch') as request:
                with self.assertRaises(b.CoinGeckoCooldown):
                    b.cg(endpoint, {})
                request.assert_not_called()
        with patch.object(b.time, 'time', return_value=1120), patch.object(b, 'fetch', return_value=[]) as request:
            self.assertEqual(b.cg('coins/markets', {}), [])
            request.assert_called_once()

    def test_a_successful_page_does_not_reset_repeated_429_backoff(self):
        with patch.object(b.time, 'time', return_value=1000), patch.object(b, 'fetch', side_effect=self.limited()):
            with self.assertRaises(b.CoinGeckoCooldown):
                b.cg('coins/markets', {'page': 1})
        with patch.object(b.time, 'time', return_value=1120), patch.object(b, 'fetch', side_effect=[[], self.limited()]):
            b.cg('coins/markets', {'page': 1})
            with self.assertRaises(b.CoinGeckoCooldown):
                b.cg('coins/markets', {'page': 2})
        self.assertEqual(b.read_rate_limit(), {'retry_at': 1360, 'failures': 2})

    def test_non_429_errors_are_not_retried_or_classified_as_cooldown(self):
        error = urllib.error.HTTPError('https://api.coingecko.com', 401, 'Unauthorized', {}, None)
        self.addCleanup(error.close)
        with patch.object(b, 'fetch', side_effect=error) as request:
            with self.assertRaises(urllib.error.HTTPError):
                b.cg('coins/markets', {})
            request.assert_called_once()
        self.assertFalse(Path(b.rate_limit_path()).exists())

    def test_failed_market_collection_publishes_failure_without_redating_quotes(self):
        snapshot = self.directory / 'orbit.json'
        original = json.dumps({'snapshot': '2020-01-01T00:00:00Z', 'coins': [coin()], 'status': {}}).encode()
        snapshot.write_bytes(original)
        with patch.object(b, 'LOGO_DIR', str(self.directory / 'logos')), patch.object(b, 'get_social', return_value=({}, {'ok': False})), patch.object(b, 'get_macro', return_value=(None, {'ok': False})), patch.object(b, 'fetch', side_effect=self.limited()) as request:
            b.build()
            b.build()
            request.assert_called_once()
            data = json.loads(snapshot.read_text())
            self.assertEqual(data['coins'][0]['last_updated'], coin()['last_updated'])
            self.assertEqual(data['coins'][0]['current_price'], coin()['current_price'])
            self.assertFalse(data['status']['coingecko_markets']['ok'])
            self.assertIsNone(data['status']['coingecko_markets']['fetched_at'])
            self.assertIn('retry_at', data['status']['coingecko_markets'])

    def test_category_rate_limit_preserves_original_quotes_and_blocks_global_call(self):
        old = {**coin('test-xstock'), 'asset_type': 'xstock'}
        previous = {'coins': [old], 'status': {'coingecko_xstocks': {'ok': True, 'fetched_at': '2020-01-01T00:00:00Z'}}}
        with patch.object(b, 'fetch', side_effect=self.limited('300')) as request:
            coins, _, status = b.get_xstocks(previous)
            self.assertEqual(coins, [old])
            self.assertFalse(status['ok'])
            self.assertEqual(status['last_success_at'], '2020-01-01T00:00:00Z')
            with self.assertRaises(b.CoinGeckoCooldown):
                b.cg('global', {})
            request.assert_called_once()

    def test_invalid_and_symlinked_transport_state_fail_before_network(self):
        file = Path(b.rate_limit_path())
        invalid = ['[]', '{}', '{bad', 'x' * 4097, json.dumps({'retry_at': True, 'failures': 1}), json.dumps({'retry_at': 1, 'failures': 100}), json.dumps({'retry_at': -1, 'failures': 0})]
        for text in invalid:
            file.write_text(text)
            with patch.object(b, 'fetch') as request:
                with self.assertRaises(ValueError):
                    b.cg('global', {})
                request.assert_not_called()
        file.unlink()
        target = self.directory / 'untouched'
        target.write_text('untouched')
        file.symlink_to(target)
        with patch.object(b, 'fetch') as request:
            with self.assertRaises(OSError):
                b.cg('global', {})
            request.assert_not_called()
        self.assertEqual(target.read_text(), 'untouched')

    def test_completed_recovery_resets_backoff(self):
        Path(b.rate_limit_path()).write_text(json.dumps({'retry_at': 1000, 'failures': 3}))
        with patch.object(b, 'LOGO_DIR', str(self.directory)), patch.object(b, 'load_previous', return_value={}), patch.object(b, 'get_markets', return_value=[coin()]), patch.object(b, 'get_xstocks', return_value=([], [], {'ok': True})), patch.object(b, 'get_social', return_value=({}, {'ok': False})), patch.object(b, 'get_macro', return_value=(None, {'ok': False})), patch.object(b, 'cg', return_value={'data': {'test': 1}}), patch.object(b, 'cache_logo', return_value=False):
            b.build()
        self.assertFalse(Path(b.rate_limit_path()).exists())

    def test_service_invocations_publish_cooldown_without_refetching_or_redating(self):
        snapshot = self.directory / 'orbit.json'
        original = json.dumps({'snapshot': '2020-01-01T00:00:00Z', 'coins': [coin()]}).encode()
        snapshot.write_bytes(original)
        env = {'PATH': os.environ['PATH'], 'ORBIT_OUT_DIR': str(self.directory), 'ORBIT_LOGO_DIR': str(self.directory / 'logos'), 'CG_API_TIER': 'demo', 'CG_API_KEY': 'synthetic-test-only'}
        builder = str(Path(__file__).parents[1] / 'build_snapshot.py')
        script = """
import runpy, sys, urllib.request, urllib.error
from unittest.mock import patch
failure = urllib.error.HTTPError('https://api.coingecko.com/?test=synthetic-test-only', 429, 'Too Many Requests', {}, None) if sys.argv[2] == 'first' else AssertionError('No request is permitted during cooldown')
with patch.object(urllib.request.OpenerDirector, 'open', side_effect=failure):
    runpy.run_path(sys.argv[1], run_name='__main__')
"""
        for phase in ('first', 'next'):
            result = subprocess.run([sys.executable, '-c', script, builder, phase], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('snapshot degraded', result.stderr)
            self.assertNotIn('synthetic-test-only', result.stderr)
            self.assertNotIn('https:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            data = json.loads(snapshot.read_text())
            self.assertEqual(data['coins'][0]['last_updated'], coin()['last_updated'])
            self.assertEqual(data['status']['coingecko_markets']['error'], 'CoinGeckoCooldown')
            self.assertIsNone(data['status']['coingecko_markets']['fetched_at'])


if __name__ == '__main__':
    unittest.main()
