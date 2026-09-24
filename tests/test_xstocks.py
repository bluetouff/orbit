"""Synthetic boundary fixtures, never application or preview data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_builder import b, v, coin


class XstocksTests(unittest.TestCase):
    def test_reads_only_kraken_cache_without_any_network_or_old_coingecko_fallback(self):
        raw = {**coin('apple-xstock'), 'asset_type': 'xstock', 'price_source': 'kraken', 'market_pair': 'AAPLxUSD', 'fetched_at': b.utc_now(), 'market_cap': None, 'total_volume': None}
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'OUT_DIR', directory), patch.object(b, 'cg') as cg, patch.object(b, 'fetch') as fetch:
            coins, _, status = b.get_xstocks({'coins': [{**raw, 'price_source': 'coingecko'}]})
            self.assertEqual(coins, []); self.assertFalse(status['ok'])
            cache = Path(directory) / '.kraken-xstocks.json'
            cache.write_text(json.dumps({'coins': [raw], 'status': {'ok': True, 'fetched_at': b.utc_now()}}))
            coins, _, status = b.get_xstocks({})
            self.assertEqual(len(coins), 1); self.assertEqual(coins[0]['price_source'], 'kraken')
            self.assertTrue(status['ok']); self.assertIsNone(coins[0]['market_cap'])
            cg.assert_not_called(); fetch.assert_not_called()
            cache.write_text(json.dumps({'coins': [{**raw, 'last_updated': 'invalid'}], 'status': {'ok': True}}))
            self.assertFalse(b.get_xstocks({})[2]['ok'])

    def test_kraken_cache_cannot_leak_crypto_metrics_or_invalid_trade_dates(self):
        raw = {**coin('apple-xstock', 'aaplx'), 'asset_type': 'xstock', 'price_source': 'kraken', 'market_pair': 'AAPLxUSD', 'fetched_at': b.utc_now(), 'market_cap': 100, 'total_volume': 10, 'ath': 500}
        normalized = b.normalize_coin(raw, {}, True)
        self.assertIsNone(normalized['market_cap']); self.assertIsNone(normalized['total_volume'])
        self.assertNotIn('ath', normalized); self.assertNotIn('spark', normalized)
        for change in ({'current_price': 0}, {'last_updated': '2099-01-01T00:00:00Z'}, {'fetched_at': 'bad'}):
            self.assertIsNone(b.normalize_coin({**raw, **change}, {}, False))
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'orbit.json'
            def validate(c):
                snapshot.write_text(json.dumps({'snapshot': b.utc_now(), 'count': 1, 'coins': [c]}))
                return v.main(str(snapshot))
            self.assertEqual(validate(normalized), 0)
            for change in ({'market_cap': 5}, {'price_change_percentage_24h_in_currency': 2}, {'fetched_at': None}, {'market_pair': '../invalid'}, {'current_price': 0}):
                self.assertEqual(validate({**normalized, **change}), 1)

    def test_identity_is_not_truncated_and_logo_requests_stay_allowlisted(self):
        for cid in ["../secret", "bad\n", "x" * 81, ["test"], "test/../key"]:
            self.assertIsNone(b.normalize_coin({**coin(), "id": cid}, {}, True))
        urls = ["http://assets.coingecko.com/a.png", "https://assets.coingecko.com.evil.invalid/a.png", "https://user:pass@assets.coingecko.com/a.png", "https://assets.coingecko.com:444/a.png", "https://127.0.0.1/a.png"]
        with tempfile.TemporaryDirectory() as directory, patch.object(b, "LOGO_DIR", directory), patch.object(b, "fetch") as fetch:
            for url in urls:
                self.assertFalse(b.cache_logo({"id": "test-xstock", "image": url}))
            fetch.assert_not_called()

    def test_build_deduplicates_feeds_and_caps_failed_logo_attempts(self):
        stocks = [{**coin("test-xstock"), "asset_type": "xstock"}]
        markets = [coin("test-xstock"), coin("undiscovered-xstock"), coin("bitcoin"), coin("ethereum")]
        with tempfile.TemporaryDirectory() as directory, patch.object(b, "OUT_DIR", directory), patch.object(b, "LOGO_DIR", directory), patch.object(b, "LOGO_FETCH_PER_RUN", 2), patch.object(b, "load_previous", return_value={}), patch.object(b, "get_markets", return_value=markets), patch.object(b, "get_xstocks", return_value=(stocks, [coin("test-xstock")], {"ok": True, "fetched_at": b.utc_now()})), patch.object(b, "get_social", return_value=({}, {"ok": False})), patch.object(b, "get_macro", return_value=(None, {"ok": False})), patch.object(b, "cg", return_value={}), patch.object(b, "cache_logo", return_value=False) as logos:
            b.build()
            data = json.loads((Path(directory) / "orbit.json").read_text())
        self.assertEqual(logos.call_count, 2)
        self.assertEqual([c["id"] for c in data["coins"]], ["bitcoin", "ethereum", "test-xstock"])
        self.assertEqual(data["status"]["coingecko_markets"]["valid"], 2)

    def test_coingecko_keys_use_headers_and_never_query_strings(self):
        for tier in ("demo", "pro"):
            with patch.object(b, "CG_TIER", tier), patch.object(b, "CG_KEY", "synthetic-test-only"), patch.object(b, "fetch", return_value=[]) as request:
                b.cg("coins/markets", {"page": 1})
            self.assertNotIn("synthetic-test-only", request.call_args.args[0])
            self.assertEqual(request.call_args.kwargs["headers"], {f"x-cg-{tier}-api-key": "synthetic-test-only"})

    def test_redirects_cannot_escape_provider_allowlists(self):
        self.assertIsNone(b._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://127.0.0.1/private"))
