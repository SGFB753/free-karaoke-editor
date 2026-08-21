#!/usr/bin/env python3
"""Measure the timing, so “it feels better” can become “it is better”.

    python3 app/tools/bench.py song.mp3 lyrics.txt
    python3 app/tools/bench.py song.mp3 lyrics.txt --models small,medium
    python3 app/tools/bench.py song.mp3 lyrics.txt --keep work/   (reuse the stems)

Every row is one way of handing the same song to the aligner. Nothing here
needs a “right answer” to compare against, which is what makes it usable on
your own music:

    failed   segments stable-ts itself gave up on
    sure     how sure the model was of the words it did align (median)
    piled    the share of lines dumped at one instant — our own measure
    time     seconds spent

A word on reading it: the numbers are comparable between rows of one run, not
between songs. A screamed vocal sits low everywhere.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio import align as A          # noqa: E402
from kstudio import audio as AU         # noqa: E402
from kstudio import lang as LG          # noqa: E402
from kstudio import lyrics as L         # noqa: E402
from kstudio import separate as S       # noqa: E402

VARIANTS = ("mix", "voice", "levelled")


def row(name: str, failed, sure, piled, secs) -> str:
    return (f"  {name:<12}{failed:>7}{sure:>9.3f}{piled:>8.1f}%{secs:>8.0f}s"
            if isinstance(sure, float) else
            f"  {name:<12}{failed:>7}{'—':>9}{piled:>8.1f}%{secs:>8.0f}s")


def measure(model, audio_path: str, text: str, levelled: bool):
    """One run: give the aligner this audio and this text, count what came out."""
    import numpy as np

    pcm = AU.read_pcm_mono(audio_path, 16000, af=AU.LEVEL_VOICE if levelled else None)
    audio = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
    lyr = L.parse(text)
    started = time.time()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = model.align(audio, lyr.plain_text(), language=LG.detect(text),
                          original_split=True)
    failed = 0
    for w in caught:
        m = re.search(r"(\d+)\s*/\s*(\d+)\s+segments\s+failed", str(w.message))
        if m:
            failed = int(m.group(1))
    rec, probs = [], []
    for seg in res.segments:
        for w in (seg.words or []):
            key = A.normalize_token(w.word)
            if not key:
                continue
            p = getattr(w, "probability", None)
            rec.append((key, float(w.start), float(w.end), float(p) if p is not None else None))
            if p is not None:
                probs.append(float(p))
    A._apply_recognized(lyr.words, rec)
    A._fill_lines(lyr, len(audio) / 16000)
    probs.sort()
    return (failed,
            probs[len(probs) // 2] if probs else None,
            A.pile_share(lyr) * 100,
            time.time() - started)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio")
    ap.add_argument("lyrics")
    ap.add_argument("--models", default="small",
                    help="which models to try, comma separated")
    ap.add_argument("--variants", default=",".join(VARIANTS),
                    help="mix | voice | levelled")
    ap.add_argument("--keep", default="",
                    help="a folder to keep the separated stems in and reuse")
    args = ap.parse_args()

    # The arguments first: a typo in a file name is about what was typed here,
    # and hearing about a missing library instead sends a person the wrong way.
    for path in (args.audio, args.lyrics):
        if not os.path.isfile(path):
            print(f"No such file: {path}", file=sys.stderr)
            return 2
    try:
        import stable_whisper
    except ImportError:
        print("This needs stable-ts: pip install stable-ts", file=sys.stderr)
        return 2

    text = L.decode_text(open(args.lyrics, "rb").read())
    want = [v.strip() for v in args.variants.split(",") if v.strip() in VARIANTS]
    tmp = args.keep or tempfile.mkdtemp(prefix="karaoke_bench_")
    os.makedirs(tmp, exist_ok=True)
    mix = os.path.join(tmp, "song.wav")
    if not os.path.isfile(mix):
        AU.to_wav(args.audio, mix)
    voice = os.path.join(tmp, "vocals.wav")
    if any(v in want for v in ("voice", "levelled")) and not os.path.isfile(voice):
        if not S.available():
            print("Demucs is not installed — only the mix can be measured",
                  file=sys.stderr)
            want = ["mix"]
        else:
            print("Separating the voice, this is the long part…", flush=True)
            _, got = S.separate(mix, os.path.join(tmp, "stems"),
                                log=lambda m: print("   ", m, flush=True))
            shutil.copyfile(got, voice)

    print(f"\n  {os.path.basename(args.audio)} — {len(L.parse(text).lines)} lines, "
          f"{AU.duration(mix):.0f} s")
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"\n  model: {name}")
        print(f"  {'variant':<12}{'failed':>7}{'sure':>9}{'piled':>9}{'time':>9}")
        model = stable_whisper.load_model(name)
        for v in want:
            path = mix if v == "mix" else voice
            failed, sure, piled, secs = measure(model, path, text, v == "levelled")
            print(row(v, failed, sure if sure is not None else "—", piled, secs), flush=True)
        del model
    if not args.keep:
        print(f"\n  (stems left in {tmp} — pass --keep to reuse them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
