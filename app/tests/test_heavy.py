#!/usr/bin/env python3
"""Настоящие нейросети: Whisper размечает, Demucs отделяет вокал.

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
    print(("  OK   " if cond else "  ПРОВАЛ ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def spoken(path, words, sr=16000):
    """Грубая имитация пения: на каждое слово — свой тон с огибающей.

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
        print("  пропуск: KARAOKE_HEAVY не задан (модели качаются из сети)")
        return 0

    from kstudio import align as A
    from kstudio import audio as AU
    from kstudio import lyrics as L
    from kstudio import separate as S

    tmp = tempfile.mkdtemp(prefix="karaoke_heavy_")
    words = ["one", "two", "three", "four", "five", "six"]
    song = spoken(os.path.join(tmp, "song.wav"), words)
    text = "title: Heavy\n\none two three\nfour five six\n"

    print("Разметка настоящим Whisper (модель tiny)")
    try:
        import stable_whisper  # noqa: F401
        have = True
    except ImportError:
        have = False
    check("stable-ts установлен", have)
    if have:
        lyr = L.parse(text)
        t0 = time.time()
        lyr, engine = A.align(lyr, song, AU.duration(song), "whisper",
                              model_name="tiny", language="en", log=lambda m: None)
        spent = time.time() - t0
        check("движок отработал именно whisper", engine == "whisper", engine)
        check("у каждого слова есть время",
              all(w.start is not None and w.end is not None for w in lyr.words),
              [w.text for w in lyr.words if w.start is None][:3])
        check("слова идут по порядку",
              all(a.start <= b.start + 1e-6 for a, b in zip(lyr.words, lyr.words[1:])))
        check("строки не налезают друг на друга",
              all(a.end <= b.start + 1e-6 for a, b in zip(lyr.lines, lyr.lines[1:])),
              [(round(l.start, 2), round(l.end, 2)) for l in lyr.lines])
        check("разметка укладывается в длину песни",
              lyr.lines[-1].end <= AU.duration(song) + 0.01,
              f"{lyr.lines[-1].end:.2f} при длине {AU.duration(song):.2f}")
        check("текст не подменён распознанным",
              [l.text for l in lyr.lines] == ["one two three", "four five six"],
              [l.text for l in lyr.lines])
        print(f"     (заняло {spent:.0f} с)")

    print("\nОтделение вокала настоящим Demucs")
    if not S.available():
        check("demucs установлен", False, "нет модуля")
    else:
        t0 = time.time()
        instr, voc = S.separate(song, os.path.join(tmp, "stems"), log=lambda m: None)
        spent = time.time() - t0
        check("обе дорожки получены", bool(instr and voc), f"{instr} | {voc}")
        if instr and voc:
            check("файлы не пустые",
                  os.path.getsize(instr) > 10_000 and os.path.getsize(voc) > 10_000,
                  f"{os.path.getsize(instr)} / {os.path.getsize(voc)}")
            check("длина совпадает с исходной",
                  abs(AU.duration(instr) - AU.duration(song)) < 0.5,
                  f"{AU.duration(instr):.2f} против {AU.duration(song):.2f}")
            # Размер у них одинаковый (та же длина и формат) — сравнивать надо
            # содержимое: стемы обязаны отличаться и вместе давать оригинал.
            import numpy as np
            def pcm(path):
                raw = AU.read_pcm_mono(path, 16000)
                return np.frombuffer(raw.tobytes(), dtype="<i2").astype(np.float32) / 32768
            a, b, orig = pcm(instr), pcm(voc), pcm(song)
            n = min(len(a), len(b), len(orig))
            a, b, orig = a[:n], b[:n], orig[:n]
            check("это разные дорожки, а не копия",
                  float(np.abs(a - b).mean()) > 1e-4,
                  f"средняя разница {float(np.abs(a - b).mean()):.5f}")
            back = a + b
            err = float(np.sqrt(((back - orig) ** 2).mean()))
            base = float(np.sqrt((orig ** 2).mean())) or 1e-9
            check("минус плюс голос дают исходную запись", err / base < 0.2,
                  f"расхождение {100 * err / base:.1f}%")
            print(f"     (заняло {spent:.0f} с)")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("ПРОВАЛЕНО: " + ", ".join(failures) if failures else "Все проверки пройдены"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
