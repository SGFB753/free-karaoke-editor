"""The sound from a link.

yt-dlp does the downloading, ffmpeg pulls the audio out of what came back.
Neither is required for the program to work: without yt-dlp the window says so
and the file picker is still there.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import site
import subprocess
import sys
import sysconfig
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


# YouTube answers a client it does not like with a refusal that says nothing
# about the video: “The page needs to be reloaded”, a format list with nothing
# in it, a bot check. Another client walks straight in, so it is worth asking
# again as a different one instead of handing that to a person as the answer.
CLIENTS = ("", "android", "ios", "tv")

TRY_AGAIN = re.compile(
    r"page needs to be reloaded|sign in to confirm|not a bot|"
    r"format is not available|unable to extract|player response|"
    r"precondition check failed|sabr|failed to extract any player response", re.I)

# What is left to try when every client was refused: almost always the
# downloader itself is older than the site it is talking to.
STALE = ("pip install -U yt-dlp",)


class FetchError(RuntimeError):
    pass


def extra_args() -> list:
    """Whatever the person adds to the downloader themselves.

    A locked-down video needs cookies, and that is not something the program
    can decide for anyone: the way in is `yt-dlp-args` in settings.ini, or
    KARAOKE_YTDLP_ARGS in the environment. For example:
        yt-dlp-args = --cookies-from-browser chrome
    """
    raw = (os.environ.get("KARAOKE_YTDLP_ARGS") or "").strip()
    if not raw:
        app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for ini in (os.path.join(app, "settings.ini"),
                    os.path.join(os.path.dirname(app), "settings.ini")):
            try:
                with open(ini, encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        if key.strip().lower() in ("yt-dlp-args", "ключи-загрузчика"):
                            raw = val.strip()
                            break
            except OSError:
                continue
            if raw:
                break
    try:
        return shlex.split(raw)
    except ValueError:
        return []


def places() -> list:
    """Folders where pip leaves the command when PATH knows nothing about them.

    On macOS `pip install yt-dlp` writes into ~/Library/Python/3.x/bin, which a
    double-clicked window has never heard of; Homebrew has its own two. Looking
    there is the difference between “it works” and “not installed”.
    """
    out = []
    try:
        out.append(sysconfig.get_path("scripts"))
        out.append(sysconfig.get_path("scripts", f"{os.name}_user"))
    except (KeyError, ValueError):
        pass
    try:
        out.append(os.path.join(site.getuserbase(), "bin"))
    except Exception:
        pass
    if sys.executable:
        out.append(os.path.dirname(sys.executable))
    out += ["/opt/homebrew/bin", "/usr/local/bin",
            os.path.expanduser("~/.local/bin")]
    return [p for p in out if p]


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
    for folder in places():                 # installed, but not where PATH looks
        path = os.path.join(folder, "yt-dlp.exe" if os.name == "nt" else "yt-dlp")
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return [path]
    try:                                    # installed as a library, no command
        import yt_dlp  # noqa: F401
    except ImportError:
        return None
    # A Python that cannot say where it lives cannot be asked to run a module;
    # passing that emptiness on gives a crash about NoneType instead of an
    # answer about the song.
    return [sys.executable, "-m", "yt_dlp"] if sys.executable else None


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
    """Why there is nothing to download with, in the words that fit the case."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return tr("yt-dlp is not installed — it is what takes the sound out of a "
                  "link. Install it with: pip install yt-dlp",
                  "Не установлен yt-dlp — он и достаёт звук из ссылки. "
                  "Поставить: pip install yt-dlp")
    # The library is here and the command is not, and this Python cannot even
    # say where it lives itself — so it cannot be asked to run the library.
    return tr("yt-dlp is installed as a library, but the command is nowhere to "
              "be found and this Python cannot say where it lives. Install the "
              "command: pip install -U yt-dlp — or point KARAOKE_YTDLP at it.",
              "yt-dlp стоит как библиотека, но команды нигде нет, а этот Python "
              "не может сказать, где он сам лежит. Поставьте команду: "
              "pip install -U yt-dlp — или укажите путь в KARAOKE_YTDLP.")


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


def _tools(tmp: str) -> tuple:
    """A folder where ffmpeg and ffprobe answer to those very names.

    yt-dlp is handed a folder and looks inside it for “ffmpeg” and “ffprobe”.
    The copy pip installs is one file named after its platform and version, and
    it brings no ffprobe at all — give yt-dlp that folder and it falls over an
    empty path, saying only “expected str, bytes or os.PathLike object, not
    NoneType”, which tells a person nothing about their song.

    Gives back the folder to point at (or None) and whether the sound can be
    pulled out of the video on the spot, which needs ffprobe.
    """
    try:
        ff = AU.ffmpeg()
    except AU.AudioError:
        return None, False
    fp = AU.ffprobe()
    exe = ".exe" if os.name == "nt" else ""
    if (os.path.basename(ff) == "ffmpeg" + exe and fp
            and os.path.basename(fp) == "ffprobe" + exe
            and os.path.dirname(ff) == os.path.dirname(fp)):
        return os.path.dirname(ff), True          # an ordinary install: as is
    # Everything else gets a small folder of its own, with the names yt-dlp
    # expects pointing at whatever was actually found.
    folder = os.path.join(tmp, "bin")
    try:
        os.makedirs(folder, exist_ok=True)
        for src, name in ((ff, "ffmpeg" + exe), (fp, "ffprobe" + exe)):
            if not src:
                continue
            link = os.path.join(folder, name)
            if not os.path.exists(link):      # a second try reuses the folder
                os.symlink(src, link)
    except (OSError, AttributeError, NotImplementedError):
        # No links to be had (Windows without the right, say): better to let
        # yt-dlp look for itself than to point it at half a folder.
        return None, False
    return folder, bool(fp)


