#!/usr/bin/env python3
"""The finished video: the voice colours, and that the texts do not overlap.

Проверять только исходники мало: в MP4 всё рисуется своим кодом, и цвета там
однажды оказались одинаковыми, хотя в редакторе были разные.
"""

from __future__ import annotations

import array
import importlib.util
import json
import math
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
        intro = False
        intro = False        # these frames measure the song, not the opening
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

    print("\nThe cover stands behind the lyrics, dark enough to read over")
    # A red cover: the backdrop must take its colour, stay dark, and blur away
    # every sharp edge — the words are what the frame is for.
    from PIL import Image as _Img
    import base64 as _b64
    import io as _io
    cbuf = _io.BytesIO()
    half = _Img.new("RGB", (320, 180), (230, 20, 20))
    half.paste(_Img.new("RGB", (160, 180), (20, 20, 230)), (160, 0))
    half.save(cbuf, "JPEG")
    cover_uri = "data:image/jpeg;base64," + _b64.b64encode(cbuf.getvalue()).decode()
    bgc = video.make_background(640, 360, cover_uri)
    px_l = bgc.getpixel((80, 180))
    px_r = bgc.getpixel((560, 180))
    check("the backdrop takes the cover's colours",
          px_l[0] > px_l[2] and px_r[2] > px_r[0], (px_l, px_r))
    check("and stays dark enough to read over",
          max(sum(bgc.getpixel((x, y))) for x, y in
              [(80, 60), (320, 180), (560, 300)]) < 330,
          [sum(bgc.getpixel(p2)) for p2 in [(80, 60), (320, 180), (560, 300)]])
    mid = bgc.getpixel((320, 180))
    check("the seam between the halves is blurred away",
          abs(int(mid[0]) - int(mid[2])) < 60, mid)
    check("a broken cover falls back to the gradient without a word",
          video.make_background(64, 36, "data:image/jpeg;base64,AAAA").getpixel((2, 2))
          == video.make_background(64, 36).getpixel((2, 2)))

    print("\nThe countdown aims at the singer's line")
    # A na-na-na in the gap is not the singer's cue: the dots and the pill both
    # skip backing lines when picking their target.
    q_lines = [
        {"text": "lead", "start": 2.0, "end": 4.0, "voice": 1, "words": []},
        {"text": "(na)", "start": 8.0, "end": 9.0, "voice": 2, "backing": True,
         "words": []},
        {"text": "(na again)", "start": 10.0, "end": 11.0, "voice": 2,
         "backing": True, "words": []},
        {"text": "next lead", "start": 20.0, "end": 22.0, "voice": 1, "words": []},
    ]
    check("the dots skip one backing line", video.next_sung(q_lines, 0) == 3)
    check("and a chain of them", video.next_sung(q_lines, 1) == 3)
    check("from before the first line too", video.next_sung(q_lines, -1) == 0)
    check("and past the end they say so", video.next_sung(q_lines, 3) == 4)

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

    print("\nA duet frame: the backing smaller, to the right, off the dots")
    # The second voice used to draw at full size and land on the countdown
    # dots. Now the lead sits where a solo line sits, and the backing is
    # smaller, right-aligned, tucked under it like a reply.
    duet_song = {"colors": ["#00ff00", "#ff00ff"],
                 "theme": {"bg": "#000000", "text": "#ffffff"},
                 "data": {"title": "T", "duration": 20.0, "lines": [
                     {"text": "lead line here", "start": 5.0, "end": 9.0, "voice": 1,
                      "words": [{"w": "lead", "t": 5.0, "d": 1.3, "s": 1},
                                {"w": "line", "t": 6.3, "d": 1.3, "s": 1},
                                {"w": "here", "t": 7.6, "d": 1.3, "s": 1}]},
                     {"text": "(na-na-na)", "start": 5.5, "end": 10.5, "voice": 2,
                      "backing": True,
                      "words": [{"w": "(na-na-na)", "t": 5.5, "d": 5.0, "s": 3}]},
                     {"text": "next lead", "start": 12.0, "end": 14.0, "voice": 1,
                      "words": [{"w": "next", "t": 12.0, "d": 1.0, "s": 1},
                                {"w": "lead", "t": 13.0, "d": 1.0, "s": 1}]}]}}
    wavd = tone(os.path.join(tmp, "d.wav"), 220.0, 20.0)
    class AD:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        intro = False
        start, seconds, audio, timings = 5.8, 4.5, "minus", None
        output = os.path.join(tmp, "duet.mp4")
    video.render(duet_song, wavd, AD.output, AD())
    pngd = os.path.join(tmp, "duet.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "1.0", "-i", AD.output,
                    "-frames:v", "1", pngd], check=True)
    imd = Image.open(pngd).convert("RGB")
    Wd, Hd = imd.size

    def ink_at(y0, y1, x0=0.0, x1=1.0):
        return sum(1 for y in range(int(Hd * y0), int(Hd * y1))
                   for x in range(int(Wd * x0), int(Wd * x1), 2)
                   if sum(imd.getpixel((x, y))) > 90)

    lead_ink = ink_at(0.38, 0.50)
    back_left = ink_at(0.50, 0.60, 0.0, 0.5)
    back_right = ink_at(0.50, 0.60, 0.5, 1.0)
    check("the lead is drawn where a solo line sits", lead_ink > 150, lead_ink)
    check("the backing is there, under it", back_left + back_right > 30,
          back_left + back_right)
    check("and it leans right, smaller than the lead",
          back_right > back_left * 1.5 and (back_left + back_right) < lead_ink,
          f"left {back_left}, right {back_right}, lead {lead_ink}")

    # …and when the lead ends but the na-na-na carries on, the backing keeps
    # its side seat instead of being promoted to the main one, full size, in
    # the way of the lead text.
    png_alone = os.path.join(tmp, "duet-alone.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "3.9", "-i", AD.output,
                    "-frames:v", "1", png_alone], check=True)
    ima = Image.open(png_alone).convert("RGB")
    Wa, Ha = ima.size

    def ink_a(y0, y1, x0=0.0, x1=1.0):
        return sum(1 for y in range(int(Ha * y0), int(Ha * y1))
                   for x in range(int(Wa * x0), int(Wa * x1), 2)
                   if sum(ima.getpixel((x, y))) > 90)

    main_seat = ink_a(0.36, 0.48)
    side_left = ink_a(0.46, 0.58, 0.0, 0.5)
    side_right = ink_a(0.46, 0.58, 0.5, 1.0)
    check("with the lead gone, the main seat stays empty",
          main_seat < 40, main_seat)
    check("the lone backing still sits small to the right",
          side_right > 30 and side_right > side_left * 1.5,
          f"left {side_left}, right {side_right}")
    check("and the next lead still waits below",
          ink_a(0.58, 0.70) > 40, ink_a(0.58, 0.70))

    print("\nThe frame reads forward, not back")
    # The sung line is gone from the frame; the current line has the next one
    # under it and the one after that fainter still — a queue, not a history.
    frames_song = {"colors": ["#00ff00", "#ff00ff"],
                   "theme": {"bg": "#000000", "text": "#ffffff"},
                   "data": {"title": "T", "duration": 20.0, "lines": [
                       {"text": "spent line", "start": 1.0, "end": 3.0, "voice": 1,
                        "words": [{"w": "spent", "t": 1.0, "d": 1.0, "s": 1},
                                  {"w": "line", "t": 2.0, "d": 1.0, "s": 1}]},
                       {"text": "current one", "start": 5.0, "end": 8.0, "voice": 1,
                        "words": [{"w": "current", "t": 5.0, "d": 1.5, "s": 2},
                                  {"w": "one", "t": 6.5, "d": 1.5, "s": 1}]},
                       {"text": "coming next", "start": 9.0, "end": 11.0, "voice": 1,
                        "words": [{"w": "coming", "t": 9.0, "d": 1.0, "s": 2},
                                  {"w": "next", "t": 10.0, "d": 1.0, "s": 1}]},
                       {"text": "after that", "start": 12.0, "end": 14.0, "voice": 1,
                        "words": [{"w": "after", "t": 12.0, "d": 1.0, "s": 2},
                                  {"w": "that", "t": 13.0, "d": 1.0, "s": 1}]}]}}
    wavq = tone(os.path.join(tmp, "q.wav"), 220.0, 20.0)
    class AQ:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        intro = False
        start, seconds, audio, timings = 5.5, 2.0, "minus", None
        output = os.path.join(tmp, "queue.mp4")
    video.render(frames_song, wavq, AQ.output, AQ())
    pngq = os.path.join(tmp, "queue.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "1.0", "-i", AQ.output,
                    "-frames:v", "1", pngq], check=True)
    imq = Image.open(pngq).convert("RGB")
    Wq, Hq = imq.size
    def band_ink(y0, y1):
        return sum(1 for y in range(int(Hq * y0), int(Hq * y1))
                   for x in range(0, Wq, 2) if sum(imq.getpixel((x, y))) > 90)
    top = band_ink(0.25, 0.40)          # where the spent line used to sit
    mainb = band_ink(0.40, 0.52)
    nextb = band_ink(0.55, 0.66)
    next2b = band_ink(0.67, 0.78)
    check("the sung line is gone from the frame", top < mainb * 0.15,
          f"top {top} vs main {mainb}")
    check("the current line is the brightest thing", mainb > 100, mainb)
    check("the next line waits under it", nextb > 40, nextb)
    check("and the one after that is present but fainter",
          0 < next2b < nextb, f"{next2b} vs {nextb}")

    print("\nThe frame speaks the language of the song")
    # The countdown stands among the lyrics, not among the program's menus:
    # “END” over a Russian song is somebody else's caption pasted on.
    ru_song = {"data": {"lines": [{"text": "Пожелай мне удачи в бою"}]}}
    en_song = {"data": {"lines": [{"text": "Tear out my heart and soul"}]}}
    check("a Russian song is spoken to in Russian", video.frame_lang(ru_song) == "ru")
    check("an English one in English", video.frame_lang(en_song) == "en")
    check("and the page's own choice does not overrule the letters",
          video.frame_lang({"uiLang": "en",
                            "data": {"lines": [{"text": "Группа крови"}]}}) == "ru")
    check("with no letters to judge by, that choice stands",
          video.frame_lang({"uiLang": "ru", "data": {"lines": [{"text": "..."}]}}) == "ru")
    ru_pill = video.pill_text("ru", -1, {"text": "Пожелай мне"}, 9.4)
    en_pill = video.pill_text("en", 5, None, 4.0)
    check("the intro pill is written the same way",
          ru_pill.startswith("ВСТУПЛЕНИЕ") and "до «Пожелай мне»" in ru_pill
          and "10 с" in ru_pill, ru_pill)
    check("and an English song ends in English",
          en_pill == "END   4 s   until the end", en_pill)

    print("\nThe dots count a wait, and the song ends on an empty stage")
    # Three dots under a line being sung, with the next line already in the
    # queue below, told the singer nothing. They belong to a real wait. And a
    # last line hanging lit to the end of the recording read as a frozen
    # picture: it stays a few seconds, then the stage empties.
    def one_line(text, a, b):
        return {"text": text, "start": a, "end": b, "voice": 1,
                "words": [{"w": text, "t": a, "d": b - a, "s": 1}]}
    ending = {"colors": ["#00ff00", "#ff00ff"],
              "theme": {"bg": "#000000", "text": "#ffffff"},
              "data": {"title": "T", "duration": 24.0, "lines": [
                  one_line("first line here", 1.0, 3.0),
                  one_line("second right after", 3.5, 5.5),
                  one_line("third after a pause", 12.0, 14.0)]}}
    wav3 = tone(os.path.join(tmp, "c.wav"), 220.0, 24.0)
    class A5:
        width, height, fps, crf = 640, 360, 5, 30
        preset, font = "ultrafast", None
        intro = False
        start, seconds, audio, timings = 0.0, 24.0, "minus", None
        output = os.path.join(tmp, "ending.mp4")
    video.render(ending, wav3, A5.output, A5())

    def band(at, y0, y1, lit=False):
        # `lit` counts only the dots that burn: a grey dot and a lit one are
        # both ink, and counting ink alone would call a countdown one that
        # never counts.
        shot = os.path.join(tmp, f"end-{at}.png")
        subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", str(at),
                        "-i", A5.output, "-frames:v", "1", shot], check=True)
        im5 = Image.open(shot).convert("RGB")
        W5, H5 = im5.size
        px = (im5.getpixel((x, y))
              for y in range(int(H5 * y0), int(H5 * y1)) for x in range(0, W5, 2))
        if lit:                       # the main voice's colour, #00ff00 here
            return sum(1 for r, g, b in px if g > 120 and r < 90 and b < 90)
        return sum(1 for c in px if sum(c) > 90)

    DOTS, SEAT = (0.50, 0.56), (0.38, 0.50)
    check("no dots under a line being sung with the next one close behind",
          band(2.0, *DOTS) == 0, band(2.0, *DOTS))
    check("but the singing itself is there", band(2.0, *SEAT) > 150, band(2.0, *SEAT))
    check("in a real wait the dots come up", band(6.5, *DOTS) > 20, band(6.5, *DOTS))
    check("far from the line none of them burns yet",
          band(6.5, *DOTS, lit=True) == 0, band(6.5, *DOTS, lit=True))
    check("and they are lit as the line comes in",
          band(11.5, *DOTS, lit=True) > 10, band(11.5, *DOTS, lit=True))
    check("the last line stays a few seconds after it is sung",
          band(16.0, *SEAT) > 150, band(16.0, *SEAT))
    check("and then the stage empties instead of freezing",
          band(20.0, *SEAT) == 0, band(20.0, *SEAT))

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
        intro = False
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

    print("\nThe song's name is readable and clear of the countdown")
    # The name grew from caption size to its own font — and the pill moved
    # down. Neither may lean on the other: not one pixel row is shared.
    named = {"colors": ["#00ff00", "#ff00ff"], "theme": {"bg": "#000000", "text": "#ffffff"},
             "title": "Forevermore — Lorna Shore",
             "data": {"title": "Forevermore", "artist": "Lorna Shore",
                      "duration": 24.0, "lines": [
                 {"text": "Первая строка после долгого ожидания",
                  "start": 13.0, "end": 16.5, "voice": 1,
                  "words": [{"w": "Первая", "t": 13.0, "d": 3.5, "s": 1}]}]}}
    class A4:
        width, height, fps, crf = 1280, 720, 5, 30
        preset, font = "ultrafast", None
        intro = False
        start, seconds, audio, timings = 3.0, 1.0, "minus", None
        output = os.path.join(tmp, "named.mp4")
    video.render(named, wav2, A4.output, A4())
    png4 = os.path.join(tmp, "named.png")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", "0.5", "-i", A4.output,
                    "-frames:v", "1", png4], check=True)
    im4 = Image.open(png4).convert("RGB")
    W4, H4 = im4.size
    # The name lives at the left edge, the pill's tail in the right half.
    # The strips stay far apart on the x axis too: a wide pill reaches well
    # into the left third, and must not be mistaken for the name.
    t_rows = [y for y in range(0, int(H4 * 0.12))
              for x in range(int(W4 * 0.04), int(W4 * 0.18), 2)
              if sum(im4.getpixel((x, y))) > 90]
    p_rows = [y for y in range(0, int(H4 * 0.25))
              for x in range(int(W4 * 0.55), int(W4 * 0.96), 2)
              if sum(im4.getpixel((x, y))) > 90]
    check("the name is drawn large enough to read",
          t_rows and (max(t_rows) - min(t_rows)) >= H4 * 0.017,
          f"name rows span {max(t_rows) - min(t_rows) if t_rows else 0}px of {H4}")
    check("the name and the pill do not touch",
          t_rows and p_rows and max(t_rows) < min(p_rows) - H4 * 0.008,
          f"name ends {max(t_rows) if t_rows else '—'}, pill starts {min(p_rows) if p_rows else '—'}")

    print("\nThe clip opens with the name and a count of three")
    # A karaoke that starts on the first frame catches everybody mid-breath.
    class AI:
        width, height, fps, crf = 480, 270, 4, 30
        preset, font = "ultrafast", None
        intro = True
        start, seconds, audio, timings = 0.0, 12.0, "minus", None
        output = os.path.join(tmp, "opening.mp4")
    class NoIntro(AI):
        intro = False
    check("the opening is the card and the count", video.intro_lead(AI(), "Name") == 6.0,
          video.intro_lead(AI(), "Name"))
    check("a nameless song is only counted in", video.intro_lead(AI(), "") == 3.0,
          video.intro_lead(AI(), ""))
    check("and it can be turned off altogether",
          video.intro_lead(NoIntro(), "Name") == 0.0, video.intro_lead(NoIntro(), "Name"))

    opening = {"colors": ["#00ff00", "#ff00ff"],
               "theme": {"bg": "#000000", "text": "#ffffff"},
               "data": {"title": "Named Song", "artist": "Somebody",
                        "duration": 12.0, "lines": [
                   one_line("the first line of it", 7.0, 10.0)]}}
    wav4 = tone(os.path.join(tmp, "d.wav"), 220.0, 12.0)
    video.render(opening, wav4, AI.output, AI())
    check("the clip grew by the opening, and by exactly that much",
          abs(AU.duration(AI.output) - 18.0) < 0.35, AU.duration(AI.output))

    def mid_ink(at, lit=False):
        # `lit` counts only what is being sung right now: before the song a
        # frame legitimately holds the coming line, dim, in the queue — ink
        # that says nothing about whether anybody has started singing.
        shot = os.path.join(tmp, f"open-{at}.png")
        subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", str(at),
                        "-i", AI.output, "-frames:v", "1", shot], check=True)
        imo = Image.open(shot).convert("RGB")
        Wo, Ho = imo.size
        px = (imo.getpixel((x, y)) for y in range(int(Ho * 0.30), int(Ho * 0.75))
              for x in range(0, Wo, 2))
        if lit:
            return sum(1 for r, g, b in px if g > 120 and r < 90 and b < 90)
        return sum(1 for c in px if sum(c) > 110)

    check("the name stands large on the opening card", mid_ink(1.0) > 200, mid_ink(1.0))
    check("then the count takes its place", mid_ink(4.5) > 40, mid_ink(4.5))
    check("and the count is one figure, not a line of words",
          mid_ink(4.5) < mid_ink(1.0), f"{mid_ink(4.5)} vs {mid_ink(1.0)}")
    # The song itself is pushed back by the opening: what used to happen at 8 s
    # now happens at 14 s, and the sound waits with it.
    check("the singing arrives after the opening, not during it",
          mid_ink(14.0, lit=True) > 20 and mid_ink(8.0, lit=True) == 0,
          f"{mid_ink(14.0, lit=True)} lit at 14 s, {mid_ink(8.0, lit=True)} at 8 s")

    heard = os.path.join(tmp, "opening.wav")
    subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-i", AI.output,
                    "-ac", "1", "-ar", "8000", heard], check=True)
    with wave.open(heard) as fh:
        sr_o = fh.getframerate()
        pcm = array.array("h")
        pcm.frombytes(fh.readframes(fh.getnframes()))

    def loud(t0, t1):
        seg = pcm[int(t0 * sr_o):int(t1 * sr_o)]
        return math.sqrt(sum(x * x for x in seg) / max(len(seg), 1))

    check("the music holds back while the count runs", loud(0.5, 5.5) < 20, loud(0.5, 5.5))
    check("and comes in when the count is done", loud(7.0, 11.0) > 200, loud(7.0, 11.0))

    print("\nThe backing does not keep the ending to itself")
    # The last sound is not always the last line in the list: a na-na-na is
    # written under the lead it answers, and a lead can outlast a backing that
    # started later. Asking the list which line is last left the backing
    # hanging alone at the end — and blanked a lead that was still singing.
    tail = {"colors": ["#00ff00", "#ff00ff"],
            "theme": {"bg": "#000000", "text": "#ffffff"},
            "data": {"title": "T", "duration": 24.0, "lines": [
                dict(one_line("then she said she liked", 7.0, 10.0)),
                dict(one_line("(na-na-na)", 9.0, 12.0), voice=2, backing=True)]}}
    wav5 = tone(os.path.join(tmp, "e.wav"), 220.0, 24.0)
    class AT:
        width, height, fps, crf = 480, 270, 4, 30
        preset, font = "ultrafast", None
        intro = False
        start, seconds, audio, timings = 0.0, 24.0, "minus", None
        output = os.path.join(tmp, "tail.mp4")
    video.render(tail, wav5, AT.output, AT())

    def tail_ink(at):
        shot = os.path.join(tmp, f"tail-{at}.png")
        subprocess.run([AU.ffmpeg(), "-y", "-v", "error", "-ss", str(at),
                        "-i", AT.output, "-frames:v", "1", shot], check=True)
        imt = Image.open(shot).convert("RGB")
        Wt, Ht = imt.size
        return sum(1 for y in range(int(Ht * 0.30), int(Ht * 0.75))
                   for x in range(0, Wt, 2) if sum(imt.getpixel((x, y))) > 110)

    check("the lone backing is still there just after it is sung",
          tail_ink(13.5) > 20, tail_ink(13.5))
    check("and the stage empties five seconds after the backing, not the lead",
          tail_ink(17.5) == 0, tail_ink(17.5))

    # …and the mirror case: the backing is written last but ends first, while
    # the lead sings on. Nothing may be blanked while a voice is sounding.
    outlast = {"colors": ["#00ff00", "#ff00ff"],
               "theme": {"bg": "#000000", "text": "#ffffff"},
               "data": {"title": "T", "duration": 24.0, "lines": [
                   dict(one_line("a lead that carries on and on", 7.0, 20.0)),
                   dict(one_line("(na-na)", 9.0, 11.0), voice=2, backing=True)]}}
    AT.output = os.path.join(tmp, "outlast.mp4")
    video.render(outlast, wav5, AT.output, AT())
    check("a lead that outlasts its backing keeps singing on screen",
          tail_ink(19.0) > 20, tail_ink(19.0))

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
