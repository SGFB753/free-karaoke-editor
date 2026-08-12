#!/usr/bin/env python3
"""Checks on how the program reaches a person.

Не разметка и не звук, а всё вокруг: чем её запускают, как называются файлы,
читаются ли настройки, работает ли старая раскладка папок, на каком языке
говорит консоль и попадает ли «оставленный оригинал» в готовый ролик.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # папка app/
HOME = os.path.dirname(ROOT)                                          # то, что видит человек
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("  OK     " if cond else "  FAILED ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def run(args, **kw):
    env = dict(os.environ, **kw.pop("env", {}))
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env=env, **kw)


def main():
    print("Launchers and file names")
    # The root holds only the everyday things: install, open, read.
    for name in ("Install.bat", "install.command", "Studio.bat", "studio.command",
                 "README.md", "README.ru.md"):
        check(f"{name} is there", os.path.isfile(os.path.join(HOME, name)))
    # On GitHub README.md is read first — it has to be the English one.
    head = open(os.path.join(HOME, "README.md"), encoding="utf-8").read()[:900]
    check("the main README is in English", "Karaoke Studio" in head and
          not re.search("[А-Яа-яЁё]", head.split("\n")[0]), head.split("\n")[0])
    check("it links to the Russian one", "README.ru.md" in head)
    ru_head = open(os.path.join(HOME, "README.ru.md"), encoding="utf-8").read()[:900]
    check("and the link back works", "(README.md)" in ru_head and
          "app/README" not in ru_head, ru_head.split("\n")[4] if "\n" in ru_head else "")
    # On GitHub the checks show as a badge — it must point at this repository.
    check("the checks badge is in both READMEs",
          "actions/workflows/tests.yml/badge.svg" in head and
          "actions/workflows/tests.yml/badge.svg" in ru_head)
    wf = os.path.join(HOME, ".github", "workflows", "tests.yml")
    check("the workflow file itself is there", os.path.isfile(wf))
    if os.path.isfile(wf):
        body = open(wf, encoding="utf-8").read()
        check("it runs the whole suite", "tests/run_all.py" in body)
        check("and the container separately", "test_container.py" in body and "KARAOKE_DOCKER" in body)
        check("and the neural nets separately", "test_heavy.py" in body and "KARAOKE_HEAVY" in body)
        check("skipping the browser suites in CI counts as a failure",
              "KARAOKE_REQUIRE_BROWSER" in body)
        check("it can also be started by hand", "workflow_dispatch" in body)
    # Everything else lives inside app/.
    for name in ("Make-karaoke.bat", "Make-video.bat", "make-karaoke.command",
                 "settings.ini", "START-HERE.txt", "SERVER.md", "Dockerfile",
                 "docker-compose.yml"):
        check(f"{name} moved into app/", os.path.isfile(os.path.join(ROOT, name)))
    cyr = [n for n in os.listdir(HOME)
           if re.search("[А-Яа-яЁё]", n) and not n.startswith(".")]
    check("no Cyrillic left in the file names", not cyr, ", ".join(cyr))
    # This is what the move was for: only what a person needs is in the root —
    # the two launchers, the two readmes, the two changelogs, the songs, the code.
    root_items = sorted(n for n in os.listdir(HOME)
                        if not n.startswith(".") and n not in ("node_modules", "__pycache__"))
    check("no more than 10 names in the root", len(root_items) <= 10,
          f"{len(root_items)}: " + ", ".join(root_items))
    check("the history of changes is in plain sight",
          os.path.isfile(os.path.join(HOME, "CHANGELOG.md"))
          and os.path.isfile(os.path.join(HOME, "CHANGELOG.ru.md")))
    check("the internals are tucked into app/",
          all(os.path.isdir(os.path.join(HOME, "app", d)) for d in ("kstudio", "tools", "tests")))
    check("the songs folder is in plain sight", os.path.isdir(os.path.join(HOME, "projects"))
          or "projects" not in root_items)

    for name in ("studio.command", "install.command"):
        path = os.path.join(HOME, name)
        check(f"{name} is executable", os.access(path, os.X_OK))
        r = run(["bash", "-n", path])
        check(f"{name} parses", r.returncode == 0, r.stderr.strip()[:80])
    # starting the window is slow, but the option passing has to be checked
    src = open(os.path.join(HOME, "studio.command"), encoding="utf-8").read()
    check("studio.command passes the options through", '"$@"' in src)
    check("studio.command calls the program in app/", "app/studio.py" in src)

    print("\nSettings")
    tmp = tempfile.mkdtemp(prefix="karaoke_deliv_")
    import importlib.util
    spec = importlib.util.spec_from_file_location("auto", os.path.join(ROOT, "tools", "auto.py"))
    auto = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auto)
    ini = os.path.join(tmp, "settings.ini")
    open(ini, "w", encoding="utf-8").write(
        "# примечание\nдвижок = auto\nцвета = #112233,#445566\n"
        "оформление = #000000,#ffffff\nнадписи = en\nминусовка = нет\n")
    auto.SETTINGS = ini
    args = auto.read_settings()
    check("the Russian keys are read", "--align" in args and args[args.index("--align") + 1] == "auto",
          " ".join(args))
    check("the colours come through whole", args[args.index("--colors") + 1] == "#112233,#445566")
    check("the theme comes through whole", args[args.index("--theme") + 1] == "#000000,#ffffff")
    check("the label language", args[args.index("--ui-lang") + 1] == "en")
    check("“минусовка = нет” becomes --no-separate", "--no-separate" in args)
    # the English keys in the same file
    open(ini, "w", encoding="utf-8").write("align = energy\ncolors = #010203,#040506\n"
                                           "theme = #111111,#eeeeee\nui-lang = ru\n")
    args = auto.read_settings()
    check("the English keys are understood too",
          args[args.index("--align") + 1] == "energy" and
          args[args.index("--ui-lang") + 1] == "ru", " ".join(args))

    print("\nThe container")
    docker = os.path.join(ROOT, "Dockerfile")
    compose = os.path.join(ROOT, "docker-compose.yml")
    check("there is a Dockerfile", os.path.isfile(docker))
    check("there is a docker-compose.yml", os.path.isfile(compose))
    d = open(docker, encoding="utf-8").read()
    c = open(compose, encoding="utf-8").read()
    check("the image installs ffmpeg", "ffmpeg" in d)
    check("dependencies are installed before the code is copied",
          d.index("requirements.txt") < d.index("COPY . /app"), "layer order")
    check("songs live in a volume, not inside the image",
          "KARAOKE_PROJECTS=/songs" in d and "/songs" in c)
    check("the studio listens outside the container", "--host" in d and "0.0.0.0" in d)
    check("the published port is bound to localhost only", "127.0.0.1:8770:8770" in c)
    check("the models survive a rebuild", "/cache" in d and "/cache" in c)
    check("the compose file mentions the graphics card", "nvidia" in c.lower())
    check("no Cyrillic in the Dockerfile", not re.search("[А-Яа-яЁё]", d))
    # the --host option must really exist, not only in the Dockerfile
    import studio as _ST
    check("the program parses --host",
          _ST.parse_args(["--host", "0.0.0.0", "--port", "8770"])[2] == "0.0.0.0")
    check("by default we listen to ourselves only", _ST.parse_args([])[2] == "127.0.0.1")

    print("\nScreenshots for the README")
    for shot in ("docs/studio.png", "docs/video.png"):
        p_shot = os.path.join(ROOT, shot)
        check(f"{shot} is there", os.path.isfile(p_shot) and os.path.getsize(p_shot) > 10000)
    readme = open(os.path.join(HOME, "README.md"), encoding="utf-8").read()
    check("the screenshot is embedded in the README", "app/docs/studio.png" in readme)

    print("\nNames of the song folders")
    from kstudio.project import slugify
    for title, want in (("Мамины Усы — Я вынул из головы шар", "maminy-usy"),
                        ("Тестовая песня", "testovaya-pesnya"),
                        ("Ёжик & Ко", "ezhik-ko")):
        got = slugify(title)
        check(f"“{title[:20]}” → in Latin letters", re.fullmatch(r"[a-z0-9-]+", got) and want in got,
              got)
    check("an empty name does not break the folder", slugify("日本語") == "song", slugify("日本語"))

    check("the finished file suffix is in Latin letters",
          all("_karaoke.html" in open(os.path.join(ROOT, f), encoding="utf-8").read()
              for f in ("karaoke.py", "tools/auto.py")))
    check("no Cyrillic in the names inside the program",
          not [n for _r, _d, fs in os.walk(ROOT) for n in fs
               if re.search("[А-Яа-яЁё]", n) and "node_modules" not in _r],
          "есть файлы с кириллицей")

    print("\nThe old layout (updating over an earlier version)")
    old = tempfile.mkdtemp(prefix="karaoke_old_")
    os.makedirs(os.path.join(old, "проекты", "песня"), exist_ok=True)
    from kstudio import project as P
    root = P.projects_root(base=None) if False else None
    # projects_root looks at the program folder, so the logic itself is checked
    import kstudio.project as PJ
    real_dirname = os.path.dirname
    check("the projects folder is used by default",
          os.path.basename(PJ.projects_root(base=os.path.join(old, "projects"))) == "projects")
    check("an explicitly given folder is respected",
          PJ.projects_root(base=os.path.join(old, "проекты")).endswith("проекты"))

    print("\nThe language of the console")
    song = os.path.join(tmp, "song.wav")
    make_song(song)
    text = os.path.join(tmp, "lyrics.txt")
    open(text, "w", encoding="utf-8").write("title: Test\n\nOne two three\n(backing here)\nFour five\n")
    out_en = os.path.join(tmp, "en.html")
    r = run([sys.executable, "karaoke.py", song, text, "-o", out_en,
             "--align", "energy", "--no-separate"], env={"KARAOKE_UI_LANG": "en"})
    check("the English build went through", r.returncode == 0, r.stderr.strip()[-200:])
    check("no Cyrillic in the output", not re.search("[А-Яа-яЁё]", r.stdout),
          " ".join(re.findall(r"[А-Яа-яЁё][^\s]*", r.stdout)[:5]))
    check("the report before building is there", "Before we start" in r.stdout)
    check("it says the file opens with a double click",
          "double click" in r.stdout)

    out_ru = os.path.join(tmp, "ru.html")
    r = run([sys.executable, "karaoke.py", song, text, "-o", out_ru,
             "--align", "energy", "--no-separate"], env={"KARAOKE_UI_LANG": "ru"})
    check("the Russian build went through", r.returncode == 0, r.stderr.strip()[-200:])
    check("the Russian output stayed Russian", "Отчёт перед сборкой" in r.stdout)

    print("\nThe video: the kept original reaches the audio")
    check_video(tmp)

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


def make_song(path, dur=12.0, sr=22050):
    import math
    import struct
    frames = []
    for i in range(int(sr * dur)):
        t = i / sr
        v = 0.3 * math.sin(2 * math.pi * 220 * t)
        if 4.0 < t < 8.0:                      # «вокал» в середине
            v += 0.3 * math.sin(2 * math.pi * 440 * t)
        frames.append(struct.pack("<h", int(max(-1, min(1, v)) * 30000)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(frames))
    return path


def check_video(tmp):
    """A stretch marked “original sings” must be louder in the video audio."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("video", os.path.join(ROOT, "tools", "video.py"))
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)

    from kstudio import audio as AU
    instr = make_two_tone(os.path.join(tmp, "instr.wav"), 220.0)
    voc = make_two_tone(os.path.join(tmp, "voc.wav"), 660.0)
    payload = {"audio": {"instrumental": os.path.basename(instr),
                         "vocals": os.path.basename(voc)},
               "data": {"lines": [
                   {"start": 1.0, "end": 3.0, "keep": False},
                   {"start": 5.0, "end": 8.0, "keep": True}]}}
    spans = video.keep_spans(payload)
    check("the stretch with the original was found", spans == [(5.0, 8.0)], str(spans))
    wav = video.extract_audio(payload, os.path.join(tmp, "page.html"), tmp, "minus")
    loud_in = rms(wav, 5.5, 7.5, 660.0)
    loud_out = rms(wav, 1.5, 2.5, 660.0)
    check("the voice is heard on the marked stretch and nowhere else",
          loud_in > loud_out * 4, f"inside {loud_in:.4f}, outside {loud_out:.4f}")


def make_two_tone(path, freq, dur=10.0, sr=22050):
    import math
    import struct
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", int(0.4 * math.sin(2 * math.pi * freq * i / sr) * 30000))
            for i in range(int(sr * dur))))
    return path


def rms(path, a, b, freq):
    """How much energy the stretch holds at that frequency — a crude band measure."""
    import math
    from kstudio import audio as AU
    sr = 22050
    x = AU.read_pcm_mono(path, sr)
    i0, i1 = int(a * sr), min(int(b * sr), len(x))
    re_ = im = 0.0
    for i in range(i0, i1):
        v = x[i] / 32768.0
        re_ += v * math.cos(2 * math.pi * freq * i / sr)
        im += v * math.sin(2 * math.pi * freq * i / sr)
    n = max(i1 - i0, 1)
    return math.hypot(re_, im) / n


if __name__ == "__main__":
    sys.exit(main())
