"""Synthetic boundary fixtures, never application or preview data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_builder import b, v, coin


class XstocksTests(unittest.TestCase):
    def test_category_is_bounded_and_duplicates_and_invalid_data_are_removed(self):
        rows = [coin("test-xstock"), coin("test-xstock"), {**coin("../invalid"), "image": "https://evil.invalid/"}, None]
        with patch.object(b, "cg", return_value=rows) as request:
            coins, logos, status = b.get_xstocks({})
        self.assertEqual(len(coins), 1)
        self.assertEqual(coins[0]["asset_type"], "xstock")
        self.assertTrue(status["ok"])
        self.assertEqual(status["invalid"], 3)
        self.assertEqual(request.call_args.args[1]["category"], "xstocks-ecosystem")
        self.assertEqual(request.call_args.args[1]["per_page"], 250)
        self.assertEqual(status["fetched_at"], status["last_success_at"])

    def test_cache_keeps_observation_and_collection_time_without_requests(self):
        stamp = b.utc_now()
        old = {**coin("test-xstock"), "asset_type": "xstock"}
        previous = {"coins": [old], "status": {"coingecko_xstocks": {"ok": True, "fetched_at": stamp, "last_success_at": stamp}}}
        with patch.object(b, "cg") as request:
            coins, logos, status = b.get_xstocks(previous)
        request.assert_not_called()
        self.assertEqual(coins, [old])
        self.assertEqual(logos, [])
        self.assertEqual(status["last_success_at"], stamp)
        self.assertEqual(coins[0]["last_updated"], old["last_updated"])

    def test_failure_keeps_real_old_quotes_and_never_exposes_error_text(self):
        old = {**coin("test-xstock"), "asset_type": "xstock"}
        previous = {"coins": [old], "status": {"coingecko_xstocks": {"ok": True, "fetched_at": "2026-01-01T00:00:00Z"}}}
        with patch.object(b, "cg", side_effect=ValueError("synthetic-secret-do-not-expose")):
            coins, _, status = b.get_xstocks(previous)
        self.assertEqual(coins, [old])
        self.assertFalse(status["ok"])
        self.assertEqual(status["last_success_at"], "2026-01-01T00:00:00Z")
        self.assertNotIn("synthetic-secret", json.dumps(status))
        with patch.object(b, "cg") as request:
            _, _, retry = b.get_xstocks({"coins": coins, "status": {"coingecko_xstocks": status}})
        request.assert_not_called()
        self.assertFalse(retry["ok"])

    def test_invalid_payloads_fail_closed(self):
        for response in [None, {}, {"error": "bad"}, [], [coin()] * 251, [None], [{**coin(), "current_price": None}]]:
            with self.subTest(response=type(response).__name__), patch.object(b, "cg", return_value=response):
                coins, _, status = b.get_xstocks({})
                self.assertEqual(coins, [])
                self.assertFalse(status["ok"])

    def test_unknown_cap_and_volume_are_null_and_social_is_not_matched(self):
        raw = {**coin("test-xstock"), "asset_type": "xstock", "market_cap": None, "total_volume": None}
        normalized = b.normalize_coin(raw, {"TST": {"galaxy_score": 95}}, True)
        self.assertIsNone(normalized["market_cap"])
        self.assertIsNone(normalized["total_volume"])
        self.assertNotIn("galaxy_score", normalized)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "snapshot.json"
            file.write_text(json.dumps({"snapshot": b.utc_now(), "count": 1, "coins": [normalized]}))
            self.assertEqual(v.main(file), 0)

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
                b.cg("coins/markets", {"category": "xstocks-ecosystem"})
            self.assertNotIn("synthetic-test-only", request.call_args.args[0])
            self.assertEqual(request.call_args.kwargs["headers"], {f"x-cg-{tier}-api-key": "synthetic-test-only"})

    def test_redirects_cannot_escape_provider_allowlists(self):
        self.assertIsNone(b._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://127.0.0.1/private"))
