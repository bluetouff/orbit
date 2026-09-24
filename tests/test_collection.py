"""Deterministic collection cycles, with no provider or real credential access."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from test_builder import b, coin


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.clock = [1767225600]
        for name, value in [('OUT_DIR', str(self.path)), ('LOGO_DIR', str(self.path)), ('LOGO_FETCH_PER_RUN', 0), ('MARKETS_REFRESH_SEC', 60), ('XSTOCKS_REFRESH_SEC', 60), ('_CG_LAST_REQUEST', None)]:
            context = patch.object(b, name, value)
            context.start(); self.addCleanup(context.stop)
        for context in [patch.object(b.time, 'time', side_effect=lambda: self.clock[0]), patch.object(b.time, 'sleep'), patch.object(b, 'utc_now', side_effect=lambda: b.datetime.datetime.fromtimestamp(self.clock[0], b.datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')), patch.object(b, 'get_social', return_value=({}, {'ok': False})), patch.object(b, 'get_macro', return_value=({'us10y': {'value': 1, 'date': '2026-01-01'}}, {'ok': True, 'fetched_at': '2026-01-01T00:00:00Z'}))]:
            context.start(); self.addCleanup(context.stop)
        self.crypto = coin('bitcoin', 'btc')
        self.stock = coin('apple-xstock', 'aaplx')

    def read(self):
        return json.loads((self.path / 'orbit.json').read_text())

    def respond(self, path, params):
        if path == 'global': return {'data': {'total_market_cap': {'usd': 1}}}
        return [self.stock] if params.get('category') else [self.crypto]

    def test_cached_crypto_and_xstocks_preserve_dates_and_reduce_calls(self):
        with patch.object(b, 'cg', side_effect=self.respond) as request:
            b.build()
            first = self.read()
            self.clock[0] += 35
            b.build()
            second = self.read()
            self.assertEqual(request.call_count, 3)
            self.assertNotEqual(first['snapshot'], second['snapshot'])
            self.assertEqual(first['coins'], second['coins'])
            for key in ('coingecko_markets', 'coingecko_xstocks'):
                self.assertTrue(second['status'][key]['reused'])
                self.assertEqual(first['status'][key]['fetched_at'], second['status'][key]['fetched_at'])
            self.clock[0] += 35
            b.build()
            third = self.read()
            self.assertEqual(request.call_count, 5)
            self.assertNotEqual(second['status']['coingecko_markets']['fetched_at'], third['status']['coingecko_markets']['fetched_at'])
            self.assertNotEqual(second['status']['coingecko_xstocks']['fetched_at'], third['status']['coingecko_xstocks']['fetched_at'])

    def test_crypto_error_does_not_stop_xstocks_or_macro_and_recovers(self):
        with patch.object(b, 'cg', side_effect=self.respond): b.build()
        old = self.read()
        self.clock[0] += 70
        def failure(path, params):
            if path == 'coins/markets' and not params.get('category'):
                raise urllib.error.HTTPError('https://example.invalid/private', 503, 'sensitive response', {}, None)
            return self.respond(path, params)
        with patch.object(b, 'cg', side_effect=failure): b.build()
        data = self.read()
        status = data['status']['coingecko_markets']
        self.assertFalse(status['ok']); self.assertEqual(status['http_status'], 503)
        self.assertEqual(status['fetched_at'], old['status']['coingecko_markets']['fetched_at'])
        self.assertEqual(data['coins'][0], old['coins'][0])
        self.assertTrue(data['status']['coingecko_xstocks']['ok'])
        self.assertNotEqual(data['status']['coingecko_xstocks']['fetched_at'], old['status']['coingecko_xstocks']['fetched_at'])
        self.assertTrue(data['status']['fred']['ok'])
        self.assertNotIn('sensitive', json.dumps(data)); self.assertNotIn('private', json.dumps(data))
        self.clock[0] += 70
        with patch.object(b, 'cg', side_effect=self.respond): b.build()
        recovered = self.read()['status']['coingecko_markets']
        self.assertTrue(recovered['ok']); self.assertNotIn('error', recovered)

    def test_partial_pagination_never_replaces_complete_previous_crypto(self):
        with patch.object(b, 'cg', side_effect=self.respond): b.build()
        old = self.read(); self.clock[0] += 70
        def failure(path, params):
            if params.get('category') or path == 'global': return self.respond(path, params)
            if params['page'] == 1: return [coin('test-' + str(i)) for i in range(250)]
            raise TimeoutError('sensitive')
        with patch.object(b, 'TOP', 500), patch.object(b, 'cg', side_effect=failure): b.build()
        self.assertEqual(self.read()['coins'][0], old['coins'][0])
        self.assertFalse(self.read()['status']['coingecko_markets']['ok'])

    def test_cooldown_is_shared_but_macro_still_publishes(self):
        with patch.object(b, 'cg', side_effect=self.respond): b.build()
        old = self.read(); self.clock[0] += 3700
        def limit(*args, **kwargs):
            raise urllib.error.HTTPError('https://example.invalid', 429, 'ignored', {'Retry-After': '300'}, None)
        with patch.object(b, 'fetch', side_effect=limit) as request:
            b.build(); self.clock[0] += 70; b.build()
            request.assert_called_once()
        data = self.read()
        for key in ('coingecko_markets', 'coingecko_xstocks'):
            self.assertFalse(data['status'][key]['ok'])
            self.assertEqual(data['status'][key]['last_success_at'], old['status'][key]['fetched_at'])
            self.assertIn('retry_at', data['status'][key])
        self.assertTrue(data['status']['fred']['ok'])
        self.assertEqual(data['coins'], old['coins'])

    def test_transport_spaces_requests_without_retry(self):
        with patch.object(b.time, 'monotonic', side_effect=[10, 10.5, 12]), patch.object(b.time, 'sleep') as sleep, patch.object(b, 'fetch', return_value=[]) as request:
            b.cg('coins/markets', {'page': 1}); b.cg('coins/markets', {'page': 2})
        sleep.assert_called_once_with(1.5)
        self.assertEqual(request.call_count, 2)

    def test_crypto_unknown_price_times_are_not_invented_by_cache(self):
        self.crypto.pop('last_updated')
        with patch.object(b, 'cg', side_effect=self.respond):
            b.build(); self.clock[0] += 35; b.build()
        self.assertNotIn('last_updated', self.read()['coins'][0])

if __name__ == '__main__':
    unittest.main()
