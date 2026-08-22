#!/usr/bin/env python3
"""Rendering a karaoke video to MP4 for YouTube — no OBS, no screen capture.

    py tools\\video.py "D:\\Music\\Pesnya_karaoke.html"
    py tools\\video.py "...html" -o clip.mp4 --audio guide
    py tools\\video.py "...html" --start 60 --seconds 20     # a quick sample

Frames are drawn in code and piped into ffmpeg, which is faster than real
time. The text, the timings and the audio all come from the HTML page itself.
If the timing was edited in the player, export it (“Edit” → “Download timings”)
and pass it with --timings.
"""

from __future__ import annotations

import argparse
import base64
import bisect
import math
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio.i18n import tr        # noqa: E402
from kstudio import audio as AU      # noqa: E402
from kstudio import build as B       # noqa: E402

# ---------------------------------------------------------------- look
# The defaults match the page. When the page carries its own colours and look,
# the video takes them: otherwise everything came out the same colour in the
# finished file while the editor showed two different voices.
BG_TOP = (10, 11, 20)
BG_BOTTOM = (20, 24, 48)
COL_DIM = (93, 100, 128)        # not sung yet
COL_HOT = (77, 225, 255)        # sung, main voice
COL_HOT2 = (255, 138, 209)      # sung, second voice
COL_SIDE = (63, 69, 92)         # neighbouring lines
COL_SECT = (255, 204, 77)       # section label
COL_BAR = (77, 225, 255)
COL_PIP = (52, 58, 82)          # guide dots between lines


