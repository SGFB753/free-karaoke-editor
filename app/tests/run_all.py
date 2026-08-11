#!/usr/bin/env python3
"""Прогнать все проверки разом.

    python3 tests/run_all.py              всё, что доступно
    KARAOKE_HEAVY=1  … run_all.py         плюс настоящие Whisper и Demucs
    KARAOKE_DOCKER=1 … run_all.py         плюс сборка и запуск контейнера
    python3 tests/run_all.py --quick      только Python, без браузерных
    python3 tests/run_all.py --list       перечислить наборы и выйти

Что происходит:
  1. Проверки самого конвейера (`test_pipeline.py`) — нужен только ffmpeg.
  1б. Проверки доставки (`test_delivery.py`): чем запускают, как названы файлы,
     читаются ли настройки, на каком языке говорит консоль, что со звуком ролика.
  2. Собирается тестовая песня и две страницы: с одной дорожкой и с минусовкой.
  3. Поднимается студия на свободном порту со свежим проектом.
  4. Прогоняются наборы из tests/ui — окно и страница целиком, в jsdom.
  5. Если стоит puppeteer с Chrome — ещё и tests/test_browser.mjs: настоящий
     браузер смотрит на вёрстку, которую jsdom не рисует.

Для пунктов 4–5 нужен Node.js: `npm install jsdom` (и `puppeteer` для пятого).
Без Node всё остальное всё равно отработает.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(ROOT, "tests", "ui")


# Этим наборам нужен настоящий браузер: они проверяют попадание курсором,
# а jsdom его не делает вовсе.
def NEEDS_BROWSER(name: str) -> bool:
    return any(k in name for k in ("real-mouse", "word-length", "replace-track", "scroll-and-end", "quiet-and-voice", "two-lanes", "requirements", "duo-layout", "multiselect"))
sys.path.insert(0, ROOT)


def say(msg=""):
    print(msg, flush=True)


def head(title):
    say()
    say("=" * 62)
    say("  " + title)
    say("=" * 62)


def have_node() -> bool:
    return shutil.which("node") is not None


def have_module(name: str) -> bool:
    """Установлен ли пакет Node — проверяем его же средствами."""
    try:
        r = subprocess.run(["node", "-e", f"import('{name}').then(()=>0)"],
                           cwd=ROOT, capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float = 40) -> bool:
    until = time.time() + seconds
    while time.time() < until:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.4)
    return False


def build_pages(tmp: str) -> tuple:
    """Тестовая песня и две страницы: одна дорожка и минус + вокал."""
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    from test_pipeline import TEXT, make_song  # noqa: F401

    song = os.path.join(tmp, "песня.wav")
    text = os.path.join(tmp, "текст.txt")
    make_song(song)
    with open(text, "w", encoding="utf-8") as f:
        f.write(TEXT)

    mix = os.path.join(tmp, "одна_дорожка.html")
    stems = os.path.join(tmp, "с_минусовкой.html")
    kar = os.path.join(ROOT, "karaoke.py")
    # Прежние наборы сверяются с русскими надписями — им и собираем русскую.
    # Английскую проверяет отдельный набор.
    base = [sys.executable, kar, song, text, "--align", "energy", "--ui-lang", "ru"]
    subprocess.run(base + ["-o", mix, "--no-separate"], cwd=ROOT,
                   capture_output=True, check=True)

    # Страница с двумя дорожками. Demucs ради теста гонять незачем: собираем
    # вторую страницу из другого звука и переставляем дорожки руками. Важно,
    # чтобы минус и вокал ОТЛИЧАЛИСЬ — иначе проверка рассинхрона ничего не ловит.
    other = os.path.join(tmp, "второй.wav")
    make_song(other, dur=26.0)
    quieter(other)
    alt = os.path.join(tmp, "второй.html")
    subprocess.run([sys.executable, kar, other, text, "--align", "energy",
                    "--ui-lang", "ru", "-o", alt, "--no-separate"], cwd=ROOT,
                   capture_output=True, check=True)

    # И английская страница — её проверяет набор про язык интерфейса.
    eng = os.path.join(tmp, "english.html")
    subprocess.run([sys.executable, kar, song, text, "--align", "energy",
                    "--ui-lang", "en", "-o", eng, "--no-separate"],
                   cwd=ROOT, capture_output=True, check=True)
    two_tracks(stems, mix, alt)
    return song, text, mix, stems, eng


def quieter(path: str) -> None:
    """Тише вдвое — чтобы вторая дорожка отличалась от первой байтами."""
    import audioop
    import wave
    with wave.open(path, "rb") as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    with wave.open(path, "wb") as w:
        w.setparams(params)
        w.writeframes(audioop.mul(frames, params.sampwidth, 0.5))


def payload(path: str):
    import json
    import re
    s = open(path, encoding="utf-8").read()
    m = re.search(r'(<script id="payload"[^>]*>)(.*?)(</script>)', s, re.S)
    raw = (m.group(2).replace("\\u003c", "<").replace("\\u003e", ">")
                     .replace("\\u0026", "&"))
    return s, m, json.loads(raw)


def two_tracks(dst: str, src_a: str, src_b: str) -> None:
    """Собрать страницу с минусом и вокалом из двух разных записей."""
    import json
    import shutil as sh
    sh.copyfile(src_a, dst)
    s, m, p = payload(dst)
    _, _, b = payload(src_b)
    audio = p.get("audio") or {}
    other = (b.get("audio") or {}).get("mix")
    if "mix" in audio and other:
        audio["instrumental"] = audio.pop("mix")
        audio["vocals"] = other
    out = (json.dumps(p).replace("<", "\\u003c").replace(">", "\\u003e")
                        .replace("&", "\\u0026"))
    open(dst, "w", encoding="utf-8").write(s[:m.start(2)] + out + s[m.end(2):])


def start_studio(port: int, projects: str):
    # Окно Студии теперь двуязычное; наборы писались по русским надписям,
    # поэтому стенд поднимаем по-русски. Английский проверяет отдельный набор.
    env = dict(os.environ, KARAOKE_PROJECTS=projects, KARAOKE_UI_LANG="ru")
    return subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "studio.py"),
         "--port", str(port), "--no-browser"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def make_project(api: str, song: str, text: str) -> bool:
    import json
    body = json.dumps({"audio": song, "lyrics": text,
                       "align": "energy", "separate": False}).encode()
    req = urllib.request.Request(api + "/api/new", data=body,
                                 headers={"Content-Type": "application/json"})
    jid = json.load(urllib.request.urlopen(req, timeout=30))["job"]
    for _ in range(120):
        time.sleep(1)
        with urllib.request.urlopen(f"{api}/api/job?id={jid}", timeout=10) as r:
            job = json.load(r)
        if job.get("done"):
            return bool(job.get("ok"))
    return False


def run_suite(path: str, env: dict) -> tuple:
    try:
        r = subprocess.run(["node", path], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "не уложился в 10 минут"
    out = (r.stdout or "") + (r.stderr or "")
    last = out.strip().splitlines()[-1] if out.strip() else ""
    return last == "Все проверки пройдены", out


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        for f in sorted(os.listdir(UI_DIR)):
            say("  " + f)
        return 0
    quick = "--quick" in args

    head("1. Конвейер: текст, разметка, сборка страницы")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_pipeline.py")],
                       cwd=ROOT)
    if r.returncode != 0:
        say("\nПРОВАЛ на проверках конвейера — дальше идти незачем.")
        return 1
    head("1б. Доставка: запуск, имена файлов, настройки, язык консоли, ролик")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_delivery.py")],
                       cwd=ROOT)
    if r.returncode != 0:
        say("\nПРОВАЛ на проверках доставки.")
        return 1

    head("1в. Командная строка: ключи, ошибки, пакетный режим")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_cli.py")], cwd=ROOT)
    if r.returncode != 0:
        say("\nПРОВАЛ на проверках командной строки.")
        return 1

    if os.environ.get("KARAOKE_HEAVY"):
        head("1в–. Настоящие нейросети: Whisper размечает, Demucs отделяет")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_heavy.py")],
                           cwd=ROOT)
        if r.returncode != 0:
            say("\nПРОВАЛ на проверках с нейросетями.")
            return 1

    if os.environ.get("KARAOKE_DOCKER"):
        head("1в+. Контейнер: образ, окно и сборка песни внутри")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_container.py")],
                           cwd=ROOT)
        if r.returncode != 0:
            say("\nПРОВАЛ на проверках контейнера.")
            return 1

    head("1г. Готовый ролик: цвета голосов и что тексты не наезжают")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_video_colors.py")],
                       cwd=ROOT)
    if r.returncode != 0:
        say("\nПРОВАЛ на проверках ролика.")
        return 1

    if quick:
        say("\n--quick: браузерные наборы пропущены.")
        return 0

    if not have_node():
        say("\nNode.js не найден — наборы для окна и страницы пропущены.")
        say("Поставьте Node и `npm install jsdom`, чтобы их прогонять.")
        if os.environ.get("KARAOKE_REQUIRE_BROWSER"):
            say("KARAOKE_REQUIRE_BROWSER=1 — пропуск считается провалом.")
            return 1
        return 0
    if not have_module("jsdom"):
        say("\nНет пакета jsdom — наборы для окна и страницы пропущены.")
        say("Лечится так:  npm install jsdom")
        return 0

    tmp = tempfile.mkdtemp(prefix="karaoke_tests_")
    projects = os.path.join(tmp, "projects")
    os.makedirs(projects, exist_ok=True)
    srv = None
    failed = []
    try:
        head("2. Тестовая песня и страницы")
        song, text, mix, stems, eng = build_pages(tmp)
        say(f"  собрано: {os.path.basename(mix)}, {os.path.basename(stems)}")

        head("3. Студия на свободном порту")
        port = free_port()
        api = f"http://127.0.0.1:{port}"
        srv = start_studio(port, projects)
        if not wait_for(api + "/"):
            say("  студия не поднялась — наборы для окна пропущены")
            return 1
        say(f"  {api} — свежий проект…")
        if not make_project(api, song, text):
            say("  проект не собрался")
            return 1
        say("  проект готов")

        env = dict(os.environ, KARAOKE_API=api, KARAOKE_ROOT=ROOT, KARAOKE_PAGE_MIX=mix,
                   KARAOKE_PAGE_STEMS=stems, KARAOKE_PAGE_EN=eng, PAGE=stems,
                   KARAOKE_SONG=song, KARAOKE_TEXT=text)

        head("4. Окно и страница (jsdom)")
        for name in sorted(os.listdir(UI_DIR)):
            if not name.endswith(".mjs") or NEEDS_BROWSER(name):
                continue      # ему нужен настоящий браузер, он идёт следующим шагом
            ok, out = run_suite(os.path.join(UI_DIR, name), env)
            say(f"  {'ok   ' if ok else 'ПРОВАЛ'}  {name}")
            if not ok:
                failed.append(name)
                for line in [l for l in out.strip().splitlines() if "✗" in l or "ПРОВАЛЕНО" in l][:12] or out.strip().splitlines()[-12:]:
                    say("        " + line)

        head("5. Настоящий браузер")
        if have_module("puppeteer"):
            mouse = [os.path.join(UI_DIR, n) for n in sorted(os.listdir(UI_DIR))
                     if NEEDS_BROWSER(n)]
            for path in [os.path.join(ROOT, "tests", "test_browser.mjs")] + mouse:
                ok, out = run_suite(path, env)
                say(f"  {'ok   ' if ok else 'ПРОВАЛ'}  {os.path.basename(path)}")
                if not ok:
                    failed.append(os.path.basename(path))
                    for line in [l for l in out.strip().splitlines() if "✗" in l or "ПРОВАЛЕНО" in l][:12] or out.strip().splitlines()[-12:]:
                        say("        " + line)
        else:
            say("  puppeteer не установлен — пропускаю.")
            say("  npm install puppeteer && npx puppeteer browsers install chrome")
            # Молчаливый пропуск половины проверок выглядит как «всё зелёное».
            # На сервере это недопустимо: там просят прогнать всё.
            if os.environ.get("KARAOKE_REQUIRE_BROWSER"):
                failed.append("браузерные наборы пропущены")
    finally:
        if srv:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except Exception:
                srv.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    head("Итог")
    if failed:
        say("  провалено: " + ", ".join(failed))
        return 1
    say("  всё зелёное")
    return 0


if __name__ == "__main__":
    sys.exit(main())
