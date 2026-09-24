"""Synthetic boundary fixtures, never application or preview data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_builder import b, v, coin


class ProviderBoundaryTests(unittest.TestCase):
    def test_tokens_are_rejected_even_when_legacy_metadata_is_incomplete(self):
        variants = [{'asset_type': 'xstock'}, {'price_source': 'kraken'},
                    {'id': 'apple-xstock'}, {'name': 'Apple xStock'}]
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'orbit.json'
            for change in variants:
                raw = {**coin(), **change}
                self.assertIsNone(b.normalize_coin(raw, {}, False))
                snapshot.write_text(json.dumps({'snapshot': b.utc_now(), 'count': 1, 'coins': [raw]}))
                self.assertEqual(v.main(str(snapshot)), 1)

    def test_identity_is_not_truncated_and_logo_requests_stay_allowlisted(self):
        for cid in ["../secret", "bad\n", "x" * 81, ["test"], "test/../key"]:
            self.assertIsNone(b.normalize_coin({**coin(), "id": cid}, {}, True))
        urls = ["http://assets.coingecko.com/a.png", "https://assets.coingecko.com.evil.invalid/a.png", "https://user:pass@assets.coingecko.com/a.png", "https://assets.coingecko.com:444/a.png", "https://127.0.0.1/a.png"]
        with tempfile.TemporaryDirectory() as directory, patch.object(b, "LOGO_DIR", directory), patch.object(b, "fetch") as fetch:
            for url in urls:
                self.assertFalse(b.cache_logo({"id": "test-xstock", "image": url}))
            fetch.assert_not_called()

    def test_build_deduplicates_feeds_and_caps_failed_logo_attempts(self):
        markets = [coin("test-xstock"), coin("undiscovered-xstock"), coin("bitcoin"), coin("ethereum")]
        with tempfile.TemporaryDirectory() as directory, patch.object(b, "OUT_DIR", directory), patch.object(b, "LOGO_DIR", directory), patch.object(b, "LOGO_FETCH_PER_RUN", 2), patch.object(b, "load_previous", return_value={}), patch.object(b, "get_markets", return_value=markets), patch.object(b, "get_social", return_value=({}, {"ok": False})), patch.object(b, "get_macro", return_value=(None, {"ok": False})), patch.object(b, "cg", return_value={}), patch.object(b, "cache_logo", return_value=False) as logos:
            b.build()
            data = json.loads((Path(directory) / "orbit.json").read_text())
        self.assertEqual(logos.call_count, 2)
        self.assertEqual([c["id"] for c in data["coins"]], ["bitcoin", "ethereum"])
        self.assertEqual(data["status"]["coingecko_markets"]["valid"], 2)

    def test_coingecko_keys_use_headers_and_never_query_strings(self):
        for tier in ("demo", "pro"):
            with patch.object(b, "CG_TIER", tier), patch.object(b, "CG_KEY", "synthetic-test-only"), patch.object(b, "fetch", return_value=[]) as request:
                b.cg("coins/markets", {"page": 1})
            self.assertNotIn("synthetic-test-only", request.call_args.args[0])
            self.assertEqual(request.call_args.kwargs["headers"], {f"x-cg-{tier}-api-key": "synthetic-test-only"})

    def test_redirects_cannot_escape_provider_allowlists(self):
        self.assertIsNone(b._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://127.0.0.1/private"))
