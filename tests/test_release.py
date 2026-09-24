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
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected', side_effect=ValueError('source unavailable')), patch.object(release.front, 'run') as front_run:
            with self.assertRaisesRegex(ValueError, 'source unavailable'):
                release.run(args)
            front_run.assert_not_called()
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)
        self.assertFalse((self.install / 'validate_snapshot.py').exists())

    def test_front_failure_restores_collector(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected'), patch.object(release.front, 'run', side_effect=ValueError('front proof failed')):
            with self.assertRaisesRegex(ValueError, 'front proof failed'):
                release.run(args)
        self.assertEqual((self.install / 'build_snapshot.py').read_bytes(), self.old)

    def test_success_records_both_backups_and_preserves_generated_snapshot(self):
        release.SNAPSHOT.write_bytes(b'generated data retained')
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(release, 'preflight'), patch.object(release, 'check_environment_paths'), patch.object(release, 'systemctl'), patch.object(release, 'property_value', return_value='inactive'), patch.object(release, 'validate_collected'), patch.object(release.front, 'run', return_value=self.backups / 'front-backup'):
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


if __name__ == '__main__':
    unittest.main()
