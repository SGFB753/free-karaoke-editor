"""The sound from a link.

yt-dlp does the downloading, ffmpeg pulls the audio out of what came back.
Neither is required for the program to work: without yt-dlp the window says so
and the file picker is still there.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional

from . import audio as AU
from .i18n import tr

# A download that never ends is worse than one that fails: the window would sit
# on it forever. Fifteen minutes is far more than audio ever needs.
TIMEOUT = int(os.environ.get("KARAOKE_FETCH_TIMEOUT") or 900)
MAX_MB = 600                      # the same ceiling a dropped file has

# yt-dlp leaves these behind while it works; they are not the download.
LEFTOVERS = (".part", ".ytdl", ".temp", ".info.json")

# “Song (Official Video) [HD]” is a name for a page, not for a song: the words
# in brackets and the marks that come with them only get in the way of looking
# the lyrics up.
NOISE = re.compile(
    r"""[\(\[]\s*
        (?:official\s*|music\s*|the\s*)*
        (?:video|audio|lyrics?|lyric\s*video|visuali[sz]er|clip|mv|live|
           hd|hq|4k|8k|full\s*hd|remaster(?:ed)?(?:\s*\d{4})?|
           audio\s*only|sound|explicit|cover|karaoke)
        [^)\]]*[\)\]]""",
    re.I | re.X)


class FetchError(RuntimeError):
    pass


def tool() -> Optional[list]:
    """The command that downloads, or None if there is nothing to run.

    KARAOKE_YTDLP comes first: it is how a person points at their own copy —
    and how the checks put a stand-in there instead of the real internet.
    """
    own = (os.environ.get("KARAOKE_YTDLP") or "").strip()
    if own:
        return [own]
    found = shutil.which("yt-dlp")
    if found:
        return [found]
    try:                                    # installed as a library, no command
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        return None


def available() -> bool:
    return tool() is not None


def check_url(url: str) -> str:
    """Only an ordinary web link, and never something that reads as an option."""
    url = (url or "").strip()
    if not url:
        raise FetchError(tr("No link given.", "Ссылка не введена."))
    if not re.match(r"^https?://", url, re.I):
        raise FetchError(tr("A link has to start with http:// or https://",
                            "Ссылка должна начинаться с http:// или https://"))
    return url


def how_to_install() -> str:
    return tr("yt-dlp is not installed — it is what takes the sound out of a "
              "link. Install it with: pip install yt-dlp",
              "Не установлен yt-dlp — он и достаёт звук из ссылки. "
              "Поставить: pip install yt-dlp")


def _reason(lines: list, code: int) -> str:
    """What to show a person out of everything the downloader said."""
    for line in reversed(lines):
        s = line.strip()
        if s.upper().startswith("ERROR:"):
            # “ERROR: [youtube] zzz123: Video unavailable” — the tail is the
            # point; the site and the id of the video say nothing to anyone.
            s = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?", "", s, flags=re.I)
            return re.sub(r"^[\w-]{6,}:\s*", "", s).strip()
    for line in reversed(lines):
        if line.strip():
            return line.strip()
    return tr(f"the downloader stopped with code {code}",
              f"загрузчик завершился с кодом {code}")


def clean_title(title: str) -> str:
    """The name of the song as a person would write it, without page furniture."""
    out = NOISE.sub("", title or "")
    out = re.sub(r"\s*\|.*$", "", out)              # “Song | Artist | Label”
    out = re.sub(r"\s*[-–—]\s*topic\s*$", "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" -–—_")


def split_name(title: str, artist: str = "") -> tuple:
    """Artist and song out of what the video is called.

    yt-dlp knows the two apart only when the upload carries the tags; the rest
    of the time there is “Artist - Song” and nothing else.
    """
    title = clean_title(title)
    if artist:
        # the same dash form, with the artist already known from the tags
        head = re.match(r"^\s*" + re.escape(artist) + r"\s*[-–—]\s*(.+)$", title, re.I)
        return artist.strip(), (head.group(1).strip() if head else title)
    parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    if len(parts) == 2 and all(p.strip() for p in parts):
        return parts[0].strip(), parts[1].strip()
    return "", title


def _info(folder: str) -> dict:
    """What yt-dlp wrote down about the video, if it wrote anything."""
    for name in os.listdir(folder):
        if name.endswith(".info.json"):
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    return json.load(f) or {}
            except (OSError, ValueError):
                return {}
    return {}


def _pick(folder: str) -> str:
    """What was downloaded: the biggest finished file in the folder."""
    got = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and not name.endswith(LEFTOVERS):
            got.append((os.path.getsize(path), path))
    if not got:
        raise FetchError(tr("Nothing was downloaded.", "Ничего не скачалось."))
    return max(got)[1]


def _free_name(folder: str, name: str) -> str:
    dst = os.path.join(folder, name)
    stem, ext = os.path.splitext(dst)
    n = 2
    while os.path.exists(dst):
        dst = f"{stem}-{n}{ext}"
        n += 1
    return dst


def download(url: str, dest_dir: str, log: Optional[Callable] = None) -> dict:
    """Put the sound of `url` into `dest_dir` and say what came out.

    Raises FetchError with something readable: a link that leads nowhere, a
    video that is private or age-walled, no yt-dlp at all. The window shows
    that as it is — there is nothing better to say than what the downloader
    saw.
    """
    say = log or (lambda _m: None)
    url = check_url(url)
    cmd = tool()
    if not cmd:
        raise FetchError(how_to_install())

    os.makedirs(dest_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".fetch-", dir=dest_dir)
    args = list(cmd) + [
        "--no-playlist",          # a link that also holds a playlist: one song
        "--newline",              # progress in whole lines, not rewritten ones
        "--no-colors",
        "--retries", "3",
        "--socket-timeout", "30",
        "--max-filesize", f"{MAX_MB}m",
        "--write-info-json",      # the name and the artist, for looking the lyrics up
        "-f", "bestaudio/best",
        "-x",                     # the sound alone; no format given = no re-encoding
        "--restrict-filenames",   # Latin letters, like everywhere else here
        "-o", os.path.join(tmp, "%(title).60s [%(id)s].%(ext)s"),
    ]
    try:                          # a pip-installed ffmpeg is not on PATH
        args += ["--ffmpeg-location", os.path.dirname(AU.ffmpeg())]
    except AU.AudioError:
        pass
    args += ["--", url]

    say(tr("Taking the sound from the link…", "Достаю звук по ссылке…"))
    lines = []
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError(tr(f"could not start the downloader: {e}",
                            f"не вышло запустить загрузчик: {e}"))

    started = time.time()
    try:
        for line in p.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                del lines[:-40]
                say(line)
            if time.time() - started > TIMEOUT:
                p.kill()
                raise FetchError(tr(f"the download took longer than {TIMEOUT // 60} minutes",
                                    f"загрузка идёт дольше {TIMEOUT // 60} минут"))
        code = p.wait()
        if code != 0:
            raise FetchError(_reason(lines, code))
        info = _info(tmp)
        got = _pick(tmp)
        dst = _free_name(dest_dir, os.path.basename(got))
        shutil.move(got, dst)
    except FetchError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError(str(e))
    shutil.rmtree(tmp, ignore_errors=True)

    mb = os.path.getsize(dst) / 1024 / 1024
    say(tr(f"Got it: {os.path.basename(dst)} ({mb:.1f} MB)",
           f"Готово: {os.path.basename(dst)} ({mb:.1f} МБ)"))
    shown = info.get("title") or os.path.splitext(os.path.basename(dst))[0]
    artist, track = split_name(shown, info.get("artist") or info.get("creator") or "")
    if info.get("track"):
        track = info["track"]
    return {"path": dst, "name": os.path.basename(dst),
            "title": clean_title(shown), "track": track, "artist": artist,
            "duration": info.get("duration") or 0}
