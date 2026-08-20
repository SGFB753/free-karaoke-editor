#!/usr/bin/env python3
"""A stand-in for yt-dlp, so the checks never touch the internet.

KARAOKE_STUB_AUDIO — the file it pretends to have downloaded.
KARAOKE_STUB_FAIL   — say what a dead link says, and fail the way yt-dlp fails.

A link with “fail” in it does the same thing, so that both endings can be
walked through against one running studio.
"""

import json
import os
import shutil
import sys

TITLE = "Stub Artist - Stub Song (Official Video)"


def main() -> int:
    args = sys.argv[1:]
    out = ""
    for i, a in enumerate(args):
        if a == "-o" and i + 1 < len(args):
            out = args[i + 1]
    folder = os.path.dirname(out) or "."
    url = args[-1] if args else ""

    if os.environ.get("KARAOKE_STUB_FAIL") or "fail" in url:
        print("[youtube] zzz123: Downloading webpage")
        print("ERROR: [youtube] zzz123: Video unavailable. This video is private",
              file=sys.stderr)
        return 1

    src = os.environ.get("KARAOKE_STUB_AUDIO") or ""
    stem = "Stub_Artist_-_Stub_Song_[zzz123]"
    ext = os.path.splitext(src)[1] or ".m4a"
    dst = os.path.join(folder, stem + ext)
    print("[youtube] zzz123: Downloading webpage")
    print("[download]  50.0% of 3.00MiB at 1.00MiB/s ETA 00:01")
    if src and os.path.isfile(src):
        shutil.copyfile(src, dst)
    else:
        with open(dst, "wb") as f:
            f.write(b"\0" * 4096)
    print("[download] 100% of 3.00MiB in 00:02")
    if "--write-info-json" in args:
        with open(os.path.join(folder, stem + ".info.json"), "w", encoding="utf-8") as f:
            json.dump({"title": TITLE, "id": "zzz123", "duration": 21,
                       "artist": "Stub Artist", "track": "Stub Song"}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
