import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts = Path(__file__).parents[1] / 'scripts'
with patch.object(sys, 'path', [str(scripts), *sys.path]):
    spec = importlib.util.spec_from_file_location('collection_verify', scripts / 'verify_collection.py')
    verify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify)

NOW = 1767225600


def snapshot(offset=0):
    stamp = verify.dt.datetime.fromtimestamp(NOW + offset, verify.dt.timezone.utc).isoformat()
    return {'snapshot': stamp, 'status': {key: {'ok': True, 'fetched_at': stamp} for key in ('coingecko_markets',)},
            'coins': [{'asset_type': 'crypto', 'last_updated': stamp, 'id': 'bitcoin'}]}


class VerifyTests(unittest.TestCase):
    def test_recent_file_cannot_hide_failed_or_old_sources_or_tokens(self):
        verify.inspect(snapshot(), NOW)
        for change in ('failed', 'stale', 'unknown', 'future', 'token', 'old_source'):
            data = snapshot()
            if change == 'failed': data['status']['coingecko_markets']['ok'] = False
            if change == 'stale': data['status']['coingecko_markets']['fetched_at'] = snapshot(-181)['snapshot']
            if change == 'unknown': data['status']['coingecko_markets'].pop('fetched_at')
            if change == 'future': data['status']['coingecko_markets']['fetched_at'] = snapshot(61)['snapshot']
            if change == 'token': data['coins'][0]['asset_type'] = 'xstock'
            if change == 'old_source': data['status']['kraken_xstocks'] = {'ok': True}
            with self.subTest(change=change), self.assertRaises(verify.CollectionError):
                verify.inspect(data, NOW)

    def test_requires_two_advances_of_each_source_not_just_new_file_dates(self):
        clock = [NOW]
        unchanged = snapshot()
        def sleep(seconds): clock[0] += seconds
        def response(path):
            data = copy.deepcopy(unchanged)
            data['snapshot'] = snapshot(clock[0] - NOW)['snapshot']
            return json.dumps(data).encode(), {}
        with patch.object(verify.time, 'time', side_effect=lambda: clock[0]), patch.object(verify.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(verify.time, 'sleep', side_effect=sleep), patch.object(verify, 'public', side_effect=response):
            with self.assertRaisesRegex(verify.CollectionError, 'Required collection renewals'):
                verify.verify(timeout=60, interval=30)

    def test_two_real_source_advances_pass_and_regressions_fail(self):
        clock = [NOW]
        def sleep(seconds): clock[0] += seconds
        for offsets, fail in [([0, 30, 60], False), ([0, 30, 0], True)]:
            clock[0] = NOW
            responses = [(json.dumps(snapshot(n)).encode(), {}) for n in offsets]
            with patch.object(verify.time, 'time', side_effect=lambda: clock[0]), patch.object(verify.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(verify.time, 'sleep', side_effect=sleep), patch.object(verify, 'public', side_effect=responses):
                if fail:
                    with self.assertRaisesRegex(verify.CollectionError, 'regressed'): verify.verify()
                else: verify.verify()
