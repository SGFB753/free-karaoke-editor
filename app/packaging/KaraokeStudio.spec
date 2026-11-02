# -*- mode: python ; coding: utf-8 -*-
import os
import json
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
APP = os.path.join(ROOT, "app")

datas = [
    (os.path.join(APP, "kstudio", "studio.html"), "kstudio"),
    (os.path.join(APP, "kstudio", "player.html"), "kstudio"),
    (os.path.join(APP, "kstudio", "ui.js"), "kstudio"),
    (os.path.join(APP, "kstudio", "icon.png"), "kstudio"),
    (os.path.join(APP, "kstudio", "icon-32.png"), "kstudio"),
    (os.path.join(APP, "kstudio", "favicon.ico"), "kstudio"),
    (os.path.join(APP, "kstudio", "messages"), os.path.join("kstudio", "messages")),
    (os.path.join(APP, "tools", "video.py"), "tools"),
    (os.path.join(ROOT, "build", "build-info.json"), "."),
]
binaries = []
hiddenimports = []

# These libraries discover plugins, model descriptions or data files at
# runtime.  PyInstaller cannot see those dynamic imports by reading studio.py.
for package in ("demucs", "stable_whisper", "whisper", "yt_dlp", "imageio_ffmpeg",
                "pytubefix", "yt_dlp_ejs"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Optional engine packages live in the separately cached runtime, including
# their Python code: omitting only model weights does not make the core small.
component_exclusions = ["qwen_asr", "transformers", "nagisa", "soynlp"]
exclusion_file = os.path.join(ROOT, "build", "component-exclusions.json")
if os.path.isfile(exclusion_file):
    with open(exclusion_file, encoding="utf-8") as source:
        component_exclusions += json.load(source)
component_exclusions = [name for name in component_exclusions if name != "nodejs_wheel"]
hiddenimports += ["nodejs_wheel", "nodejs_wheel.executable"]

for distribution in ("demucs", "stable-ts", "openai-whisper", "yt-dlp",
                     "soundfile", "imageio-ffmpeg", "yt-dlp-ejs"):
    try:
        datas += copy_metadata(distribution, recursive=True)
    except Exception:
        pass

hiddenimports += collect_submodules("demucs")
hiddenimports += collect_submodules("yt_dlp")
# tools/video.py is loaded from its file at runtime, so Analysis cannot see
# the PIL modules imported inside its rendering functions.  Keep the whole
# small Pillow module family; otherwise the EXE builds successfully and only
# fails later on ImageEnhance/ImageDraw when a person asks for an MP4.
hiddenimports += collect_submodules("PIL")
# Cached Qwen packages are ordinary .py files. Their standard-library imports
# are not visible to the core's static graph (for example filecmp in HF).
hiddenimports += [name for name in sys.stdlib_module_names if name not in
                  {"antigravity", "this", "tkinter", "turtle", "idlelib", "ensurepip", "venv", "_tkinter"}
                  and not name.startswith("_test")]
for package in ("email", "http", "urllib", "importlib", "xml", "html", "concurrent", "multiprocessing"):
    hiddenimports += collect_submodules(package)

# Model weights are deliberately not part of a normal release.  Whisper and
# Demucs already download the selected weight once into the user's cache and
# reuse it afterwards.  A maintainer may still request a fully offline build;
# the explicit environment flag prevents a populated CI/developer cache from
# accidentally making every ordinary ZIP a gigabyte larger.
if os.environ.get("KARAOKE_BUNDLE_MODELS") == "1":
    # Qwen weights always download separately into the persistent user cache,
    # including offline builds of the other engines.
    whisper_cache = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
    small_model = os.path.join(whisper_cache, "small.pt")
    if os.path.isfile(small_model):
        datas.append((small_model, os.path.join("models", "whisper")))

    torch_cache = os.path.join(os.path.expanduser("~"), ".cache", "torch")
    if os.path.isdir(torch_cache):
        datas.append((torch_cache, os.path.join("models", "torch")))

    hf_hub = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if os.path.isdir(hf_hub):
        for name in os.listdir(hf_hub):
            if name.startswith("models--adefossez--HTDemucs"):
                datas.append((os.path.join(hf_hub, name),
                              os.path.join("models", "huggingface", "hub", name)))

a = Analysis(
    [os.path.join(APP, "studio.py")],
    pathex=[APP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.tests", "numpy.tests"] + component_exclusions,
    noarchive=False,
)

# PyInstaller's torch hook copies the distribution metadata recursively.  New
# torch wheels contain a deeply nested third-party license tree whose paths
# exceed Explorer's legacy extraction limit below Downloads/Desktop.  Preserve
# all notices in one short-path text file; the application does not need their
# original directory layout at runtime.
torch_notices = []
kept_datas = []
for entry in a.datas:
    destination = entry[0].replace("/", "\\").lower()
    if (destination.startswith("torch-") and
            ".dist-info\\licenses\\third_party\\" in destination):
        torch_notices.append(entry)
    else:
        kept_datas.append(entry)
if torch_notices:
    notices_path = os.path.join(ROOT, "build", "THIRD-PARTY-NOTICES-PYTORCH.txt")
    os.makedirs(os.path.dirname(notices_path), exist_ok=True)
    with open(notices_path, "w", encoding="utf-8", newline="\n") as notices:
        for destination, source, _kind in sorted(torch_notices):
            notices.write("\n\n===== " + destination.replace("\\", "/") + " =====\n\n")
            with open(source, encoding="utf-8", errors="replace") as license_file:
                notices.write(license_file.read())
    kept_datas.append(("THIRD-PARTY-NOTICES-PYTORCH.txt", notices_path, "DATA"))
a.datas = kept_datas
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="KaraokeStudio", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=os.path.join(APP, "packaging", "KaraokeStudio.ico"),
    manifest=os.path.join(APP, "packaging", "KaraokeStudio.manifest"),
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False,
    upx_exclude=[], name="KaraokeStudio",
)
