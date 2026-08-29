"""Signed-by-checksum updates for the packaged Windows application.

Source checkouts are deliberately never rewritten.  A frozen release knows
the GitHub repository it was built from, downloads the matching release ZIP,
checks its SHA-256 file and hands replacement to the tiny external updater.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from typing import Callable, Dict, Optional

from . import __version__
from .i18n import tr

ASSET = "KaraokeStudio-windows-x64.zip"
CHECKSUM = ASSET + ".sha256"
MAX_DOWNLOAD = 2_100_000_000


def _bundle_root() -> str:
    return os.path.dirname(os.path.abspath(sys.executable))


def _build_info() -> Dict:
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "build-info.json"))
    candidates.append(os.path.join(_bundle_root(), "build-info.json"))
    for path in candidates:
        try:
            # utf-8-sig accepts both normal JSON and the BOM emitted by older
            # Windows PowerShell release scripts.
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def repository() -> str:
    value = (os.environ.get("KARAOKE_UPDATE_REPOSITORY")
             or _build_info().get("repository") or "").strip()
    return value if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) else ""


def supported() -> bool:
    return bool(getattr(sys, "frozen", False) and os.name == "nt" and repository())


def _version_tuple(value: str):
    nums = re.findall(r"\d+", (value or "").lstrip("vV"))
    return tuple(int(n) for n in nums[:4]) or (0,)


def _request(url: str):
    return urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"KaraokeStudio/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    })


def latest() -> Dict:
    """Return release metadata safe to expose to the local UI."""
    if not supported():
        return {"supported": False, "current": __version__}
    repo = repository()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    with urllib.request.urlopen(_request(url), timeout=12) as response:
        release = json.load(response)
    assets = {a.get("name"): a.get("browser_download_url")
              for a in release.get("assets") or []}
    version = str(release.get("tag_name") or "").lstrip("vV")
    available = (_version_tuple(version) > _version_tuple(__version__)
                 and bool(assets.get(ASSET)) and bool(assets.get(CHECKSUM)))
    return {"supported": True, "available": available,
            "current": __version__, "version": version,
            "page": release.get("html_url") or "", "repository": repo,
            "_zip": assets.get(ASSET), "_sha": assets.get(CHECKSUM)}


def public(info: Dict) -> Dict:
    return {k: v for k, v in info.items() if not k.startswith("_")}


def _download(url: str, path: str, log: Callable[[str], None], limit: int) -> None:
    req = _request(url)
    with urllib.request.urlopen(req, timeout=45) as response, open(path, "wb") as out:
        announced = int(response.headers.get("Content-Length") or 0)
        if announced > limit:
            raise RuntimeError(tr("the update is unexpectedly large",
                                  "обновление неожиданно большое"))
        done, next_note = 0, 64 * 1024 * 1024
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > limit:
                raise RuntimeError(tr("the update is unexpectedly large",
                                      "обновление неожиданно большое"))
            out.write(chunk)
            if done >= next_note:
                log(tr(f"Downloaded {done // 1024 // 1024} MB…",
                       f"Скачано {done // 1024 // 1024} МБ…"))
                next_note += 64 * 1024 * 1024


def download(log: Callable[[str], None]) -> Dict:
    info = latest()
    if not info.get("available"):
        raise RuntimeError(tr("there is no newer release",
                              "новой версии нет"))
    temp = tempfile.mkdtemp(prefix="karaoke-update-")
    archive = os.path.join(temp, ASSET)
    checksum = os.path.join(temp, CHECKSUM)
    try:
        log(tr(f"Downloading Karaoke Studio {info['version']}…",
               f"Скачиваю Karaoke Studio {info['version']}…"))
        _download(info["_sha"], checksum, log, 64 * 1024)
        _download(info["_zip"], archive, log, MAX_DOWNLOAD)
        with open(checksum, encoding="ascii", errors="ignore") as f:
            expected = re.search(r"\b[0-9a-fA-F]{64}\b", f.read())
        if not expected:
            raise RuntimeError(tr("the release has a bad checksum file",
                                  "в релизе неверный файл контрольной суммы"))
        digest = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected.group(0).lower():
            raise RuntimeError(tr("the update checksum does not match",
                                  "контрольная сумма обновления не совпала"))
        log(tr("The update is verified and ready.",
               "Обновление проверено и готово."))
        return {"path": archive, "version": info["version"]}
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def launch(archive: str) -> None:
    """Run a copy of the updater outside the directory it will replace."""
    if not supported() or not os.path.isfile(archive):
        raise RuntimeError(tr("the downloaded update is gone",
                              "скачанное обновление пропало"))
    source = os.path.join(_bundle_root(), "KaraokeUpdater.exe")
    if not os.path.isfile(source):
        raise RuntimeError(tr("KaraokeUpdater.exe is missing from the installation",
                              "в установленной программе нет KaraokeUpdater.exe"))
    temp_dir = tempfile.mkdtemp(prefix="karaoke-updater-")
    updater = os.path.join(temp_dir, "KaraokeUpdater.exe")
    shutil.copy2(source, updater)
    subprocess.Popen([updater, "--pid", str(os.getpid()), "--archive", archive,
                      "--install", _bundle_root(), "--exe", "KaraokeStudio.exe"],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True)
