"""External, dependency-free updater for a PyInstaller one-folder release."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import shutil
import subprocess
import tempfile
import time
import traceback
import zipfile


PRESERVED = {"projects", "output", "settings.ini"}
RETRY_SECONDS = 20.0
RETRY_DELAY = 0.25


def safe_extract(archive: str, target: str) -> str:
    root = os.path.abspath(target)
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            dst = os.path.abspath(os.path.join(root, item.filename))
            if os.path.commonpath([root, dst]) != root:
                raise RuntimeError("unsafe path in update archive")
        zf.extractall(root)
    children = [os.path.join(root, n) for n in os.listdir(root)]
    dirs = [p for p in children if os.path.isdir(p)]
    candidate = dirs[0] if len(dirs) == 1 else root
    if not os.path.isfile(os.path.join(candidate, "KaraokeStudio.exe")):
        raise RuntimeError("KaraokeStudio.exe is missing from update archive")
    return candidate


def wait_for(pid: int, seconds: int = 90) -> None:
    if os.name == "nt":
        # os.kill(pid, 0) is the usual POSIX liveness probe, but on Windows it
        # goes through TerminateProcess.  In the frozen updater it can fail with
        # “returned a result with an exception set” just after Studio exits.
        # A process handle is both safer and more exact: Windows signals it when
        # the old executable has released every DLL in the install directory.
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        synchronize = 0x00100000
        wait_object_0, wait_timeout, wait_failed = 0, 0x102, 0xFFFFFFFF
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:              # ERROR_INVALID_PARAMETER: already gone
                return
            raise ctypes.WinError(error)
        try:
            result = kernel32.WaitForSingleObject(handle, max(0, int(seconds * 1000)))
            if result == wait_object_0:
                return
            if result == wait_timeout:
                raise RuntimeError("Karaoke Studio did not close")
            if result == wait_failed:
                raise ctypes.WinError(ctypes.get_last_error())
            raise RuntimeError(f"could not wait for Karaoke Studio ({result})")
        finally:
            kernel32.CloseHandle(handle)

    for _ in range(seconds * 5):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    raise RuntimeError("Karaoke Studio did not close")


def preserve(old: str, new: str) -> None:
    for name in PRESERVED:
        src, dst = os.path.join(old, name), os.path.join(new, name)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        shutil.move(src, dst)


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def _copy_entry(src: str, dst: str) -> None:
    if os.path.isdir(src) and not os.path.islink(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def _temporary_windows_lock(error: OSError) -> bool:
    """True for the short-lived locks left by Windows/virus scanners."""
    return (getattr(error, "winerror", None) in (5, 32, 33)
            or getattr(error, "errno", None) in (errno.EACCES, errno.EPERM))


def _retry(action, seconds=None) -> None:
    if seconds is None:
        seconds = RETRY_SECONDS
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        try:
            action()
            return
        except OSError as error:
            if not _temporary_windows_lock(error) or time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_DELAY)


def _remove_retry(path: str) -> None:
    _retry(lambda: _remove(path))


def _copy_retry(src: str, dst: str) -> None:
    def copy_fresh():
        if os.path.exists(dst):
            _remove(dst)
        _copy_entry(src, dst)
    _retry(copy_fresh)


def _same_file(src: str, dst: str) -> bool:
    """Cheap proof that a locked destination is already the backup copy."""
    if not os.path.isfile(src) or not os.path.isfile(dst):
        return False
    try:
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        with open(src, "rb") as left, open(dst, "rb") as right:
            while True:
                a, b = left.read(1024 * 1024), right.read(1024 * 1024)
                if a != b:
                    return False
                if not a:
                    return True
    except OSError:
        return False


def replace_in_place(staged: str, install: str, backup: str) -> None:
    """Replace program entries without renaming the directory they live in.

    Explorer, Chrome or a terminal may hold a directory handle to the install
    root. Windows then refuses to rename that root even though Studio itself
    has exited and every EXE/DLL can be replaced safely. Keep the root and the
    user's three entries stationary; snapshot and replace everything else.
    """
    os.makedirs(install, exist_ok=True)
    os.makedirs(backup)
    old_names = [n for n in os.listdir(install) if n not in PRESERVED]
    for name in old_names:
        _copy_entry(os.path.join(install, name), os.path.join(backup, name))
    try:
        for name in old_names:
            _remove_retry(os.path.join(install, name))
        for name in os.listdir(staged):
            src, dst = os.path.join(staged, name), os.path.join(install, name)
            if name in PRESERVED and os.path.exists(dst):
                continue
            _copy_retry(src, dst)
    except Exception as original:
        # Remove only program files. Projects, finished exports and settings
        # never moved, so rollback cannot accidentally replace user data.
        rollback_errors = []
        for name in os.listdir(install):
            if name not in PRESERVED:
                try:
                    _remove_retry(os.path.join(install, name))
                except OSError as error:
                    rollback_errors.append(f"remove {name}: {error}")
        for name in os.listdir(backup):
            src, dst = os.path.join(backup, name), os.path.join(install, name)
            if _same_file(src, dst):
                continue
            try:
                _copy_retry(src, dst)
            except OSError as error:
                rollback_errors.append(f"restore {name}: {error}")
        if rollback_errors:
            note = "rollback: " + "; ".join(rollback_errors)
            if hasattr(original, "add_note"):
                original.add_note(note)
            else:  # Python 3.8–3.10, still supported by the source edition.
                original.args = (*original.args, note)
        raise original


def apply(archive: str, install: str, exe: str, pid: int) -> None:
    wait_for(pid)
    install = os.path.abspath(install)
    parent = os.path.dirname(install)
    stage_root = tempfile.mkdtemp(prefix="karaoke-stage-", dir=parent)
    staged = safe_extract(archive, stage_root)
    backup = install + ".previous"
    if os.path.exists(backup):
        shutil.rmtree(backup, ignore_errors=True)
    try:
        replace_in_place(staged, install, backup)
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen([os.path.join(install, exe)], cwd=tempfile.gettempdir(),
                         env=env)
    except Exception:
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    try:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)
    except OSError:
        pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--archive", required=True)
    p.add_argument("--install", required=True)
    p.add_argument("--exe", default="KaraokeStudio.exe")
    a = p.parse_args()
    error_path = os.path.join(tempfile.gettempdir(), "karaoke-update-error.txt")
    try:
        os.remove(error_path)
    except (FileNotFoundError, OSError):
        pass
    try:
        apply(a.archive, a.install, a.exe, a.pid)
        return 0
    except Exception:
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
