#!/usr/bin/env python3
"""Диагностика готовой караоке-страницы: где разъехались тайминги.

    py tools\\diagnose.py "D:\\Музыка\\Pesnya_karaoke.html"
    py tools\\diagnose.py "...html" "D:\\Музыка\\Песня.mp3"    # ещё и сверить с оригиналом

Печатает отчёт — скопируйте его целиком в чат.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio import audio as AU  # noqa: E402

PAYLOAD_RE = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)


def mmss(t) -> str:
    if t is None:
        return "—"
    return f"{int(t // 60)}:{t % 60:05.2f}"


def load_payload(html_path: str) -> dict:
    with open(html_path, encoding="utf-8") as f:
        m = PAYLOAD_RE.search(f.read())
    if not m:
        raise SystemExit("Это не похоже на страницу, собранную этой программой.")
    raw = (m.group(1).replace("\\u003c", "<").replace("\\u003e", ">")
           .replace("\\u0026", "&"))
    return json.loads(raw)


def track_duration(uri: str, tmp: str, name: str):
    """Длительность дорожки: она внутри страницы (data:) или лежит файлом рядом."""
    if uri.startswith("data:"):
        head, _, b64 = uri.partition(",")
        ext = ".mp3" if "mpeg" in head else (".ogg" if "ogg" in head else ".m4a")
        path = os.path.join(tmp, name + ext)
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        size = os.path.getsize(path)
    else:
        from urllib.parse import unquote
        path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), unquote(uri))
        if not os.path.isfile(path):
            return None, 0
        size = os.path.getsize(path)
    try:
        return AU.duration(path), size
    except Exception:
        return None, size


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    html_path = argv[0]
    if not os.path.isfile(html_path):
        print(f"Не найден файл: {html_path}")
        return 2

    P = load_payload(html_path)
    D = P["data"]
    lines = D["lines"]
    words = [w for ln in lines for w in ln["words"]]

    print("=" * 62)
    print("  ДИАГНОСТИКА КАРАОКЕ")
    print("=" * 62)
    print(f"Файл       : {os.path.basename(html_path)}")
    print(f"Песня      : {D.get('title') or '—'} / {D.get('artist') or '—'}")
    print(f"Разметка   : {P.get('engineLabel')}")
    ver = P.get("player")
    from kstudio import __version__ as cur
    if not ver:
        print(f"Плеер      : старее 1.4 — страницу стоит пересобрать (сейчас {cur})")
    elif ver != cur:
        print(f"Плеер      : {ver}, а программа уже {cur} — стоит пересобрать")
    else:
        print(f"Плеер      : {ver} (актуальный)")
    print(f"Строк      : {len(lines)}   слов: {len(words)}")

    dur = D.get("duration") or 0
    print(f"\nДлительность в разметке : {mmss(dur)}")

    tmp = tempfile.mkdtemp(prefix="karaoke_diag_")
    real = {}
    for name, uri in P.get("audio", {}).items():
        d, size = track_duration(uri, tmp, name)
        real[name] = d
        kind = "внутри страницы" if uri.startswith("data:") else "файлом рядом"
        print(f"Дорожка {name:12}: {mmss(d)}  ({size/1024/1024:.1f} МБ, {kind})")

    if len(argv) > 1 and os.path.isfile(argv[1]):
        try:
            print(f"Исходный файл           : {mmss(AU.duration(argv[1]))}")
        except Exception as e:
            print(f"Исходный файл           : не прочитался ({e})")

    if not lines:
        print("\nВ странице нет ни одной строки текста.")
        return 1

    first, last = lines[0]["start"], lines[-1]["end"]
    print(f"\nПервая строка начинается: {mmss(first)}")
    print(f"Последняя заканчивается : {mmss(last)}")

    base = max([d for d in real.values() if d] + [dur]) or 1
    cover = last / base
    print(f"Покрытие песни текстом  : {cover * 100:.0f}%")

    print("\n" + "-" * 62)
    problems = []
    if cover < 0.75:
        problems.append(
            f"Текст кончается на {cover*100:.0f}% песни — разметка сжата примерно "
            f"в {1/cover:.1f} раза. Именно это ощущается как «текст бежит быстрее»."
        )
    if cover > 1.02:
        problems.append("Разметка вылезает за конец песни.")

    durs = [d for d in real.values() if d]
    if durs and dur and abs(max(durs) - dur) > 1.0:
        problems.append(
            f"Звук в странице ({mmss(max(durs))}) не совпадает с длительностью, "
            f"под которую считалась разметка ({mmss(dur)})."
        )
    if len(durs) > 1 and max(durs) - min(durs) > 1.0:
        problems.append(f"Дорожки разной длины: {mmss(min(durs))} и {mmss(max(durs))}.")

    gaps = [lines[i + 1]["start"] - lines[i]["start"] for i in range(len(lines) - 1)]
    if len(gaps) > 3:
        avg = sum(gaps) / len(gaps)
        spread = (sum((g - avg) ** 2 for g in gaps) / len(gaps)) ** 0.5
        print(f"Шаг между строками: в среднем {avg:.2f}с, разброс {spread:.2f}с")
        if spread < 0.15 * avg:
            problems.append(
                "Строки идут через равные промежутки — признак того, что "
                "выравнивание не сработало и текст разложен механически."
            )

    zero = sum(1 for w in words if w.get("d", 0) <= 0.01)
    if zero:
        problems.append(f"{zero} слов нулевой длины.")

    print()
    if problems:
        print("НАЙДЕНО:")
        for p in problems:
            print("  • " + p)
    else:
        print("Ничего подозрительного не нашёл: разметка покрывает песню целиком,")
        print("длины дорожек сходятся, шаг строк неравномерный (значит, реальный).")

    print("\nПервые 5 строк:")
    for ln in lines[:5]:
        print(f"  [{mmss(ln['start'])}] {ln['text'][:44]}")
    print("Последние 3 строки:")
    for ln in lines[-3:]:
        print(f"  [{mmss(ln['start'])}] {ln['text'][:44]}")
    print("=" * 62)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
