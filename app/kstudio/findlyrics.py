"""Looking the lyrics up by the name of the song.

LRCLIB (lrclib.net) is open, fast, and can supply useful line timings. Genius
is also searched through the same public search its web site uses; no account
or API token is required. Results from both are offered so a timed record does
not hide a better version of the words.

Whatever comes back is a suggestion and nothing more. The words are shown for
a person to read before they are used, because a wrong text lays wrong lines
over the whole song.
"""

from __future__ import annotations

import json
import os
import re
import difflib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .i18n import tr

BASE = (os.environ.get("KARAOKE_LYRICS_API") or "https://lrclib.net").rstrip("/")
GENIUS_BASE = (os.environ.get("KARAOKE_GENIUS_URL") or "https://genius.com").rstrip("/")
TIMEOUT = int(os.environ.get("KARAOKE_LYRICS_TIMEOUT") or 12)
LRCLIB_SOURCE = "LRCLIB"
GENIUS_SOURCE = "Genius"
SOURCE = "LRCLIB / Genius"
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 Chrome/138.0 Safari/537.36")

# [00:12.34] in front of every line: that is a timed text, and the timing is
# ours to make — the words are what is wanted here.
LRC_TAG = re.compile(r"^\s*(\[[0-9]{1,3}:[0-9]{2}(?:[.:][0-9]{1,3})?\]\s*)+")
# The first stamp of a line, the one that says when it is sung.
ONE_TAG = re.compile(r"^\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


class LyricsError(RuntimeError):
    pass


def _clean_name(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", (value or "").casefold(), re.UNICODE))


def artist_matches(wanted: str, got: str) -> bool:
    """Whether two artist labels plausibly name the same act.

    Video metadata often says ``MickeyMouse`` while a lyrics site says
    ``MickeyMouse (RUS)``; spaces, punctuation and such suffixes must not turn
    that into a mismatch. A completely different act with the same song title
    must not be offered as if it were the requested recording.
    """
    wanted, got = _clean_name(wanted), _clean_name(got)
    if not wanted:
        return True
    if not got:
        return False
    a, b = wanted.replace(" ", ""), got.replace(" ", "")
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.68


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
        raise LyricsError(tr(f"{LRCLIB_SOURCE} answered with {e.code}",
                             f"{LRCLIB_SOURCE} ответил кодом {e.code}"))
    except (urllib.error.URLError, OSError) as e:
        raise LyricsError(tr(f"could not reach {LRCLIB_SOURCE}: {e.reason if hasattr(e, 'reason') else e}",
                             f"не достучаться до {LRCLIB_SOURCE}: {e.reason if hasattr(e, 'reason') else e}"))
    except ValueError:
        raise LyricsError(tr(f"{LRCLIB_SOURCE} answered with something that is not a list of songs",
                             f"{LRCLIB_SOURCE} ответил не списком песен"))
    return data if isinstance(data, list) else [data]


def _search_lrclib(track: str, artist: str, duration: float, limit: int) -> list:
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
        found_artist = item.get("artistName") or ""
        if artist.strip() and not artist_matches(artist, found_artist):
            continue
        # The same words with the library's own times, when it has them: the
        # window offers to take them as pegs.
        pegged = timed(item)
        out.append({"source": LRCLIB_SOURCE,
                    "title": item.get("trackName") or track,
                    "artist": found_artist,
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


class _GeniusPage(HTMLParser):
    """Text inside Genius' stable data-lyrics-container elements."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.depth and attrs.get("data-lyrics-container") == "true":
            if self.parts and self.parts[-1] != "\n":
                self.parts.append("\n")
            self.depth = 1
            return
        if self.depth:
            if tag == "br":
                self.parts.append("\n")
                return
            if tag not in ("img", "input", "meta", "link", "hr"):
                self.depth += 1
            if tag in ("p", "div"):
                self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if self.depth and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in ("p", "div") and self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")
        self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts).replace("\r", "")
        text = text.replace("\u00a0", " ").replace("\u2005", " ")
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        # Genius places its small “Embed” control at the end of the container.
        text = re.sub(r"\s*\d*Embed\s*$", "", text, flags=re.I).strip()
        lines = text.splitlines()
        sections = [i for i, line in enumerate(lines)
                    if re.match(r"^\s*\[[^\]]+\]\s*$", line)]
        if sections:
            start = sections[0]
            # “[Текст песни «…»]” is a page caption, not a sung section. The
            # actual [Куплет]/[Verse] immediately after it is the useful start.
            caption = lines[start].strip("[] ").casefold()
            if ("текст песни" in caption or caption.endswith(" lyrics")) \
                    and len(sections) > 1:
                start = sections[1]
            text = "\n".join(lines[start:]).strip()
        else:
            # Some pages are one continuous verse with no [Verse] headings.
            # Their small page title is still present before the first word.
            heading = next((i for i, line in enumerate(lines[:8])
                            if re.search(r"\bLyrics\s*$", line, re.I)), None)
            if heading is not None and heading + 1 < len(lines):
                text = "\n".join(lines[heading + 1:]).strip()
        return text


def _genius_get(url: str, accept: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": WEB_UA,
        "Accept": accept,
        "Referer": GENIUS_BASE + "/",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return b""
        raise LyricsError(tr(f"{GENIUS_SOURCE} answered with {e.code}",
                             f"{GENIUS_SOURCE} ответил кодом {e.code}"))
    except (urllib.error.URLError, OSError) as e:
        why = e.reason if hasattr(e, "reason") else e
        raise LyricsError(tr(f"could not reach {GENIUS_SOURCE}: {why}",
                             f"не достучаться до {GENIUS_SOURCE}: {why}"))


def genius_page(url: str) -> str:
    raw = _genius_get(url, "text/html,application/xhtml+xml")
    if not raw:
        return ""
    parser = _GeniusPage()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return parser.text()


def search_genius(track: str, artist: str = "", limit: int = 5) -> list:
    candidates, seen = [], set()
    simple_track = re.sub(r"\s*[\[(][^)\]]*[)\]]", "", track).strip()
    queries = []
    for title in (track.strip(), simple_track):
        query = " ".join(x for x in (artist.strip(), title) if x)
        if query and query not in queries:
            queries.append(query)
    for query in queries:
        url = GENIUS_BASE + "/api/search/multi?" + urllib.parse.urlencode({"q": query})
        raw = _genius_get(url, "application/json, text/plain, */*")
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            sections = payload.get("response", {}).get("sections", [])
        except (ValueError, AttributeError):
            raise LyricsError(tr("Genius answered with invalid search results",
                                 "Genius ответил непонятными результатами поиска"))
        for section in sections:
            for hit in section.get("hits", []) if isinstance(section, dict) else []:
                item = hit.get("result", {}) if isinstance(hit, dict) else {}
                page = item.get("url") or ""
                if (hit.get("type") != "song" or not page or page in seen
                        or not page.startswith(GENIUS_BASE + "/")):
                    continue
                seen.add(page)
                candidates.append(item)

    wanted_title, wanted_artist = _clean_name(track), _clean_name(artist)

    def relevance(item: dict):
        primary = item.get("primary_artist") or {}
        got_artist = _clean_name(primary.get("name") if isinstance(primary, dict) else "")
        got_title = _clean_name(item.get("title") or "")
        artist_score = (difflib.SequenceMatcher(None, wanted_artist, got_artist).ratio()
                        if wanted_artist and got_artist else 0.0)
        title_score = difflib.SequenceMatcher(None, wanted_title, got_title).ratio()
        exact_artist = bool(wanted_artist and
                            (wanted_artist in got_artist or got_artist in wanted_artist))
        unwanted_cover = "cover" in got_title and "cover" not in wanted_title
        return (1 if exact_artist else 0, artist_score,
                0 if unwanted_cover else 1, title_score)

    candidates.sort(key=relevance, reverse=True)
    if artist.strip():
        candidates = [item for item in candidates
                      if artist_matches(
                          artist,
                          ((item.get("primary_artist") or {}).get("name", "")
                           if isinstance(item.get("primary_artist") or {}, dict)
                           else ""))]

    out = []
    page_errors = []
    for item in candidates[:max(limit * 2, limit)]:
        try:
            words = genius_page(item.get("url") or "")
        except LyricsError as e:
            page_errors.append(e)
            continue
        if not words:
            continue
        primary = item.get("primary_artist") or {}
        artist_name = (primary.get("name") if isinstance(primary, dict) else "") or ""
        out.append({"source": GENIUS_SOURCE,
                    "title": item.get("title") or track,
                    "artist": artist_name,
                    "duration": 0,
                    "lines": len([ln for ln in words.splitlines() if ln.strip()]),
                    "text": words,
                    "timed": False,
                    "textTimed": ""})
        if len(out) >= limit:
            break
    if not out and candidates and page_errors:
        raise page_errors[0]
    return out


def search(track: str, artist: str = "", duration: float = 0, limit: int = 5) -> list:
    """Offer both LRCLIB and Genius instead of hiding one successful source.

    LRCLIB's timings are useful, but its words are not necessarily the version
    a person wants to sing. Genius is therefore a genuine alternative, not
    merely an error fallback. The independent requests run together so showing
    both choices does not make the dialog wait for them one after another.
    """
    track = (track or "").strip()
    if not track:
        raise LyricsError(tr("There is no song name to look for.",
                             "Нет названия песни, по которому искать."))
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = (
            pool.submit(_search_lrclib, track, artist, duration, limit),
            pool.submit(search_genius, track, artist, limit),
        )
        found = []
        for job in jobs:                         # LRCLIB stays first on screen
            try:
                found.extend(job.result())
            except LyricsError as e:
                errors.append(e)
    if found:
        return found
    if errors:
        raise LyricsError("; ".join(str(e) for e in errors))
    return []