def _hex_rgb(value, fallback):
    """“#4de1ff” → (77, 225, 255). Anything unclear is left as it was."""
    c = str(value or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return fallback
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _mix(a, b, k):
    return tuple(int(round(a[i] * (1 - k) + b[i] * k)) for i in range(3))


def _lum(c):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable(color, bg, need):
    """Keep a colour off its background: black on black is an empty video."""
    up = _lum(bg) < 0.5
    out = tuple(color)
    for _ in range(40):
        if _contrast(out, bg) >= need:
            return out
        out = tuple(min(255, int(v + (255 - v) * 0.1 + 3)) if up
                    else max(0, int(v - v * 0.1 - 3)) for v in out)
    return (255, 255, 255) if up else (0, 0, 0)


def apply_colors(payload) -> None:
    """Carry the page colours over into the video."""
    global COL_HOT, COL_HOT2, COL_BAR, COL_DIM, COL_SIDE, BG_TOP, BG_BOTTOM
    colors = payload.get("colors") or []
    COL_HOT = _hex_rgb(colors[0] if len(colors) > 0 else None, COL_HOT)
    COL_HOT2 = _hex_rgb(colors[1] if len(colors) > 1 else None, COL_HOT2)
    COL_BAR = COL_HOT
    theme = payload.get("theme") or {}
    bg = _hex_rgb(theme.get("bg"), None)
    text = _hex_rgb(theme.get("text"), None)
    if bg:
        BG_TOP = bg
        BG_BOTTOM = _mix(bg, (255, 255, 255), 0.06)
    if text and bg:
        # Dim lines use the same colour, only muted: on a light background the
        # default grey would not read at all.
        COL_DIM = _readable(_mix(text, bg, 0.45), bg, 2.2)
        COL_SIDE = _readable(_mix(text, bg, 0.68), bg, 1.6)
    COL_HOT = _readable(COL_HOT, BG_TOP, 2.5)
    COL_HOT2 = _readable(COL_HOT2, BG_TOP, 2.5)


def mmss(t) -> str:
    t = max(float(t or 0), 0.0)
    return f"{int(t // 60)}:{t % 60:04.1f}"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\verdanab.ttf", r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def find_font(explicit=None) -> str:
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit(tr(f"Font not found: {explicit}", f"Шрифт не найден: {explicit}"))
        return explicit
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            return p
    import glob
    for pat in ("/usr/share/fonts/**/*Bold*.ttf", "C:\\Windows\\Fonts\\*.ttf"):
        found = glob.glob(pat, recursive=True)
        if found:
            return found[0]
    raise SystemExit(tr("No .ttf font found — point to one with --font",
                            "Не нашёл ни одного шрифта .ttf — укажите его ключом --font"))


def pips_lit(gap: float, left: float) -> int:
    """How many countdown dots burn, `left` seconds before the next line.

    The wait is divided into three equal thirds of ITSELF — not into fixed
    seconds. A pause of 2.6 s would otherwise give the first dot 0.6 s and the
    others a full second each: a countdown that stutters is worse than none.
    The window is the last three seconds, or the whole pause when it is shorter.
    """
    if gap <= 2.5 or left <= 0 or left > 3:
        return 0
    window = min(3.0, gap)
    done = max(0.0, 1.0 - left / window)
    return min(3, max(1, int(done * 3) + 1))


# ---------------------------------------------------------------- audio
def keep_spans(payload: dict) -> list:
    """Stretches where the original voice is deliberately kept.

    Two sources say so: “♪ Original” on a line, and the stretches marked as
    holding no words — a vocalise has nothing to sing over, and muting it
    would put a hole in the video where the song is loudest.
    """
    data = payload.get("data") or {}
    out = []
    for ln in data.get("lines") or []:
        if ln.get("keep"):
            out.append((float(ln.get("start") or 0), float(ln.get("end") or 0)))
    for pair in data.get("keepSpans") or []:
        try:
            a, b = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        out.append((a, b))
    out.sort()
    merged = []
    for a, b in out:
        if b <= a:
            continue
        if merged and a - merged[-1][1] < 0.35:      # adjacent lines make one stretch
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def extract_audio(payload: dict, html_path: str, tmp: str, mode: str) -> str:
    """Pull the needed track out of the page (or a file next to it) into WAV."""
    srcs = {}
    for name, uri in payload.get("audio", {}).items():
        if uri.startswith("data:"):
            head, _, b64 = uri.partition(",")
            ext = ".mp3" if "mpeg" in head else (".ogg" if "ogg" in head else ".m4a")
            path = os.path.join(tmp, name + ext)
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        else:
            from urllib.parse import unquote
            path = os.path.join(os.path.dirname(os.path.abspath(html_path)), unquote(uri))
            if not os.path.isfile(path):
                continue
        srcs[name] = path

    if not srcs:
        raise SystemExit(tr("The page has no audio.", "В странице нет звука."))

    out = os.path.join(tmp, "track.wav")
    instr, voc, mix = srcs.get("instrumental"), srcs.get("vocals"), srcs.get("mix")

    if mode == "minus":
        spans = keep_spans(payload)
        if spans and instr and voc:
            # On marked lines the voice must stay: backing vocals, speech, a bit
            # that matters to the story. Everywhere else the vocal is muted.
            # volume's `enable` works along the timeline: where the filter is off,
            # the audio passes through untouched.
            # The commas inside the expression are escaped for ffmpeg, not Python.
            cond = "+".join("between(t\\,%.3f\\,%.3f)" % (a, b) for a, b in spans)
            total = sum(b - a for a, b in spans)
            print(tr(f"Video audio: instrumental, the original voice kept on "
                     f"{len(spans)} stretches ({total:.1f} s)",
                     f"Звук ролика: минусовка, оригинальный голос оставлен "
                     f"на {len(spans)} кусках ({total:.1f} с)"))
            p = subprocess.run(
                [AU.ffmpeg(), "-y", "-v", "error", "-i", instr, "-i", voc,
                 "-filter_complex",
                 f"[1:a]volume=0:enable='not({cond})'[v];"
                 f"[0:a][v]amix=inputs=2:normalize=0[a]",
                 "-map", "[a]", "-c:a", "pcm_s16le", out],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                return out
            print(tr("Mixing failed, taking the plain instrumental:\n",
                     "Смешать не вышло, беру чистую минусовку:\n") +
                  p.stderr.decode(errors="replace")[-300:])
        src = instr or mix
        if src is instr and instr:
            print(tr("Video audio: instrumental", "Звук ролика: минусовка"))
        else:
            print(tr("Video audio: the original track (the page has no instrumental)",
                  "Звук ролика: исходная дорожка (минусовки в странице нет)"))
        AU.to_wav(src, out)
        return out

    if instr and voc:
        level = "1.0" if mode == "original" else "0.35"
        print(tr(f"Clip audio: instrumental + vocal ({float(level)*100:.0f}%)",
                 f"Звук ролика: минусовка + вокал ({float(level)*100:.0f}%)"))
        p = subprocess.run(
            [AU.ffmpeg(), "-y", "-v", "error", "-i", instr, "-i", voc,
             "-filter_complex", f"[1:a]volume={level}[v];[0:a][v]amix=inputs=2:normalize=0[a]",
             "-map", "[a]", "-c:a", "pcm_s16le", out],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise SystemExit(tr("Could not mix the tracks:\n",
                                "Не удалось смешать дорожки:\n") +
                             p.stderr.decode(errors="replace")[-500:])
        return out

    print(tr("Video audio: the original track", "Звук ролика: исходная дорожка"))
    AU.to_wav(mix or instr or voc, out)
    return out


# ---------------------------------------------------------------- layout
class LineArt:
    """Prepared images of a line: dim and lit, plus the word positions."""

    def __init__(self, line, font_for, width, margin, main=True, align="center"):
        from PIL import Image, ImageDraw
        words = [w["w"] for w in line["words"]] or [line["text"]]
        text = " ".join(words)
        self.font = font_for(text, width - 2 * margin, main)
        asc, desc = self.font.getmetrics()
        self.h = asc + desc + 8

        total = self.font.getlength(text)
        # the backing sits to the right, tucked under its lead like a reply
        x0 = (width - margin - total) if align == "right" else (width - total) / 2
        x0 = max(x0, margin)
        self.word_x, self.word_w = [], []
        prefix = ""
        for i, wd in enumerate(words):
            self.word_x.append(x0 + self.font.getlength(prefix))
            prefix += wd + (" " if i < len(words) - 1 else "")
            self.word_w.append(x0 + self.font.getlength(prefix) - self.word_x[-1])

        def draw(color):
            img = Image.new("RGBA", (width, self.h), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((x0, 4), text, font=self.font, fill=color + (255,))
            return img

        self.dim = draw(COL_DIM if main else COL_SIDE)
        # the line after the next one: present, but clearly further away
        self.faint = self.dim.copy()
        self.faint.putalpha(self.faint.getchannel("A").point(lambda v: v * 45 // 100))
        hot = COL_HOT2 if line.get("voice") == 2 else COL_HOT
        # a duet's backing line fills as it is sung too — only the queue lines
        # (drawn dim ahead of their time) never need a hot layer
        self.hot = draw(hot) if (main or align == "right") else None

    def fill_x(self, line, t) -> float:
        """How far the line is filled in at moment t."""
        ws = line["words"]
        if not ws or t < ws[0]["t"]:
            return 0.0
        for i, w in enumerate(ws):
            end = w["t"] + max(w["d"], 1e-6)
            if t < w["t"]:
                return self.word_x[i]
            if t < end:
                p = (t - w["t"]) / (end - w["t"])
                return self.word_x[i] + p * self.word_w[i]
        return self.word_x[-1] + self.word_w[-1]


def make_background(W, H):
    from PIL import Image
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        f = y / max(H - 1, 1)
        row = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * f) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return img


# ---------------------------------------------------------------- render
def render(payload, audio_wav, out_path, args, on_progress=None):
    from PIL import Image, ImageDraw, ImageFont

    apply_colors(payload)
    if on_progress:
        # Show in the window right away what song and which colours are being
        # drawn: an empty log looks like nothing is happening.
        for row in video_report(payload, args, AU.duration(audio_wav),
                                min(args.seconds or 1e9,
                                    AU.duration(audio_wav) - args.start)).splitlines():
            if row.strip():
                on_progress(row)
    D = payload["data"]
    lines = D["lines"]
    if not lines:
        raise SystemExit(tr("The page has no lyrics.", "В странице нет текста."))
    duration = AU.duration(audio_wav)

    W, H = args.width, args.height
    margin = int(W * 0.06)
    font_path = find_font(args.font)
    base_main = int(H * 0.072)
    base_side = int(H * 0.042)
    cache_font = {}

    def font_for(text, max_w, main):
        size = base_main if main else base_side
        key = (text, size)
        if key in cache_font:
            return cache_font[key]
        f = ImageFont.truetype(font_path, size)
        while size > 18 and f.getlength(text) > max_w:
            size -= 2
            f = ImageFont.truetype(font_path, size)
        cache_font[key] = f
        return f

    bg = make_background(W, H)
    small = ImageFont.truetype(font_path, int(H * 0.020))
    # The countdown pill: readable from a couch, which the small caption font
    # was not. It still sits in the top strip where no lyrics are ever drawn,
    # so nothing gets covered — the strip only grows a little.
    pill_font = ImageFont.truetype(font_path, int(H * 0.030))

    art, art_side = {}, {}

    art_duo = {}

    def get(i, main=True, duo_side=False):
        store = art_duo if duo_side else (art if main else art_side)
        if i not in store:
            if len(store) > 10:
                store.clear()
            store[i] = LineArt(lines[i], font_for, W, margin, main,
                               align="right" if duo_side else "center")
        return store[i]

    starts = [ln["start"] for ln in lines]
    # The line already sung is dead weight on the screen — the eye never goes
    # back to it. The frame holds the current line and the queue ahead: the
    # next line, and the one after it fainter still. Slightly above centre, so
    # the group sits balanced.
    y_main = int(H * 0.44)
    y_next = int(H * 0.60)
    y_next2 = int(H * 0.72)

    t_start = args.start
    if t_start >= duration:
        raise SystemExit(tr(
            f"--start {t_start:g} s is past the end of the song "
            f"({int(duration//60)}:{duration%60:05.2f}) — there is nothing to render.",
            f"--start {t_start:g} с выходит за конец песни "
            f"({int(duration//60)}:{duration%60:05.2f}) — рендерить нечего."))
    t_end = min(duration, t_start + args.seconds) if args.seconds else duration
    total_frames = max(int((t_end - t_start) * args.fps), 1)

    cmd = [AU.ffmpeg(), "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(args.fps), "-i", "-",
           "-ss", f"{t_start}", "-i", audio_wav,
           "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    title = (D.get("title") or "") + ((" — " + D["artist"]) if D.get("artist") else "")
    t0 = time.time()

    try:
        for n in range(total_frames):
            t = t_start + n / args.fps
            frame = bg.copy()
            d = ImageDraw.Draw(frame)

            idx = bisect.bisect_right(starts, t) - 1

            # The second voice can sound together with the main one. It is drawn
            # on its own row below — otherwise the two texts would overlap.
            duo = -1
            if idx >= 0:
                for j in (idx - 1, idx + 1):
                    if 0 <= j < len(lines) and lines[j]["start"] <= t < lines[j]["end"] \
                            and (lines[j].get("voice") == 2) != (lines[idx].get("voice") == 2):
                        duo = j
                        break

            duo_bottom = 0
            if idx >= 0 and lines[idx].get("backing") and duo < 0:
                # The backing singing alone — the lead has ended, the na-na-na
                # carries on. It used to be promoted to the main seat, full
                # size, in the lead's way. It keeps its side seat instead: the
                # main seat stays empty, and the queue below points at the next
                # lead line as always.
                pic = get(idx, main=False, duo_side=True)
                y_b = y_main + int(H * 0.036)
                frame.paste(pic.dim, (0, y_b), pic.dim)
                fxb = int(pic.fill_x(lines[idx], t))
                if fxb > 0:
                    boxb = (0, 0, min(fxb, W), pic.h)
                    frame.paste(pic.hot.crop(boxb), (0, y_b), pic.hot.crop(boxb))
                duo_bottom = y_b + pic.h
            elif idx >= 0:
                # The lead stays exactly where a solo line sits; the backing is
                # smaller, to the right, tucked under it like a reply — two full
                # rows used to collide with the dots and the queue.
                pair = [idx] if duo < 0 else sorted(
                    [idx, duo], key=lambda j: lines[j].get("voice") == 2)
                y_j = 0
                for k, j in enumerate(pair):
                    is_back = k == 1
                    pic = get(j, main=not is_back, duo_side=is_back)
                    if not is_back:
                        y_j = y_main - pic.h // 2
                    else:
                        y_j = y_j + get(pair[0]).h + int(H * 0.002)
                        duo_bottom = y_j + pic.h
                    frame.paste(pic.dim, (0, y_j), pic.dim)
                    fx = int(pic.fill_x(lines[j], t))
                    if fx > 0:
                        box = (0, 0, min(fx, W), pic.h)
                        frame.paste(pic.hot.crop(box), (0, y_j), pic.hot.crop(box))
                    if k == 0 and lines[j].get("section"):
                        d.text((margin, y_j - int(H * 0.055)),
                               lines[j]["section"].upper(), font=small, fill=COL_SECT)

            # Guide dots between lines, as in the player: always visible so the
            # next line is expected, and they count down before it starts.
            def dots(cy, lit=0):
                r = max(int(H * 0.0055), 3)
                for k in range(3):
                    x = W // 2 + (k - 1) * r * 5
                    d.ellipse([x - r, cy - r, x + r, cy + r],
                              fill=COL_HOT if k < lit else COL_PIP)

            if idx + 1 < len(lines) and idx + 1 != duo:
                nx = get(idx + 1, False)
                frame.paste(nx.dim, (0, y_next - nx.h // 2), nx.dim)

                gap = lines[idx + 1]["start"] - (lines[idx]["end"] if idx >= 0 else 0)
                left = lines[idx + 1]["start"] - t
                lit = pips_lit(gap, left)
                dots(max((y_main + y_next) // 2, duo_bottom + int(H * 0.018)), lit)

                # …and one more ahead, fainter: the singer reads forward, never
                # back, and the queue keeps the frame symmetric.
                if idx + 2 < len(lines) and idx + 2 != duo:
                    n2 = get(idx + 2, False)
                    frame.paste(n2.faint, (0, y_next2 - n2.h // 2), n2.faint)

            # While nobody sings the screen is empty and it is unclear whether
            # the song is running. At the top — a countdown to the next line, as
            # in the program itself. Short gaps are not counted: they are obvious.
            nxt = None
            for ln in lines:
                if ln["start"] > t:
                    nxt = ln
                    break
            singing = idx >= 0 and t < lines[idx]["end"]
            if not singing:
                prev_end = lines[idx]["end"] if idx >= 0 else 0.0
                gap = (nxt["start"] - prev_end) if nxt else (duration - prev_end)
                # Ten seconds, as in the program itself: a shorter gap is a
                # breath between lines, and counting it down is noise.
                if gap >= 10.0:
                    left = (nxt["start"] if nxt else duration) - t
                    head = (tr("INTRO", "ВСТУПЛЕНИЕ") if idx < 0 else
                            (tr("INTERLUDE", "ПРОИГРЫШ") if nxt else tr("END", "КОНЕЦ")))
                    num = (mmss(left) if left >= 60
                           else f"{int(math.ceil(left))} " + tr("s", "с"))
                    tail = (tr("until “", "до «") + nxt["text"][:34] + tr("”", "»")
                            if nxt else tr("until the end", "до конца записи"))
                    # The pill is built around the text, and the text sits in its
                    # centre — horizontally and vertically.
                    cx, cy = W // 2, int(H * 0.105)
                    txt = f"{head}   {num}   {tail}"
                    box = d.textbbox((0, 0), txt, font=pill_font)
                    tw, th = box[2] - box[0], box[3] - box[1]
                    pad_x, pad_y = int(H * 0.030), int(H * 0.022)
                    d.rounded_rectangle(
                        [cx - tw // 2 - pad_x, cy - th // 2 - pad_y,
                         cx + tw // 2 + pad_x, cy + th // 2 + pad_y],
                        radius=int(th // 2 + pad_y),
                        fill=_mix(BG_TOP, (255, 255, 255), 0.10),
                        outline=_mix(BG_TOP, (255, 255, 255), 0.28))
                    d.text((cx, cy), txt, font=pill_font,
                           fill=_mix(COL_DIM, (255, 255, 255), 0.35), anchor="mm")
                    # The bar is centred too, right under the pill.
                    bw = max(int(W * 0.16), tw // 2)
                    bx, by = cx - bw // 2, cy + th // 2 + pad_y + int(H * 0.012)
                    bh = max(int(H * 0.004), 2)
                    done_k = 0.0 if gap <= 0 else min(max((t - prev_end) / gap, 0), 1)
                    d.rectangle([bx, by, bx + bw, by + bh],
                                fill=_mix(BG_TOP, (255, 255, 255), 0.18))
                    d.rectangle([bx, by, bx + int(bw * done_k), by + bh], fill=COL_HOT)

            if title:
                d.text((margin, int(H * 0.045)), title, font=small, fill=(120, 128, 155))

            bar_y, bar_h = int(H * 0.955), max(int(H * 0.004), 2)
            d.rectangle([margin, bar_y, W - margin, bar_y + bar_h], fill=(40, 45, 68))
            prog = min(max(t / duration, 0), 1)
            d.rectangle([margin, bar_y, margin + (W - 2 * margin) * prog, bar_y + bar_h],
                        fill=COL_BAR)

            proc.stdin.write(frame.tobytes())

            if n % (args.fps * 5) == 0 or n == total_frames - 1:
                done = (n + 1) / total_frames
                el = time.time() - t0
                eta = el / done - el if done > 0.01 else 0
                msg = (tr("frame ", "кадр ") + f"{n+1}/{total_frames}  {done*100:5.1f}%  "
                       + tr("left ~", "осталось ~")
                       + f"{int(eta)//60}:{int(eta)%60:02d}")
                if on_progress:
                    on_progress(msg)
                else:
                    print("\r  " + msg, end="", flush=True)
        print()
    except BrokenPipeError:
        pass
    finally:
        if proc.stdin:
            proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        code = proc.wait()

    if code != 0:
        raise SystemExit(tr("ffmpeg failed:\n", "ffmpeg завершился с ошибкой:\n") + err[-800:])
    return out_path


def apply_timings(payload: dict, path: str) -> None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    src = data.get("lines", data if isinstance(data, list) else [])
    cur = payload["data"]["lines"]
    if len(src) != len(cur):
        raise SystemExit(tr(f"{path} has {len(src)} lines, the page has {len(cur)}.",
                            f"В {path} {len(src)} строк, а в странице {len(cur)}."))
    for ln, s in zip(cur, src):
        ln["start"], ln["end"] = float(s["start"]), float(s["end"])
        for w, sw in zip(ln["words"], s.get("words") or []):
            w["t"], w["d"] = float(sw["t"]), float(sw["d"])
    print(tr(f"Timings taken from {os.path.basename(path)}",
                  f"Тайминги взяты из {os.path.basename(path)}"))


def list_pages(folder: str) -> list:
    """Karaoke pages in a folder — ours first."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    pages = [os.path.join(folder, n) for n in names if n.lower().endswith(".html")]
    pages.sort(key=lambda p: (0 if ("karaoke" in os.path.basename(p).lower()
                                    or "караоке" in os.path.basename(p).lower()) else 1,
                              os.path.basename(p).lower()))
    return pages


def pick_pages() -> list:
    """Nothing was dropped in — show what is around and let one be chosen."""
    seen, pages = set(), []
    for folder in (os.getcwd(), ROOT):
        for p in list_pages(folder):
            key = os.path.abspath(p).lower()
            if key not in seen:
                seen.add(key)
                pages.append(p)

    if not pages:
        print(tr("There is no built karaoke page next to this script.",
                  "Рядом нет ни одной собранной страницы караоке."))
        print(tr("Drag an HTML file onto Make-video.bat — or give the path.",
                  "Перетащите HTML-файл на «Make-video.bat» — или укажите путь."))
        return []
    if len(pages) == 1:
        print(tr(f"Found one page: {os.path.basename(pages[0])}",
                  f"Нашёл одну страницу: {os.path.basename(pages[0])}"))
        return pages

    print(tr("Karaoke pages found:\n", "Нашёл страницы караоке:\n"))
    for i, p in enumerate(pages, 1):
        mb = os.path.getsize(p) / 1024 / 1024
        print(f"  {i:2}. {os.path.basename(p)}  ({mb:.1f} " + tr("MB", "МБ") + ")")
    print(tr("\n   0. all of them", "\n   0. все сразу"))
    try:
        ans = input(tr("\nNumber (Enter — the first one): ",
                       "\nНомер (Enter — первая): ")).strip()
    except EOFError:
        return pages[:1]
    if not ans:
        return pages[:1]
    if ans == "0":
        return pages
    if ans.isdigit() and 1 <= int(ans) <= len(pages):
        return [pages[int(ans) - 1]]
    print(tr("I did not understand the choice.", "Не понял выбор."))
    return []


def find_timings(html_path: str):
    """Timing edits exported from the player and left next to the page."""
    folder = os.path.dirname(os.path.abspath(html_path))
    stem = os.path.splitext(os.path.basename(html_path))[0].lower()
    best = None
    for name in sorted(os.listdir(folder)):
        low = name.lower()
        if not low.endswith(".json"):
            continue
        if "timings" in low or "тайминг" in low:
            # a file named after the song beats a plain timings.json
            if os.path.splitext(low)[0].replace("_timings", "").strip("_ -") in stem:
                return os.path.join(folder, name)
            best = best or os.path.join(folder, name)
    return best


def _try_timings(payload: dict, path: str) -> bool:
    """Apply an edits file found next to the page. If it belongs to another
    song, just skip it: a stray JSON must not abort the render."""
    try:
        apply_timings(payload, path)
        return True
    except SystemExit as e:
        print(f"  {e}")
        print(tr("  This file does not fit the song — taking the timing from the page.",
                      "  Этот файл к песне не подходит — беру разметку из самой страницы."))
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="video.py", description="An MP4 karaoke clip from a finished HTML page.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("html", nargs="*",
                   help="pages, or a folder with them; with no arguments — pick from a list")
    p.add_argument("-o", "--output", help="where to save the MP4")
    p.add_argument("--audio", choices=["minus", "guide", "original"], default="minus",
                   help="minus — the instrumental (default), guide — with a quiet vocal, "
                        "original — as recorded")
    p.add_argument("--timings", help="a JSON with timing edits from the player")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--crf", type=int, default=20, help="quality: lower is better (18–24)")
    p.add_argument("--preset", default="medium", help="x264 encoding speed")
    p.add_argument("--font", help="path to a .ttf")
    p.add_argument("--start", type=float, default=0.0, help="start from this second")
    p.add_argument("--seconds", type=float, default=0.0, help="render only N seconds (a sample)")
    args = p.parse_args(argv)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print(tr("The Pillow library is needed:\n    pip install pillow",
                  "Нужна библиотека Pillow:\n    pip install pillow"), file=sys.stderr)
        return 1

    targets = []
    for a in args.html:
        if os.path.isdir(a):
            targets += list_pages(a)
        elif os.path.isfile(a):
            targets.append(a)
        else:
            print(tr(f"Not found: {a}", f"Не найдено: {a}"))
    if not args.html:
        targets = pick_pages()
    if not targets:
        return 2
    if args.output and len(targets) > 1:
        print(tr("-o was given but there are several pages — I will name them after "
                     "the files.",
                     "Ключ -o задан, а страниц несколько — имена сделаю по названиям файлов."))
        args.output = None

    AU.ffmpeg()
    failed = 0
    for k, html_path in enumerate(targets, 1):
        if len(targets) > 1:
            print(f"\n[{k}/{len(targets)}] {os.path.basename(html_path)}\n" + "-" * 60)
        try:
            failed += render_one(html_path, args)
        except SystemExit as e:
            print(tr(f"  error: {e}", f"  ошибка: {e}"))
            failed += 1
    return 1 if failed else 0


def video_report(payload, args, song: float, want: float) -> str:
    """What the song is and what will happen to it — before the long drawing.

    There is such a report before a page is built, but there was none before a
    clip: a mistake — the wrong audio, the wrong colours, forgotten marks —
    could only be seen on the finished file, ten minutes later.
    """
    D = payload.get("data") or {}
    lines = D.get("lines") or []
    v2 = sum(1 for l in lines if l.get("voice") == 2)
    kept = keep_spans(payload)
    kept_s = sum(b - a for a, b in kept)
    colors = payload.get("colors") or []
    theme = payload.get("theme") or {}
    duo = 0
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            if b["start"] >= a["end"]:
                break
            if (b.get("voice") == 2) != (a.get("voice") == 2):
                duo += 1
    audio_name = {"minus": tr("instrumental", "минусовка"),
                  "guide": tr("instrumental + quiet vocal", "минусовка + тихий вокал"),
                  "original": tr("the original", "оригинал")}.get(args.audio, args.audio)
    fps, frames = args.fps, int(want * args.fps)
    rows = [
        (tr("Song", "Песня"), (D.get("title") or "—") +
         ((" — " + D["artist"]) if D.get("artist") else "")),
        (tr("Length", "Длина"), mmss(song) +
         (tr(f", rendering {mmss(want)}", f", рисуем {mmss(want)}") if want < song - 0.05 else "")),
        (tr("Lines", "Строк"), f"{len(lines)}" +
         (tr(f", second voice: {v2}", f", второй голос: {v2}") if v2 else "")),
        (tr("Together", "Одновременно"),
         tr(f"{duo} place{'s' if duo != 1 else ''} where two voices sing at once",
            f"{duo} мест, где поют вдвоём")
         if duo else tr("voices do not overlap", "голоса не пересекаются")),
        (tr("Original sings", "Поёт оригинал"),
         tr(f"{len(kept)} stretch{'es' if len(kept) != 1 else ''}, {kept_s:.0f} s",
            f"{len(kept)} кусков, {kept_s:.0f} с")
         if kept else tr("nothing marked", "не отмечено")),
        (tr("Colours", "Цвета"), ", ".join(colors) if colors else tr("default", "по умолчанию")),
        (tr("Look", "Оформление"),
         f"{theme.get('bg')} / {theme.get('text')}" if theme.get("bg")
         else tr("default", "по умолчанию")),
        (tr("Audio", "Звук"), audio_name),
        (tr("Frames", "Кадров"), f"{frames} ({fps} " + tr("fps", "к/с") + ")"),
    ]
    width = max(len(k) for k, _ in rows) + 2
    out = ["", tr("Before rendering", "Отчёт перед роликом"), "─" * 46]
    out += [f"  {k.ljust(width)}{v}" for k, v in rows]
    if not colors:
        out.append(tr("  ! The page has no colours of its own — the video takes the "
                      "defaults.", "  ! В странице нет своих цветов — ролик возьмёт "
                      "стандартные."))
    out.append("")
    return "\n".join(out)


def render_one(html_path: str, args) -> int:
    payload = B.read_payload(html_path)

    timings = args.timings or find_timings(html_path)
    if timings:
        if not args.timings:
            print(tr(f"Timing edits found next to it: {os.path.basename(timings)} — taking them.",
                  f"Рядом лежат правки разметки: {os.path.basename(timings)} — беру их."))
        if not _try_timings(payload, timings):
            timings = None
    elif payload.get("edited"):
        print(tr("The timing comes from the page — it already has your edits.",
                  "Разметка взята из страницы — она уже с вашими правками."))
    else:
        print(tr("The timing comes from the page itself (machine-made).",
                  "Разметка взята из самой страницы (машинная)."))
        print(tr("  If you edited it in the player, note: the edits live in the browser,",
                  "  Если вы правили её в плеере, учтите: правки хранятся в браузере, а не"))
        print(tr("  not in the file, and will not reach the video. In the player press",
                  "  в файле, и в ролик не попадут. Нажмите в плеере «Правка» →"))
        print(tr("  “Edit” → “Save page with edits” and make the video from that page.",
                  "  «Сохранить страницу с правками» и делайте видео из сохранённой страницы."))

    out = args.output or os.path.splitext(html_path)[0] + ".mp4"
    tmp = tempfile.mkdtemp(prefix="karaoke_video_")
    t0 = time.time()
    try:
        wav = extract_audio(payload, html_path, tmp, args.audio)
        song = AU.duration(wav)
        want = min(song - args.start, args.seconds) if args.seconds else song - args.start
        print(video_report(payload, args, song, want))
        print(tr(f"Frame {args.width}×{args.height}, {args.fps} fps, "
                 f"video length {mmss(want)}. Drawing…",
                 f"Кадр {args.width}×{args.height}, {args.fps} к/с, "
                 f"длина ролика {mmss(want)}. Рисую…"))
        render(payload, wav, out, args)

        size = os.path.getsize(out) / 1024 / 1024
        got = None
        try:
            got = AU.duration(out)
        except Exception:
            pass
        # Print the video LENGTH explicitly, not just the build time: the two
        # get confused, and a truncated file is easy to miss.
        spent = int(time.time() - t0)
        print(tr(f"\nDone: {out}", f"\nГотово: {out}"))
        print(tr(f"  video length : {mmss(got) if got else '?'}   ({size:.1f} MB)",
                  f"  длина ролика : {mmss(got) if got else '?'}   ({size:.1f} МБ)"))
        print(tr(f"  built in     : {spent // 60}:{spent % 60:02d}",
                  f"  собрано за   : {spent // 60}:{spent % 60:02d}"))
        if got and abs(got - want) > 1.0:
            print(tr(f"\n  NOTE: {mmss(want)} was expected but {mmss(got)} came out — "
                     f"the video is cut short.\n  Send this output, it is a bug.",
                     f"\n  ВНИМАНИЕ: ожидалась длина {mmss(want)}, а получилось {mmss(got)} — "
                     f"ролик обрезан.\n  Пришлите этот вывод, это ошибка программы."))
        else:
            print(tr("\nThe file can go straight to YouTube.",
                  "\nФайл можно заливать на YouTube как есть."))
        return 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
