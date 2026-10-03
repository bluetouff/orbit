"""Isolated failure, budget and coverage checks; no provider traffic."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_builder import b, coin
import orbit_health as health

NOW = 1767225601


def universe(count=40):
    return [coin('bitcoin' if i == 0 else f'asset-{i}') for i in range(count)]


class CoverageTests(unittest.TestCase):
    def test_runtime_demo_matches_freshness_floor_and_rejects_truncated_universe(self):
        with patch.object(b, 'PROFILE', 'demo-250-v1'), patch.object(b, 'TOP', 250), patch.object(b.time, 'time', return_value=NOW):
            b.check_market_coverage(universe(40), universe(40))
            b.check_market_coverage(universe(36), universe(40))
            for coins in [universe(1), universe(35), universe(40)[1:], universe(20)*2]:
                with self.assertRaises(b.MarketCoverageError):
                    b.check_market_coverage(coins, universe(40))
            coins = universe()
            for row in coins[:5]: row['last_updated'] = '2025-12-31T00:00:00Z'
            with self.assertRaises(b.MarketCoverageError): b.check_market_coverage(coins, [])
            coins = universe(); coins[0]['last_updated'] = '2026-01-01T00:02:00Z'
            with self.assertRaises(b.MarketCoverageError): b.check_market_coverage(coins, [])

    def test_partial_success_retains_whole_previous_universe_and_its_dates(self):
        previous = {'coins': universe(40), 'status': {'coingecko_markets': {'ok': True, 'fetched_at': '2025-12-31T23:40:00Z', 'policy': 'demo-250-v1'}}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(b, 'OUT_DIR', tmp), patch.object(b, 'LOGO_DIR', tmp), patch.object(b, 'PROFILE', 'demo-250-v1'), patch.object(b, 'TOP', 250), patch.object(b.time, 'time', return_value=NOW), patch.object(b, 'load_previous', return_value=previous), patch.object(b, 'get_markets', return_value=universe(1)), patch.object(b, 'LUNAR_KEY', ''), patch.object(b, 'FRED_KEY', ''), patch.object(b, 'cg', return_value={}):
            b.build()
            data = json.loads((Path(tmp)/'orbit.json').read_text())
        self.assertEqual(len(data['coins']), 40)
        self.assertEqual(data['coins'][0]['last_updated'], previous['coins'][0]['last_updated'])
        self.assertEqual(data['status']['coingecko_markets']['last_success_at'], previous['status']['coingecko_markets']['fetched_at'])
        self.assertFalse(data['status']['coingecko_markets']['ok'])
        self.assertEqual(data['status']['coingecko_markets']['error'], 'MarketCoverageError')

    def test_malformed_social_is_an_isolated_failure(self):
        for payload in [[], None, {'data': None}, {'data':[None]}, {'data':[{'symbol':1}]}]:
            with patch.object(b, 'LUNAR_KEY', 'synthetic-test-only'), patch.object(b, 'fetch', return_value=payload):
                social,status=b.get_social()
            self.assertEqual(social,{})
            self.assertFalse(status['ok'])

    def test_nonfinite_macro_is_unavailable_and_partial_series_not_healthy(self):
        for value in ['NaN','Infinity','-Infinity',True,'1e999','bad']:
            with patch.object(b,'FRED_KEY','synthetic-test-only'),patch.object(b,'fetch',return_value={'observations':[{'date':'2026-01-01','value':value}]}):
                macro,status=b.get_macro()
            self.assertIsNone(macro)
            self.assertFalse(status['ok'])
        with patch.object(b,'FRED_KEY','synthetic-test-only'),patch.object(b,'fetch',side_effect=[{'observations':[{'date':'2026-01-01','value':'1.25'}]},ValueError('isolated')]):
            macro,status=b.get_macro()
        self.assertEqual(macro['us10y']['value'],1.25)
        self.assertFalse(status['ok']);self.assertEqual(status['series'],1)

    def test_invalid_json_never_replaces_last_public_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(b,'OUT_DIR',tmp):
            file=Path(tmp)/'orbit.json';file.write_text('{"previous":true}')
            with self.assertRaises(ValueError):b.publish_snapshot({'macro':{'us10y':{'value':float('nan')}}})
            self.assertEqual(file.read_text(),'{"previous":true}')

    def test_private_health_write_failure_does_not_misreport_publication(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(b,'OUT_DIR',tmp),patch.object(b,'LOGO_DIR',tmp),patch.object(b,'TOP',40),patch.object(b,'load_previous',return_value={}),patch.object(b,'get_markets',return_value=universe()),patch.object(b,'LUNAR_KEY',''),patch.object(b,'FRED_KEY',''),patch.object(b,'cg',return_value={}),patch.object(b.orbit_health,'record',side_effect=OSError('private report')),contextlib.redirect_stderr(io.StringIO()) as output:
            b.build()
            self.assertEqual(len(json.loads((Path(tmp)/'orbit.json').read_text())['coins']),40)
            self.assertIn('health-report-failed',output.getvalue())
            self.assertNotIn('previous snapshot retained',output.getvalue())


class HealthTests(unittest.TestCase):
    def test_projection_uses_actual_reservations_plus_future_schedule_not_fake_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Path(tmp)/'ledger'
            self.assertIsNone(health.budget_projection(ledger,NOW)['calls'])
            ledger.write_text(json.dumps({'month':'2026-01','calls':0}))
            result=health.budget_projection(ledger,NOW)
            self.assertEqual(result['projected_calls'],9672)
            self.assertEqual(result['state'],'low-margin')
            ledger.write_text(json.dumps({'month':'2026-01','calls':10000}))
            self.assertEqual(health.budget_projection(ledger,NOW)['state'],'exhausted')
            for raw in ['{}','{"month":"2026-01","calls":true}','{"month":"2026-02","calls":1}']:
                ledger.write_text(raw)
                self.assertEqual(health.budget_projection(ledger,NOW)['state'],'unknown')

    def test_real_collection_and_quote_age_control_health(self):
        snapshot={'coins':universe(),'status':{'coingecko_markets':{'policy':'demo-250-v1','ok':True,'fetched_at':'2026-01-01T00:00:00Z'}}}
        self.assertEqual(health.assess(snapshot,NOW)['state'],'ok')
        self.assertEqual(health.assess(snapshot,NOW+420)['state'],'critical')
        snapshot['status']['coingecko_markets']['ok']=False
        self.assertIn('market-collection-failed',health.assess(snapshot,NOW)['issues'])

    def test_alerts_on_transitions_and_recovery_only_with_private_file(self):
        snapshot={'coins':universe(),'status':{'coingecko_markets':{'policy':'demo-250-v1','ok':True,'fetched_at':'2026-01-01T00:00:00Z'}}}
        with tempfile.TemporaryDirectory() as tmp,patch.object(health.time,'time',return_value=NOW),contextlib.redirect_stderr(io.StringIO()) as output:
            health.record(snapshot,tmp)
            health.record(snapshot,tmp)
            health.record(snapshot,tmp,failure='collector-failed')
            health.record(snapshot,tmp,failure='collector-failed')
            health.record(snapshot,tmp)
            self.assertEqual(len(output.getvalue().splitlines()),3)
            self.assertEqual((Path(tmp)/'.orbit-health.json').stat().st_mode&0o777,0o600)

    def test_exhausted_budget_remains_critical_when_context_is_unavailable(self):
        snapshot={'coins':universe(),'status':{'coingecko_markets':{'policy':'demo-250-v1','ok':True,'fetched_at':'2026-01-01T00:00:00Z'},'fred':{'enabled':True,'ok':False}}}
        self.assertEqual(health.assess(snapshot,NOW)['state'],'warning')
        report=health.assess(snapshot,NOW,{'state':'exhausted'})
        self.assertEqual(report['state'],'critical')
        self.assertEqual(report['issues'],['fred-unavailable','budget-exhausted'])


if __name__=='__main__':unittest.main()
