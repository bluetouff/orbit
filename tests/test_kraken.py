import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('kraken', Path(__file__).parents[1] / 'collect_xstocks.py')
k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
NOW = 1767225600
PAIR = {'aclass_base': 'tokenized_asset', 'quote': 'ZUSD', 'base': 'AAPLx', 'altname': 'AAPLxUSD'}
TRADE = {'AAPLxUSD': [['10.25', '1', NOW, 'b', 'l', '', 123]], 'last': str(NOW)}

class KrakenTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for context in (patch.object(k, 'OUT_DIR', self.root), patch.object(k, '_last_request', None), patch.object(k.time, 'time', return_value=NOW)):
            context.start(); self.addCleanup(context.stop)

    def test_catalog_deduplicates_aliases_and_excludes_non_usd_and_crypto(self):
        pairs = {'internal': PAIR, 'alias': PAIR, 'btc': {**PAIR, 'aclass_base': 'currency'}, 'eur': {**PAIR, 'quote': 'ZEUR'}}
        self.assertEqual(k.catalog(pairs), [('AAPLxUSD', 'AAPLx')])
        for base in ['../AAPLx', 'AAPLx?secret=', 'AAPLx\n']:
            with self.assertRaises(ValueError): k.catalog({'bad': {**PAIR, 'base': base}})

    def test_trades_preserve_real_dates_and_do_not_create_returns_or_capitalization(self):
        c = k.trade_coin('AAPLxUSD', 'AAPLx', TRADE, {'aaplx': ('apple-xstock', 'Apple xStock')}, NOW+900)
        self.assertEqual(c['id'], 'apple-xstock'); self.assertEqual(c['current_price'], 10.25)
        self.assertEqual(c['last_updated'], '2026-01-01T00:00:00+00:00')
        self.assertIsNone(c['market_cap']); self.assertIsNone(c['total_volume'])
        self.assertFalse(any(key.startswith('price_change') for key in c))
        self.assertIsNone(k.trade_coin('AAPLxUSD', 'AAPLx', {'AAPLxUSD': [], 'last': '0'}, {}, NOW))

    def test_bad_prices_and_future_trades_fail_closed(self):
        for price, observed in [('NaN', NOW), ('inf', NOW), ('-1', NOW), (True, NOW), ('1', NOW+61), ('1', True), ('1', float('nan'))]:
            with self.subTest(price=price, observed=observed), self.assertRaises((ValueError, TypeError)):
                k.trade_coin('AAPLxUSD', 'AAPLx', {'pair': [[price, '1', observed]]}, {}, NOW)

    def test_identity_migration_does_not_reuse_metrics_or_ambiguous_symbols(self):
        old = {'coins': [{'id': 'apple-xstock', 'asset_type': 'xstock', 'symbol': 'aaplx', 'name': 'Apple xStock', 'current_price': 999}]}
        self.assertEqual(k.identities(old), {'aaplx': ('apple-xstock', 'Apple xStock')})
        old['coins'].append({**old['coins'][0], 'id': 'other-xstock'})
        self.assertEqual(k.identities(old), {})

    def test_complete_cycle_uses_only_public_catalog_and_trades_and_private_atomic_cache(self):
        with patch.object(k, 'request', side_effect=[{'a': PAIR}, TRADE]) as request:
            self.assertTrue(k.collect())
        data = k.read_json(self.root / k.CACHE_NAME)
        self.assertTrue(data['status']['ok']); self.assertEqual(data['status']['ttl'], 1800)
        self.assertEqual([call.args[0] for call in request.call_args_list], ['AssetPairs', 'Trades'])
        self.assertEqual((self.root / k.CACHE_NAME).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / 'orbit.json').exists())

    def test_failed_cycle_retains_previous_quotes_and_dates_without_external_error_text(self):
        with patch.object(k, 'request', side_effect=[{'a': PAIR}, TRADE]): self.assertTrue(k.collect())
        old = k.read_json(self.root / k.CACHE_NAME)
        error = urllib.error.HTTPError('https://example.invalid/private', 429, 'sensitive-test-text', {'Retry-After': '7200'}, None)
        with patch.object(k, 'request', side_effect=error): self.assertFalse(k.collect())
        data = k.read_json(self.root / k.CACHE_NAME)
        self.assertEqual(data['coins'], old['coins'])
        self.assertEqual(data['status']['last_success_at'], old['status']['last_success_at'])
        self.assertFalse(data['status']['ok']); self.assertNotIn('sensitive', json.dumps(data)); self.assertNotIn('private', json.dumps(data))
        with patch.object(k, 'request') as request:
            self.assertFalse(k.collect()); request.assert_not_called()

    def test_timer_activation_skips_only_a_just_completed_warmup(self):
        stamp = dt.datetime.fromtimestamp(NOW, dt.timezone.utc).isoformat()
        k.write_cache({'coins': [], 'status': {'ok': True, 'fetched_at': stamp}})
        with patch.object(k, 'request') as request:
            self.assertTrue(k.collect()); request.assert_not_called()
        with patch.object(k.time, 'time', return_value=NOW+1800), patch.object(k, 'request', side_effect=[{'a': PAIR}, TRADE]) as request:
            self.assertTrue(k.collect()); self.assertEqual(request.call_count, 2)

    def test_symlinks_size_limits_and_redirects_are_rejected(self):
        file = self.root / 'data'; file.write_text('{}')
        link = self.root / 'link'; link.symlink_to(file)
        with self.assertRaises(OSError): k.read_json(link)
        with patch.object(k, 'MAX_BYTES', 1):
            with self.assertRaises(ValueError): k.read_json(file)
        self.assertIsNone(k.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private'))

    def test_request_is_paced_bounded_and_sends_no_authentication(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"error":[],"result":{}}'
        with patch.object(k.OPENER, 'open', return_value=Response()) as opened, patch.object(k.time, 'monotonic', side_effect=[10, 10.5, 11.1]), patch.object(k.time, 'sleep') as sleep:
            k.request('Trades', {'pair':'AAPLxUSD'}); k.request('Trades', {'pair':'TSLAxUSD'})
        self.assertAlmostEqual(sleep.call_args.args[0], .6)
        self.assertEqual(opened.call_args.kwargs['timeout'], 8)
        self.assertEqual(set(opened.call_args.args[0].headers), {'Accept', 'User-agent'})
        with self.assertRaises(ValueError): k.request('../private/Balance', {})

if __name__ == '__main__': unittest.main()
