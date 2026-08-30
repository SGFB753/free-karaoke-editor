"""External, dependency-free updater for a PyInstaller one-folder release."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import tempfile
import time
import zipfile


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
    for name in ("projects", "settings.ini"):
        src, dst = os.path.join(old, name), os.path.join(new, name)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        shutil.move(src, dst)


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
        os.replace(install, backup)
        if staged == stage_root:
            os.replace(stage_root, install)
        else:
            os.replace(staged, install)
            shutil.rmtree(stage_root, ignore_errors=True)
        preserve(backup, install)
    except Exception:
        if os.path.exists(install):
            shutil.rmtree(install, ignore_errors=True)
        if os.path.exists(backup):
            os.replace(backup, install)
        raise
    subprocess.Popen([os.path.join(install, exe)], cwd=install)
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
    except Exception as e:
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
