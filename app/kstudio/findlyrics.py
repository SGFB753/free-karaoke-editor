"""Looking the lyrics up by the name of the song.

The source is LRCLIB (lrclib.net) — an open library that asks for no key and
no account. Genius and Musixmatch both want a registered token, so they are
not built in: a suggestion has to work on the first run, without a signup.

Whatever comes back is a suggestion and nothing more. The words are shown for
a person to read before they are used, because a wrong text lays wrong lines
over the whole song.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .i18n import tr

BASE = (os.environ.get("KARAOKE_LYRICS_API") or "https://lrclib.net").rstrip("/")
TIMEOUT = int(os.environ.get("KARAOKE_LYRICS_TIMEOUT") or 12)
SOURCE = "LRCLIB"

# [00:12.34] in front of every line: that is a timed text, and the timing is
# ours to make — the words are what is wanted here.
LRC_TAG = re.compile(r"^\s*(\[[0-9]{1,3}:[0-9]{2}(?:[.:][0-9]{1,3})?\]\s*)+")
# The first stamp of a line, the one that says when it is sung.
ONE_TAG = re.compile(r"^\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


class LyricsError(RuntimeError):
    pass


def timed(item: dict, every: int = 4, gap: float = 4.0) -> str:
    """The words of a found record with a few of the library's own times.

    A synced record carries “[02:27.10]” for every single line. Kept on every
    line they stop being pegs and become the timing itself: the model is never
    asked, the words inside a line are merely spread — and a record made from
    another master drifts, with the drift baked in for good.

    So they are kept sparsely: at the start, wherever a real pause opens
    (`gap` seconds — the places where a line goes wandering), and otherwise
    once `every` lines have gone by without one. Between them the song is
    aligned as usual, so the places are the library's and the words are the
    model's.
    """
    synced = (item.get("syncedLyrics") or "").strip()
    if not synced:
        return ""
    out, prev, since, pegged = [], None, 0, False
    for raw in synced.splitlines():
        m = ONE_TAG.match(raw.strip())
        words = LRC_TAG.sub("", raw).strip()
        if not words:
            # An empty stamp marks a pause: it holds nothing to sing, so it
            # cannot be a peg. The pause still shows — as the distance to the
            # next line that does have words.
            continue
        t = None
        if m:
            t = int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))
        take = t is not None and (not pegged or since >= every
                                  or (prev is not None and t - prev >= gap))
        if take:
            out.append(f"[{int(t // 60)}:{t % 60:05.2f}] {words}")
            since, pegged = 0, True
        else:
            out.append(words)
            since += 1
        if t is not None:
            prev = t
    return "\n".join(out).strip()


def plain(item: dict) -> str:
    """The words of a found record, timed or not."""
    text = (item.get("plainLyrics") or "").strip()
    if text:
        return text
    synced = (item.get("syncedLyrics") or "").strip()
    if not synced:
        return ""
    lines = [LRC_TAG.sub("", ln).strip() for ln in synced.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _ask(path: str, params: dict) -> list:
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        # LRCLIB asks callers to name themselves, and it is only fair.
        "User-Agent": f"KaraokeStudio/{__version__} (open source karaoke maker)",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise LyricsError(tr(f"{SOURCE} answered with {e.code}",
                             f"{SOURCE} ответил кодом {e.code}"))
    except (urllib.error.URLError, OSError) as e:
        raise LyricsError(tr(f"could not reach {SOURCE}: {e.reason if hasattr(e, 'reason') else e}",
                             f"не достучаться до {SOURCE}: {e.reason if hasattr(e, 'reason') else e}"))
    except ValueError:
        raise LyricsError(tr(f"{SOURCE} answered with something that is not a list of songs",
                             f"{SOURCE} ответил не списком песен"))
    return data if isinstance(data, list) else [data]


def search(track: str, artist: str = "", duration: float = 0, limit: int = 5) -> list:
    """Songs whose words might be the ones. Nearest length first.

    A record with no words in it is dropped: it would look like a suggestion
    and then turn out to be empty.
    """
    track = (track or "").strip()
    if not track:
        raise LyricsError(tr("There is no song name to look for.",
                             "Нет названия песни, по которому искать."))
    params = {"track_name": track}
    if artist.strip():
        params["artist_name"] = artist.strip()
    found = _ask("/api/search", params)
    if not found and artist.strip():
        # The artist from the video tags can be a channel name; without it the
        # library often finds the song anyway.
        found = _ask("/api/search", {"q": track})
    out = []
    for item in found:
        words = plain(item)
        if not words:
            continue
        # The same words with the library's own times, when it has them: the
        # window offers to take them as pegs.
        pegged = timed(item)
        out.append({"source": SOURCE,
                    "title": item.get("trackName") or track,
                    "artist": item.get("artistName") or "",
                    "duration": item.get("duration") or 0,
                    "lines": len([ln for ln in words.splitlines() if ln.strip()]),
                    "text": words,
                    "timed": bool(pegged),
                    "textTimed": pegged})
    if duration:
        # Same name, different recording: a live take runs minutes longer, and
        # its words are laid out differently.
        out.sort(key=lambda x: abs((x["duration"] or 0) - duration))
    return out[:limit]
