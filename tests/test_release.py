import argparse
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / 'scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('release', SCRIPTS / 'deploy_release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)

REV = 'a' * 40


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.install = self.base / 'install'
        self.backups = self.base / 'backups'
        self.repo = self.base / 'repo'
        for directory in (self.install, self.backups, self.repo / 'scripts'):
            directory.mkdir(parents=True)
        self.old = b'previous builder'
        (self.install / 'build_snapshot.py').write_bytes(self.old)
        for name, source in release.FILES.items():
            (self.repo / source).write_bytes(('new ' + name).encode())
        for obj, attr, value in [(release, 'INSTALL', self.install), (release.front, 'BACKUPS', self.backups), (release.front, 'REPO', self.repo), (release, 'SNAPSHOT', self.base / 'orbit.json')]:
            context = patch.object(obj, attr, value)
            context.start()
            self.addCleanup(context.stop)

    def activate_files(self):
        for name, source in release.FILES.items():
            release.front.atomic_write(self.install / name, (self.repo / source).read_bytes())

    def test_backup_restores_builder_and_removes_previously_absent_validator(self):
        backup, record = release.create_backup(REV)
        self.activate_files()
        release.restore_collector(backup, record)
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)
        self.assertFalse((self.install / 'validate_snapshot.py').exists())

    def test_tampered_backup_and_newer_collector_block_all_restoration(self):
        backup, record = release.create_backup(REV)
        self.activate_files()
        (self.install / 'build_snapshot.py').write_bytes(b'newer revision')
        with self.assertRaisesRegex(ValueError, 'Newer or modified'):
            release.restore_collector(backup, record)
        self.assertTrue((self.install / 'validate_snapshot.py').exists())
        self.activate_files()
        (backup / 'build_snapshot.py').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            release.restore_collector(backup, record)

    def test_timer_resumes_when_body_fails(self):
        with patch.object(release, 'systemctl') as ctl, patch.object(release, 'property_value', return_value='inactive'):
            with self.assertRaisesRegex(ValueError, 'failure'):
                with release.paused_timer():
                    raise ValueError('failure')
        self.assertEqual(ctl.call_args_list[0].args, ('stop', release.TIMER))
        self.assertEqual(ctl.call_args_list[-1].args, ('start', release.TIMER))

    def test_active_collector_timeout_does_not_enter_activation_and_resumes_timer(self):
        with patch.object(release, 'systemctl') as ctl, patch.object(release, 'property_value', return_value='activating'), patch.object(release.time, 'monotonic', side_effect=[0, 61]):
            with self.assertRaisesRegex(ValueError, 'still running'):
                with release.paused_timer():
                    self.fail('Must not enter activation')
        self.assertEqual(ctl.call_args_list[-1].args, ('start', release.TIMER))
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)

    def test_snapshot_failure_restores_collector_without_publishing_front(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'wait_for_provider'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected', side_effect=ValueError('source unavailable')), patch.object(release.front, 'run') as front_run:
            with self.assertRaisesRegex(ValueError, 'source unavailable'):
                release.run(args)
            front_run.assert_not_called()
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)
        self.assertFalse((self.install / 'validate_snapshot.py').exists())

    def test_front_failure_restores_collector(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'wait_for_provider'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected'), patch.object(release.front, 'run', side_effect=ValueError('front proof failed')):
            with self.assertRaisesRegex(ValueError, 'front proof failed'):
                release.run(args)
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)

    def test_success_records_both_backups_and_preserves_generated_snapshot(self):
        release.SNAPSHOT.write_bytes(b'generated data retained')
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        def activate_front(args, on_backup):
            on_backup(self.backups / 'front-backup')
            # The recovery manifest is durable before frontend activation begins.
            saved = json.loads(next(self.backups.glob('collector-*/collector.json')).read_text())
            self.assertEqual(saved['front_backup'], 'front-backup')
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'wait_for_provider'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected'), patch.object(release.front, 'run', side_effect=activate_front):
            release.run(args)
        record = json.loads(next(self.backups.glob('collector-*/collector.json')).read_text())
        self.assertEqual(record['front_backup'], 'front-backup')
        self.assertEqual(release.SNAPSHOT.read_bytes(), b'generated data retained')

    def test_snapshot_requires_new_generation_and_independent_current_xstocks(self):
        now = dt.datetime.now(dt.timezone.utc)
        stamp = now.isoformat()
        data = {'snapshot': stamp, 'coins': [{'asset_type': 'xstock'}], 'status': {name: {'ok': True, 'fetched_at': stamp} for name in ('coingecko_markets', 'coingecko_xstocks')}}
        def check(value, start=0):
            release.SNAPSHOT.write_text(json.dumps(value))
            with patch.object(release.subprocess, 'run', return_value=argparse.Namespace(returncode=0)):
                release.validate_collected(start)
        check(data)
        with self.assertRaisesRegex(ValueError, 'new snapshot'):
            check(data, now.timestamp() + 1)
        data['status']['coingecko_xstocks']['ok'] = False
        with self.assertRaisesRegex(ValueError, 'coingecko_xstocks'):
            check(data)
        data['status']['coingecko_xstocks'] = {'ok': True, 'fetched_at': (now-dt.timedelta(minutes=10)).isoformat()}
        with self.assertRaisesRegex(ValueError, 'coingecko_xstocks'):
            check(data)
        data['status']['coingecko_xstocks']['fetched_at'] = stamp
        data['coins'] = [{'asset_type': 'crypto'}]
        with self.assertRaisesRegex(ValueError, 'No xStocks'):
            check(data)

    def test_wrong_output_paths_do_not_expose_credentials(self):
        env_file = self.base / 'provider.env'
        env_file.write_text('CG_API_KEY=test-only-never-log\nORBIT_OUT_DIR=/unexpected\n')
        with patch.object(release, 'ENV_FILE', env_file), patch.object(release, 'property_value', return_value=''):
            with self.assertRaisesRegex(ValueError, '^Unexpected ORBIT_OUT_DIR; inspect paths before release$'):
                release.check_environment_paths()

    def test_rollback_traversal_and_symlink_rejected(self):
        for name in ['../elsewhere', '/tmp/collector-backup']:
            with self.assertRaises(ValueError):
                release.rollback(name)
        (self.backups / 'collector-link').symlink_to(self.base)
        with self.assertRaisesRegex(ValueError, 'Unexpected backup path'):
            release.rollback('collector-link')

    def test_collection_retries_once_only_after_recorded_provider_backpressure(self):
        with patch.object(release, 'wait_for_provider') as wait, patch.object(release, 'systemctl') as ctl, patch.object(release, 'provider_retry_at', return_value=200), patch.object(release.time, 'time', return_value=100), patch.object(release, 'validate_collected', side_effect=[release.CollectionNotReady('no new snapshot'), None]):
            release.collect_for_release()
        self.assertEqual([call.args for call in wait.call_args_list], [(60,), (0,)])
        self.assertEqual([call.args for call in ctl.call_args_list], [('start', release.SERVICE)] * 2)

    def test_collection_does_not_retry_service_or_schema_failure(self):
        for service_failure in (False, True):
            with patch.object(release, 'wait_for_provider'), patch.object(release, 'systemctl', side_effect=ValueError('service failed') if service_failure else None) as ctl, patch.object(release, 'provider_retry_at', return_value=10**10), patch.object(release, 'validate_collected', side_effect=ValueError('invalid snapshot')):
                with self.assertRaises(ValueError):
                    release.collect_for_release()
                ctl.assert_called_once_with('start', release.SERVICE)

    def test_repeated_rate_limits_do_not_create_an_unbounded_retry_loop(self):
        with patch.object(release, 'wait_for_provider') as wait, patch.object(release, 'systemctl') as ctl, patch.object(release, 'provider_retry_at', return_value=200), patch.object(release.time, 'time', return_value=100), patch.object(release, 'validate_collected', side_effect=release.CollectionNotReady('no new snapshot')):
            with self.assertRaises(ValueError):
                release.collect_for_release()
        self.assertEqual(wait.call_count, 2)
        self.assertEqual(ctl.call_count, 2)

    def test_wait_honors_deadline_without_network_and_uses_bounded_sleep_chunks(self):
        current = [100]
        chunks = []
        def sleep(seconds):
            chunks.append(seconds)
            current[0] += seconds
        with patch.object(release, 'provider_retry_at', return_value=220), patch.object(release.time, 'time', side_effect=lambda: current[0]), patch.object(release.time, 'sleep', side_effect=sleep), patch.object(release, 'systemctl') as ctl:
            release.wait_for_provider(60)
            ctl.assert_not_called()
        self.assertEqual(current[0], 220)
        self.assertEqual(chunks, [30, 30, 30, 30])

    def test_long_provider_delay_is_not_shortened(self):
        with patch.object(release, 'provider_retry_at', return_value=1000), patch.object(release.time, 'time', return_value=100), patch.object(release.time, 'sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'deployment deferred without a new request'):
                release.wait_for_provider(60)
            sleep.assert_not_called()

    def test_legacy_timer_restart_cannot_bypass_recorded_cooldown(self):
        order = []
        with patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'systemctl', side_effect=lambda *args: order.append(args)), patch.object(release, 'wait_for_provider', side_effect=lambda *args, **kwargs: order.append(('cooldown', args, kwargs))):
            with release.paused_timer():
                order.append(('restored',))
        self.assertEqual(order, [('stop', release.TIMER), ('restored',), ('cooldown', (0,), {'maximum': 1800}), ('start', release.TIMER)])

    def test_unmanageable_cooldown_leaves_timer_paused_instead_of_forcing_provider(self):
        with patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'systemctl') as ctl, patch.object(release, 'wait_for_provider', side_effect=ValueError('long cooldown')):
            with self.assertRaisesRegex(ValueError, 'long cooldown'):
                with release.paused_timer():
                    pass
        ctl.assert_called_once_with('stop', release.TIMER)

    def test_transport_state_rejects_invalid_or_symlinked_file_without_printing_values(self):
        file = release.SNAPSHOT.parent / '.coingecko-rate-limit.json'
        for raw in ['{}', '[]', '{bad', 'x' * 4097, '{"retry_at": true}', '{"retry_at": -1}']:
            file.write_text(raw)
            with self.assertRaises(ValueError):
                release.provider_retry_at()
        file.unlink()
        file.symlink_to(self.repo / 'build_snapshot.py')
        with self.assertRaises(OSError):
            release.provider_retry_at()


if __name__ == '__main__':
    unittest.main()