def _base_args(cmd: list, tmp: str) -> list:
    args = list(cmd) + [
        "--no-playlist",          # a link that also holds a playlist: one song
        "--newline",              # progress in whole lines, not rewritten ones
        "--no-colors",
        "--retries", "3",
        "--socket-timeout", "30",
        "--max-filesize", f"{MAX_MB}m",
        "--write-info-json",      # the name and the artist, for looking the lyrics up
        "-f", "bestaudio/best",   # no audio-only format on offer: take the video's
        "--restrict-filenames",   # Latin letters, like everywhere else here
        "-o", os.path.join(tmp, "%(title).60s [%(id)s].%(ext)s"),
    ]
    where, can_extract = _tools(tmp)
    if where:                     # a pip-installed ffmpeg is not on PATH
        args += ["--ffmpeg-location", where]
    if can_extract:
        # The sound alone; no format named = no re-encoding. Without ffprobe
        # yt-dlp cannot do this at all, and the video comes down whole — the
        # program takes the sound out of it later anyway.
        args.append("-x")
    return args


def _attempt(args: list, say: Callable, deadline: float) -> tuple:
    """Run the downloader once and give back its code and its last words."""
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        raise FetchError(tr(f"could not start the downloader: {e}",
                            f"не вышло запустить загрузчик: {e}"))
    lines = []
    for line in p.stdout:
        line = line.rstrip()
        if line:
            lines.append(line)
            del lines[:-40]
            say(line)
        if time.time() > deadline:
            p.kill()
            raise FetchError(tr(f"the download took longer than {TIMEOUT // 60} minutes",
                                f"загрузка идёт дольше {TIMEOUT // 60} минут"))
    return p.wait(), lines


def _empty(folder: str) -> None:
    """Wipe what a failed attempt left, so the next one starts on clean ground."""
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            os.remove(path) if os.path.isfile(path) else shutil.rmtree(path, True)
        except OSError:
            pass


def download(url: str, dest_dir: str, log: Optional[Callable] = None) -> dict:
    """Put the sound of `url` into `dest_dir` and say what came out.

    Raises FetchError with something readable: a link that leads nowhere, a
    video that is private or age-walled, no yt-dlp at all. The window shows
    that as it is — there is nothing better to say than what the downloader
    saw.

    A refusal aimed at the client rather than at the video is not passed on
    until every client has been turned away: YouTube says “the page needs to
    be reloaded” to one and hands the sound over to the next.
    """
    say = log or (lambda _m: None)
    url = check_url(url)
    cmd = tool()
    if not cmd:
        raise FetchError(how_to_install())

    os.makedirs(dest_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".fetch-", dir=dest_dir)
    deadline = time.time() + TIMEOUT
    say(tr("Taking the sound from the link…", "Достаю звук по ссылке…"))
    try:
        for i, client in enumerate(CLIENTS):
            args = _base_args(cmd, tmp)
            if client:
                args += ["--extractor-args", f"youtube:player_client={client}"]
            args += extra_args() + ["--", url]
            code, lines = _attempt(args, say, deadline)
            if code == 0:
                break
            reason = _reason(lines, code)
            again = bool(TRY_AGAIN.search("\n".join(lines[-8:])))
            if again and i + 1 < len(CLIENTS):
                say(tr(f"The site turned this client away ({reason}) — "
                       f"asking again as “{CLIENTS[i + 1]}”…",
                       f"Сайт отказал этому клиенту ({reason}) — "
                       f"спрашиваю ещё раз как «{CLIENTS[i + 1]}»…"))
                _empty(tmp)
                continue
            if again:
                raise FetchError(reason + tr(
                    f" — and every player was turned away. The downloader is "
                    f"probably older than the site: {STALE[0]}. A video that "
                    f"asks you to sign in needs cookies — see yt-dlp-args in "
                    f"settings.ini.",
                    f" — и отказано каждому клиенту. Скорее всего загрузчик "
                    f"старше сайта: {STALE[0]}. Видео, которое просит войти, "
                    f"требует куки — см. yt-dlp-args в settings.ini."))
            raise FetchError(reason)
        info = _info(tmp)
        got = _pick(tmp)
        dst = _free_name(dest_dir, os.path.basename(got))
        shutil.move(got, dst)
    except FetchError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        # Not a refusal from the site but a fault of ours: name the kind of it,
        # because “not NoneType” alone leaves nobody anywhere to look.
        raise FetchError(f"{type(e).__name__}: {e}")
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
