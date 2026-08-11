#!/usr/bin/env python3
"""The real neural nets: Whisper does the timing, Demucs splits the vocal.

Остальные наборы обходят их стороной — подсовывают готовые времена слов и
проверяют только обвязку. Здесь всё честно, поэтому долго и с загрузкой моделей
из сети. Включается отдельно:

    KARAOKE_HEAVY=1 python3 tests/test_heavy.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

failures = []


def check(name, cond, extra=""):
    print(("  OK     " if cond else "  FAILED ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def spoken(path, words, sr=16000):
    """A crude imitation of singing: a tone with an envelope per word.

    Настоящую речь синтезировать нечем, а Whisper на такой звук всё равно
    выдаёт слова с временами: нам важно, что путь целиком отрабатывает и
    времена идут по порядку, а не то, что он расслышал текст.
    """
    import math
    import struct
    import wave
    total = int(sr * (len(words) * 0.8 + 1.0))
    buf = [0.0] * total
    for i, _w in enumerate(words):
        start = int(sr * (0.5 + i * 0.8))
        freq = 180 + 40 * (i % 5)
        for k in range(int(sr * 0.55)):
            if start + k >= total:
                break
            env = math.sin(math.pi * k / (sr * 0.55)) ** 2
            buf[start + k] += 0.5 * env * math.sin(2 * math.pi * freq * k / sr)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 30000))
                               for v in buf))
    return path


def main():
    if not os.environ.get("KARAOKE_HEAVY"):
        print("  skipped: KARAOKE_HEAVY is not set (the models come from the net)")
        return 0

    from kstudio import align as A
    from kstudio import audio as AU
    from kstudio import lyrics as L
    from kstudio import separate as S

    tmp = tempfile.mkdtemp(prefix="karaoke_heavy_")
    words = ["one", "two", "three", "four", "five", "six"]
    song = spoken(os.path.join(tmp, "song.wav"), words)
    text = "title: Heavy\n\none two three\nfour five six\n"

    print("Timing with the real Whisper (tiny model)")
    try:
        import stable_whisper  # noqa: F401
        have = True
    except ImportError:
        have = False
    check("stable-ts is installed", have)
    if have:
        lyr = L.parse(text)
        t0 = time.time()
        lyr, engine = A.align(lyr, song, AU.duration(song), "whisper",
                              model_name="tiny", language="en", log=lambda m: None)
        spent = time.time() - t0
        check("the engine really was whisper", engine == "whisper", engine)
        check("every word has a time",
              all(w.start is not None and w.end is not None for w in lyr.words),
              [w.text for w in lyr.words if w.start is None][:3])
        check("the words are in order",
              all(a.start <= b.start + 1e-6 for a, b in zip(lyr.words, lyr.words[1:])))
        check("the lines do not overlap",
              all(a.end <= b.start + 1e-6 for a, b in zip(lyr.lines, lyr.lines[1:])),
              [(round(l.start, 2), round(l.end, 2)) for l in lyr.lines])
        check("the timing fits inside the song",
              lyr.lines[-1].end <= AU.duration(song) + 0.01,
              f"{lyr.lines[-1].end:.2f} of {AU.duration(song):.2f}")
        check("the text was not replaced by what was recognised",
              [l.text for l in lyr.lines] == ["one two three", "four five six"],
              [l.text for l in lyr.lines])
        print(f"     (took {spent:.0f} s)")

    print("\nSeparating the vocal with the real Demucs")
    if not S.available():
        check("demucs is installed", False, "no module")
    else:
        t0 = time.time()
        instr, voc = S.separate(song, os.path.join(tmp, "stems"), log=lambda m: None)
        spent = time.time() - t0
        check("both tracks came out", bool(instr and voc), f"{instr} | {voc}")
        if instr and voc:
            check("the files are not empty",
                  os.path.getsize(instr) > 10_000 and os.path.getsize(voc) > 10_000,
                  f"{os.path.getsize(instr)} / {os.path.getsize(voc)}")
            check("the length matches the original",
                  abs(AU.duration(instr) - AU.duration(song)) < 0.5,
                  f"{AU.duration(instr):.2f} vs {AU.duration(song):.2f}")
            # Their size is identical (same length, same format) — the contents
            # are what to compare: the stems must differ and add up to the original.
            import numpy as np
            def pcm(path):
                raw = AU.read_pcm_mono(path, 16000)
                return np.frombuffer(raw.tobytes(), dtype="<i2").astype(np.float32) / 32768
            a, b, orig = pcm(instr), pcm(voc), pcm(song)
            n = min(len(a), len(b), len(orig))
            a, b, orig = a[:n], b[:n], orig[:n]
            check("these are two different tracks, not a copy",
                  float(np.abs(a - b).mean()) > 1e-4,
                  f"mean difference {float(np.abs(a - b).mean()):.5f}")
            back = a + b
            err = float(np.sqrt(((back - orig) ** 2).mean()))
            base = float(np.sqrt((orig ** 2).mean())) or 1e-9
            check("instrumental plus voice make the original recording", err / base < 0.2,
                  f"error {100 * err / base:.1f}%")
            print(f"     (took {spent:.0f} s)")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
