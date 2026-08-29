"""Small, offline checks for release/update machinery."""

from __future__ import annotations

import os
import json
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio import update
import updater


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

    build_path = os.path.join(ROOT, "packaging", "build-windows.ps1")
    with open(build_path, encoding="utf-8-sig") as f:
        build_script = f.read()
    check("finished EXE gets a video dependency smoke test",
          "--internal-package-smoke" in build_script)

    workflow_path = os.path.join(os.path.dirname(ROOT), ".github", "workflows",
                                 "windows-release.yml")
    with open(workflow_path, encoding="utf-8") as f:
        release_workflow = f.read()
    check("normal GitHub releases leave model weights in the user cache",
          "-WithModels" not in release_workflow)

    check("a source checkout cannot overwrite itself", not update.supported())
    check("versions compare numerically",
          update._version_tuple("v4.10.0") > update._version_tuple("4.9.9"))
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
        os.makedirs(os.path.join(old, "projects")); os.makedirs(new)
        with open(os.path.join(old, "projects", "song.json"), "w") as f:
            f.write("song")
        with open(os.path.join(old, "settings.ini"), "w") as f:
            f.write("settings")
        updater.preserve(old, new)
        check("updates preserve songs",
              os.path.isfile(os.path.join(new, "projects", "song.json")))
        check("updates preserve settings",
              os.path.isfile(os.path.join(new, "settings.ini")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
