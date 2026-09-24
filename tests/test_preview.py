import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('preview', Path(__file__).parents[1] / 'scripts/preview.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PreviewTests(unittest.TestCase):
    def test_local_snapshot_preserves_timestamps_and_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'snapshot.json'
            raw = json.dumps({'snapshot': '2020-01-01T00:00:00Z', 'coins': []}).encode()
            file.write_bytes(raw)
            cache = p.PublicCache(file)
            with patch.object(cache, 'fetch') as fetch:
                self.assertEqual(cache.get('/data.json'), (raw, 'application/json'))
                fetch.assert_not_called()
            file.write_text('invalid')
            self.assertIsNone(cache.get('/data.json')[0])

    def test_local_logo_traversal_and_symlink_escape_never_expose_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logos = root / 'logos'
            logos.mkdir()
            secret = root / 'private.png'
            secret.write_bytes(b'synthetic-private-test')
            (logos / 'test.png').symlink_to(secret)
            cache = p.PublicCache(logo_dir=logos)
            with patch.object(cache, 'fetch', side_effect=OSError):
                for path in ['/logos/../private.png', '/logos/%2e%2e/private.png', '/logos/test.png', '/env.example']:
                    self.assertIsNone(cache.get(path)[0])
