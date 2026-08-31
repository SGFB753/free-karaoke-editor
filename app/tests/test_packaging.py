"""Small, offline checks for release/update machinery."""

from __future__ import annotations

import os
import ctypes
import json
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio import update
import updater
import studio


def check(name, yes):
    print(("  OK   " if yes else "  FAIL ") + name)
    if not yes:
        raise AssertionError(name)


def main():
    spec_path = os.path.join(ROOT, "packaging", "KaraokeStudio.spec")
    with open(spec_path, encoding="utf-8") as f:
        spec = f.read()
    check("packaged renderer carries dynamic Pillow imports",
          'collect_submodules("PIL")' in spec)
    check("model weights are opt-in for release archives",
          'KARAOKE_BUNDLE_MODELS") == "1"' in spec)
    icon_path = os.path.join(ROOT, "packaging", "KaraokeStudio.ico")
    with open(icon_path, "rb") as f:
        icon_header = f.read(6)
    check("the Windows EXE has the branded multi-size icon",
          'icon=os.path.join(APP, "packaging", "KaraokeStudio.ico")' in spec
          and icon_header[:4] == b"\x00\x00\x01\x00"
          and int.from_bytes(icon_header[4:6], "little") >= 6)
    check("the packaged browser window carries taskbar-size icons",
          '"icon-32.png"' in spec and '"favicon.ico"' in spec
          and os.path.isfile(os.path.join(ROOT, "kstudio", "icon-32.png"))
          and os.path.isfile(os.path.join(ROOT, "kstudio", "favicon.ico")))

    build_path = os.path.join(ROOT, "packaging", "build-windows.ps1")
    with open(build_path, encoding="utf-8-sig") as f:
        build_script = f.read()
    check("finished EXE gets a media dependency smoke test",
          "--internal-package-smoke" in build_script)
    updater_spec_path = os.path.join(ROOT, "packaging", "KaraokeUpdater.spec")
    with open(updater_spec_path, encoding="utf-8") as f:
        updater_spec = f.read()
    check("the updater starts from a one-folder runtime",
          "exclude_binaries=True" in updater_spec and "COLLECT(" in updater_spec
          and "updater-dist\\KaraokeUpdater" in build_script)

    workflow_path = os.path.join(os.path.dirname(ROOT), ".github", "workflows",
                                 "windows-release.yml")
    with open(workflow_path, encoding="utf-8") as f:
        release_workflow = f.read()
    check("normal GitHub releases leave model weights in the user cache",
          "-WithModels" not in release_workflow)

    check("a source checkout cannot overwrite itself", not update.supported())
    check("versions compare numerically",
          update._version_tuple("v4.10.0") > update._version_tuple("4.9.9"))

    # The app window is a separate Chromium process. During an update the old
    # server must own and close exactly that process, or its completed restart
    # screen remains beside the newly launched version forever.
    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        studio.DESKTOP_WINDOW_PROC = owned
        studio.close_desktop_window()
        check("an update closes the old Studio app window process",
              owned.poll() is not None and studio.DESKTOP_WINDOW_PROC is None)
    finally:
        if owned.poll() is None:
            owned.kill()
        owned.wait()
    browser_cmd = studio.browser_command("chrome.exe", "http://127.0.0.1:8770/",
                                         r"C:\Temp\studio-profile")
    check("the Studio window has a private browser process",
          any(a.startswith("--user-data-dir=") for a in browser_cmd)
          and "--no-first-run" in browser_cmd
          and any(a.startswith("--app=http://127.0.0.1:8770/") for a in browser_cmd))
    old_frozen = getattr(studio.sys, "frozen", None)
    try:
        studio.sys.frozen = True
        check("the first fixed release recognises a Windows launch from the old updater",
              studio.launched_by_updater(tempfile.gettempdir()) == (os.name == "nt"))
        check("an ordinary launch is not mistaken for an update",
              not studio.launched_by_updater(os.path.join(tempfile.gettempdir(), "elsewhere")))
    finally:
        if old_frozen is None:
            delattr(studio.sys, "frozen")
        else:
            studio.sys.frozen = old_frozen

    # The external updater must wait until the old executable releases its DLLs.
    # os.kill(pid, 0), while useful on POSIX, is not a harmless liveness probe on
    # Windows and used to crash the frozen updater at this exact point.
    sleeper = subprocess.Popen([sys.executable, "-c",
                                "import time; time.sleep(0.2)"])
    try:
        updater.wait_for(sleeper.pid, seconds=3)
        check("the updater waits safely for the old Windows process",
              sleeper.poll() is not None)
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
        sleeper.wait()

    class RedirectResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def geturl(self):
            return "https://github.com/owner/fork/releases/tag/v9.9.9"

    requested = []
    old_urlopen = update.urllib.request.urlopen
    try:
        def fake_urlopen(request, timeout=0):
            requested.append((request.full_url, timeout))
            return RedirectResponse()
        update.urllib.request.urlopen = fake_urlopen
        release = update._latest_release("owner/fork")
    finally:
        update.urllib.request.urlopen = old_urlopen
    check("update checks do not spend the anonymous GitHub API quota",
          requested == [("https://github.com/owner/fork/releases/latest", 12)])
    check("the redirect supplies the latest version",
          release["tag_name"] == "v9.9.9")
    check("public asset links are built from the published tag",
          release["assets"][update.ASSET] ==
          "https://github.com/owner/fork/releases/download/v9.9.9/" +
          update.ASSET)
    with tempfile.TemporaryDirectory() as tmp:
        info = {"repository": "owner/fork", "version": "9.9.9"}
        with open(os.path.join(tmp, "build-info.json"), "w",
                  encoding="utf-8-sig") as f:
            json.dump(info, f)
        old_meipass = getattr(sys, "_MEIPASS", None)
        sys._MEIPASS = tmp
        try:
            check("release metadata from older PowerShell BOMs is accepted",
                  update._build_info() == info)
        finally:
            if old_meipass is None:
                del sys._MEIPASS
            else:
                sys._MEIPASS = old_meipass

        broken_root = os.path.join(tmp, "half-rolled-back")
        previous_updater = os.path.join(broken_root + ".previous", "updater")
        os.makedirs(previous_updater)
        open(os.path.join(previous_updater, "KaraokeUpdater.exe"), "wb").write(b"updater")
        check("a half-rollback can recover its updater from the complete snapshot",
              update._updater_source(broken_root) == previous_updater)

        good = os.path.join(tmp, "good.zip")
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("KaraokeStudio/KaraokeStudio.exe", b"exe")
            z.writestr("KaraokeStudio/_internal/ui.js", b"js")
        out = os.path.join(tmp, "out")
        app = updater.safe_extract(good, out)
        check("a release archive is unpacked",
              os.path.isfile(os.path.join(app, "KaraokeStudio.exe")))

        bad = os.path.join(tmp, "bad.zip")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../outside.txt", b"no")
        try:
            updater.safe_extract(bad, os.path.join(tmp, "bad-out"))
            escaped = True
        except RuntimeError:
            escaped = False
        check("an update archive cannot escape its staging folder", not escaped)

        old, new = os.path.join(tmp, "old"), os.path.join(tmp, "new")
        os.makedirs(os.path.join(old, "projects"))
        os.makedirs(os.path.join(old, "output")); os.makedirs(new)
        with open(os.path.join(old, "projects", "song.json"), "w") as f:
            f.write("song")
        with open(os.path.join(old, "settings.ini"), "w") as f:
            f.write("settings")
        with open(os.path.join(old, "output", "finished.mp4"), "wb") as f:
            f.write(b"video")
        updater.preserve(old, new)
        check("updates preserve songs",
              os.path.isfile(os.path.join(new, "projects", "song.json")))
        check("updates preserve settings",
              os.path.isfile(os.path.join(new, "settings.ini")))
        check("updates preserve finished files",
              os.path.isfile(os.path.join(new, "output", "finished.mp4")))

        # A browser or terminal may keep the install directory itself open.
        # Replacing files inside it must still work, and user data must never
        # move through the rollback area.
        locked = os.path.join(tmp, "locked-install")
        staged = os.path.join(tmp, "staged-app")
        backup = os.path.join(tmp, "locked-backup")
        os.makedirs(os.path.join(locked, "_internal"))
        os.makedirs(os.path.join(locked, "projects"))
        os.makedirs(os.path.join(locked, "output"))
        os.makedirs(os.path.join(staged, "_internal"))
        open(os.path.join(locked, "KaraokeStudio.exe"), "wb").write(b"old")
        open(os.path.join(locked, "_internal", "obsolete.dll"), "wb").write(b"old")
        open(os.path.join(locked, "projects", "song.json"), "wb").write(b"song")
        open(os.path.join(locked, "output", "video.mp4"), "wb").write(b"video")
        open(os.path.join(staged, "KaraokeStudio.exe"), "wb").write(b"new")
        open(os.path.join(staged, "_internal", "current.dll"), "wb").write(b"new")
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                                  cwd=locked)
        try:
            updater.replace_in_place(staged, locked, backup)
        finally:
            holder.terminate(); holder.wait()
        check("an open install root does not prevent an in-place update",
              open(os.path.join(locked, "KaraokeStudio.exe"), "rb").read() == b"new")
        check("obsolete application files are removed",
              not os.path.exists(os.path.join(locked, "_internal", "obsolete.dll"))
              and os.path.isfile(os.path.join(locked, "_internal", "current.dll")))
        check("in-place updates never move projects or finished files",
              os.path.isfile(os.path.join(locked, "projects", "song.json"))
              and os.path.isfile(os.path.join(locked, "output", "video.mp4")))

        # Defender and Explorer can retain an image/DLL for a fraction of a
        # second after the process exits.  One temporary denial must not turn
        # a sound update into a broken rollback.
        retry_install = os.path.join(tmp, "retry-install")
        retry_stage = os.path.join(tmp, "retry-stage")
        retry_backup = os.path.join(tmp, "retry-backup")
        os.makedirs(retry_install); os.makedirs(retry_stage)
        retry_exe = os.path.join(retry_install, "KaraokeStudio.exe")
        open(retry_exe, "wb").write(b"old")
        open(os.path.join(retry_stage, "KaraokeStudio.exe"), "wb").write(b"new")
        real_remove = updater._remove
        denied = [False]
        try:
            def deny_once(path):
                if path == retry_exe and not denied[0]:
                    denied[0] = True
                    raise PermissionError(13, "temporarily locked", path)
                return real_remove(path)
            updater._remove = deny_once
            updater.replace_in_place(retry_stage, retry_install, retry_backup)
        finally:
            updater._remove = real_remove
        check("a temporary executable lock is retried",
              denied[0] and open(retry_exe, "rb").read() == b"new")

        if os.name == "nt":
            # Use a real Windows no-sharing handle, the same kind of lock an
            # EXE image or an antivirus scan leaves behind after shutdown.
            from ctypes import wintypes
            probe = os.path.join(tmp, "windows-lock-probe.exe")
            open(probe, "wb").write(b"probe")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.argtypes = (
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                wintypes.HANDLE)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.CreateFileW(probe, 0x80000000, 0, None,
                                          3, 0, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            released = threading.Timer(0.6, kernel32.CloseHandle,
                                       args=(handle,))
            released.start()
            started = time.monotonic()
            updater._remove_retry(probe)
            elapsed = time.monotonic() - started
            released.join()
            check("a real Windows sharing lock is waited out",
                  not os.path.exists(probe) and elapsed >= 0.4)

        # Even a persistent lock must not stop rollback before updater/other
        # entries have been restored.  This is the exact shape of the damaged
        # 4.47.0 installation reported in the field.
        partial = os.path.join(tmp, "partial-install")
        partial_stage = os.path.join(tmp, "partial-stage")
        partial_backup = os.path.join(tmp, "partial-backup")
        os.makedirs(os.path.join(partial, "updater")); os.makedirs(partial_stage)
        partial_exe = os.path.join(partial, "KaraokeStudio.exe")
        open(os.path.join(partial, "updater", "KaraokeUpdater.exe"), "wb").write(b"old-updater")
        open(partial_exe, "wb").write(b"old")
        open(os.path.join(partial_stage, "KaraokeStudio.exe"), "wb").write(b"new")
        real_seconds = updater.RETRY_SECONDS
        try:
            updater.RETRY_SECONDS = 0
            def keep_exe_locked(path):
                if path == partial_exe:
                    raise PermissionError(13, "still locked", path)
                return real_remove(path)
            updater._remove = keep_exe_locked
            try:
                updater.replace_in_place(partial_stage, partial, partial_backup)
            except PermissionError:
                pass
        finally:
            updater._remove = real_remove
            updater.RETRY_SECONDS = real_seconds
        check("a locked executable does not prevent restoring the updater",
              open(os.path.join(partial, "updater", "KaraokeUpdater.exe"), "rb").read()
              == b"old-updater")

        # If copying the new application fails halfway, the old program comes
        # back while projects/output remain where they were.
        rollback = os.path.join(tmp, "rollback-install")
        staged_bad = os.path.join(tmp, "staged-bad")
        backup_bad = os.path.join(tmp, "rollback-backup")
        os.makedirs(os.path.join(rollback, "projects")); os.makedirs(staged_bad)
        open(os.path.join(rollback, "KaraokeStudio.exe"), "wb").write(b"old")
        open(os.path.join(rollback, "projects", "keep.json"), "wb").write(b"keep")
        open(os.path.join(staged_bad, "KaraokeStudio.exe"), "wb").write(b"new")
        real_copy = updater._copy_entry
        try:
            def fail_new(src, dst):
                if os.path.abspath(src).startswith(os.path.abspath(staged_bad)):
                    raise OSError("simulated copy failure")
                return real_copy(src, dst)
            updater._copy_entry = fail_new
            try:
                updater.replace_in_place(staged_bad, rollback, backup_bad)
            except OSError:
                pass
        finally:
            updater._copy_entry = real_copy
        check("a failed in-place update restores the old application",
              open(os.path.join(rollback, "KaraokeStudio.exe"), "rb").read() == b"old")
        check("rollback leaves project data untouched",
              open(os.path.join(rollback, "projects", "keep.json"), "rb").read() == b"keep")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
