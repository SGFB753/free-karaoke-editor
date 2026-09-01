"""External, dependency-free updater for a PyInstaller one-folder release."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile


PRESERVED = {"projects", "output", "settings.ini"}
RETRY_SECONDS = 20.0
RETRY_DELAY = 0.25
STATUS_FILE = "karaoke-update.log"


def prepare_console() -> None:
    """Make the temporary progress window readable on Russian Windows."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetConsoleTitleW(
            "Karaoke Studio — обновление / update")
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def status(message: str) -> None:
    """Leave a visible and persistent breadcrumb for the silent hand-off."""
    line = time.strftime("%H:%M:%S  ") + message
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(os.path.join(tempfile.gettempdir(), STATUS_FILE), "a",
                  encoding="utf-8") as log:
            log.write(line + "\n")
    except OSError:
        pass


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


def make_stage_root() -> str:
    """A writable staging folder that does not require Program Files rights.

    ``tempfile.mkdtemp(dir=r"C:\Program Files")`` can spin through billions of
    candidate names on Windows when ``os.access`` claims that directory is
    writable but ``CreateDirectory`` denies it.  Replacement already copies
    entries one by one, so staging does not need to be beside the installation.
    """
    return tempfile.mkdtemp(prefix="karaoke-stage-")


def make_backup_path() -> str:
    """A not-yet-created rollback path below a writable temporary root."""
    root = tempfile.mkdtemp(prefix="karaoke-rollback-")
    return os.path.join(root, "previous")


def install_writable(install: str) -> bool:
    """Test the real operation Program Files may deny, not ``os.access``.

    On Windows ``os.access`` can report a Program Files directory as writable
    even though CreateFile is rejected by its ACL.  A tiny exclusive probe is
    exact and is removed before any application file is touched.
    """
    probe = os.path.join(os.path.abspath(install),
                         f".karaoke-update-write-{os.getpid()}-{time.time_ns()}")
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        try:
            os.remove(probe)
        except OSError:
            pass
        return False


def _relay_status_log(offset: int) -> int:
    """Print worker progress in the original non-elevated console."""
    path = os.path.join(tempfile.gettempdir(), STATUS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as log:
            log.seek(offset)
            piece = log.read()
            offset = log.tell()
        if piece:
            print(piece, end="", flush=True)
    except OSError:
        pass
    return offset


def elevate_and_wait(args) -> int:
    """Run the replacement worker through UAC and return its exit code.

    This non-elevated updater remains alive and later starts Studio itself, so
    the new application does not accidentally inherit an administrator token.
    The worker is hidden; its detailed stages still go to the shared log while
    this console clearly says that administrator access is being used.
    """
    if os.name != "nt":
        raise RuntimeError("administrator elevation is only available on Windows")
    from ctypes import wintypes

    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE), ("lpIDList", wintypes.LPVOID),
            ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(SHELLEXECUTEINFO),)
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE,
                                             ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    executable = os.path.abspath(sys.executable)
    worker_args = list(args)
    if not getattr(sys, "frozen", False):
        worker_args.insert(0, os.path.abspath(__file__))
    parameters = subprocess.list2cmdline(worker_args)
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040             # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.lpDirectory = tempfile.gettempdir()
    info.nShow = 0                       # SW_HIDE: keep one progress window

    status_path = os.path.join(tempfile.gettempdir(), STATUS_FILE)
    try:
        relay_offset = os.path.getsize(status_path)
    except OSError:
        relay_offset = 0
    previous_reset = os.environ.get("PYINSTALLER_RESET_ENVIRONMENT")
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == 1223:            # ERROR_CANCELLED: UAC was declined
                raise RuntimeError(
                    "administrator permission was cancelled / "
                    "запрос прав администратора отменён")
            raise ctypes.WinError(error)
    finally:
        if previous_reset is None:
            os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
        else:
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = previous_reset

    if not info.hProcess:
        raise RuntimeError("the elevated updater did not start")
    try:
        deadline = time.monotonic() + 10 * 60
        while True:
            result = kernel32.WaitForSingleObject(info.hProcess, 250)
            relay_offset = _relay_status_log(relay_offset)
            if result == 0:
                break
            if result != 0x102:
                raise ctypes.WinError(ctypes.get_last_error())
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "the elevated update did not finish within 10 minutes")
        _relay_status_log(relay_offset)
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


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


