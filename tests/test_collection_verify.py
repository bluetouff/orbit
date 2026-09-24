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
    return {'snapshot': stamp, 'status': {key: {'ok': True, 'fetched_at': stamp} for key in ('coingecko_markets', 'kraken_xstocks')},
            'coins': [{'asset_type': 'xstock', 'last_updated': stamp, 'fetched_at': stamp, 'price_source': 'kraken'}]}


class VerifyTests(unittest.TestCase):
    def test_existing_xstocks_interval_is_respected_but_cannot_disable_expiry(self):
        data = snapshot()
        data['status']['kraken_xstocks'].update(ttl=180, fetched_at=snapshot(-240)['snapshot'])
        verify.inspect(data, NOW)
        data['status']['kraken_xstocks'].update(ttl=86400, fetched_at=snapshot(-2101)['snapshot'])
        with self.assertRaises(verify.CollectionError): verify.inspect(data, NOW)

    def test_recent_file_cannot_hide_failed_or_old_sources_or_undated_quotes(self):
        verify.inspect(snapshot(), NOW)
        for change in ('failed', 'stale', 'unknown', 'old_check', 'future_quote'):
            data = snapshot()
            if change == 'failed': data['status']['kraken_xstocks']['ok'] = False
            if change == 'stale': data['status']['coingecko_markets']['fetched_at'] = snapshot(-181)['snapshot']
            if change == 'unknown': data['coins'][0].pop('last_updated')
            if change == 'old_check': data['coins'][0]['fetched_at'] = snapshot(-2401)['snapshot']
            if change == 'future_quote': data['coins'][0]['last_updated'] = snapshot(61)['snapshot']
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

    def test_old_trade_is_not_relabelled_as_a_failed_collection(self):
        data = snapshot()
        data['coins'][0]['last_updated'] = snapshot(-86400)['snapshot']
        verify.inspect(data, NOW)

    def test_extended_check_requires_kraken_renewal(self):
        clock = [NOW]
        def sleep(seconds): clock[0] += seconds
        def response(path):
            data = snapshot(clock[0] - NOW)
            data['status']['kraken_xstocks']['fetched_at'] = snapshot()['snapshot']
            return json.dumps(data).encode(), {}
        with patch.object(verify.time, 'time', side_effect=lambda: clock[0]), patch.object(verify.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(verify.time, 'sleep', side_effect=sleep), patch.object(verify, 'public', side_effect=response):
            with self.assertRaisesRegex(verify.CollectionError, 'Required collection renewals'):
                verify.verify(timeout=60, interval=30, kraken_renewal=True)

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
