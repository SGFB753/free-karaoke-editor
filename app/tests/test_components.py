"""Optional engines install atomically, survive core updates and preserve weights."""
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kstudio import components as C, jobcontrol as JC


class ComponentTests(unittest.TestCase):
    def archive(self, unsafe=False):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('node.exe', b'node runtime')
            z.writestr('runtime.json', json.dumps(dict(component='node', revision=C.REVISION,
                abi=C.abi(), files=[dict(path='node.exe', size=12)])))
            if unsafe:
                z.writestr('../outside.txt', 'bad')
        return out.getvalue()

    def fake_download(self, content, calls, bad_hash=False):
        def download(url, path, *args):
            calls.append(url)
            if url.endswith('.sha256'):
                digest = '0'*64 if bad_hash else hashlib.sha256(content).hexdigest()
                Path(path).write_text(digest+'  runtime.zip', encoding='ascii')
            else:
                Path(path).write_bytes(content)
        return download

    def test_component_is_downloaded_once_and_survives_install_directory_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root, calls = Path(folder), []
            with patch.object(C, 'cache_root', return_value=root), patch.dict(C.os.environ, {}, clear=False), \
                    patch.object(C, '_download', side_effect=self.fake_download(self.archive(), calls)):
                first = C.ensure('node')
                with patch.object(sys, '_MEIPASS', str(root/'new-install'), create=True):
                    second = C.ensure('node')
                self.assertEqual(first, second)
                self.assertEqual(len(calls), 2)  # checksum + ZIP, never per core version
                self.assertTrue(C.ready('node'))

    def test_bad_checksum_and_unsafe_archives_do_not_install_or_touch_weights(self):
        for bad_hash, unsafe in ((True, False), (False, True)):
            with self.subTest(bad_hash=bad_hash, unsafe=unsafe), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                weights = root/'model.safetensors'; weights.write_bytes(b'keep weights')
                with patch.object(C, 'cache_root', return_value=root), \
                        patch.object(C, '_download', side_effect=self.fake_download(self.archive(unsafe), [], bad_hash)):
                    destination = C.component_dir('node')
                    with self.assertRaises(ValueError):
                        C.ensure('node')
                self.assertEqual(weights.read_bytes(), b'keep weights')
                self.assertFalse((root/'outside.txt').exists())
                self.assertFalse(destination.exists())
                self.assertEqual(list(root.iterdir()), [weights])

    def test_cancellation_keeps_cache_and_model_data_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(C, 'cache_root', return_value=root), \
                    patch.object(C, '_download', side_effect=JC.Cancelled):
                with self.assertRaises(JC.Cancelled):
                    C.ensure('node')
            self.assertEqual(list(root.iterdir()), [])

    def test_missing_runtime_file_is_detected_after_previous_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(C, 'cache_root', return_value=root), \
                    patch.object(C, '_download', side_effect=self.fake_download(self.archive(), [])):
                installed = C.ensure('node')
                (installed/'node.exe').unlink()
                self.assertFalse(C.ready('node'))


if __name__ == '__main__':
    unittest.main()