def replace_in_place(staged: str, install: str, backup: str,
                     log=None) -> None:
    """Replace program entries without renaming the directory they live in.

    Explorer, Chrome or a terminal may hold a directory handle to the install
    root. Windows then refuses to rename that root even though Studio itself
    has exited and every EXE/DLL can be replaced safely. Keep the root and the
    user's three entries stationary; snapshot and replace everything else.
    """
    os.makedirs(install, exist_ok=True)
    os.makedirs(backup)
    old_names = [n for n in os.listdir(install) if n not in PRESERVED]
    if log:
        log("Creating the rollback copy / Создаю резервную копию…")
    for name in old_names:
        _copy_entry(os.path.join(install, name), os.path.join(backup, name))
    try:
        if log:
            log("Replacing application files / Заменяю файлы программы…")
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


def apply(archive: str, install: str, exe: str, pid: int,
          launch_after: bool = True) -> None:
    status("Waiting for Karaoke Studio to close / Жду закрытия Студии…")
    wait_for(pid)
    status("The old process has closed / Старый процесс закрыт.")
    install = os.path.abspath(install)
    if not install_writable(install):
        raise PermissionError(
            f"administrator permission is required to update {install}")
    stage_root = make_stage_root()
    status("Unpacking the update / Распаковываю обновление…")
    staged = safe_extract(archive, stage_root)
    # The user may own C:\Program Files\KaraokeStudio without permission to
    # create its sibling KaraokeStudio.previous. Keep rollback data in Temp as
    # well; replacement only touches entries inside the writable install root.
    backup = make_backup_path()
    backup_root = os.path.dirname(backup)
    try:
        replace_in_place(staged, install, backup, status)
        if launch_after:
            start_application(install, exe)
    except Exception:
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    shutil.rmtree(backup_root, ignore_errors=True)
    try:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)
    except OSError:
        pass


def start_application(install: str, exe: str) -> None:
    """Start Studio from a non-elevated updater process."""
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    status("Starting the new version / Запускаю новую версию…")
    subprocess.Popen([os.path.join(install, exe)], cwd=tempfile.gettempdir(),
                     env=env)


def main() -> int:
    prepare_console()
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--archive", required=True)
    p.add_argument("--install", required=True)
    p.add_argument("--exe", default="KaraokeStudio.exe")
    p.add_argument("--elevated", action="store_true",
                   help=argparse.SUPPRESS)
    a = p.parse_args()
    error_path = os.path.join(tempfile.gettempdir(), "karaoke-update-error.txt")
    status_path = os.path.join(tempfile.gettempdir(), STATUS_FILE)
    if not a.elevated:
        try:
            os.remove(status_path)
        except (FileNotFoundError, OSError):
            pass
        try:
            os.remove(error_path)
        except (FileNotFoundError, OSError):
            pass
    try:
        if not a.elevated:
            status("Karaoke Studio update / Обновление Караоке-студии")
        if (os.name == "nt" and not a.elevated
                and not install_writable(a.install)):
            status("Administrator access is required for Program Files; "
                   "confirm the Windows prompt / Для Program Files нужны "
                   "права администратора — подтвердите запрос Windows…")
            worker = ["--pid", str(a.pid), "--archive", a.archive,
                      "--install", a.install, "--exe", a.exe, "--elevated"]
            code = elevate_and_wait(worker)
            if code:
                raise RuntimeError(f"the elevated updater failed ({code})")
            start_application(a.install, a.exe)
        else:
            apply(a.archive, a.install, a.exe, a.pid,
                  launch_after=not a.elevated)
        status("Done / Готово.")
        return 0
    except Exception:
        already_reported = os.path.isfile(error_path) and os.path.getsize(error_path) > 0
        with open(error_path, "a" if already_reported else "w", encoding="utf-8") as f:
            if already_reported:
                f.write("\n\n--- parent updater ---\n")
            f.write(traceback.format_exc())
        status("Update failed; details: " + error_path)
        if os.name == "nt" and not a.elevated:
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "Не удалось обновить Караоке-студию.\n\nПодробности:\n" + error_path,
                    "Karaoke Studio — update failed", 0x10)
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
