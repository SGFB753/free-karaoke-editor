#!/usr/bin/env python3
"""Готовый ролик: цвета голосов и то, что тексты не наезжают друг на друга.

Проверять только исходники мало: в MP4 всё рисуется своим кодом, и цвета там
однажды оказались одинаковыми, хотя в редакторе были разные.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  ПРОВАЛ ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def tone(path, freq=220.0, dur=8.0, sr=22050):
    import math
    import struct
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", int(0.3 * math.sin(2 * math.pi * freq * i / sr) * 30000))
            for i in range(int(sr * dur))))
    return path


def main():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("  пропуск: нет Pillow, ролик не нарисовать")
        return 0

    spec = importlib.util.spec_from_file_location("video", os.path.join(ROOT, "tools", "video.py"))
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)

    tmp = tempfile.mkdtemp(prefix="karaoke_vid_")
    wav = tone(os.path.join(tmp, "a.wav"))
    # Две строки звучат одновременно: первый голос и второй.
    payload = {
        "colors": ["#00ff00", "#ff00ff"],
        "theme": {"bg": "#000000", "text": "#ffffff"},
        "data": {"title": "T", "duration": 8.0, "lines": [
            {"text": "aaa", "start": 1.0, "end": 5.0, "voice": 1,
             "words": [{"w": "aaa", "t": 1.0, "d": 4.0, "s": 1}]},
            {"text": "bbb", "start": 1.2, "end": 5.0, "voice": 2,
             "words": [{"w": "bbb", "t": 1.2, "d": 3.8, "s": 1}]},
        ]}}

    class Args:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        start, seconds, audio, timings = 0.0, 6.0, "minus", None
        output = os.path.join(tmp, "out.mp4")

    args = Args()
    video.render(payload, wav, args.output, args)
    check("ролик собрался", os.path.isfile(args.output) and os.path.getsize(args.output) > 1000,
          str(os.path.getsize(args.output)) if os.path.isfile(args.output) else "нет файла")

    from kstudio import audio as AU
    png = os.path.join(tmp, "frame.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "4.0", "-i", args.output,
                    "-frames:v", "1", png], check=True)
    from PIL import Image
    im = Image.open(png).convert("RGB")
    W, H = im.size
    rows = {}
    for y in range(H):
        for x in range(0, W, 2):
            r, g, b = im.getpixel((x, y))
            if g > 150 and r < 90 and b < 90:
                rows.setdefault("v1", set()).add(y)
            elif r > 150 and b > 150 and g < 90:
                rows.setdefault("v2", set()).add(y)
    check("первый голос нарисован своим цветом", "v1" in rows, sorted(rows))
    check("второй голос — своим", "v2" in rows, sorted(rows))
    if "v1" in rows and "v2" in rows:
        a, b = rows["v1"], rows["v2"]
        check("цвета разные, а не один на двоих", a != b)
        check("строки не налезают друг на друга", not (a & b),
              f"общих строк пикселей: {len(a & b)}")
        check("вторая строка ниже первой", min(b) > min(a),
              f"первый y={min(a)}, второй y={min(b)}")

    print("\nОтсчёт вступления в ролике")
    intro = {"colors": ["#00ff00", "#ff00ff"], "theme": {"bg": "#000000", "text": "#ffffff"},
             "data": {"title": "T", "duration": 20.0, "lines": [
                 {"text": "aaa", "start": 6.0, "end": 9.5, "voice": 1,
                  "words": [{"w": "aaa", "t": 6.0, "d": 3.5, "s": 1}]}]}}
    wav2 = tone(os.path.join(tmp, "b.wav"), 220.0, 20.0)
    class A3:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        start, seconds, audio, timings = 0.0, 10.0, "minus", None
        output = os.path.join(tmp, "intro.mp4")
    video.render(intro, wav2, A3.output, A3())
    png2 = os.path.join(tmp, "intro.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "3.0", "-i", A3.output,
                    "-frames:v", "1", png2], check=True)
    im2 = Image.open(png2).convert("RGB")
    W2, H2 = im2.size
    top = [im2.getpixel((x, y)) for y in range(int(H2 * 0.06), int(H2 * 0.20))
           for x in range(0, W2, 3)]
    lit = [c for c in top if sum(c) > 90]
    check("во вступлении сверху что-то нарисовано", len(lit) > 40, f"ярких точек: {len(lit)}")
    green = [c for c in top if c[1] > 120 and c[0] < 90 and c[2] < 90]
    check("полоска отсчёта своим цветом", len(green) > 5, f"зелёных точек: {len(green)}")
    # когда поют — плашки быть не должно
    png3 = os.path.join(tmp, "sing.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "7.5", "-i", A3.output,
                    "-frames:v", "1", png3], check=True)
    im3 = Image.open(png3).convert("RGB")
    top3 = [im3.getpixel((x, y)) for y in range(int(H2 * 0.06), int(H2 * 0.20))
            for x in range(0, W2, 3)]
    # Текст должен стоять по центру плашки, а не липнуть к краю.
    # Берём только полосу самой плашки: выше неё слева стоит название песни,
    # и вместе с ним центр «рисунка» уехал бы влево.
    y0, y1 = int(H2 * 0.075), int(H2 * 0.155)
    rows = [y for y in range(y0, y1)
            for x in range(0, W2, 2) if sum(im2.getpixel((x, y))) > 90]
    cols = [x for y in range(y0, y1)
            for x in range(0, W2, 2) if sum(im2.getpixel((x, y))) > 90]
    if rows and cols:
        cx_ink = (min(cols) + max(cols)) / 2
        check("плашка стоит по центру кадра", abs(cx_ink - W2 / 2) <= W2 * 0.03,
              f"центр рисунка {cx_ink:.0f}, центр кадра {W2/2:.0f}")
        # ищем края самой плашки по её рамке в той же полосе
        band = int((min(rows) + max(rows)) / 2)
        lit_x = [x for x in range(W2) if sum(im2.getpixel((x, band))) > 60]
        if lit_x:
            left_gap = min(lit_x)
            right_gap = W2 - max(lit_x)
            check("плашка симметрична по краям", abs(left_gap - right_gap) <= W2 * 0.02,
                  f"слева {left_gap}, справа {right_gap}")

    check("на пении плашка исчезает", len([c for c in top3 if sum(c) > 90]) < len(lit) / 3,
          f"было {len(lit)}, стало {len([c for c in top3 if sum(c) > 90])}")

    print("\nЦвета не схлопываются в пустой кадр")
    dark = {"colors": ["#050505", "#0a0a0a"], "theme": {"bg": "#000000", "text": "#050505"},
            "data": payload["data"]}
    video.apply_colors(dark)
    def contrast(c):
        return video._contrast(c, video.BG_TOP)
    check("подсветка первого голоса видна на фоне", contrast(video.COL_HOT) >= 2.4,
          f"{video.COL_HOT} на {video.BG_TOP}: {contrast(video.COL_HOT):.1f}")
    check("подсветка второго тоже", contrast(video.COL_HOT2) >= 2.4,
          f"{video.COL_HOT2}: {contrast(video.COL_HOT2):.1f}")
    check("неспетые строки различимы", contrast(video.COL_DIM) >= 2.0,
          f"{video.COL_DIM}: {contrast(video.COL_DIM):.1f}")
    video.apply_colors(payload)          # возвращаем цвета проверки

    print("\nОтчёт перед роликом")
    class A2:
        width, height, fps, audio = 1920, 1080, 30, "minus"
    rep = video.video_report(payload, A2(), 8.0, 8.0)
    for what in ("Song", "Lines", "Together", "Original sings", "Colours", "Audio", "Frames"):
        check(f"в отчёте есть «{what}»", what in rep, rep.replace("\n", " | ")[:100])
    check("сказано про второй голос", "second voice: 1" in rep, rep)
    check("сказано, что голоса пересекаются", "1 place where" in rep, rep)
    check("цвета названы", "#00ff00" in rep and "#ff00ff" in rep, rep)
    from kstudio import i18n
    i18n.set_lang("ru")
    rep_ru = video.video_report(payload, A2(), 8.0, 8.0)
    check("по-русски тоже", "Отчёт перед роликом" in rep_ru and "Одновременно" in rep_ru,
          rep_ru.replace("\n", " | ")[:80])
    i18n.set_lang("en")
    plain = {"data": {"lines": [{"text": "a", "start": 0, "end": 1, "words": []}]}}
    warn = video.video_report(plain, A2(), 8.0, 8.0)
    check("без своих цветов отчёт предупреждает", "!" in warn, warn.replace("\n", " | ")[:90])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("ПРОВАЛЕНО: " + ", ".join(failures) if failures else "Все проверки пройдены"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
