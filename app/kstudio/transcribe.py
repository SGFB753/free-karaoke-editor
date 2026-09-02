"""Make an editable first draft of lyrics directly from a recording."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional

from .i18n import tr

Log = Callable[[str], None]


@dataclass
class HeardWord:
    text: str
    start: float
    end: float


def _clean_join(words: List[HeardWord]) -> str:
    text = " ".join(w.text.strip() for w in words if w.text.strip())
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    text = re.sub(r"([«(])\s+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _result_lines(result, max_chars: int = 60,
                  max_seconds: float = 8.0) -> List[tuple]:
    """Turn Whisper's speech segments into readable karaoke-sized lines."""
    out: List[tuple] = []
    for segment in getattr(result, "segments", []) or []:
        heard = []
        for word in getattr(segment, "words", []) or []:
            text = str(getattr(word, "word", "") or "").strip()
            if not text:
                continue
            heard.append(HeardWord(text, float(getattr(word, "start", 0.0) or 0.0),
                                   float(getattr(word, "end", 0.0) or 0.0)))
        if not heard:
            text = re.sub(r"\s+", " ", str(getattr(segment, "text", "") or "")).strip()
            if text:
                out.append((float(getattr(segment, "start", 0.0) or 0.0), text))
            continue

        line: List[HeardWord] = []
        for word in heard:
            pause = word.start - line[-1].end if line else 0.0
            candidate = _clean_join(line + [word])
            too_long = len(candidate) > max_chars
            too_slow = bool(line) and word.end - line[0].start > max_seconds
            clear_pause = bool(line) and pause >= 0.85
            if line and (too_long or too_slow or clear_pause):
                out.append((line[0].start, _clean_join(line)))
                line = []
            line.append(word)
            if len(_clean_join(line)) >= 24 and re.search(r"[.!?…]$", word.text.strip()):
                out.append((line[0].start, _clean_join(line)))
                line = []
        if line:
            out.append((line[0].start, _clean_join(line)))
    clean = [(start, text) for start, text in out if text]
    # Whisper often cuts a sung sentence into a normal phrase plus a tiny
    # one-word segment ("сегодня я счастлив" / "секунду"). Such fragments
    # are awkward karaoke lines and are safer joined to the phrase before them.
    merged: List[tuple] = []
    for start, text in clean:
        if (merged and len(text) < 16
                and not re.search(r"[.!?…]$", merged[-1][1])
                and len(merged[-1][1]) + 1 + len(text) <= max_chars):
            previous_start, previous_text = merged[-1]
            merged[-1] = (previous_start,
                          re.sub(r"\s+([,.;:!?…])", r"\1",
                                 previous_text + " " + text))
        else:
            merged.append((start, text))
    return merged


def _lrc_time(seconds: float) -> str:
    centis = max(0, round(float(seconds) * 100))
    return f"[{centis // 6000:02d}:{(centis % 6000) / 100:05.2f}]"


def _editable_lrc(lines: List[tuple], peg_every: int = 4) -> str:
    """Keep location hints without pretending the word timing is finished.

    A timestamp on every input line means “manual timing” to the project
    builder, which would skip Whisper alignment after the text was corrected.
    Sparse pegs hold verses in place while still allowing every word to be
    aligned against the recording.
    """
    out = []
    previous = None
    for index, (start, text) in enumerate(lines):
        peg = len(lines) > 1 and (index % max(1, peg_every) == 0
                                  or previous is not None and start - previous >= 10.0)
        out.append((_lrc_time(start) + " " if peg else "") + text)
        previous = start
    return "\n".join(out)


def draft(audio_path: str, model_name: str = "small", language: str = "auto",
          device: Optional[str] = None, log: Log = lambda _m: None) -> dict:
    """Transcribe a song and return editable LRC plus the detected language."""
    import stable_whisper
    import numpy as np

    from . import audio as A
    from . import models as M
    from .progress import Heartbeat

    log(M.load_note(model_name))
    with Heartbeat(log, M.step_label(model_name), every=10.0):
        model = stable_whisper.load_model(model_name, device=device)

    log(tr("Preparing the recording for recognition…",
           "Готовлю запись к распознаванию…"))
    pcm = A.read_pcm_mono(audio_path, 16000)
    samples = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
    if not len(samples):
        raise ValueError(tr("the recording is empty", "запись пустая"))

    chosen = None if not language or language == "auto" else language
    kwargs = {"verbose": False, "word_timestamps": True}
    if chosen:
        kwargs["language"] = chosen
    log(tr("Listening for the lead lyrics…", "Распознаю основной текст…"))
    with Heartbeat(log, tr("recognition", "распознавание"), every=15.0,
                   slow_after=600.0,
                   slow_note=tr("A smaller Whisper model will finish faster.",
                                "Модель Whisper поменьше закончит быстрее.")) as hb:
        try:
            result = model.transcribe(samples, progress_callback=hb.progress, **kwargs)
        except TypeError:
            result = model.transcribe(samples, **kwargs)

    lines = _result_lines(result)
    if not lines:
        raise ValueError(tr("Whisper did not hear any words",
                            "Whisper не расслышал ни одного слова"))
    text = _editable_lrc(lines)
    detected = str(getattr(result, "language", "") or chosen or "").lower()
    log(tr(f"Draft ready: {len(lines)} lines. Read and correct it before building.",
           f"Черновик готов: {len(lines)} строк. Прочитайте и поправьте его перед сборкой."))
    return {"text": text, "lines": len(lines), "language": detected}
