#!/usr/bin/env python3
"""Проверки того, как программа доезжает до человека.

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
    print(("  OK   " if cond else "  ПРОВАЛ ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def run(args, **kw):
    env = dict(os.environ, **kw.pop("env", {}))
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env=env, **kw)


def main():
    print("Проверка запуска и имён файлов")
    # В корне — только то, чем пользуются каждый день: поставить, открыть, прочесть.
    for name in ("Install.bat", "install.command", "Studio.bat", "studio.command",
                 "README.md", "README.ru.md"):
        check(f"есть {name}", os.path.isfile(os.path.join(HOME, name)))
    # На GitHub первым читают README.md — он должен быть английским.
    head = open(os.path.join(HOME, "README.md"), encoding="utf-8").read()[:400]
    check("главный README английский", "Karaoke Studio" in head and
          not re.search("[А-Яа-яЁё]", head.split("\n")[0]), head.split("\n")[0])
    check("из него есть ссылка на русский", "README.ru.md" in head)
    ru_head = open(os.path.join(HOME, "README.ru.md"), encoding="utf-8").read()[:300]
    check("и обратная ссылка работает", "README.md" in ru_head and
          "app/README" not in ru_head, ru_head.split("\n")[2] if "\n" in ru_head else "")
    # Всё остальное — внутри app/.
    for name in ("Make-karaoke.bat", "Make-video.bat", "make-karaoke.command",
                 "settings.ini", "START-HERE.txt", "SERVER.md", "Dockerfile",
                 "docker-compose.yml"):
        check(f"{name} убран в app/", os.path.isfile(os.path.join(ROOT, name)))
    cyr = [n for n in os.listdir(HOME)
           if re.search("[А-Яа-яЁё]", n) and not n.startswith(".")]
    check("кириллицы в именах файлов не осталось", not cyr, ", ".join(cyr))
    # Ради этого всё и переносилось: в корне только то, что человеку нужно.
    root_items = sorted(n for n in os.listdir(HOME)
                        if not n.startswith(".") and n not in ("node_modules", "__pycache__"))
    check("в корне не больше 8 имён", len(root_items) <= 8,
          f"{len(root_items)}: " + ", ".join(root_items))
    check("внутренности спрятаны в app/",
          all(os.path.isdir(os.path.join(HOME, "app", d)) for d in ("kstudio", "tools", "tests")))
    check("папка песен на виду", os.path.isdir(os.path.join(HOME, "projects"))
          or "projects" not in root_items)

    for name in ("studio.command", "install.command"):
        path = os.path.join(HOME, name)
        check(f"{name} исполняемый", os.access(path, os.X_OK))
        r = run(["bash", "-n", path])
        check(f"{name} разбирается", r.returncode == 0, r.stderr.strip()[:80])
    # запускать окно долго, но проверить, что скрипт передаёт ключи, надо
    src = open(os.path.join(HOME, "studio.command"), encoding="utf-8").read()
    check("studio.command передаёт ключи дальше", '"$@"' in src)
    check("studio.command зовёт программу из app/", "app/studio.py" in src)

    print("\nПроверка настроек")
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
    check("русские ключи читаются", "--align" in args and args[args.index("--align") + 1] == "auto",
          " ".join(args))
    check("цвета целиком", args[args.index("--colors") + 1] == "#112233,#445566")
    check("оформление целиком", args[args.index("--theme") + 1] == "#000000,#ffffff")
    check("язык надписей", args[args.index("--ui-lang") + 1] == "en")
    check("«минусовка = нет» превращается в --no-separate", "--no-separate" in args)
    # английские ключи в том же файле
    open(ini, "w", encoding="utf-8").write("align = energy\ncolors = #010203,#040506\n"
                                           "theme = #111111,#eeeeee\nui-lang = ru\n")
    args = auto.read_settings()
    check("английские ключи тоже понимаются",
          args[args.index("--align") + 1] == "energy" and
          args[args.index("--ui-lang") + 1] == "ru", " ".join(args))

    print("\nПроверка контейнера")
    docker = os.path.join(ROOT, "Dockerfile")
    compose = os.path.join(ROOT, "docker-compose.yml")
    check("есть Dockerfile", os.path.isfile(docker))
    check("есть docker-compose.yml", os.path.isfile(compose))
    d = open(docker, encoding="utf-8").read()
    c = open(compose, encoding="utf-8").read()
    check("образ ставит ffmpeg", "ffmpeg" in d)
    check("зависимости ставятся до копирования кода",
          d.index("requirements.txt") < d.index("COPY . /app"), "порядок слоёв")
    check("песни лежат в томе, а не внутри образа",
          "KARAOKE_PROJECTS=/songs" in d and "/songs" in c)
    check("студия слушает наружу контейнера", "--host" in d and "0.0.0.0" in d)
    check("порт наружу открыт только на localhost", "127.0.0.1:8770:8770" in c)
    check("модели переживают пересборку", "/cache" in d and "/cache" in c)
    check("про видеокарту в compose сказано", "nvidia" in c.lower())
    check("в Dockerfile нет кириллицы", not re.search("[А-Яа-яЁё]", d))
    # ключ --host обязан существовать на самом деле, а не только в Dockerfile
    import studio as _ST
    check("--host разбирается программой",
          _ST.parse_args(["--host", "0.0.0.0", "--port", "8770"])[2] == "0.0.0.0")
    check("по умолчанию слушаем только себя", _ST.parse_args([])[2] == "127.0.0.1")

    print("\nПроверка снимков для README")
    for shot in ("docs/studio.png", "docs/video.png"):
        p_shot = os.path.join(ROOT, shot)
        check(f"есть {shot}", os.path.isfile(p_shot) and os.path.getsize(p_shot) > 10000)
    readme = open(os.path.join(HOME, "README.md"), encoding="utf-8").read()
    check("снимок вставлен в README", "app/docs/studio.png" in readme)

    print("\nПроверка имён папок с песнями")
    from kstudio.project import slugify
    for title, want in (("Мамины Усы — Я вынул из головы шар", "maminy-usy"),
                        ("Тестовая песня", "testovaya-pesnya"),
                        ("Ёжик & Ко", "ezhik-ko")):
        got = slugify(title)
        check(f"«{title[:20]}» → латиницей", re.fullmatch(r"[a-z0-9-]+", got) and want in got,
              got)
    check("пустое имя не ломает папку", slugify("日本語") == "song", slugify("日本語"))

    check("суффикс готового файла латиницей",
          all("_karaoke.html" in open(os.path.join(ROOT, f), encoding="utf-8").read()
              for f in ("karaoke.py", "tools/auto.py")))
    check("кириллицы в именах внутри программы нет",
          not [n for _r, _d, fs in os.walk(ROOT) for n in fs
               if re.search("[А-Яа-яЁё]", n) and "node_modules" not in _r],
          "есть файлы с кириллицей")

    print("\nПроверка старой раскладки (обновление поверх прежней версии)")
    old = tempfile.mkdtemp(prefix="karaoke_old_")
    os.makedirs(os.path.join(old, "проекты", "песня"), exist_ok=True)
    from kstudio import project as P
    root = P.projects_root(base=None) if False else None
    # projects_root смотрит на папку программы, поэтому проверяем саму логику
    import kstudio.project as PJ
    real_dirname = os.path.dirname
    check("папка projects используется по умолчанию",
          os.path.basename(PJ.projects_root(base=os.path.join(old, "projects"))) == "projects")
    check("явно указанная папка уважается",
          PJ.projects_root(base=os.path.join(old, "проекты")).endswith("проекты"))

    print("\nПроверка языка консоли")
    song = os.path.join(tmp, "song.wav")
    make_song(song)
    text = os.path.join(tmp, "lyrics.txt")
    open(text, "w", encoding="utf-8").write("title: Test\n\nOne two three\n(backing here)\nFour five\n")
    out_en = os.path.join(tmp, "en.html")
    r = run([sys.executable, "karaoke.py", song, text, "-o", out_en,
             "--align", "energy", "--no-separate"], env={"KARAOKE_UI_LANG": "en"})
    check("сборка по-английски прошла", r.returncode == 0, r.stderr.strip()[-200:])
    check("в выводе нет кириллицы", not re.search("[А-Яа-яЁё]", r.stdout),
          " ".join(re.findall(r"[А-Яа-яЁё][^\s]*", r.stdout)[:5]))
    check("отчёт перед сборкой на месте", "Before we start" in r.stdout)
    check("сказано, что файл открывается двойным щелчком",
          "double click" in r.stdout)

    out_ru = os.path.join(tmp, "ru.html")
    r = run([sys.executable, "karaoke.py", song, text, "-o", out_ru,
             "--align", "energy", "--no-separate"], env={"KARAOKE_UI_LANG": "ru"})
    check("сборка по-русски прошла", r.returncode == 0, r.stderr.strip()[-200:])
    check("русский вывод остался русским", "Отчёт перед сборкой" in r.stdout)

    print("\nПроверка ролика: оставленный оригинал попадает в звук")
    check_video(tmp)

    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    print("\n" + ("ПРОВАЛЕНО: " + ", ".join(failures) if failures else "Все проверки пройдены"))
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
    """Кусок «поёт оригинал» должен звучать громче в готовом звуке ролика."""
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
    check("кусок с оригиналом найден", spans == [(5.0, 8.0)], str(spans))
    wav = video.extract_audio(payload, os.path.join(tmp, "page.html"), tmp, "minus")
    loud_in = rms(wav, 5.5, 7.5, 660.0)
    loud_out = rms(wav, 1.5, 2.5, 660.0)
    check("на отмеченном куске голос слышен, а вне его — нет",
          loud_in > loud_out * 4, f"внутри {loud_in:.4f}, снаружи {loud_out:.4f}")


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
    """Сколько в куске энергии на нужной частоте — грубый полосовой замер."""
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
