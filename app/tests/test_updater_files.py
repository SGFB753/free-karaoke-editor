"""Avoid repeated bulk copies without sharing old and new program contents."""
import errno
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater as U
from kstudio import update as UP


class UpdaterFilesTests(unittest.TestCase):
    def test_cancelled_download_does_not_leave_a_partial_archive(self):
        class Abort(BaseException):
            pass
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(tempfile, 'tempdir', str(root)), \
                    patch.object(UP, 'latest', return_value={'available': True, 'version': 'next'}):
                with self.assertRaises(Abort):
                    UP.download(lambda _: (_ for _ in ()).throw(Abort()))
            self.assertEqual(list(root.iterdir()), [])

    def test_failed_helper_copy_or_launch_removes_the_partial_helper(self):
        for failure in ('copy', 'launch'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                install = root/'install'; (install/'updater').mkdir(parents=True)
                (install/'updater/KaraokeUpdater.exe').write_bytes(b'helper')
                archive = root/'update.zip'; archive.write_bytes(b'archive')
                target = UP.shutil if failure == 'copy' else UP.subprocess
                name = 'copytree' if failure == 'copy' else 'Popen'
                with patch.object(tempfile, 'tempdir', str(root)), \
                        patch.object(UP, 'supported', return_value=True), \
                        patch.object(UP, '_bundle_root', return_value=str(install)), \
                        patch.object(target, name, side_effect=OSError('simulated failure')):
                    with self.assertRaises(OSError):
                        UP.launch(str(archive))
                self.assertEqual(sorted(p.name for p in root.iterdir()), ['install', 'update.zip'])

    def test_failed_extraction_cleans_partial_stage_and_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            install = root/'install'; install.mkdir()
            (install/'KaraokeStudio.exe').write_bytes(b'original')
            download = root/'karaoke-update-broken'; download.mkdir()
            archive = download/'update.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('partial/data.dll', b'unpacked before missing EXE is detected')
            with patch.object(tempfile, 'tempdir', str(root)), patch.object(U, 'status'):
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    U.apply(str(archive), str(install), 'KaraokeStudio.exe', 0, launch_after=False)
            self.assertEqual(list(root.iterdir()), [install])
            self.assertEqual((install/'KaraokeStudio.exe').read_bytes(), b'original')

    def test_repeated_install_removes_obsolete_libraries_and_all_staging_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            install = root/'install'; install.mkdir()
            (install/'KaraokeStudio.exe').write_bytes(b'original')
            (install/'qwen-obsolete.dll').write_bytes(b'old bundled runtime')
            (install/'projects').mkdir()
            (install/'projects/song.json').write_bytes(b'project')
            weights = root/'cache/model.safetensors'; weights.parent.mkdir(); weights.write_bytes(b'weights')
            for _ in range(2):
                download = root/'karaoke-update-test'; download.mkdir()
                archive = download/'update.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('KaraokeStudio/KaraokeStudio.exe', b'new executable')
                    z.writestr('KaraokeStudio/_internal/engine.dll', b'new engine')
                with patch.object(tempfile, 'tempdir', str(root)), patch.object(U, 'status'):
                    U.apply(str(archive), str(install), 'KaraokeStudio.exe', 0, launch_after=False)
                self.assertEqual(sorted(p.name for p in root.iterdir()), ['cache', 'install'])
                self.assertFalse((install/'qwen-obsolete.dll').exists())
                self.assertEqual((install/'projects/song.json').read_bytes(), b'project')
                self.assertEqual(weights.read_bytes(), b'weights')

    def test_old_helpers_are_retired_but_running_and_unrelated_folders_are_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('old', 'active'):
                helper = root/('karaoke-updater-'+name)/'updater'
                (helper/'_internal').mkdir(parents=True)
                (helper/'KaraokeUpdater.exe').write_bytes(b'helper')
                (helper/'_internal/base_library.zip').write_bytes(b'runtime')
            unrelated = root/'karaoke-updater-unrelated'; unrelated.mkdir()
            (unrelated/'user.txt').write_bytes(b'keep')
            backup = root/'karaoke-rollback-recovery'; backup.mkdir()
            (backup/'previous.exe').write_bytes(b'recovery')
            with patch.object(tempfile, 'tempdir', str(root)), \
                    patch.object(UP, '_retire_helper_executable', side_effect=lambda p: 'active' not in p):
                UP.cleanup_helpers(attempts=1)
            self.assertFalse((root/'karaoke-updater-old').exists())
            self.assertTrue((root/'karaoke-updater-active/updater/KaraokeUpdater.exe').exists())
            self.assertEqual((unrelated/'user.txt').read_bytes(), b'keep')
            self.assertEqual((backup/'previous.exe').read_bytes(), b'recovery')

    def test_snapshots_and_new_install_do_not_copy_file_contents_on_same_volume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, stage, backup = root/'install', root/'stage', root/'backup'
            for path in (old, stage):
                (path/'_internal').mkdir(parents=True)
            (old/'KaraokeStudio.exe').write_bytes(b'old executable')
            (old/'_internal'/'engine.dll').write_bytes(b'old engine')
            (stage/'KaraokeStudio.exe').write_bytes(b'new executable')
            (stage/'_internal'/'engine.dll').write_bytes(b'new engine')
            with patch.object(U.shutil, 'copy2', side_effect=AssertionError('unnecessary byte copy')):
                U.replace_in_place(str(stage), str(old), str(backup))
            self.assertEqual((backup/'KaraokeStudio.exe').read_bytes(), b'old executable')
            self.assertEqual((backup/'_internal'/'engine.dll').read_bytes(), b'old engine')
            self.assertEqual((old/'KaraokeStudio.exe').read_bytes(), b'new executable')
            self.assertEqual((old/'_internal'/'engine.dll').read_bytes(), b'new engine')
            self.assertFalse(os.path.samefile(old/'_internal'/'engine.dll', backup/'_internal'/'engine.dll'))
            # Cleanup unlinks the temporary name without deleting installed data.
            (stage/'_internal'/'engine.dll').unlink()
            self.assertEqual((old/'_internal'/'engine.dll').read_bytes(), b'new engine')

    def test_cross_volume_or_unsupported_hardlinks_fall_back_to_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            src, dst = Path(folder)/'source', Path(folder)/'destination'
            src.write_bytes(b'original')
            with patch.object(U.os, 'link', side_effect=OSError(errno.EXDEV, 'different volumes')):
                U._copy_entry(str(src), str(dst))
            src.write_bytes(b'changed')
            self.assertEqual(dst.read_bytes(), b'original')

    def test_rollback_restores_all_original_bytes_after_partial_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, stage, backup = root/'install', root/'stage', root/'backup'
            old.mkdir(); stage.mkdir()
            (old/'KaraokeStudio.exe').write_bytes(b'old executable')
            (old/'engine.dll').write_bytes(b'old engine')
            (stage/'KaraokeStudio.exe').write_bytes(b'new executable')
            (stage/'engine.dll').write_bytes(b'new engine')
            real_copy = U._copy_entry
            count = 0
            def fail_second_new(src, dst):
                nonlocal count
                if Path(src).parent == stage:
                    count += 1
                    if count == 2:
                        raise OSError(errno.EIO, 'interrupted update')
                return real_copy(src, dst)
            with patch.object(U, '_copy_entry', side_effect=fail_second_new):
                with self.assertRaises(OSError):
                    U.replace_in_place(str(stage), str(old), str(backup))
            self.assertEqual((old/'KaraokeStudio.exe').read_bytes(), b'old executable')
            self.assertEqual((old/'engine.dll').read_bytes(), b'old engine')


if __name__ == '__main__':
    unittest.main()
