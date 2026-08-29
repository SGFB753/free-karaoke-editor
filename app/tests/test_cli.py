#!/usr/bin/env python3
"""The command line: options, batch mode, and that the files end up in place.

Окно проверяется браузерными наборами, а этот путь — для тех, кто перетаскивает
файлы на .bat или зовёт karaoke.py руками. Он ломается так же тихо.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("  OK     " if cond else "  FAILED ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def run(args, **kw):
    # A redirected Windows console can advertise a legacy code page even when
    # the files and the application are UTF-8. Keep the CLI test independent
    # of the terminal hosting it (PowerShell, CI, or an IDE task).
    env = dict(os.environ, KARAOKE_UI_LANG="ru", PYTHONIOENCODING="utf-8",
               **kw.pop("env", {}))
    return subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=env, **kw)


def payload_of(path):
    from kstudio import build as B
    return B.read_payload(path)


def main():
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_pipeline import TEXT, make_song

    tmp = tempfile.mkdtemp(prefix="karaoke_cli_")
    song = os.path.join(tmp, "song.wav")
    make_song(song)
    text = os.path.join(tmp, "song.txt")
    open(text, "w", encoding="utf-8").write(TEXT)

    print("Options of karaoke.py")
    out = os.path.join(tmp, "one.html")
    r = run(["karaoke.py", song, text, "-o", out, "--align", "energy",
             "--no-separate", "--lrc"])
    check("the build went through", r.returncode == 0, r.stderr.strip()[-200:])
    check("the page is there", os.path.isfile(out) and os.path.getsize(out) > 50_000,
          os.path.getsize(out) if os.path.isfile(out) else "нет файла")
    lrc = os.path.splitext(out)[0] + ".lrc"
    check("--lrc saved a file next to it", os.path.isfile(lrc))
    if os.path.isfile(lrc):
        body = open(lrc, encoding="utf-8").read()
        check("the .lrc has [mm:ss.dd] timings",
              bool(re.search(r"^\[\d\d:\d\d\.\d\d\]", body, re.M)), body.splitlines()[:1])
        # The file has a [ti:] and [ar:] header — count only the timed lines.
        timed = [l for l in body.splitlines() if re.match(r"^\[\d\d:\d\d\.\d\d\]", l)]
        check("the .lrc has as many lines as the song",
              len(timed) == len(payload_of(out)["data"]["lines"]),
              f"{len(timed)} vs {len(payload_of(out)['data']['lines'])}")
        check("the .lrc header carries the title", body.startswith("[ti:"), body.splitlines()[0])

    # --timings: edits from the player must reach the new build
    p = payload_of(out)
    shifted = {"lines": [{"text": l["text"], "start": round(l["start"] + 1.5, 3),
                          "end": round(l["end"] + 1.5, 3),
                          "words": [{"w": w["w"], "t": round(w["t"] + 1.5, 3), "d": w["d"]}
                                    for w in l["words"]]}
                         for l in p["data"]["lines"]]}
    tj = os.path.join(tmp, "timings.json")
    open(tj, "w", encoding="utf-8").write(json.dumps(shifted, ensure_ascii=False))
    out2 = os.path.join(tmp, "two.html")
    r = run(["karaoke.py", song, text, "-o", out2, "--timings", tj, "--no-separate"])
    check("the build with ready timings went through", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        got = payload_of(out2)["data"]["lines"]
        check("the timings came from the file, they were not recomputed",
              abs(got[0]["start"] - shifted["lines"][0]["start"]) < 0.01,
              f'{got[0]["start"]} vs {shifted["lines"][0]["start"]}')

    # --no-embed: the audio goes next to the page, the page stays light
    out3 = os.path.join(tmp, "light.html")
    r = run(["karaoke.py", song, text, "-o", out3, "--align", "energy",
             "--no-separate", "--no-embed"])
    check("the build without embedding went through", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        size = os.path.getsize(out3)
        near = [n for n in os.listdir(tmp) if n.startswith("light") and not n.endswith(".html")]
        check("the page came out light", size < 200_000, f"{size} bytes")
        check("the audio sits next to it as a file", bool(near), ", ".join(near) or "nothing there")
        check("the audio file is named in Latin letters",
              all(not re.search("[А-Яа-яЁё]", n) for n in near), ", ".join(near))

    print("\nThe look options")
    out4 = os.path.join(tmp, "colors.html")
    r = run(["karaoke.py", song, text, "-o", out4, "--align", "energy", "--no-separate",
             "--colors", "#101010,#f0f0f0", "--theme", "#ffffff,#fefefe",
             "--ui-lang", "en"])
    check("the build with colours went through", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        p4 = payload_of(out4)
        check("the voice colours reached the page", p4["colors"] == ["#101010", "#f0f0f0"],
              str(p4.get("colors")))
        check("an unreadable pair was corrected", p4["theme"]["text"] != "#fefefe",
              str(p4.get("theme")))
        check("the label language was set by the option", p4["uiLang"] == "en", str(p4.get("uiLang")))

    print("\nErrors: the program explains instead of dying with a traceback")
    r = run(["karaoke.py", os.path.join(tmp, "нет.mp3"), text])
    check("the missing file is named", r.returncode != 0 and "нет.mp3" in r.stdout + r.stderr,
          (r.stdout + r.stderr).strip()[-120:])
    check("no traceback in the output", "Traceback" not in r.stderr, r.stderr.strip()[-120:])
    empty = os.path.join(tmp, "empty.txt")
    open(empty, "w", encoding="utf-8").write("\n\n")
    r = run(["karaoke.py", song, empty])
    check("an empty text is explained", r.returncode != 0 and
          re.search("ни одной строки", r.stdout + r.stderr), (r.stdout + r.stderr)[-120:])

    print("\nBatch mode (a folder was dropped in)")
    folder = os.path.join(tmp, "batch")
    os.makedirs(folder, exist_ok=True)
    for name in ("first", "second"):
        shutil.copyfile(song, os.path.join(folder, name + ".wav"))
        open(os.path.join(folder, name + ".txt"), "w", encoding="utf-8").write(TEXT)
    open(os.path.join(folder, "lonely.txt"), "w", encoding="utf-8").write(TEXT)   # без пары
    r = run(["tools/auto.py", folder, "--align", "energy", "--no-separate"])
    check("the batch build went through", r.returncode == 0, r.stderr.strip()[-200:])
    made = sorted(n for n in os.listdir(folder) if n.endswith("_karaoke.html"))
    check("both pairs were built", made == ["first_karaoke.html", "second_karaoke.html"],
          ", ".join(made))
    check("lyrics without a song did not break the batch", "lonely_karaoke.html" not in made)
    check("the report says how many were done", re.search(r"(Готово|Done): 2", r.stdout),
          r.stdout.strip()[-160:])
    r = run(["tools/auto.py", folder, "--align", "energy", "--no-separate"])
    check("a second run does not rebuild what is done", ("пропускаю" in r.stdout or "skipping" in r.stdout),
          r.stdout.strip()[-160:])

    print("\nThe measuring tool")
    # It exists so that “it feels better” can be answered with numbers. It must
    # explain itself, refuse politely where the neural nets are missing, and
    # never end in a traceback.
    r = run(["tools/bench.py", "--help"])
    check("bench.py explains itself", r.returncode == 0 and "failed" in r.stdout,
          r.stdout.strip()[:80])
    check("and says what its columns mean",
          all(w in r.stdout for w in ("sure", "piled", "time")), r.stdout[:120])

    open(os.path.join(tmp, "lyrics.txt"), "w", encoding="utf-8").write(TEXT)
    os.makedirs(os.path.join(tmp, "nonets"), exist_ok=True)
    open(os.path.join(tmp, "nonets", "sitecustomize.py"), "w").write(
        "import sys\n"
        "class Gone:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('stable_whisper', 'whisper'):\n"
        "            raise ImportError(name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Gone())\n")
    r = run(["tools/bench.py", song, os.path.join(tmp, "lyrics.txt")],
            env={"PYTHONPATH": os.path.join(tmp, "nonets")})
    check("without stable-ts it says so instead of falling over",
          r.returncode == 2 and "stable-ts" in (r.stderr + r.stdout),
          (r.stderr or r.stdout).strip()[-120:])
    check("and there is no traceback in it", "Traceback" not in r.stderr, r.stderr[-120:])

    r = run(["tools/bench.py", os.path.join(tmp, "nope.mp3"), os.path.join(tmp, "lyrics.txt")])
    check("a missing file is named, not guessed at",
          r.returncode == 2 and "nope.mp3" in (r.stderr + r.stdout),
          (r.stderr or r.stdout).strip()[-100:])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
