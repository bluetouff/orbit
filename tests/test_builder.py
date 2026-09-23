import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("builder", Path(__file__).parents[1] / "build_snapshot.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
validator_spec = importlib.util.spec_from_file_location("validator", Path(__file__).parents[1] / "scripts/validate_snapshot.py")
v = importlib.util.module_from_spec(validator_spec)
validator_spec.loader.exec_module(v)


def coin(cid="test", symbol="tst"):
    return {"id": cid, "symbol": symbol, "name": "Synthetic test asset", "current_price": 1,
            "market_cap": 100, "total_volume": 10, "last_updated": "2026-01-01T00:00:00.123Z"}


class BuilderTests(unittest.TestCase):
    def test_price_observation_is_preserved_with_timezone(self):
        c = coin()
        self.assertEqual(b.normalize_coin(c, {}, False)["last_updated"], "2026-01-01T00:00:00.123000+00:00")
        c["last_updated"] = "2026-01-01T00:00:00"
        self.assertNotIn("last_updated", b.normalize_coin(c, {}, False))

    def test_booleans_missing_and_nonfinite_numbers_are_rejected(self):
        for value in [True, False, None, "", float("nan"), float("inf")]:
            self.assertIsNone(b.finite_num(value))
        self.assertEqual(b.finite_num(0), 0)
        self.assertFalse(v.is_num(True))

    def test_snapshot_validator_accepts_observation_timezone(self):
        c = b.normalize_coin(coin(), {}, False)
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "data.json"
            payload = {"snapshot": "2026-01-01T00:00:00Z", "count": 1, "coins": [c]}
            file.write_text(json.dumps(payload))
            self.assertEqual(v.main(file), 0)
            c["last_updated"] = "2026-01-01T00:00:00"
            file.write_text(json.dumps(payload))
            self.assertEqual(v.main(file), 1)

    def test_ambiguous_social_symbols_are_not_matched(self):
        rows = [{"symbol": "TST", "galaxy_score": 10}, {"symbol": "tst", "galaxy_score": 90}]
        with patch.object(b, "LUNAR_KEY", "synthetic-test-only"), patch.object(b, "fetch", return_value={"data": rows}):
            social, _ = b.get_social()
        self.assertEqual(social, {})
        self.assertEqual(b.previous_social({"coins": rows}), {})

    def test_failed_macro_refresh_keeps_original_success_time(self):
        old = "2025-12-31T00:00:00Z"
        previous = {"macro": {"us10y": {"value": 1, "date": "2025-12-30"}}, "status": {"fred": {"ok": True, "fetched_at": old}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(b, "OUT_DIR", tmp), patch.object(b, "LOGO_DIR", tmp), patch.object(b, "load_previous", return_value=previous), patch.object(b, "get_markets", return_value=[coin()]), patch.object(b, "get_social", return_value=({}, {"ok": False})), patch.object(b, "cg", return_value={}), patch.object(b, "get_macro", return_value=(None, {"ok": False, "fetched_at": "2026-01-01T00:00:00Z"})), patch.object(b, "cache_logo", return_value=False):
            b.build()
            data = json.loads((Path(tmp) / "orbit.json").read_text())
        self.assertEqual(data["status"]["fred"]["last_success_at"], old)
        self.assertFalse(data["status"]["fred"]["ok"])
        self.assertEqual(data["macro"], previous["macro"])


if __name__ == "__main__":
    unittest.main()
