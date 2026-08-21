#!/usr/bin/env python3
"""The finished video: the voice colours, and that the texts do not overlap.

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
    print(("  OK     " if cond else "  FAILED ") + name + (" — " + str(extra) if extra else ""))
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
        print("  skipped: no Pillow, the video cannot be drawn")
        return 0

    spec = importlib.util.spec_from_file_location("video", os.path.join(ROOT, "tools", "video.py"))
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)

    tmp = tempfile.mkdtemp(prefix="karaoke_vid_")
    wav = tone(os.path.join(tmp, "a.wav"))
    # Two lines sound at once: the first voice and the second.
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
    check("the video was built", os.path.isfile(args.output) and os.path.getsize(args.output) > 1000,
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
    check("the first voice is drawn in its own colour", "v1" in rows, sorted(rows))
    check("the second in its own", "v2" in rows, sorted(rows))
    if "v1" in rows and "v2" in rows:
        a, b = rows["v1"], rows["v2"]
        check("the colours differ, not one for both", a != b)
        check("the lines do not overlap", not (a & b),
              f"shared pixel rows: {len(a & b)}")
        check("the second line is below the first", min(b) > min(a),
              f"first y={min(a)}, second y={min(b)}")

    print("\nThe countdown dots burn one per second")
    # Two at once and then the third — how it used to go — reads as a stutter,
    # not a countdown. The staircase must match the player's: 1, 2, 3.
    stair = [video.pips_lit(10.0, left) for left in (2.9, 1.9, 0.9)]
    check("in a long pause: one dot, then two, then three", stair == [1, 2, 3], stair)
    # a short pause is divided into thirds of ITSELF, so no dot is starved
    short = [video.pips_lit(2.6, left) for left in (2.4, 1.5, 0.5)]
    check("a short pause still counts in even thirds", short == [1, 2, 3], short)
    check("the second third begins where it should",
          video.pips_lit(2.6, 1.75) == 1 and video.pips_lit(2.6, 1.70) == 2,
          [video.pips_lit(2.6, 1.75), video.pips_lit(2.6, 1.70)])
    check("outside the window nothing burns",
          video.pips_lit(10.0, 3.4) == 0 and video.pips_lit(10.0, 0.0) == 0
          and video.pips_lit(1.0, 2.0) == 0)
    check("and it never jumps past three", video.pips_lit(10.0, 0.01) == 3)

    print("\nThe intro countdown in the video")
    # The wait has to be a real one: a countdown is shown from ten seconds up,
    # because anything shorter is a breath between lines, not an interlude.
    intro = {"colors": ["#00ff00", "#ff00ff"], "theme": {"bg": "#000000", "text": "#ffffff"},
             "data": {"title": "T", "duration": 24.0, "lines": [
                 {"text": "aaa", "start": 13.0, "end": 16.5, "voice": 1,
                  "words": [{"w": "aaa", "t": 13.0, "d": 3.5, "s": 1}]}]}}
    wav2 = tone(os.path.join(tmp, "b.wav"), 220.0, 24.0)
    class A3:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        start, seconds, audio, timings = 0.0, 18.0, "minus", None
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
    check("something is drawn at the top during the intro", len(lit) > 40, f"bright pixels: {len(lit)}")
    green = [c for c in top if c[1] > 120 and c[0] < 90 and c[2] < 90]
    check("the countdown bar has its own colour", len(green) > 5, f"green pixels: {len(green)}")
    # while singing there must be no pill
    png3 = os.path.join(tmp, "sing.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "14.5", "-i", A3.output,
                    "-frames:v", "1", png3], check=True)
    im3 = Image.open(png3).convert("RGB")
    top3 = [im3.getpixel((x, y)) for y in range(int(H2 * 0.06), int(H2 * 0.20))
            for x in range(0, W2, 3)]
    # The text must sit in the centre of the pill, not cling to an edge.
    # Only the pill's own band is measured: above it, on the left, sits the song
    # title, and with it the centre of the “ink” would drift left.
    y0, y1 = int(H2 * 0.075), int(H2 * 0.155)
    rows = [y for y in range(y0, y1)
            for x in range(0, W2, 2) if sum(im2.getpixel((x, y))) > 90]
    cols = [x for y in range(y0, y1)
            for x in range(0, W2, 2) if sum(im2.getpixel((x, y))) > 90]
    if rows and cols:
        cx_ink = (min(cols) + max(cols)) / 2
        check("the pill is centred in the frame", abs(cx_ink - W2 / 2) <= W2 * 0.03,
              f"ink centre {cx_ink:.0f}, frame centre {W2/2:.0f}")
        # find the pill's own edges by its outline in the same band
        band = int((min(rows) + max(rows)) / 2)
        lit_x = [x for x in range(W2) if sum(im2.getpixel((x, band))) > 60]
        if lit_x:
            left_gap = min(lit_x)
            right_gap = W2 - max(lit_x)
            check("the pill has equal margins", abs(left_gap - right_gap) <= W2 * 0.02,
                  f"left {left_gap}, right {right_gap}")

    check("the pill disappears once singing starts", len([c for c in top3 if sum(c) > 90]) < len(lit) / 3,
          f"was {len(lit)}, now {len([c for c in top3 if sum(c) > 90])}")

    print("\nColours do not collapse into an empty frame")
    dark = {"colors": ["#050505", "#0a0a0a"], "theme": {"bg": "#000000", "text": "#050505"},
            "data": payload["data"]}
    video.apply_colors(dark)
    def contrast(c):
        return video._contrast(c, video.BG_TOP)
    check("the first voice is visible against the background", contrast(video.COL_HOT) >= 2.4,
          f"{video.COL_HOT} on {video.BG_TOP}: {contrast(video.COL_HOT):.1f}")
    check("so is the second one", contrast(video.COL_HOT2) >= 2.4,
          f"{video.COL_HOT2}: {contrast(video.COL_HOT2):.1f}")
    check("unsung lines are distinguishable", contrast(video.COL_DIM) >= 2.0,
          f"{video.COL_DIM}: {contrast(video.COL_DIM):.1f}")
    video.apply_colors(payload)          # возвращаем цвета проверки

    print("\nThe report before the video")
    class A2:
        width, height, fps, audio = 1920, 1080, 30, "minus"
    rep = video.video_report(payload, A2(), 8.0, 8.0)
    for what in ("Song", "Lines", "Together", "Original sings", "Colours", "Audio", "Frames"):
        check(f"the report has “{what}”", what in rep, rep.replace("\n", " | ")[:100])
    check("the second voice is mentioned", "second voice: 1" in rep, rep)
    check("it says the voices overlap", "1 place where" in rep, rep)
    check("the colours are named", "#00ff00" in rep and "#ff00ff" in rep, rep)
    from kstudio import i18n
    i18n.set_lang("ru")
    rep_ru = video.video_report(payload, A2(), 8.0, 8.0)
    check("in Russian as well", "Отчёт перед роликом" in rep_ru and "Одновременно" in rep_ru,
          rep_ru.replace("\n", " | ")[:80])
    i18n.set_lang("en")
    plain = {"data": {"lines": [{"text": "a", "start": 0, "end": 1, "words": []}]}}
    warn = video.video_report(plain, A2(), 8.0, 8.0)
    check("without its own colours the report warns", "!" in warn, warn.replace("\n", " | ")[:90])

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
