import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deploy', Path(__file__).parents[1] / 'scripts/deploy_front.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
REV = 'a' * 40


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'www'
        (self.root / 'legal').mkdir(parents=True)
        self.old = {name: ('Old ' + name).encode() for name in d.PAGES}
        for name, body in self.old.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(body)
        (self.root / 'app.js').write_text('legacy script')
        (self.root / 'data.json').write_text('protected snapshot')
        self.backups = self.base / 'backups'
        self.assets = {'app.js': b'new script', 'icons/LICENSE': b'license'}
        self.pages = {name: ('New ' + name).encode() for name in d.PAGES}

    def prepare(self):
        return d.prepare(self.root, self.backups, REV, self.assets, self.pages)

    def assert_old(self):
        for name, body in self.old.items():
            self.assertEqual((self.root / name).read_bytes(), body)

    def test_versioned_payload_rewrites_only_assets_and_marks_both_pages(self):
        assets, pages = d.payload(d.REPO / 'web', REV)
        self.assertIn('core.js', assets)
        self.assertIn('i18n.js', assets)
        self.assertNotIn('data.json', assets)
        self.assertTrue(all(not n.startswith('logos/') for n in assets))
        for name, body in pages.items():
            text = body.decode()
            self.assertIn(f'/releases/{REV}/app.css', text)
            if name in d.LEGACY_PAGES:
                self.assertIn(f'/releases/{REV}/i18n.js', text)
            else:
                self.assertNotIn('<script', text)
            self.assertIn(f'name="orbit-release" content="{REV}"', text)
            self.assertNotIn('orbit2-experience-1', text)
        self.assertIn('href="legal/"', pages['index.html'].decode())

    def test_missing_icons_remain_blocking_with_localization_asset(self):
        empty_web = self.base / 'empty-web'
        (empty_web / 'icons').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'Missing local icons'):
            d.payload(empty_web, REV)

    def test_external_asset_and_path_traversal_are_refused(self):
        for url in ['https://evil.example/x.js', '//evil.example/x.js', '../private.js', '/private.js']:
            parser = d.ReleaseHTML('index.html', REV, self.assets)
            with self.assertRaises(ValueError):
                parser.feed(f'<script src="{url}"></script>')
        with self.assertRaises(ValueError):
            d.payload(d.REPO / 'web', '../unsafe')

    def test_prepare_does_not_activate_and_retains_legacy_and_data(self):
        backup = self.prepare()
        self.assert_old()
        self.assertEqual((self.root / 'app.js').read_text(), 'legacy script')
        self.assertEqual((self.root / 'data.json').read_text(), 'protected snapshot')
        self.assertEqual((backup / 'index.html').read_bytes(), self.old['index.html'])
        self.assertEqual((self.root / 'releases' / REV / 'app.js').read_bytes(), self.assets['app.js'])

    def test_activation_and_rollback_restore_both_pages(self):
        backup = self.prepare()
        d.activate(self.root, backup, self.pages)
        for name, body in self.pages.items():
            self.assertEqual((self.root / name).read_bytes(), body)
        d.restore(self.root, backup)
        self.assert_old()
        self.assertTrue((self.root / 'releases' / REV / 'app.js').is_file())

    def test_new_documentation_pages_are_removed_on_rollback(self):
        for name in d.PAGES:
            if name not in d.LEGACY_PAGES:
                (self.root / name).unlink()
        backup = self.prepare()
        d.activate(self.root, backup, self.pages)
        self.assertTrue((self.root / 'docs/en/index.html').is_file())
        d.restore(self.root, backup)
        for name in d.PAGES:
            if name in d.LEGACY_PAGES:
                self.assertEqual((self.root / name).read_bytes(), self.old[name])
            else:
                self.assertFalse((self.root / name).exists())

    def test_legacy_two_page_backup_remains_restorable(self):
        backup = self.prepare()
        d.activate(self.root, backup, self.pages)
        manifest = json.loads((backup / 'manifest.json').read_text())
        manifest['pages'] = {name: manifest['pages'][name] for name in d.LEGACY_PAGES}
        (backup / 'manifest.json').write_text(json.dumps(manifest))
        d.restore(self.root, backup)
        for name in d.LEGACY_PAGES:
            self.assertEqual((self.root / name).read_bytes(), self.old[name])
        self.assertEqual((self.root / 'docs/index.html').read_bytes(), self.pages['docs/index.html'])

    def test_new_page_preflight_requires_public_404_and_safe_path(self):
        for name in d.PAGES:
            if name not in d.LEGACY_PAGES:
                (self.root / name).unlink()
        def public(path):
            if path.startswith('/docs/'):
                raise d.urllib.error.HTTPError(path, 404, 'Not found', {}, None)
            name = 'index.html' if path == '/' else 'legal/index.html'
            return self.old[name], {'Content-Security-Policy': "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"}
        with patch.object(d, 'public', side_effect=public), patch.object(d, 'check_snapshot'):
            d.preflight(self.root)
        with patch.object(d, 'public', return_value=(b'existing page', {})):
            with self.assertRaises(ValueError):
                d.preflight(self.root)
        (self.root / 'docs/en').rmdir()
        (self.root / 'docs').rmdir()
        (self.root / 'docs').symlink_to(self.base)
        with self.assertRaises(ValueError):
            d.page_body(self.root, 'docs/index.html')

    def test_immutable_release_cannot_be_overwritten(self):
        self.prepare()
        self.assets['app.js'] = b'different'
        with self.assertRaises(ValueError):
            self.prepare()
        self.assert_old()

    def test_symlinked_release_directory_is_refused(self):
        (self.root / 'releases').symlink_to(self.base)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assert_old()

    def test_rollback_cannot_overwrite_a_newer_release(self):
        backup = self.prepare()
        d.activate(self.root, backup, self.pages)
        (self.root / 'index.html').write_bytes(b'newer release')
        with self.assertRaises(ValueError):
            d.restore(self.root, backup)
        self.assertEqual((self.root / 'index.html').read_bytes(), b'newer release')
        self.assertEqual((self.root / 'legal/index.html').read_bytes(), self.pages['legal/index.html'])

    def test_modified_backup_cannot_be_restored(self):
        backup = self.prepare()
        d.activate(self.root, backup, self.pages)
        (backup / 'index.html').write_bytes(b'modified backup')
        with self.assertRaises(ValueError):
            d.restore(self.root, backup)
        self.assertEqual((self.root / 'index.html').read_bytes(), self.pages['index.html'])

    def test_public_failure_after_activation_restores_old_front(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        def response(path):
            return self.assets[path.split(REV + '/')[1]], {'Content-Type': 'application/javascript'}
        with patch.object(d, 'WEB_ROOT', self.root), patch.object(d, 'BACKUPS', self.backups), patch.object(d, 'git', side_effect=[REV, '']), patch.object(d, 'payload', return_value=(self.assets, self.pages)), patch.object(d, 'preflight'), patch.object(d.os, 'geteuid', return_value=0), patch.object(d, 'public', side_effect=response), patch.object(d, 'verify_pages', side_effect=ValueError('failed public proof')):
            with self.assertRaisesRegex(ValueError, 'failed public proof'):
                d.run(args)
        self.assert_old()

    def test_asset_failure_prevents_activation(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(d, 'WEB_ROOT', self.root), patch.object(d, 'BACKUPS', self.backups), patch.object(d, 'git', side_effect=[REV, '']), patch.object(d, 'payload', return_value=(self.assets, self.pages)), patch.object(d, 'preflight'), patch.object(d.os, 'geteuid', return_value=0), patch.object(d, 'public', return_value=(b'wrong asset', {})):
            with self.assertRaisesRegex(ValueError, 'Asset verification failed'):
                d.run(args)
        self.assert_old()

    def test_wrong_checkout_is_refused_before_any_public_request(self):
        args = argparse.Namespace(revision=REV, apply=True, rollback=None)
        with patch.object(d, 'git', return_value='b' * 40), patch.object(d, 'public') as public:
            with self.assertRaises(ValueError):
                d.run(args)
            public.assert_not_called()
        self.assert_old()

    def test_stale_snapshot_blocks_deployment(self):
        data = {'snapshot': '2020-01-01T00:00:00Z', 'coins': [{'id': 'synthetic-test'}]}
        with patch.object(d, 'public', return_value=(json.dumps(data).encode(), {})):
            with self.assertRaisesRegex(ValueError, 'not current'):
                d.check_snapshot()


if __name__ == '__main__':
    unittest.main()
