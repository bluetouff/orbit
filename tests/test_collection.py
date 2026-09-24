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
        for name, value in [('OUT_DIR', str(self.path)), ('LOGO_DIR', str(self.path)), ('LOGO_FETCH_PER_RUN', 0), ('MARKETS_REFRESH_SEC', 60), ('XSTOCKS_REFRESH_SEC', 1800), ('_CG_LAST_REQUEST', None)]:
            context = patch.object(b, name, value)
            context.start(); self.addCleanup(context.stop)
        for context in [patch.object(b.time, 'time', side_effect=lambda: self.clock[0]), patch.object(b.time, 'sleep'), patch.object(b, 'utc_now', side_effect=lambda: b.datetime.datetime.fromtimestamp(self.clock[0], b.datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')), patch.object(b, 'get_social', return_value=({}, {'ok': False})), patch.object(b, 'get_macro', return_value=({'us10y': {'value': 1, 'date': '2026-01-01'}}, {'ok': True, 'fetched_at': '2026-01-01T00:00:00Z'}))]:
            context.start(); self.addCleanup(context.stop)
        self.crypto = coin('bitcoin', 'btc')
        self.stock = {**coin('apple-xstock', 'aaplx'), 'asset_type': 'xstock', 'price_source': 'kraken', 'market_pair': 'AAPLxUSD', 'fetched_at': b.utc_now()}
        (self.path / '.kraken-xstocks.json').write_text(json.dumps({'coins': [self.stock], 'status': {'ok': True, 'fetched_at': b.utc_now(), 'last_success_at': b.utc_now()}}))

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
            self.assertEqual(request.call_count, 2)
            self.assertNotEqual(first['snapshot'], second['snapshot'])
            self.assertEqual(first['coins'], second['coins'])
            for key in ('coingecko_markets', 'kraken_xstocks'):
                if key == 'coingecko_markets': self.assertTrue(second['status'][key]['reused'])
                self.assertEqual(first['status'][key]['fetched_at'], second['status'][key]['fetched_at'])
            self.clock[0] += 35
            b.build()
            third = self.read()
            self.assertEqual(request.call_count, 3)
            self.assertNotEqual(second['status']['coingecko_markets']['fetched_at'], third['status']['coingecko_markets']['fetched_at'])
            self.assertEqual(second['status']['kraken_xstocks']['fetched_at'], third['status']['kraken_xstocks']['fetched_at'])

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
        self.assertTrue(data['status']['kraken_xstocks']['ok'])
        self.assertEqual(data['status']['kraken_xstocks']['fetched_at'], old['status']['kraken_xstocks']['fetched_at'])
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
        for key in ('coingecko_markets',):
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

    def test_crypto_is_published_before_optional_feeds_without_redating_context(self):
        with patch.object(b, 'cg', side_effect=self.respond): b.build()
        previous = self.read()
        self.clock[0] += 70
        self.crypto['current_price'] = 2
        self.crypto['last_updated'] = b.utc_now()

        def optional_failure(_previous):
            early = self.read()
            self.assertEqual(early['coins'][0]['current_price'], 2)
            self.assertNotEqual(early['status']['coingecko_markets']['fetched_at'],
                                previous['status']['coingecko_markets']['fetched_at'])
            for source in ('kraken_xstocks', 'coingecko_global', 'lunarcrush', 'fred'):
                self.assertEqual(early['status'][source], previous['status'][source])
            self.assertEqual(early['coins'][1], previous['coins'][1])
            # Even an interrupted optional stage leaves the new crypto available.
            raise RuntimeError('isolated test interruption')

        with patch.object(b, 'cg', side_effect=self.respond) as request, patch.object(b, 'get_xstocks', side_effect=optional_failure):
            with self.assertRaisesRegex(RuntimeError, 'isolated test interruption'):
                b.build()
            request.assert_called_once()
        self.assertEqual(self.read()['coins'][0]['current_price'], 2)

    def test_early_publication_rejects_invalid_duplicates_and_tokenized_assets(self):
        rows = [self.crypto, self.crypto, self.stock, {**coin('other'), 'name': 'Other xStock'},
                {**coin('invalid'), 'current_price': None}]
        with patch.object(b, 'get_markets', return_value=rows), patch.object(b, 'get_xstocks', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError): b.build()
        data = self.read()
        self.assertEqual([c['id'] for c in data['coins']], ['bitcoin'])
        self.assertFalse(data['status']['fred']['ok'])

if __name__ == '__main__':
    unittest.main()
