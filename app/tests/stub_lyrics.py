#!/usr/bin/env python3
"""A stand-in for the lyrics library, so the checks never touch the internet.

Prints the address it listens on and then serves /api/search the way LRCLIB
does: a list of records, some timed, some not, one of them empty on purpose.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WORDS = ("the first line of the stub\nthe second line of the stub\n"
         "the third line of the stub")


class Handler(BaseHTTPRequestHandler):
    flaky_calls = 0

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/stub-genius-lyrics":
            data = (b'<html><div data-lyrics-container="true">[Verse]<br>'
                    b'Genius first line<br>Genius second line</div>'
                    b'<div data-lyrics-container="true">[Chorus]<br>'
                    b'Genius final line</div></html>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path == "/api/search/multi":
            want = (q.get("q") or [""])[0].lower()
            hits = []
            clean_gear = "\u0448\u0435\u0441\u0442\u0435\u0440\u0451\u043d\u043a\u0430" in want and "\u0430\u043b\u044c\u0431\u043e\u043c" not in want
            if "genius only" in want or "stub song" in want or "packed song" in want or clean_gear:
                host = self.headers.get("Host")
                hits = [{"type": "song", "result": {
                    "title": ("Genius Only" if "genius only" in want else
                              "\u0428\u0435\u0441\u0442\u0435\u0440\u0451\u043d\u043a\u0430" if clean_gear else
                              "Packed Song" if "packed song" in want else "Stub Song"),
                    "url": f"http://{host}/stub-genius-lyrics",
                    "primary_artist": {"name": ("Fallback Artist" if "genius only" in want
                                       else "Bumble Beezy" if clean_gear else "Stub Artist")}}}]
            body = {"response": {"sections": [{"type": "song", "hits": hits}]}}
            data = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if u.path != "/api/search":
            return self.send_error(404)
        want = (q.get("track_name") or q.get("q") or [""])[0].lower()
        if "retry once" in want:
            type(self).flaky_calls += 1
            if type(self).flaky_calls == 1:
                return self.send_error(503)
            body = [{"trackName": "Retry Once", "artistName": "Stub Artist",
                     "duration": 21, "plainLyrics": WORDS}]
            return self._json(body)
        clean_gear = "\u0448\u0435\u0441\u0442\u0435\u0440\u0451\u043d\u043a\u0430" in want and "\u0430\u043b\u044c\u0431\u043e\u043c" not in want
        if "nothing" in want or "genius only" in want or ("\u0448\u0435\u0441\u0442\u0435\u0440\u0451\u043d\u043a\u0430" in want and not clean_gear):
            body = []
        elif clean_gear:
            body = [{"trackName": "\u0428\u0435\u0441\u0442\u0435\u0440\u0451\u043d\u043a\u0430", "artistName": "Bumble Beezy",
                     "duration": 215.761, "plainLyrics": WORDS}]
        elif "packed song" in want:
            body = [{"trackName": "Packed Song", "artistName": "Stub Artist",
                     "duration": 21, "plainLyrics": WORDS,
                     "syncedLyrics": "\n".join(
                         f"[00:0{i}.00] " + ln for i, ln in enumerate(WORDS.splitlines()))}]
        else:
            body = [
                # a record with no words at all: it must never be offered
                {"trackName": "Stub Song", "artistName": "Empty Records",
                 "duration": 21, "plainLyrics": "", "syncedLyrics": ""},
                # the live take: same name, far from the length of our song
                {"trackName": "Stub Song (live)", "artistName": "Stub Artist",
                 "duration": 300, "plainLyrics": "a live line\nanother live line"},
                # only timed words — they have to be stripped down to the words
                {"trackName": "Stub Song", "artistName": "Stub Artist",
                 "duration": 21,
                 "syncedLyrics": "\n".join(
                     f"[00:0{i}.00] " + ln for i, ln in enumerate(WORDS.splitlines()))},
            ]
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"http://127.0.0.1:{srv.server_port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
