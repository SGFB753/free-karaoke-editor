#!/usr/bin/env python3
"""Проверки командной строки: ключи, пакетный режим и то, что файлы на месте.

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
    print(("  OK   " if cond else "  ПРОВАЛ ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def run(args, **kw):
    env = dict(os.environ, KARAOKE_UI_LANG="ru", **kw.pop("env", {}))
    return subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True,
                          text=True, env=env, **kw)


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

    print("Проверка ключей karaoke.py")
    out = os.path.join(tmp, "one.html")
    r = run(["karaoke.py", song, text, "-o", out, "--align", "energy",
             "--no-separate", "--lrc"])
    check("сборка прошла", r.returncode == 0, r.stderr.strip()[-200:])
    check("страница на месте", os.path.isfile(out) and os.path.getsize(out) > 50_000,
          os.path.getsize(out) if os.path.isfile(out) else "нет файла")
    lrc = os.path.splitext(out)[0] + ".lrc"
    check("--lrc сохранил файл рядом", os.path.isfile(lrc))
    if os.path.isfile(lrc):
        body = open(lrc, encoding="utf-8").read()
        check("в .lrc есть тайминги вида [мм:сс.дд]",
              bool(re.search(r"^\[\d\d:\d\d\.\d\d\]", body, re.M)), body.splitlines()[:1])
        # У файла есть шапка [ti:] и [ar:] — считаем только строки с временем.
        timed = [l for l in body.splitlines() if re.match(r"^\[\d\d:\d\d\.\d\d\]", l)]
        check("строк в .lrc столько же, сколько в песне",
              len(timed) == len(payload_of(out)["data"]["lines"]),
              f"{len(timed)} против {len(payload_of(out)['data']['lines'])}")
        check("в шапке .lrc есть название", body.startswith("[ti:"), body.splitlines()[0])

    # --timings: правки из плеера должны попадать в новую сборку
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
    check("сборка с готовыми таймингами прошла", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        got = payload_of(out2)["data"]["lines"]
        check("тайминги взяты из файла, а не посчитаны заново",
              abs(got[0]["start"] - shifted["lines"][0]["start"]) < 0.01,
              f'{got[0]["start"]} vs {shifted["lines"][0]["start"]}')

    # --no-embed: звук ложится рядом, страница остаётся лёгкой
    out3 = os.path.join(tmp, "light.html")
    r = run(["karaoke.py", song, text, "-o", out3, "--align", "energy",
             "--no-separate", "--no-embed"])
    check("сборка без встраивания прошла", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        size = os.path.getsize(out3)
        near = [n for n in os.listdir(tmp) if n.startswith("light") and not n.endswith(".html")]
        check("страница стала лёгкой", size < 200_000, f"{size} байт")
        check("звук лежит рядом файлом", bool(near), ", ".join(near) or "ничего нет")
        check("имя звукового файла латиницей",
              all(not re.search("[А-Яа-яЁё]", n) for n in near), ", ".join(near))

    print("\nПроверка ключей оформления")
    out4 = os.path.join(tmp, "colors.html")
    r = run(["karaoke.py", song, text, "-o", out4, "--align", "energy", "--no-separate",
             "--colors", "#101010,#f0f0f0", "--theme", "#ffffff,#fefefe",
             "--ui-lang", "en"])
    check("сборка с цветами прошла", r.returncode == 0, r.stderr.strip()[-200:])
    if r.returncode == 0:
        p4 = payload_of(out4)
        check("цвета голосов попали в страницу", p4["colors"] == ["#101010", "#f0f0f0"],
              str(p4.get("colors")))
        check("нечитаемая пара поправлена", p4["theme"]["text"] != "#fefefe",
              str(p4.get("theme")))
        check("язык надписей задан ключом", p4["uiLang"] == "en", str(p4.get("uiLang")))

    print("\nПроверка ошибок: программа объясняет, а не падает трассировкой")
    r = run(["karaoke.py", os.path.join(tmp, "нет.mp3"), text])
    check("пропавший файл назван по имени", r.returncode != 0 and "нет.mp3" in r.stdout + r.stderr,
          (r.stdout + r.stderr).strip()[-120:])
    check("трассировки в выводе нет", "Traceback" not in r.stderr, r.stderr.strip()[-120:])
    empty = os.path.join(tmp, "empty.txt")
    open(empty, "w", encoding="utf-8").write("\n\n")
    r = run(["karaoke.py", song, empty])
    check("пустой текст объяснён", r.returncode != 0 and
          re.search("ни одной строки", r.stdout + r.stderr), (r.stdout + r.stderr)[-120:])

    print("\nПроверка пакетного режима (перетащили папку)")
    folder = os.path.join(tmp, "batch")
    os.makedirs(folder, exist_ok=True)
    for name in ("first", "second"):
        shutil.copyfile(song, os.path.join(folder, name + ".wav"))
        open(os.path.join(folder, name + ".txt"), "w", encoding="utf-8").write(TEXT)
    open(os.path.join(folder, "lonely.txt"), "w", encoding="utf-8").write(TEXT)   # без пары
    r = run(["tools/auto.py", folder, "--align", "energy", "--no-separate"])
    check("пакетная сборка прошла", r.returncode == 0, r.stderr.strip()[-200:])
    made = sorted(n for n in os.listdir(folder) if n.endswith("_karaoke.html"))
    check("собраны обе пары", made == ["first_karaoke.html", "second_karaoke.html"],
          ", ".join(made))
    check("текст без песни не сломал пакет", "lonely_karaoke.html" not in made)
    check("в отчёте сказано, сколько сделано", re.search(r"Готово: 2", r.stdout),
          r.stdout.strip()[-160:])
    r = run(["tools/auto.py", folder, "--align", "energy", "--no-separate"])
    check("второй прогон не пересобирает готовое", "пропускаю" in r.stdout,
          r.stdout.strip()[-160:])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("ПРОВАЛЕНО: " + ", ".join(failures) if failures else "Все проверки пройдены"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
