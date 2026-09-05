"""Lining the text up with the audio — a timing for every word.

Two engines:
  whisper — forced alignment with the Whisper model (stable-ts). Accurate, but
            it needs torch.
  energy  — no neural nets: words are spread over the “mass” of vocal energy.
            Always available, respects pauses and interludes, coarser per word.
"""

from __future__ import annotations

import difflib
import re
import sys
import warnings
from typing import Callable, Dict, List, Optional

from .i18n import tr
from .lyrics import Lyrics, Word, normalize_token
from .progress import mmss

Log = Callable[[str], None]


def _noop(msg: str) -> None:
    pass


# --------------------------------------------------------------------------- #
#  The loudness engine: find sung phrases and lay the lines out over them
# --------------------------------------------------------------------------- #

def _phrases(env: List[float], dt: float, min_dur: float = 0.18,
             max_gap: float = 0.32) -> List[List[float]]:
    """Stretches of vocal activity [start, end] found by a hysteresis threshold."""
    if not env:
        return []
    ordered = sorted(env)
    floor = ordered[int(len(ordered) * 0.15)]
    peak = ordered[min(int(len(ordered) * 0.98), len(ordered) - 1)]
    rng = max(peak - floor, 1e-6)
    on, off = floor + 0.20 * rng, floor + 0.11 * rng

    lead = max(int(0.20 / dt), 1)        # how far to step back to the quiet phrase start
    segs, start, active = [], 0, False
    for i, e in enumerate(env):
        if not active and e >= on:
            active, start = True, i
            # the threshold trips once the sound is already rising; step back to
            # the real start so the line lights up slightly early, not late
            while start > 0 and i - start < lead and env[start - 1] > off * 0.7:
                start -= 1
        elif active and e < off:
            active = False
            segs.append([start * dt, i * dt])
    if active:
        segs.append([start * dt, len(env) * dt])

    merged: List[List[float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= max_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [seg for seg in merged if seg[1] - seg[0] >= min_dur]


GAP_PENALTY = 1.5      # how much costlier a gap inside a line is than a length error


def _limit_phrases(segs: List[List[float]], target: int) -> List[List[float]]:
    """Glue an over-fragmented split at its narrowest gaps (or DP gets slow)."""
    while len(segs) > target:
        gaps = [(segs[i + 1][0] - segs[i][1], i) for i in range(len(segs) - 1)]
        _, i = min(gaps)
        segs[i][1] = segs[i + 1][1]
        del segs[i + 1]
    return segs


def _fit_lines_to_phrases(lines, segs) -> None:
    """Lay the lines over the phrases optimally (DP) and set start/end."""
    N, M = len(lines), len(segs)
    voiced = [e - s for s, e in segs]
    pre = [0.0]
    for v in voiced:
        pre.append(pre[-1] + v)
    total_voiced = pre[-1] or 1.0
    total_syl = sum(ln.syllables for ln in lines) or 1
    want = [total_voiced * ln.syllables / total_syl for ln in lines]

    INF = float("inf")

    # without a cap on the group size DP grows as O(N·M²) and takes tens of
    # seconds on a long text; a line almost never spans many phrases in a row
    span_cap = max(8, 2 * -(-M // N), 2 * -(-N // M))

    if M >= N:
        # every line gets a contiguous group of one or more phrases
        dp = [[INF] * (M + 1) for _ in range(N + 1)]
        back = [[0] * (M + 1) for _ in range(N + 1)]
        dp[0][0] = 0.0
        for i in range(1, N + 1):
            for j in range(i, M - (N - i) + 1):
                best, bk = INF, i - 1
                for k in range(max(i - 1, j - span_cap), j):
                    prev = dp[i - 1][k]
                    if prev >= INF:
                        continue
                    gv = pre[j] - pre[k]
                    inner = (segs[j - 1][1] - segs[k][0]) - gv   # gaps inside the group
                    c = prev + (gv - want[i - 1]) ** 2 + GAP_PENALTY * inner ** 2
                    if c < best:
                        best, bk = c, k
                dp[i][j], back[i][j] = best, bk
        j = M
        for i in range(N, 0, -1):
            k = back[i][j]
            lines[i - 1].start, lines[i - 1].end = segs[k][0], segs[j - 1][1]
            j = k
    else:
        # fewer phrases than lines: several lines share one phrase
        dp = [[INF] * (N + 1) for _ in range(M + 1)]
        back = [[0] * (N + 1) for _ in range(M + 1)]
        dp[0][0] = 0.0
        for j in range(1, M + 1):
            for i in range(j, N - (M - j) + 1):
                best, bk = INF, j - 1
                for k in range(max(j - 1, i - span_cap), i):
                    prev = dp[j - 1][k]
                    if prev >= INF:
                        continue
                    c = prev + (voiced[j - 1] - sum(want[k:i])) ** 2
                    if c < best:
                        best, bk = c, k
                dp[j][i], back[j][i] = best, bk
        i = N
        for j in range(M, 0, -1):
            k = back[j][i]
            s, e = segs[j - 1]
            grp = lines[k:i]
            tot = sum(ln.syllables for ln in grp) or 1
            acc = 0.0
            for ln in grp:
                ln.start = s + (e - s) * acc / tot
                acc += ln.syllables
                ln.end = s + (e - s) * acc / tot
            i = k


def spans(value, duration: float = 0.0) -> List[tuple]:
    """Stretches with no words in them, as a person writes them.

    “0:00-0:42, 3:10-3:50”, a list of pairs, seconds or mm:ss — all the same
    thing. Overlapping ones are merged; nonsense is dropped rather than guessed
    at, because a wrong stretch here silently hides a piece of the song.
    """
    raw = []
    if not value:
        return []
    if isinstance(value, str):
        for part in re.split(r"[;,\n]+", value):
            m = re.match(r"^\s*([\d:.,]+)\s*[-–—]{1,2}\s*([\d:.,]+)\s*$", part)
            if m:
                raw.append((clock(m.group(1)), clock(m.group(2))))
    else:
        for item in value:
            if isinstance(item, dict):
                raw.append((clock(item.get("start")), clock(item.get("end"))))
            elif len(item) == 2:
                raw.append((clock(item[0]), clock(item[1])))
    out = []
    for a, b in sorted(raw):
        if duration:
            a, b = max(0.0, min(a, duration)), max(0.0, min(b, duration))
        if b - a < 0.3:
            continue
        if out and a <= out[-1][1] + 0.05:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return [tuple(x) for x in out]


def keep_windows(skip: List[tuple], duration: float) -> List[tuple]:
    """The other side of the coin: where the words are allowed to be."""
    out, at = [], 0.0
    for a, b in skip:
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if at < duration:
        out.append((at, duration))
    return [w for w in out if w[1] - w[0] > 0.2]


def clock(value, duration: float = 0.0) -> float:
    """A moment as a person writes it: 83, “1:23”, “1:23.5”, “0:01:23”.

    Anything that is not a time at all is no time: better to ignore a typo than
    to build the whole song around it.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        out = float(value)
    else:
        text = str(value).strip().replace(",", ".")
        if not text:
            return 0.0
        try:
            parts = [float(p) for p in text.split(":")]
        except ValueError:
            return 0.0
        out = 0.0
        for p in parts:
            out = out * 60 + p
    if out < 0 or out != out:                 # negative, or a nan
        return 0.0
    return min(out, duration) if duration else out


def align_energy(lyrics: Lyrics, audio_path: str, duration: float,
                 log: Log = _noop, skip=None) -> Lyrics:
    """Lay lines over sung phrases; inside a line, words go by syllable."""
    from . import audio as A

    log(tr("Looking for sung phrases by loudness…", "Ищу вокальные фразы по громкости…"))
    try:
        env, dt = A.rms_envelope(audio_path)
    except Exception as e:                              # pragma: no cover
        log(tr(f"  did not work ({e}) — spreading evenly", f"  не вышло ({e}) — раскладываю равномерно"))
        env, dt = [], 0.02

    # the same rule as the neural path: phrases are for the lead lines, the
    # backing is placed against them afterwards
    lines = [ln for ln in lyrics.lines if ln.words and not ln.backing] \
        or [ln for ln in lyrics.lines if ln.words]
    segs = _phrases(env, dt)
    if not segs or not lines:
        log(tr("  no phrases stood out — spreading the text evenly",
            "  фразы не выделились — раскладываю текст равномерно"))
        segs = [[0.0, duration]]
    # Phrases inside a stretch the person called wordless are not phrases to
    # put text on: a vocalise is as loud as singing, which is the whole trouble.
    skip = spans(skip, duration)
    if skip:
        segs = [g for g in segs
                if not any(g[0] >= a - 0.2 and g[1] <= b + 0.2 for a, b in skip)]
        if not segs:
            segs = [[w[0], w[1]] for w in keep_windows(skip, duration)]
        log(tr(f"  wordless stretches taken out: {len(skip)}",
               f"  выброшено участков без текста: {len(skip)}"))
    segs = _limit_phrases(segs, max(3 * len(lines) + 8, 24))
    log(tr(f"  phrases found: {len(segs)}, lines of text: {len(lines)}",
           f"  найдено фраз: {len(segs)}, строк текста: {len(lines)}"))

    if lines:
        _fit_lines_to_phrases(lines, segs)

    # words inside a line are spread in proportion to syllables.
    # The span must not be widened: on dense text lines are shorter than any
    # threshold, and stretched words would run into the next line.
    for ln in lines:
        span = max(ln.end - ln.start, 1e-3)
        acc = 0.0
        for w in ln.words:
            w.start = ln.start + span * acc / ln.syllables
            acc += w.syllables
            w.end = ln.start + span * acc / ln.syllables

    _fill_lines(lyrics, duration)
    if any(ln.backing for ln in lyrics.lines):
        place_backing(lyrics, duration, log=log)
    if skip:
        enforce_marks(lyrics, skip, duration, log=log)
        _fill_lines(lyrics, duration)
    return lyrics


# --------------------------------------------------------------------------- #
#  Whisper forced alignment
# --------------------------------------------------------------------------- #

def _alignment_blocks(lines: List[Line], max_lines: int = 8,
                      max_words: int = 55) -> List[List[Line]]:
    """Small sequential batches keep one failed phrase from losing a long song."""
    out: List[List[Line]] = []
    block: List[Line] = []
    words = 0
    for line in lines:
        count = len(line.words)
        if block and (len(block) >= max_lines or words + count > max_words):
            out.append(block)
            block, words = [], 0
        block.append(line)
        words += count
    if block:
        out.append(block)
    return out


def _safe_alignment_anchor(segments, offset: float = 0.0,
                           max_gap: float = 12.0) -> Optional[float]:
    """Last trustworthy end in one recovery block.

    stable-ts may place the first few lines correctly and then jump far ahead
    on a phrase it cannot match.  Using that late segment as the next block's
    cursor turns one bad phrase into a broken remainder of the song.
    """
    end: Optional[float] = None
    previous_end: Optional[float] = None
    for seg in segments:
        words = seg.words or []
        probs = [float(w.probability) for w in words
                 if getattr(w, "probability", None) is not None]
        start = float(seg.start) + offset
        stop = float(seg.end) + offset
        sane = (stop > start and stop - start < max(8.0, 1.5 * len(words))
                and (not probs or max(probs) >= 0.005))
        if not sane:
            break
        if previous_end is not None and start - previous_end > max_gap:
            break
        end = stop
        previous_end = stop
    return end


def _lost_alignment_index(lines: List[Line]) -> Optional[int]:
    """First line of a confidence collapse after implausible consecutive gaps."""
    def bounds(line: Line):
        timed = [w for w in line.words if w.start is not None and w.end is not None]
        return (timed[0].start, timed[-1].end) if timed else (None, None)

    def confidence(line: Line) -> float:
        got = [w.prob for w in line.words if w.prob is not None]
        return sum(got) / len(got) if got else 1.0

    for i in range(1, len(lines)):
        _a0, previous_end = bounds(lines[i - 1])
        current_start, _b1 = bounds(lines[i])
        if previous_end is None or current_start is None \
                or current_start - previous_end < 7.0:
            continue
        window = lines[i:min(i + 5, len(lines))]
        low = sum(confidence(line) < 0.30 for line in window)
        another_gap = False
        for left, right in zip(window, window[1:]):
            _x, left_end = bounds(left)
            right_start, _y = bounds(right)
            if left_end is not None and right_start is not None \
                    and right_start - left_end > 5.0:
                another_gap = True
                break
        # One quiet instrumental bridge is legitimate. Several large holes and
        # several barely recognised lines in a row mean the aligner lost place.
        if low >= 3 and another_gap:
            return i
    return None


def align_whisper(lyrics: Lyrics, audio_path: str, duration: float,
                  model_name: str = "medium", language: str = "ru",
                  device: Optional[str] = None, log: Log = _noop,
                  isolated: bool = False, skip: Optional[List[tuple]] = None,
                  model=None) -> Lyrics:
    lent = model is not None
    import stable_whisper

    from . import sysinfo
    ok, note = sysinfo.check(sysinfo.NEED_WHISPER.get(model_name, 2.2))
    if not ok:
        log("  " + note + tr(" If it crashes, take a smaller model.",
                          " Если упадёт — возьмите модель поменьше."))

    from . import lang as LG
    from . import models as M
    from .progress import Heartbeat

    # “auto” does not mean “let Whisper guess” but “we work it out from the
    # text”: the result is then predictable and visible in the log.
    if not language or language == "auto":
        language = LG.detect(lyrics.plain_text())
        log(tr(f"Language of the lyrics: {LG.label(language)} (worked out from the text)",
           f"Язык текста: {LG.label(language)} (определён по тексту)"))

    # Say what is true: if the model is on disk, promising a download is a lie —
    # the window next to it says “already downloaded”, and one of the two lied.
    if model is not None:
        # Handed in: a song aligned piece by piece must not load gigabytes anew
        # for every piece.
        pass
    else:
        log(M.load_note(model_name))
    try:
        # medium is a gigabyte and a half: both loading from disk and the first
        # download take minutes in silence, and the window looks frozen.
        need = sysinfo.NEED_WHISPER.get(model_name, 2.2)
        with Heartbeat(log, M.step_label(model_name), every=10.0,
                       slow_after=90.0,
                       slow_note=tr(
                           f"longer than usual. The “{model_name}” model needs about "
                           f"{need:.0f} GB of memory; when there is less, the system "
                           f"moves data to the disk and the step stretches out many "
                           f"times over. A smaller model helps: "
                           f"medium → small → base.",
                           f"дольше обычного. Модели «{model_name}» нужно около "
                           f"{need:.0f} ГБ памяти; если её мало, система "
                           f"перекладывает данные на диск, и шаг растягивается "
                           f"в разы. Помогает модель поменьше: "
                           f"medium → small → base.")):
            if model is None:
                model = stable_whisper.load_model(model_name, device=device)
    except Exception as e:
        # Catch a failed download separately: “Connection refused” explains
        # nothing by itself, and the cause is almost always this machine's net.
        low = str(e).lower()
        net = ("urlopen", "connection", "getaddrinfo", "timed out", "ssl",
               "max retries", "name resolution", "unreachable", "httperror")
        if any(k in low for k in net):
            raise RuntimeError(tr(
                f"could not download the Whisper model “{model_name}”. "
                f"Check the internet on this machine — the model downloads once "
                f"and then lives in ~/.cache/whisper. The original error: {e}",
                f"не удалось скачать модель Whisper «{model_name}». "
                f"Проверьте интернет на этой машине — модель качается один раз "
                f"и потом лежит в ~/.cache/whisper. Исходная ошибка: {e}"))
        if "checksum" in low or "sha256" in low:
            raise RuntimeError(tr(
                f"the “{model_name}” model file was damaged while downloading. "
                f"Delete ~/.cache/whisper and try again. The original error: {e}",
                f"файл модели «{model_name}» побился при загрузке. Удалите "
                f"~/.cache/whisper и повторите. Исходная ошибка: {e}"))
        raise

    # Given a file path, Whisper calls `ffmpeg` by name through PATH. When
    # ffmpeg comes from imageio-ffmpeg it has another name and is not found —
    # Windows answers “WinError 2”. So we decode ourselves and hand over ready
    # samples: 16 kHz mono float32 in [-1, 1], exactly what the model expects.
    audio_input = audio_path
    decoded = False
    try:
        import numpy as np
        from . import audio as A
        # On the separated voice the levels are levelled first: a screamed
        # vocal swings from a shout to a rasp, and the quiet half never reaches
        # the model otherwise. Only what the model hears changes — the sound of
        # the karaoke itself is untouched.
        pcm = A.read_pcm_mono(audio_path, 16000, af=A.LEVEL_VOICE if isolated else None)
        audio_input = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
        decoded = True
        log(tr(f"  audio decoded with our own ffmpeg ({len(audio_input) / 16000:.0f} s)"
               + (", the voice levelled out for the model" if isolated else ""),
               f"  звук декодирован своим ffmpeg ({len(audio_input) / 16000:.0f} с)"
               + (", вокал выровнен по громкости для модели" if isolated else "")))
    except Exception as e:
        log(tr(f"  could not decode in advance ({e}) — handing Whisper the file path",
               f"  не вышло декодировать заранее ({e}) — отдаю Whisper путь к файлу"))

    # A wordless intro, a vocalise, a scream with nothing to write down are all
    # voice: no measurement tells them from singing, and only a person can say
    # which is which. Where they have said it, those stretches are cut out of
    # what the model hears — what it never hears, it cannot lay words on — and
    # the times are put back into the whole song afterwards.
    skip = spans(skip, duration)
    keep = keep_windows(skip, duration) if skip else []
    if skip and decoded and keep:
        import numpy as np
        pieces = [audio_input[int(a * 16000):int(b * 16000)] for a, b in keep]
        audio_input = np.concatenate(pieces)
        log(tr(f"  no words in: {', '.join(mmss(a) + '–' + mmss(b) for a, b in skip)}"
               f" — {sum(b - a for a, b in skip):.0f} s not shown to the model",
               f"  без текста: {', '.join(mmss(a) + '–' + mmss(b) for a, b in skip)}"
               f" — {sum(b - a for a, b in skip):.0f} с модели не показываю"))
    elif skip:
        keep = []
        log(tr("  the wordless stretches cannot be cut out without decoding — "
               "the whole song goes to the model, and they only guide the repairs",
               "  вырезать куски без текста не вышло — модели уходит вся песня, "
               "они учтутся только при ремонте"))

    # The backing never reaches the model. Alignment is linear: asked to place
    # the na-na-na BETWEEN the lead lines, it drags whole choruses into the
    # silence it can hear perfectly well is empty, just to make room. The lead
    # lines anchor cleanly on their own; the backing is placed by rule after.
    main_lines = [ln for ln in lyrics.lines if not ln.backing] or lyrics.lines
    if len(main_lines) < len(lyrics.lines):
        log(tr(f"  backing lines kept away from the aligner: "
               f"{len(lyrics.lines) - len(main_lines)}",
               f"  бэк-строк не показано разметчику: "
               f"{len(lyrics.lines) - len(main_lines)}"))

    # stable-ts splits tokens internally, but after one failed phrase its audio
    # cursor can jump tens of seconds and never recover. Give each short block a
    # fresh context, starting at the end found for the previous one.
    blocks = [main_lines]

    def whole(t: float) -> float:
        """From the stitched audio back into the song it was cut from."""
        if not keep:
            return t
        at = 0.0
        for a, b in keep:
            if t <= at + (b - a):
                return a + (t - at)
            at += b - a
        return keep[-1][1]

    probs: List[float] = []
    matched_count = 0.0
    matched_total = 0
    got_words = 0
    cursor = 0.0
    log(tr("Lining the text up with the audio…", "Выравниваю текст по звуку…"))
    try:
        # stable-ts complains through the warnings module — “12/34 segments failed
        # to align” and the like. In a console that scrolls past and is gone; it
        # belongs in the log with everything else, because it names the trouble
        # before any of our repairs even start.
        caught: List[warnings.WarningMessage] = []
        stack = warnings.catch_warnings(record=True)
        caught = stack.__enter__()
        warnings.simplefilter("always")
        # The longest step after the instrumental. stable-ts can report how many
        # seconds it has processed — send that to the log rather than to a
        # console progress bar, which the studio window never shows anyway.
        with Heartbeat(log, tr("alignment", "выравнивание"), slow_after=600.0,
                       slow_note=tr(
                           "is taking a while. On a CPU medium is about five times "
                           "slower than small, and with little memory slower still. "
                           "It can be interrupted, the timing will be recomputed "
                           "with another model.",
                           "идёт долго. На процессоре medium считает примерно "
                           "впятеро дольше small, а при нехватке памяти — ещё "
                           "дольше. Прервать можно, разметка пересчитается "
                           "с другой моделью.")) as hb:
            for block_no, block in enumerate(blocks):
                offset = cursor if decoded else 0.0
                block_audio = (audio_input[int(offset * 16000):]
                               if decoded and offset > 0 else audio_input)
                block_text = "\n".join(ln.text for ln in block)

                def block_progress(done, total, n=block_no):
                    share = float(done or 0) / float(total or 1)
                    hb.progress(n + max(0.0, min(1.0, share)), len(blocks))

                try:
                    result = model.align(block_audio, block_text,
                                         language=language, original_split=True,
                                         progress_callback=block_progress,
                                         verbose=False)
                except TypeError:
                    # Older stable-ts builds lack the progress parameters.
                    result = model.align(block_audio, block_text,
                                         language=language, original_split=True)
                if result is None:
                    continue

                rec: List[tuple] = []
                safe_end = (_safe_alignment_anchor(result.segments, offset)
                            if block_no > 0 else None)
                for seg in result.segments:
                    # A recovery block can have a sound prefix and a failed
                    # last segment stretched far into the remaining track.
                    # It must not overwrite the useful timings with that tail.
                    if block_no > 0 and (safe_end is None or
                            float(seg.end) + offset > safe_end + 0.001):
                        break
                    seg_probs = [float(w.probability) for w in (seg.words or [])
                                 if getattr(w, "probability", None) is not None]
                    seg_start = float(seg.start) + offset
                    seg_end = float(seg.end) + offset
                    for w in (seg.words or []):
                        key = normalize_token(w.word)
                        if not key:
                            continue
                        p = getattr(w, "probability", None)
                        a = float(w.start) + offset
                        b = float(w.end) + offset
                        rec.append((key, whole(a), whole(b),
                                    float(p) if p is not None else None))
                        got_words += 1
                        if p is not None:
                            probs.append(float(p))

                block_words = [w for ln in block for w in ln.words]
                share = _apply_recognized(block_words, rec) if rec else 0.0
                matched_count += share * len(block_words)
                matched_total += len(block_words)
                if block_no == 0 and len(blocks) == 1 and decoded:
                    lost = _lost_alignment_index(main_lines)
                    if lost is not None:
                        recovery = _alignment_blocks(main_lines[lost:])
                        # Do not let timings from the failed full pass survive
                        # in words a recovery block could not hear either.
                        for line in main_lines[lost:]:
                            line.start = line.end = None
                            for word in line.words:
                                word.start = word.end = word.prob = None
                        blocks.extend(recovery)
                        previous = main_lines[lost - 1]
                        previous_end = max(
                            (w.end for w in previous.words if w.end is not None),
                            default=0.0)
                        cursor = max(0.0, previous_end - 0.25)
                        log(tr(
                            f"  alignment lost its place at line {lost + 1}; "
                            f"retrying the rest in {len(recovery)} short blocks",
                            f"  разметка потеряла место на строке {lost + 1}; "
                            f"остаток повторяю короткими блоками ({len(recovery)})"))
                if decoded and block_no + 1 < len(blocks):
                    if block_no > 0 or len(blocks) == 1:
                        raw_end = _safe_alignment_anchor(result.segments, offset)
                        if raw_end is None:
                            raw_end = cursor
                        cursor = max(cursor, raw_end - 0.25)
                del result
        stack.__exit__(None, None, None)
        report_warnings(caught, len(lyrics.lines), log)
    except FileNotFoundError as e:
        stack.__exit__(None, None, None)
        raise RuntimeError(tr(
            f"Whisper could not start ffmpeg ({e}). Install it into the system: "
            f"winget install Gyan.FFmpeg — and restart the command line.",
            f"Whisper не смог запустить ffmpeg ({e}). Поставьте его в систему: "
            f"winget install Gyan.FFmpeg — и перезапустите командную строку."))

    if not got_words:
        raise RuntimeError(tr("Whisper returned no timed words at all",
                              "Whisper не вернул ни одного слова с таймингом"))

    matched = matched_count / matched_total if matched_total else 0.0
    # This is NOT a “is it the right text” check: align() forces the given text
    # onto the audio, so the words always match. It catches a tokenisation
    # mismatch between our parser and Whisper's — without it such a failure
    # silently turns the timing into an evenly spread blanket.
    if matched < 0.4:
        raise RuntimeError(tr(
            f"the words could not be matched to Whisper's output "
            f"({matched:.0%} matched) — looks like an incompatible stable-ts version",
            f"слова не удалось сопоставить с выводом Whisper (совпало {matched:.0%}) — "
            f"похоже на несовместимую версию stable-ts"))

    # Low confidence, on the other hand, hints the text does not fit the audio
    if probs:
        probs.sort()
        median = probs[len(probs) // 2]
        log(tr(f"  words matched: {matched:.0%}, confidence: {median:.2f}",
               f"  сопоставлено слов: {matched:.0%}, уверенность: {median:.2f}"))
        if median < 0.08:
            log(tr("  NOTE: the confidence is very low. Check that the text really "
                   "belongs to this recording and that --lang is right; the timing "
                   "may be rubbish.",
                   "  ВНИМАНИЕ: уверенность очень низкая. Проверьте, что текст именно "
                   "от этой записи и что --lang указан верно; разметка может быть мусорной."))
    else:
        log(tr(f"  words matched: {matched:.0%}", f"  сопоставлено слов: {matched:.0%}"))

    # the model weighs gigabytes — let it go at once, it is not needed further.
    # A lent one is its owner's business: pieces of one song share it.
    if not lent:
        del model
    import gc
    gc.collect()

    _trim_leading_silence(lyrics)
    if isolated:
        refine_leading_silence(lyrics, audio_path, log=log)
    # Line bounds come from the words — without this step lines have no times
    # yet, and the repairs would compare emptiness with emptiness.
    _fill_lines(lyrics, duration)
    repair_lines(lyrics, log=log)      # Whisper sometimes drops a word far away
    # …and sometimes drops a dozen of them in one spot. Looking at the audio is
    # only worth it once we know there is a pile to spread.
    # The same stretches bound the repairs: spreading a pile over a vocalise is
    # exactly what the person said not to do.
    sung_end = min(last_sound(audio_path, duration), keep[-1][1] if keep else duration)
    text_end = max((ln.end for ln in lyrics.lines if ln.end is not None), default=0.0)
    untexted = max(0.0, sung_end - text_end)
    if pile_runs(lyrics.lines):
        repair_piles(lyrics, duration, log=log,
                     floor=max(first_sound(audio_path), keep[0][0] if keep else 0.0),
                     untexted=untexted)
    # Only on a separated vocal: there silence is silence. On a mix a “quiet”
    # stretch may simply be a quieter verse, and moving lines off it would do
    # the damage it is meant to prevent.
    if isolated or skip:
        repair_silent(lyrics, duration, audio_path, log=log, skip=skip)
    if any(ln.backing for ln in lyrics.lines):
        place_backing(lyrics, duration, log=log)
    if skip:
        # A line may still reach across a hole from the outside: the aligner
        # had to end it somewhere, and the far side of the silence was the
        # nearest thing it could find.
        clip_to_marks(lyrics, skip, log=log)
        # …and whatever is left overlapping after every gentler pass is forced
        # out: the marks are the person's own words, and they win.
        enforce_marks(lyrics, skip, duration, log=log)
    repair_overlapping_repeats(lyrics, duration, log=log)
    # Run this after every audio and pile repair: an unheard line at the edge
    # of a recovery block must remain inside the final gap and must not push or
    # overlap the accurately heard next block.
    fit_unheard_lines(lyrics, log=log)
    repair_order(lyrics, log=log)
    repair_ragged(lyrics, log=log)
    _fill_lines(lyrics, duration)      # after repairs the bounds may exceed the track

    # What could not be spread stays a pile, and a pile is not a timing: those
    # lines fly past in a blink. Better to name them than to hand over a page
    # that looks finished and is not.
    # A whole stretch of singing with no text under it means the alignment did
    # not just stumble on a line — it lost its place. Worth saying: the fix is
    # not dragging lines one by one.
    if untexted > max(15.0, 0.15 * duration):
        log(tr(f"  NOTE: the text ends at {text_end // 60:.0f}:{text_end % 60:04.1f} while "
               f"the singing goes on to {sung_end // 60:.0f}:{sung_end % 60:04.1f} — "
               f"{sung_end - text_end:.0f} s of song with no lyrics under it. Either the "
               f"text is written out fewer times than it is sung, or the alignment lost "
               f"its place. “Re-time” with the loudness engine spreads the lines over the "
               f"whole song instead.",
               f"  ВНИМАНИЕ: текст кончается на {text_end // 60:.0f}:{text_end % 60:04.1f}, "
               f"а поют до {sung_end // 60:.0f}:{sung_end % 60:04.1f} — "
               f"{sung_end - text_end:.0f} с песни без единой строки. Либо в тексте "
               f"выписано меньше повторов, чем поётся, либо разметка потеряла место. "
               f"«Разметить заново» движком по энергии разложит строки по всей песне."))

    left = pile_share(lyrics)
    if left > 0.02:
        stuck = [i + 1 for a, b in pile_runs(lyrics.lines) for i in range(a, b + 1)]
        spot = lyrics.lines[stuck[0] - 1].start if stuck else 0.0
        log(tr(f"  NOTE: {len(stuck)} of {len(lyrics.lines)} lines could not be timed — "
               f"they are piled at {spot // 60:.0f}:{spot % 60:04.1f} (lines "
               f"{stuck[0]}–{stuck[-1]}). Whisper heard no words there: a quiet or "
               f"whispered patch. Drag them into place in the studio, or press "
               f"“Re-time” with the loudness engine.",
               f"  ВНИМАНИЕ: {len(stuck)} строк из {len(lyrics.lines)} разметить не вышло — "
               f"они свалены в кучу на {spot // 60:.0f}:{spot % 60:04.1f} (строки "
               f"{stuck[0]}–{stuck[-1]}). Whisper не расслышал там слов: тихое или "
               f"шёпотом спетое место. Растащите их в студии мышкой или нажмите "
               f"«Разметить заново» с движком по энергии."))
    return lyrics


def report_warnings(caught, lines: int, log: Log) -> int:
    """Put what stable-ts muttered into the log, and say what it means.

    “12/34 segments failed to align” is the single most useful line the aligner
    ever prints, and it goes to a console window nobody is looking at. Returns
    how many lines the aligner admits it could not place.
    """
    failed = 0
    for w in caught or ():
        text = str(getattr(w, "message", w)).strip()
        if not text:
            continue
        log("  " + text.splitlines()[0])
        m = re.search(r"(\d+)\s*/\s*(\d+)\s+segments failed to align", text)
        if m:
            failed = int(m.group(1))
            total = int(m.group(2)) or lines
            log(tr(f"  that is {failed} of {total} lines with no timing of their own — "
                   f"Whisper heard no words there. They come out piled in one spot; "
                   f"what was done with them is said below.",
                   f"  это {failed} строк из {total} без своего времени — Whisper не "
                   f"расслышал там слов. Они выходят сваленными в одну точку; что с ними "
                   f"сделано, сказано ниже."))
    return failed


def _apply_recognized(words: List[Word], rec: List[tuple]) -> float:
    """Match our words against the recognised ones. Returns the exact-match share."""
    ours = [normalize_token(w.text) for w in words]
    theirs = [r[0] for r in rec]

    exact = 0
    matcher = difflib.SequenceMatcher(a=ours, b=theirs, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            exact += i2 - i1
            for k in range(i2 - i1):
                words[i1 + k].start = rec[j1 + k][1]
                words[i1 + k].end = rec[j1 + k][2]
                if len(rec[j1 + k]) > 3:
                    words[i1 + k].prob = rec[j1 + k][3]
        elif tag == "replace" and (i2 - i1) and (j2 - j1):
            # spread the matched stretch over our words in proportion to syllables
            t0, t1 = rec[j1][1], rec[j2 - 1][2]
            chunk = words[i1:i2]
            total = sum(w.syllables for w in chunk) or 1
            acc = 0.0
            # A stretch the model heard as something else: the words are ours,
            # the confidence is the worst of what it did hear there.
            heard = [r[3] for r in rec[j1:j2] if len(r) > 3 and r[3] is not None]
            for w in chunk:
                w.prob = min(heard) if heard else None
                w.start = t0 + (t1 - t0) * acc / total
                acc += w.syllables
                w.end = t0 + (t1 - t0) * acc / total

    _interpolate_gaps(words)
    return exact / len(words) if words else 0.0


def _trim_leading_silence(lyrics: Lyrics, factor: float = 3.0) -> None:
    """Whisper glues the pause before a phrase onto its first word — trim it.

    Only the first word of a line is touched, and only when it is implausibly
    long: long melismas in the middle and at the end are left alone.
    """
    for ln in lyrics.lines:
        if not ln.words:
            continue
        w = ln.words[0]
        if w.start is None or w.end is None:
            continue
        expect = 0.35 * w.syllables + 0.15
        if (w.end - w.start) > max(1.2, factor * expect):
            w.start = w.end - expect


def refine_leading_silence(lyrics: Lyrics, vocal_audio: str,
                           log: Log = _noop, max_shift: float = 3.2) -> int:
    """Move an early line start to the first real voice in its vocal stem.

    Forced alignment occasionally assigns the quiet lead-in to the first word,
    especially with the smaller Whisper models. Duration alone cannot tell
    that mistake from a genuinely held first syllable. A separated vocal can:
    move the boundary only when it contains a measured stretch with no voice
    and its end still falls inside that first word. The rest of the word and
    every later word keep their precise Whisper timing.
    """
    try:
        from . import audio as AU
        env, hop = AU.rms_envelope(vocal_audio)
        quiet = silent_spans(env, hop, least=0.35)
    except Exception:
        return 0
    duration = len(env) * hop
    if not quiet or sum(q["end"] - q["start"] for q in quiet) > 0.85 * duration:
        return 0

    fixed = 0
    for line_index, ln in enumerate(lyrics.lines):
        if line_index in lyrics.fixed_line_indices:
            continue
        if ln.backing or not ln.words:
            continue
        first = ln.words[0]
        if first.start is None or first.end is None:
            continue
        for q in quiet:
            shift = q["end"] - first.start
            if q["start"] > first.start + 0.12 or shift < 0.28 \
                    or shift > max_shift:
                continue
            # If several complete words precede the onset, the model lost more
            # than a boundary and a blind automatic rewrite is not safe.
            if q["end"] >= first.end - 0.04:
                continue
            new_start = min(q["end"] - 0.06, first.end - 0.08)
            if new_start <= first.start + 0.2:
                continue
            first.start = max(first.start, new_start)
            ln.start = first.start
            fixed += 1
            break
    if fixed:
        log(tr(f"  early line starts moved to the detected voice onset: {fixed}",
               f"  ранних начал строк перенесено к найденному вступлению вокала: {fixed}"))
    return fixed


def refine_uncertain_word_onsets(lyrics: Lyrics, vocal_audio: str,
                                 log: Log = _noop, max_shift: float = 0.95) -> int:
    """Snap doubtful internal word starts to a fresh vocal attack.

    On a held vowel forced alignment can paint the following word while the
    previous one is still being sung. It can also miss a quiet first particle
    and start the whole line a few hundred milliseconds late. A separated
    vocal exposes both attacks clearly. This pass is deliberately narrow:
    internal words still need to be at least half a second long, while a line
    start is moved only backwards, only below 15% confidence, and never into
    the preceding line. Confident melismas are left exactly where Whisper put
    them.
    """
    try:
        from . import audio as AU
        env, hop = AU.rms_envelope(vocal_audio, hop_ms=20)
    except Exception:
        return 0
    if len(env) < 12 or hop <= 0:
        return 0

    # A short before/after average reveals consonant attacks without reacting
    # to every sample. Keep only local maxima; several syllables may live in
    # the window, and the confidence decides how selective to be below.
    rise = [0.0] * len(env)
    for i in range(3, len(env) - 3):
        before = sum(env[i - 3:i + 1]) / 4.0
        after = sum(env[i:i + 4]) / 4.0
        rise[i] = max(0.0, after - before)

    fixed = 0
    for line_index, ln in enumerate(lyrics.lines):
        if line_index in lyrics.fixed_line_indices:
            continue
        ws = ln.words
        # Whisper often hears a short opening conjunction only after its
        # vowel has developed ("И, уходя" is a common shape). Look behind at
        # most 450 ms for the strongest new vocal attack. Keeping the attack
        # beyond the previous line prevents its final syllable being stolen.
        if ws:
            first = ws[0]
            if first.start is not None and first.prob is not None \
                    and first.prob < 0.15:
                floor = max(0.0, first.start - min(max_shift, 0.45))
                if line_index:
                    previous_end = lyrics.lines[line_index - 1].end
                    if previous_end is not None:
                        floor = max(floor, previous_end + 0.04)
                lo = max(1, int(floor / hop))
                hi = min(len(env) - 2, int((first.start - 0.14) / hop) + 1)
                peaks = [i for i in range(lo, hi)
                         if rise[i] >= 0.075
                         and rise[i] >= rise[i - 1] and rise[i] >= rise[i + 1]]
                if peaks:
                    pick = max(peaks, key=lambda i: (rise[i], -i))
                    new_start = pick * hop
                    if floor <= new_start <= first.start - 0.14:
                        first.start = new_start
                        ln.start = new_start
                        fixed += 1

        for k in range(1, len(ws) - 1):
            word = ws[k]
            if word.start is None or word.end is None or word.prob is None:
                continue
            length = word.end - word.start
            if word.prob >= 0.15 or length < 0.50:
                continue
            lo = max(1, int((word.start - 0.30) / hop))
            hi = min(len(env) - 2,
                     int(min(word.end + 0.10, word.start + max_shift) / hop) + 1)
            if hi <= lo:
                continue
            peaks = [i for i in range(lo, hi)
                     if rise[i] >= 0.075
                     and rise[i] >= rise[i - 1] and rise[i] >= rise[i + 1]]
            if not peaks:
                continue
            if word.prob < 0.03:
                # With virtually no recognised phoneme, ignore a weak twitch
                # at the guessed boundary and take the first clear attack.
                strongest = max(rise[i] for i in peaks)
                clear = [i for i in peaks if rise[i] >= 0.70 * strongest]
                pick = clear[0]
            else:
                # A partly heard word is already nearby: take the closest
                # plausible attack, preferring the earlier one on a tie.
                pick = min(peaks, key=lambda i: (abs(i * hop - word.start), i))
            new_start = pick * hop
            if abs(new_start - word.start) < 0.08 \
                    or abs(new_start - word.start) > max_shift:
                continue
            # Sometimes the true attack sits at the very end of the interval
            # Whisper guessed for this word (the “потом” case in a held
            # chorus). Give it room up to the next vocal attack and move the
            # following boundary with it, instead of creating an 80 ms word.
            if new_start >= word.end - 0.08:
                nxt = ws[k + 1]
                far = min(len(env) - 2,
                          int(min((nxt.end or new_start + 0.8),
                                  new_start + 0.9) / hop) + 1)
                later = [i for i in range(pick + max(2, int(0.16 / hop)), far)
                         if rise[i] >= 0.075
                         and rise[i] >= rise[i - 1] and rise[i] >= rise[i + 1]]
                if not later:
                    continue
                strongest_later = max(rise[i] for i in later)
                clear_later = [i for i in later
                               if rise[i] >= 0.70 * strongest_later]
                boundary = clear_later[0] * hop
                if boundary <= new_start + 0.10:
                    continue
                word.end = boundary
                if nxt.start is not None:
                    nxt.start = boundary
            elif new_start < word.start:
                prev = ws[k - 1]
                if prev.end is not None and prev.end > new_start:
                    prev.end = new_start
            word.start = new_start
            fixed += 1
    if fixed:
        log(tr(f"  doubtful word starts moved to vocal attacks: {fixed}",
               f"  начал неуверенно распознанных слов перенесено на атаки вокала: {fixed}"))
    return fixed


def _interpolate_gaps(words: List[Word]) -> None:
    """Words left without a time (insertions in the text) are filled in between."""
    i = 0
    n = len(words)
    while i < n:
        if words[i].start is not None:
            i += 1
            continue
        j = i
        while j < n and words[j].start is None:
            j += 1
        left = words[i - 1].end if i > 0 and words[i - 1].end is not None else 0.0
        right = words[j].start if j < n and words[j].start is not None else left + 0.4 * (j - i)
        chunk = words[i:j]
        total = sum(w.syllables for w in chunk) or 1
        acc = 0.0
        for w in chunk:
            w.start = left + (right - left) * acc / total
            acc += w.syllables
            w.end = left + (right - left) * acc / total
        i = j


# --------------------------------------------------------------------------- #

def repair_lines(lyrics: Lyrics, max_word_gap: float = 1.2, log: Log = _noop) -> int:
    """Put back together the lines whose words drifted apart in time.

    Inside one sung line there are no multi-second gaps between words. If one
    is there, alignment missed: a word flew far away from its neighbours. The
    heaviest cluster of words is taken as the line\'s real place, and the strays
    are pulled up against it, leaving the well-placed middle alone.
    """
    fixed = 0
    for idx, ln in enumerate(lyrics.lines):
        ws = ln.words
        # times may not be set yet — then there is nothing to repair
        if len(ws) < 2 or any(w.start is None or w.end is None for w in ws):
            continue

        groups, cur = [], [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            if (w.start or 0) - (prev.end or 0) > max_word_gap:
                groups.append(cur)
                cur = [w]
            else:
                cur.append(w)
        groups.append(cur)
        if len(groups) < 2:
            continue

        # Which cluster counts as the line's real place. Syllable weight alone
        # is not enough: the neighbouring lines define a window this one has to
        # fall into. Otherwise a correct word gets pulled to the wrong ones.
        prev = lyrics.lines[idx - 1] if idx else None
        lo = (prev.end if prev is not None and prev.end is not None else 0.0)
        nxt = next((l for l in lyrics.lines[idx + 1:]
                    if l.words and l.start is not None), None)
        hi = nxt.start if nxt else float("inf")

        def score(g):
            fits = (g[0].start >= lo - 0.5) and (g[-1].end <= hi + 0.5)
            return (1 if fits else 0, sum(x.syllables for x in g))

        best = max(groups, key=score)
        s, e = best[0].start, best[-1].end
        bi = ws.index(best[0])
        before, after = ws[:bi], ws[bi + len(best):]

        floor = lyrics.lines[idx - 1].end if idx else 0.0
        if before:
            need = min(0.35 * sum(w.syllables for w in before), 2.0)
            t0 = max(s - need, floor or 0.0, 0.0)
            _spread(before, t0, s)
        if after:
            need = min(0.35 * sum(w.syllables for w in after), 2.0)
            _spread(after, e, e + need)

        ln.start, ln.end = ws[0].start, ws[-1].end
        fixed += 1

    if fixed:
        log(tr(f"  lines whose words drifted apart, put back together: {fixed}",
               f"  собрал обратно строк с разъехавшимися словами: {fixed}"))
    return fixed


def fit_unheard_lines(lyrics: Lyrics, log: Log = _noop) -> int:
    """Fit one unheard line into the gap between two confidently heard lines.

    A failed final segment of a recovery block has no timing of its own. The
    generic fallback estimates its length from word count, which can overlap
    the first accurately heard line of the next block and make that whole block
    appear late. Two neighbouring audio anchors give a better, bounded answer.
    """
    fixed = 0
    lines = lyrics.lines
    for i in range(1, len(lines) - 1):
        line = lines[i]
        probs = [w.prob for w in line.words if w.prob is not None]
        if probs and max(probs) > 0.005:
            continue
        previous, following = lines[i - 1], lines[i + 1]
        previous_probs = [w.prob for w in previous.words if w.prob is not None]
        following_probs = [w.prob for w in following.words if w.prob is not None]
        if not previous_probs or max(previous_probs) <= 0.005 \
                or not following_probs or max(following_probs) <= 0.005:
            continue
        if previous.end is None or following.start is None:
            continue
        # Low confidence alone is not a reason to stretch a correctly bounded
        # short phrase across a real musical gap. This repair is specifically
        # for an unheard line that collided with the next audible anchor.
        if line.end is not None and line.end < following.start - 0.1:
            continue
        start = previous.end
        end = following.start - 0.05
        if end - start < 0.3:
            continue
        _spread(line.words, start, end)
        line.start, line.end = line.words[0].start, line.words[-1].end
        fixed += 1
    if fixed:
        log(tr(f"  unheard lines fitted between their audible neighbours: {fixed}",
               f"  нерасслышанных строк поставлено между слышимыми соседями: {fixed}"))
    return fixed


def repair_overlapping_repeats(lyrics: Lyrics, duration: float,
                               log: Log = _noop) -> int:
    """Untangle two identical adjacent blocks when the first lost its tail.

    With repeated lyrics, forced alignment can use an early copy of A-B-C-D
    for the second block while E-F-G-H at the end of the first block remains
    unheard and gets interpolated over it. The reliable second copy tells us
    both where that missing suffix was actually sung and the rhythm with which
    the complete block repeats once more.
    """
    lines = lyrics.lines

    def key(line: Line) -> str:
        return " ".join(normalize_token(w.text) for w in line.words)

    def heard(line: Line) -> bool:
        probs = [w.prob for w in line.words if w.prob is not None]
        return bool(probs and max(probs) > 0.005)

    fixed = 0
    occupied_until = 0
    for size in range(min(16, len(lines) // 2), 3, -1):
        for start in range(occupied_until, len(lines) - 2 * size + 1):
            first = lines[start:start + size]
            second = lines[start + size:start + 2 * size]
            if [key(x) for x in first] != [key(x) for x in second]:
                continue
            if not all(heard(x) and all(w.start is not None and w.end is not None
                                        for w in x.words) for x in second):
                continue
            if first[-1].end is None or second[0].start is None \
                    or first[-1].end <= second[0].start + 0.2:
                continue

            suffix = 0
            for a, b in zip(reversed(first), reversed(second)):
                if heard(a) or not heard(b):
                    break
                suffix += 1
            # A low-confidence line immediately before the collision may still
            # be correctly timed. Borrow only the part that physically reaches
            # into the next copy, not every uncertain line before it.
            while suffix and (first[-suffix].end or 0.0) \
                    <= (second[0].start or 0.0) + 0.2:
                suffix -= 1
            if suffix < 2 or suffix >= size:
                continue

            # Keep a snapshot because the first copy borrows its suffix before
            # the complete second copy is shifted to the next occurrence.
            template = [[(w.start, w.end, w.prob) for w in line.words]
                        for line in second]
            for target, source in zip(first[-suffix:], template[-suffix:]):
                if len(target.words) != len(source):
                    break
                for word, (a, b, p) in zip(target.words, source):
                    word.start, word.end, word.prob = a, b, p
                target.start, target.end = target.words[0].start, target.words[-1].end
            else:
                next_start = (first[-1].end or 0.0) + 0.05
                shift = next_start - (second[0].start or 0.0)
                last_end = second[-1].end or 0.0
                if shift <= 0.0 or last_end + shift > duration:
                    continue
                for line in second:
                    for word in line.words:
                        word.start += shift
                        word.end += shift
                    line.start, line.end = line.words[0].start, line.words[-1].end
                fixed += 1
                occupied_until = start + 2 * size
                break
        if fixed:
            break
    if fixed:
        log(tr(f"  overlapping repeated lyric blocks untangled: {fixed}",
               f"  наложившихся повторяющихся блоков разложено: {fixed}"))
    return fixed


def _spread(words: List[Word], start: float, end: float) -> None:
    total = sum(w.syllables for w in words) or 1
    span = max(end - start, 0.05)
    acc = 0.0
    for w in words:
        w.start = start + span * acc / total
        acc += w.syllables
        w.end = start + span * acc / total


# The shortest a syllable can honestly be sung. Below this the timing is not
# fast singing, it is a pile: the aligner gave up and dropped the words where
# it stopped looking.
_MIN_PER_SYLLABLE = 0.07
# An unhurried pace for a sung syllable — what a spread-out pile is given.
_SUNG_PER_SYLLABLE = 0.45


def _syl(ln) -> int:
    return sum(w.syllables for w in ln.words) or 1


def pile_runs(lines) -> List[tuple]:
    """Runs of lines dumped at one instant, as (first, last) indexes.

    A pile is judged by the run as a whole, not line by line: the aligner drops
    a whole stretch of text at one moment, and the odd line inside it may look
    plausible on its own. A run counts as a pile when several lines together
    take less time than their syllables could possibly be sung in.
    """
    runs = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].start is None or lines[i].end is None or not lines[i].words:
            i += 1
            continue
        syl = _syl(lines[i])
        best = i
        j = i + 1
        while j < n and lines[j].start is not None and lines[j].end is not None and lines[j].words:
            syl += _syl(lines[j])
            if (lines[j].end - lines[i].start) < _MIN_PER_SYLLABLE * syl:
                best = j
            elif best > i:
                break                              # the pile has ended
            j += 1
        if best > i:
            runs.append((i, best))
            i = best + 1
        else:
            i += 1
    return runs


def pile_share(lyrics: Lyrics) -> float:
    """What share of the lines is stuck in piles. 0 when the timing is sound."""
    lines = lyrics.lines
    if not lines:
        return 0.0
    return sum(b - a + 1 for a, b in pile_runs(lines)) / len(lines)


def duplicate_of(lines, a: int, b: int) -> Optional[tuple]:
    """Does the run a..b repeat, word for word, a block of lines that IS timed?

    A lyrics file often holds the song written out more times than it is sung —
    a verse pasted twice, a chorus copied “for completeness”. There is no audio
    for the extra copy, so the aligner has nowhere to put it and drops it in a
    pile. Such lines must not be spread over the music: nobody sings them there.
    Naming the block they repeat is the whole answer for the person.
    """
    run = [normalize_token(" ".join(w.text for w in ln.words)) for ln in lines[a:b + 1]]
    n = len(run)
    if n < 2:
        return None
    piled = {i for x, y in pile_runs(lines) for i in range(x, y + 1)}
    for i in range(len(lines) - n + 1):
        if i <= b and i + n - 1 >= a:                 # the run itself
            continue
        if any(k in piled for k in range(i, i + n)):   # a pile is no proof
            continue
        cand = [normalize_token(" ".join(w.text for w in ln.words))
                for ln in lines[i:i + n]]
        if difflib.SequenceMatcher(a=run, b=cand, autojunk=False).ratio() >= 0.8:
            return (i, i + n - 1)
    return None


def first_sound(audio_path: str) -> float:
    """When the singing starts — so a pile at the head is not spread over silence."""
    try:
        from . import audio as AU
        from . import report as R
        env, hop = AU.rms_envelope(audio_path)
        quiet = R.quiet_stretches(env, hop)
    except Exception:
        return 0.0
    for q in quiet:
        if q["start"] <= 0.2:                    # a silence the song opens with
            return float(q["end"])
    return 0.0


def last_sound(audio_path: str, duration: float) -> float:
    """When the singing ends — the tail of a track is usually music or silence."""
    try:
        from . import audio as AU
        from . import report as R
        env, hop = AU.rms_envelope(audio_path)
        quiet = R.quiet_stretches(env, hop)
    except Exception:
        return duration
    for q in quiet:
        if q["end"] >= duration - 0.5:            # the silence the song ends with
            return float(q["start"])
    return duration


def repair_piles(lyrics: Lyrics, duration: float, log: Log = _noop,
                 floor: float = 0.0, untexted: float = 0.0) -> int:
    """Spread out the lines an aligner piled up in one spot.

    On a quiet intro, a long instrumental or a whispered verse Whisper finds
    nothing to hold on to and returns a whole stretch of text at the single
    moment where it did hear something. On screen that is a pile: a dozen lines
    inside a fraction of a second, and the karaoke leaps through half the lyrics
    in one blink.

    The words are lost either way — but their ORDER is not, and neither is the
    free time around the pile. Spreading the run across that free time is much
    closer to the truth than one instant, and every line stays draggable.

    Only the room between the neighbouring sound lines is used, and only as much
    of it as the singing needs: a gap can hold wordless sounds — a breath, an
    intro, humming — and stretching seven lines over half a minute of those
    claims as lyrics what is not. So the run keeps a singable pace and sits
    against the line that follows it, which is where the aligner found its
    footing again.

    When the neighbours themselves contradict each other, the pile is left
    alone: moving it would just stack lines on top of a line that IS timed right.
    """
    lines = lyrics.lines
    fixed = 0
    phantom = []
    for a, b in pile_runs(lines):
        dup = duplicate_of(lines, a, b)
        if dup:
            # Not sung at all — an extra copy in the lyrics file. Spreading it
            # would paint words over music nobody sings there.
            phantom.append((a, b, dup))
            continue
        run = lines[a:b + 1]
        lo = lines[a - 1].end if a and lines[a - 1].end is not None else floor
        hi = lines[b + 1].start if b + 1 < len(lines) and lines[b + 1].start is not None \
            else duration
        lo = max(0.0, min(lo, duration))
        hi = max(0.0, min(hi, duration))
        need = sum(_syl(ln) for ln in run) * _MIN_PER_SYLLABLE
        was = (run[-1].end or 0.0) - (run[0].start or 0.0)
        if hi <= lo or (hi - lo) <= max(need, was) + 0.05:
            continue                               # nowhere to spread it
        total = sum(_syl(ln) for ln in run)
        # An unhurried sung pace. Wider than the “nobody sings that fast” floor,
        # narrower than the whole gap — the rest of the gap may well be music.
        span = min(hi - lo, max(_SUNG_PER_SYLLABLE * total, need))
        # Against the following line when there is one: a pile forms where the
        # aligner lost the text, and it re-locked at the line after it.
        base = hi - span if b + 1 < len(lines) else lo
        acc = 0.0
        for ln in run:
            t0 = base + span * acc / total
            acc += _syl(ln)
            t1 = base + span * acc / total
            _spread(ln.words, t0, max(t1 - 0.05, t0 + 0.05))
            ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        fixed += len(run)

    if fixed:
        log(tr(f"  lines the aligner piled in one spot, spread out: {fixed}",
               f"  разложил строк, сваленных разметчиком в одну точку: {fixed}"))
    for a, b, (c, d) in phantom:
        if untexted > 15.0:
            # The words are sung twice and there is a whole stretch of singing with
            # no text on it: the aligner locked onto the wrong repetition and put
            # both copies of the text on one pass of the song.
            log(tr(f"  NOTE: lines {a + 1}–{b + 1} say the same as lines {c + 1}–{d + 1}, "
                   f"and {untexted:.0f} s of singing has no text at all. The song sings "
                   f"those words twice, and the timing landed on one pass only — it is "
                   f"out by a whole repetition, not by a line. “Re-time” with the "
                   f"loudness engine lays the lines over the whole song instead.",
                   f"  ВНИМАНИЕ: строки {a + 1}–{b + 1} слово в слово повторяют строки "
                   f"{c + 1}–{d + 1}, а {untexted:.0f} с пения остались вообще без текста. "
                   f"Эти слова поются дважды, а разметка легла только на один прогон — "
                   f"она сдвинута на целый повтор, а не на строку. «Разметить заново» "
                   f"движком по энергии разложит строки по всей песне."))
        else:
            log(tr(f"  NOTE: lines {a + 1}–{b + 1} say the same as lines {c + 1}–{d + 1}, "
                   f"which are timed — and there is no audio for them. The lyrics file "
                   f"seems to be written out more times than the song sings it: remove "
                   f"the extra copy and press “Re-time”. Left where they are for now.",
                   f"  ВНИМАНИЕ: строки {a + 1}–{b + 1} слово в слово повторяют строки "
                   f"{c + 1}–{d + 1}, которые размечены, — а в записи их нет. Похоже, в "
                   f"файле с текстом песня выписана больше раз, чем поётся: уберите лишний "
                   f"повтор и нажмите «Разметить заново». Пока оставил их на месте."))
    return fixed


def silent_spans(env: List[float], dt: float, least: float = 2.5) -> List[Dict]:
    """Where there is no voice at all — measured against the loudest it gets.

    The panel's “quiet” is relative to the song's own middle, which is right for
    showing where the singing thins out. For moving lines it is wrong twice
    over: a song loud from end to end comes out “all quiet”, and a whispered
    verse — real singing, with words in it — comes out quiet as well, and its
    lines would be dragged off it.

    The question here is narrower and answerable: is there any voice at all? On
    a separated vocal that is a hundredth of the loudest moment. A whisper
    stands well above that; an interlude does not.
    """
    if not env or dt <= 0:
        return []
    peak = max(env)
    if peak <= 0:
        return []
    thr = peak * 0.02
    out, run = [], None
    for i, v in enumerate(env):
        if v <= thr:
            if run is None:
                run = i
        else:
            if run is not None and (i - run) * dt >= least:
                out.append({"start": round(run * dt, 1), "end": round(i * dt, 1)})
            run = None
    if run is not None and (len(env) - run) * dt >= least:
        out.append({"start": round(run * dt, 1), "end": round(len(env) * dt, 1)})
    return out


def _voiced_windows(lo: float, hi: float, quiet: List[Dict]) -> List[List[float]]:
    """The parts of [lo, hi] where the voice is heard: the gaps between silences."""
    out, at = [], lo
    for q in sorted(quiet, key=lambda q: q["start"]):
        a, b = max(lo, q["start"]), min(hi, q["end"])
        if a > at:
            out.append([at, min(a, hi)])
        at = max(at, b)
        if at >= hi:
            break
    if at < hi:
        out.append([at, hi])
    return [w for w in out if w[1] - w[0] > 0.2]


def repair_silent(lyrics: Lyrics, duration: float, audio_path: str,
                  log: Log = _noop, skip: Optional[List[tuple]] = None) -> int:
    """Move lines off the stretches where the separated voice is silent.

    The aligner is made to place every word somewhere, and over an interlude or
    a solo it places them on the music: the line looks timed, the karaoke shows
    words, and nobody sings. On the separated vocal such a stretch is real
    silence — so it can be known, not guessed.

    A run of lines sitting wholly inside that silence is moved to the nearest
    stretch of actual singing between its timed neighbours, at a sung pace,
    against the line that follows — the same reasoning as with piles: the exact
    words are lost, but their order is not, and singing beats silence as a place
    to put them. When there is no singing between the neighbours at all, the
    lines stay put and the log names them: perhaps they are simply not sung.
    """
    try:
        from . import audio as AU
        env, hop = AU.rms_envelope(audio_path)
        quiet = silent_spans(env, hop)
    except Exception:
        quiet = []
    # Even so: if what is left counts as silent almost from end to end, that is
    # not knowledge but its absence, and acting on it would drag the whole text
    # somewhere.
    if sum(q["end"] - q["start"] for q in quiet) > 0.85 * duration:
        quiet = []

    # A stretch a person marked as wordless counts as silence, whatever the
    # loudness says: a vocalise is voice, and only they can know it holds no
    # words.
    for a, b in (skip or []):
        quiet.append({"start": a, "end": b})
    quiet.sort(key=lambda q: q["start"])
    if not quiet:
        return 0

    lines = lyrics.lines

    def sits_in_silence(ln) -> bool:
        if ln.start is None or ln.end is None or not ln.words:
            return False
        return any(ln.start >= q["start"] - 0.25 and ln.end <= q["end"] + 0.25
                   for q in quiet)

    flags = [sits_in_silence(ln) for ln in lines]
    moved, stuck = 0, []
    i = 0
    while i < len(lines):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(lines) and flags[j + 1]:
            j += 1
        run = lines[i:j + 1]
        lo = lines[i - 1].end if i and lines[i - 1].end is not None else 0.0
        hi = lines[j + 1].start if j + 1 < len(lines) and lines[j + 1].start is not None             else duration
        lo, hi = max(0.0, min(lo, duration)), max(0.0, min(hi, duration))
        total = sum(_syl(ln) for ln in run)
        need = total * _MIN_PER_SYLLABLE
        pick = None
        # nearest to the following line: that is where the aligner re-locks
        for w in reversed(_voiced_windows(lo, hi, quiet)):
            if w[1] - w[0] >= need + 0.05:
                pick = w
                break
        if not pick:
            stuck.append((i, j, run[0].start or 0.0))
            i = j + 1
            continue
        span = min(pick[1] - pick[0], max(_SUNG_PER_SYLLABLE * total, need))
        base = (pick[1] - span) if j + 1 < len(lines) else pick[0]
        acc = 0.0
        for ln in run:
            t0 = base + span * acc / total
            acc += _syl(ln)
            t1 = base + span * acc / total
            _spread(ln.words, t0, max(t1 - 0.05, t0 + 0.05))
            ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        moved += len(run)
        i = j + 1

    if moved:
        log(tr(f"  lines that sat where the voice is silent, moved onto singing: {moved}",
               f"  строк, лежавших там, где вокал молчит, перенесено на пение: {moved}"))
    for a, b, at in stuck:
        log(tr(f"  NOTE: lines {a + 1}–{b + 1} sit at {at // 60:.0f}:{at % 60:04.1f}, "
               f"where the voice is silent — and there is no singing between their "
               f"neighbours to move them to. Perhaps they are simply not sung in this "
               f"recording; check them, or remove them from the lyrics.",
               f"  ВНИМАНИЕ: строки {a + 1}–{b + 1} стоят на {at // 60:.0f}:{at % 60:04.1f}, "
               f"где вокал молчит, — а пения между соседями, куда их перенести, нет. "
               f"Возможно, в этой записи они просто не поются; проверьте их или уберите "
               f"из текста."))
    return moved


def clip_to_marks(lyrics: Lyrics, skip: List[tuple], log: Log = _noop) -> int:
    """Keep line spans out of the stretches that hold no words.

    A line next to a marked stretch reaches across it: the aligner has to end a
    line somewhere, and the nearest thing it can find is the far side of the
    silence. On screen a line of five words then lasts a minute and a half, and
    putting that right by hand means dragging its edge across the whole hole.

    The marks already say where the emptiness is, so the span is simply cut
    back to it: a line that ends inside a hole ends where the hole begins, one
    that starts inside it starts where it ends. Words keep their order and are
    squeezed into what is left; a line lying wholly inside a hole is not this
    function's business — that is what moving it onto the singing is for.
    """
    fixed = 0
    for ln in lyrics.lines:
        if ln.start is None or ln.end is None or not ln.words:
            continue
        if ln.keep:
            # A line left to the original LIVES where the person does not
            # sing: the mark says “nothing for you here”, and this line is
            # not theirs. Trimmed out of the hole, its kept voice went with
            # it — and the intro fell silent.
            continue
        a, b = ln.start, ln.end
        for lo, hi in skip:
            if b <= lo or a >= hi:
                continue                      # nowhere near this hole
            if a >= lo and b <= hi:
                continue                      # wholly inside: not ours to trim
            if a < lo < b <= hi:
                b = lo                        # runs into the hole: end sooner
            elif lo <= a < hi < b:
                a = hi                        # starts inside it: begin later
            elif a < lo and hi < b:
                # the line spans the whole hole: keep the longer half
                if lo - a >= b - hi:
                    b = lo
                else:
                    a = hi
        if abs(a - ln.start) < 0.01 and abs(b - ln.end) < 0.01:
            continue
        if b - a < 0.2:
            continue                          # nothing usable would be left
        _spread(ln.words, a, b)
        ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        fixed += 1
    if fixed:
        log(tr(f"  lines trimmed back out of the wordless stretches: {fixed}",
               f"  строк подрезано по краям пустот: {fixed}"))
    return fixed


def enforce_marks(lyrics: Lyrics, skip, duration: float, log: Log = _noop) -> int:
    """No words on a marked stretch — as a guarantee, not an intention.

    The gentler passes move and trim where there is room. When there is none —
    the aligner crowded the following lines right against the hole — a run used
    to be left inside it, with a note in the log. But the marks are the
    person's own words about their song. A line squeezed in tight beside the
    hole is a visible flaw in the right place; a line lying over a vocalise is
    the one thing they explicitly said must not happen.
    """
    marks = spans(skip, duration)
    if not marks:
        return 0
    lines = lyrics.lines

    def hit(ln):
        if ln.start is None or ln.end is None or not ln.words:
            return None
        if ln.keep:
            return None       # the original's own line may stand in the hole
        for a, b in marks:
            if min(ln.end, b) - max(ln.start, a) > 0.05:
                return (a, b)
        return None

    moved, cramped = 0, []
    i = 0
    while i < len(lines):
        h = hit(lines[i])
        if not h:
            i += 1
            continue
        j = i
        lo_h, hi_h = h
        while j + 1 < len(lines):
            h2 = hit(lines[j + 1])
            if not h2:
                break
            lo_h, hi_h = min(lo_h, h2[0]), max(hi_h, h2[1])
            j += 1
        run = lines[i:j + 1]
        prv = lines[i - 1].end if i and lines[i - 1].end is not None else 0.0
        nxt = lines[j + 1].start if j + 1 < len(lines) and \
            lines[j + 1].start is not None else duration
        total = sum(_syl(ln) for ln in run) or 1
        need = total * _MIN_PER_SYLLABLE
        # singing between the neighbours, holes taken out; nearest the following
        # line with room to breathe, else simply the widest there is
        wins = _voiced_windows(min(prv, lo_h), max(nxt, hi_h),
                               [{"start": a, "end": b} for a, b in marks])
        wins = [w for w in wins if w[1] > prv and w[0] < max(nxt, hi_h)]
        pick = None
        for w in reversed(wins):
            if w[1] - w[0] >= need + 0.05:
                pick = w
                break
        if not pick and wins:
            pick = max(wins, key=lambda w: w[1] - w[0])
        if not pick or pick[1] - pick[0] < 0.2:
            # no singing anywhere between the neighbours: right against the
            # hole then, cramped, and said out loud
            pick = [hi_h, hi_h + max(0.3, 0.12 * sum(len(ln.words) for ln in run))]
            cramped.append((i, j, hi_h))
        span = min(pick[1] - pick[0], max(_SUNG_PER_SYLLABLE * total, need))
        base = (pick[1] - span) if j + 1 < len(lines) else pick[0]
        acc = 0.0
        for ln in run:
            t0 = base + span * acc / total
            acc += _syl(ln)
            t1 = base + span * acc / total
            _spread(ln.words, t0, max(t1 - 0.05, t0 + 0.05))
            ln.start, ln.end = ln.words[0].start, ln.words[-1].end
            moved += 1
        i = j + 1
    if moved:
        log(tr(f"  lines forced off the marked stretches: {moved}",
               f"  строк принудительно убрано с отмеченных пустот: {moved}"))
    for a, b, at in cramped:
        log(tr(f"  NOTE: lines {a + 1}–{b + 1} had nowhere to go and are squeezed in "
               f"right after the mark at {mmss(at)} — cramped on purpose: better a "
               f"tight line in the right place than words over the stretch you "
               f"marked. Spread them out by hand.",
               f"  ВНИМАНИЕ: строкам {a + 1}–{b + 1} некуда было встать, они прижаты "
               f"сразу после отметки на {mmss(at)} — тесно нарочно: лучше тесная "
               f"строка в правильном месте, чем слова поверх куска, который вы "
               f"отметили. Растащите их руками."))
    return moved


def place_backing(lyrics: Lyrics, duration: float, log: Log = _noop,
                  indices=None) -> int:
    """Put the backing lines where backing is sung: with their lead, not after.

    The aligner is linear — it looks for the na-na-na BETWEEN the lead lines,
    while the record sings it OVER them, so the model has nothing to hold on to
    and scatters them. The lead comes out right for the same reason. So the
    backing is placed by rule instead: a tail split off a lead line lies over
    that line — a duet; a standalone backing line takes the gap after its lead,
    at a sung pace. Both are one drag away from anywhere better.
    """
    lines = lyrics.lines
    placed = 0
    for i, ln in enumerate(lines):
        if indices is not None and i not in indices:
            continue
        if not ln.backing or not ln.words:
            continue
        j = i - 1
        while j >= 0 and (lines[j].backing or lines[j].start is None):
            j -= 1
        if j < 0:
            continue                      # nothing to lean on: leave the model's guess
        lead = lines[j]
        k = i + 1
        while k < len(lines) and (lines[k].backing or lines[k].start is None):
            k += 1
        nxt = lines[k].start if k < len(lines) else duration
        if ln.tail:
            # Without recognition a bracketed tail is only an approximation,
            # not evidence that one syllable lasts as long as the whole lead.
            want = min(1.2, max(0.3, ln.syllables * 0.22))
            if nxt - lead.end >= 0.25:
                t0, t1 = lead.end, min(nxt, lead.end + want)
            else:
                t1 = min(nxt, lead.end)
                t0 = max(lead.start, t1 - want)
        else:
            t0 = lead.end
            room = max(nxt - t0, 0.0)
            want = min(1.2, max(0.3, ln.syllables * 0.22))
            if room >= 0.25:
                t1 = t0 + min(room, want)
            else:
                t1 = min(nxt, lead.end)
                t0 = max(lead.start, t1 - want)
        _spread(ln.words, t0, max(t1 - 0.05, t0 + 0.3))
        ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        placed += 1
    if placed:
        log(tr(f"  backing lines placed with their leads: {placed}",
               f"  бэк-строк поставлено к своим основным: {placed}"))
    return placed


def repair_ragged(lyrics: Lyrics, log: Log = _noop) -> int:
    """Re-lay the words of a line whose insides the model tore up.

    On a fast, dense vocal the model often places the LINE well and mangles
    the words in it: one word swallows two seconds, three others get nothing,
    a couple land out of order. Fixing that by hand, line after line, is the
    work a person gave this program to do. Where the insides are plainly
    torn — a word with no time at all, a word out of order, or one hogging
    the line — the words are re-laid by syllables inside the line's own span.
    The edges do not move; a line whose words look sane is not touched.
    """
    fixed = 0
    for ln in lyrics.lines:
        ws = ln.words
        if len(ws) < 2 or ln.start is None or ln.end is None:
            continue
        if any(w.start is None or w.end is None for w in ws):
            continue
        span = ln.end - ln.start
        if span <= 0.2:
            continue
        durs = sorted(max((w.end or 0) - (w.start or 0), 0.0) for w in ws)
        med = durs[len(durs) // 2]
        torn = (
            # a word left with no time of its own
            any((w.end - w.start) < 0.03 for w in ws)
            # words out of order
            or any(a.start > b.start + 0.01 for a, b in zip(ws, ws[1:]))
            # one word hogging the line while the others are starved to
            # slivers no one could sing. A held note is NOT this: there the
            # long word is long and its neighbours still breathe.
            or (med < 0.15 and durs[-1] > max(5 * med, 0.4 * span)
                and durs[-1] > 1.5)
        )
        if not torn:
            continue
        _spread(ws, ln.start, ln.end)
        fixed += 1
    if fixed:
        log(tr(f"  lines whose words the model tore up, re-laid by syllables: {fixed}",
               f"  строк с рваными словами переложено по слогам: {fixed}"))
    return fixed


def repair_order(lyrics: Lyrics, log: Log = _noop) -> int:
    """Pull overlapping lines apart: a line must not end past the start of the
    next one, or the highlight jumps around."""
    fixed = conflicts = 0
    lines = [ln for ln in lyrics.lines
             if ln.words and ln.start is not None and ln.end is not None]
    for a, b in zip(lines, lines[1:]):
        # Two voices singing at once is a duet, not a defect: the na-na-na
        # behind a lead line is MEANT to overlap it. Only lines of the same
        # voice may not lie on each other.
        if (a.voice or 1) != (b.voice or 1):
            continue
        if b.start < a.start:
            conflicts += 1        # lines are out of order — trimming makes no sense
            continue
        if a.end <= b.start:
            continue
        last_word_end = a.words[-1].end if a.words else a.start
        new_end = b.start - 0.05
        overlap = a.end - b.start
        # A few tens of milliseconds are usually rounding at a phrase edge,
        # not two voices. Trimming that sliver from the last word is inaudible
        # and keeps the editor from rendering two same-voice clips on top of
        # each other.
        if 0.0 < overlap <= 0.2 and a.words:
            last = a.words[-1]
            if new_end > (last.start or 0.0) + 0.04:
                last.end = new_end
                a.end = new_end
                fixed += 1
                continue
        # trim only when it will not cut through words: never maim the timing
        if new_end >= max(a.start + 0.2, last_word_end):
            a.end = new_end
            fixed += 1
        else:
            conflicts += 1
    if fixed:
        log(tr(f"  overlapping lines pulled apart: {fixed}",
               f"  развёл наложившиеся строки: {fixed}"))
    if conflicts:
        log(tr(f"  NOTE: {conflicts} lines clash with their neighbours in time — "
               f"check them in the player, the timing there is unreliable",
               f"  ВНИМАНИЕ: {conflicts} строк конфликтуют с соседями по времени — "
               f"проверьте их в плеере, там разметка ненадёжна"))
    return fixed


def _fill_lines(lyrics: Lyrics, duration: float, min_word: float = 0.12) -> None:
    """Line bounds from the words, plus a sanity pass over the timings."""
    prev_end = 0.0
    for w in lyrics.words:
        if w.start is None:
            w.start = prev_end
        if w.end is None or w.end <= w.start:
            w.end = w.start + max(min_word, 0.16 * w.syllables)
        # Keep the word inside the track. Order matters: first clamp the start
        # so there is room for the minimum length, and only then the end —
        # otherwise stretching to min_word runs past the end of the song.
        w.start = min(max(w.start, 0.0), max(duration - min_word, 0.0))
        w.end = min(max(w.end, w.start + min_word), duration)
        if w.end <= w.start:
            w.end = min(w.start + min_word, duration)
        prev_end = w.end

    # A short word the aligner collapsed onto its neighbour: “A” and
    # “chilling” starting at the same instant. The article was sung just
    # before — give it that sliver back, walking backwards so a chain of
    # squeezed words unfolds one after another. Grabbing a word that occupies
    # no time is impossible in any editor.
    for ln in lyrics.lines:
        ws = ln.words
        for k in range(len(ws) - 1, 0, -1):
            w, nxt = ws[k - 1], ws[k]
            if w.start is not None and nxt.start is not None \
                    and nxt.start - w.start < 0.05:
                w.start = max(0.0, nxt.start - max(min_word, 0.07 * w.syllables))
                w.end = max(nxt.start, w.start + 0.02)

    for ln in lyrics.lines:
        if not ln.words:
            continue
        ln.start = ln.words[0].start
        ln.end = ln.words[-1].end


def align_anchored(lyrics: Lyrics, audio_path: str, duration: float,
                   model_name: str = "medium", language: str = "ru",
                   device: Optional[str] = None, log: Log = _noop,
                   isolated: bool = False, skip=None) -> Lyrics:
    """Align a song whose text carries a few times of its own.

    “[2:27] Remember this day” in the lyrics file fixes that line at 2:27 and
    also acts as a peg. The song is aligned between pegs:
    each stretch of text is shown only the audio between its own two, so a line
    cannot wander into a vocalise three minutes away, which is the one thing
    the model does that no repair can undo.

    A line with no peg is timed as always, inside the stretch it belongs to.
    """
    try:
        import stable_whisper
        have_whisper = True
    except ImportError:
        have_whisper = False

    pegs = []
    for i, ln in enumerate(lyrics.lines):
        if ln.start is None:
            continue
        if pegs and ln.start <= pegs[-1][1]:
            # Later in the text, earlier in the song: one of the two is wrong,
            # and a window that runs backwards would swallow the song whole.
            log(tr(f"  line {i + 1} is pegged at {mmss(ln.start)}, before the peg "
                   f"above it — ignoring this one",
                   f"  строка {i + 1} привязана к {mmss(ln.start)} — раньше, чем "
                   f"привязка выше; эту пропускаю"))
            ln.start = None
            continue
        pegs.append((i, ln.start))
    if not pegs:
        return align_whisper(lyrics, audio_path, duration, model_name, language,
                             device, log, isolated=isolated, skip=skip)

    from . import models as M
    log(tr(f"The text carries {len(pegs)} times of its own — aligning between them",
           f"В тексте {len(pegs)} собственных времён — размечаю между ними"))
    model = None
    if have_whisper:
        log(M.load_note(model_name))
        model = stable_whisper.load_model(model_name, device=device)
    else:
        log(tr("  stable-ts is not installed — each stretch is laid out by loudness, "
               "but still inside its own pegs",
               "  stable-ts не установлен — каждый кусок разложу по громкости, "
               "но в пределах своих привязок"))

    # A peg opens a stretch; the one before the first peg is a stretch too.
    bounds = []
    if pegs[0][0] > 0:
        bounds.append((0, pegs[0][0] - 1, 0.0, pegs[0][1]))
    for k, (i, t) in enumerate(pegs):
        last = (pegs[k + 1][0] - 1) if k + 1 < len(pegs) else len(lyrics.lines) - 1
        end = pegs[k + 1][1] if k + 1 < len(pegs) else duration
        bounds.append((i, last, t, end))

    out: List = []
    for a, b, t0, t1 in bounds:
        piece = Lyrics(lines=lyrics.lines[a:b + 1])
        for ln in piece.lines:
            ln.start = ln.end = None
            for w in ln.words:
                w.start = w.end = None
        # Let Whisper hear a short lead-in so it can recognise a clipped first
        # syllable and recover useful rhythm inside the line. The explicit
        # start itself is restored below; the following peg closes the stretch,
        # so neither the fixed line nor its neighbours can drift through the
        # song. Loudness fallback starts at the peg because there are no
        # recognised words whose rhythm could benefit from the overlap.
        hear_from = max(0.0, t0 - 1.5) if have_whisper else t0
        if have_whisper and out and out[-1].end is not None:
            # Do not mistake the tail of the preceding, already recognised
            # line for the beginning of this one. A tiny overlap remains for
            # natural legato and genuinely simultaneous syllables.
            hear_from = max(hear_from, out[-1].end - 0.12)
        outside = ([(0.0, hear_from)] if hear_from > 0.05 else []) + \
                  ([(t1, duration)] if t1 < duration - 0.05 else [])
        holes = spans((skip or []) + outside, duration)
        log(tr(f"  lines {a + 1}–{b + 1}, between {mmss(t0)} and {mmss(t1)}",
               f"  строки {a + 1}–{b + 1}, между {mmss(t0)} и {mmss(t1)}"))
        try:
            if not have_whisper:
                raise RuntimeError("no stable-ts")
            align_whisper(piece, audio_path, duration, model_name, language,
                          device, log, isolated=isolated, skip=holes, model=model)
        except Exception as e:
            log(tr(f"  this stretch would not align ({e}) — spread by loudness instead",
                   f"  этот кусок не разметился ({e}) — раскладываю по громкости"))
            align_energy(piece, audio_path, duration, log, skip=holes)
        out.extend(piece.lines)

    lyrics.lines = out
    lyrics.has_manual_times = False
    _fill_lines(lyrics, duration)
    repair_order(lyrics, log=log)
    repair_ragged(lyrics, log=log)
    # Whisper may use a short lead-in to understand a phrase, but a time the
    # person supplied is not merely a search hint. Restore every explicit line
    # boundary after the general repairs; unmarked lines retain their inferred
    # word rhythm between these anchors.
    fixed_indices = {i for i, _ in pegs}
    for i, fixed in pegs:
        limit = next((ln.start for ln in lyrics.lines[i + 1:]
                      if ln.start is not None and not ln.backing), duration)
        _pin_one_line_start(lyrics.lines[i], fixed, limit, duration)
    place_backing(lyrics, duration, log,
                  indices={i for i, ln in enumerate(lyrics.lines)
                           if ln.tail and i not in fixed_indices})
    lyrics.fixed_line_indices = fixed_indices
    return lyrics


def align(lyrics: Lyrics, audio_path: str, duration: float, engine: str = "auto",
          model_name: str = "medium", language: str = "ru",
          device: Optional[str] = None, log: Log = _noop,
          isolated: bool = False, skip=None) -> tuple:
    lyrics, used = _align_main(lyrics, audio_path, duration, engine, model_name,
                               language, device, log, isolated=isolated, skip=skip)
    if used == "whisper" and any(ln.backing for ln in lyrics.lines):
        align_backing_audio(lyrics, audio_path, duration, model_name, device, log,
                            skip=skip)
    return lyrics, used


def align_backing_audio(lyrics, audio_path, duration, model_name, device=None,
                        log=_noop, skip=None):
    """Align each backing independently in a short window around its lead."""
    from copy import deepcopy
    from . import audio as AU, lang as LG
    backs = [(i, ln) for i, ln in enumerate(lyrics.lines)
             if ln.backing and ln.words and not ln.lock]
    if not backs:
        return
    # Guessed placement must remain visibly uncertain if recognition fails.
    for _, ln in backs:
        for word in ln.words:
            word.prob = 0.0
    try:
        import numpy as np
        import stable_whisper
        pcm = AU.read_pcm_mono(audio_path, 16000)
        audio = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
        model = stable_whisper.load_model(model_name, device=device)
    except Exception as exc:
        log(tr(f"Backing vocals need manual checking: {exc}",
               f"Бэки нужно проверить вручную: {exc}"))
        return
    holes = spans(skip, duration)
    for count, (i, ln) in enumerate(backs, 1):
        lead = next((x for x in reversed(lyrics.lines[:i])
                     if not x.backing and x.start is not None), None)
        following = next((x for x in lyrics.lines[i + 1:]
                          if not x.backing and x.start is not None), None)
        lo = max(0.0, (lead.start if lead else ln.start or 0.0) - 0.2)
        hi = min(duration, following.start if following else lo + 8.0, lo + 12.0)
        # Do not stitch across wordless spans: absolute offsets stay exact.
        windows = keep_windows(holes, duration) if holes else [(0.0, duration)]
        windows = [(max(lo, a), min(hi, b)) for a, b in windows
                   if min(hi, b) - max(lo, a) >= 0.15]
        # One search per continuous audio window. Retrying a narrower gap
        # doubled inference for weak ad-libs without improving recognition.
        best = None
        log(tr(f"Backing vocals {count}/{len(backs)}: {ln.text}",
               f"Бэк {count}/{len(backs)}: {ln.text}"))
        for a, b in windows:
            try:
                result = model.align(audio[int(a * 16000):int(b * 16000)],
                                     ln.text.strip("() "), language=LG.detect(ln.text),
                                     original_split=True, verbose=False, fast_mode=True)
                rec = [(normalize_token(w.word), float(w.start) + a,
                        float(w.end) + a, getattr(w, "probability", None))
                       for seg in (result.segments if result else [])
                       for w in (seg.words or []) if normalize_token(w.word)]
                words = deepcopy(ln.words)
                for word in words:
                    word.start = word.end = word.prob = None
                matched = _apply_recognized(words, rec) if rec else 0
                if matched < 0.99 or any(w.start is None or w.end is None
                                        or w.prob is None for w in words):
                    continue
                confidence = sum(w.prob for w in words) / len(words)
                length = words[-1].end - words[0].start
                if (confidence < 0.45 or min(w.prob for w in words) < 0.1
                        or not 0.12 <= length <= max(1.2, ln.syllables * 0.5)
                        or any(w.end <= w.start or w.start < a or w.end > b
                               for w in words)
                        or any(x.end > y.start + 0.05 for x, y in zip(words, words[1:]))):
                    continue
                if best is None or confidence > best[0]:
                    best = confidence, words
                break
            except Exception as exc:
                log(tr(f"Backing recognition failed: {exc}",
                       f"Не удалось распознать бэк: {exc}"))
        if best:
            ln.words = best[1]
            ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        else:
            # Always bound an unrecognised ad-lib, including dense verses
            # with no gap. Otherwise the old whole-lead guess survives.
            if windows:
                a, b = windows[-1]
                end = min(b, lead.end) if lead and lead.end is not None else b
                start = max(a, end - min(1.2, max(0.3, ln.syllables * 0.22)))
                if end > start:
                    _spread(ln.words, start, end)
                    ln.start, ln.end = start, end
            if lead and lead.end is not None and hi - lead.end >= 0.25:
                # Even an uncertain fallback need not stretch across the
                # lead when there is a real, bounded gap after it.
                gap = next(((max(lead.end, a), b) for a, b in windows
                            if b - max(lead.end, a) >= 0.25), None)
                if gap:
                    a, b = gap
                    b = min(b, a + max(0.4, ln.syllables * 0.22))
                    _spread(ln.words, a, b)
                    ln.start, ln.end = a, b
            log(tr("Backing timing is approximate — check it in the editor.",
                   "Время бэка приблизительное — проверьте его в редакторе."))


def _align_main(lyrics: Lyrics, audio_path: str, duration: float, engine: str = "auto",
          model_name: str = "medium", language: str = "ru",
          device: Optional[str] = None, log: Log = _noop,
          isolated: bool = False, skip=None) -> tuple:
    """Returns (lyrics, engine_used)."""
    timed = sum(1 for ln in lyrics.lines if ln.start is not None)
    # A tail split from a timed LRC line has no independent timestamp.
    # It must not turn an otherwise complete LRC into dozens of anchored
    # Whisper jobs. Align the timed lines together, then attach these backs
    # to the final lead bounds.
    untimed_backs = {i for i, ln in enumerate(lyrics.lines)
                     if ln.backing and ln.start is None}
    if (lyrics.has_manual_times and timed and untimed_backs
            and timed + len(untimed_backs) == len(lyrics.lines)):
        original = lyrics.lines
        kept_indices = [i for i in range(len(original)) if i not in untimed_backs]
        from copy import copy
        lead = copy(lyrics)
        lead.lines = [original[i] for i in kept_indices]
        lead, used = align(lead, audio_path, duration, engine, model_name,
                           language, device, log, isolated=isolated, skip=skip)
        for i, ln in zip(kept_indices, lead.lines):
            original[i] = ln
        lyrics.lines = original
        lyrics.fixed_line_starts = lead.fixed_line_starts
        lyrics.fixed_line_indices = {kept_indices[i]
                                    for i in lead.fixed_line_indices}
        place_backing(lyrics, duration, log, indices=untimed_backs)
        return lyrics, used
    if lyrics.has_manual_times and timed == len(lyrics.lines):
        # A synced library knows the exact beginning of every line, but not
        # the words inside it. Keep those line starts immutable and let
        # Whisper improve only the word rhythm. “energy” remains the explicit
        # no-neural-net choice, and missing/broken Whisper falls back safely.
        starts = [float(ln.start) for ln in lyrics.lines]
        if engine in ("auto", "whisper"):
            try:
                import stable_whisper  # noqa: F401
                align_whisper(lyrics, audio_path, duration, model_name,
                              language, device, log, isolated=isolated,
                              skip=skip)
                starts = _refine_ready_starts(lyrics, starts, log)
                _pin_line_starts(lyrics, starts, duration)
                lyrics.fixed_line_starts = True
                return lyrics, "whisper"
            except Exception as e:
                if engine == "whisper":
                    raise
                log(tr(f"Whisper could not lay out the words inside the timed "
                       f"lines ({e}) — spreading them by syllable instead.",
                       f"Whisper не смог разложить слова внутри готовых строк "
                       f"({e}) — распределяю их по слогам."))
        else:
            log(tr("The text already has [mm:ss.dd] line timings.",
                   "В тексте уже есть тайминги строк [мм:сс.дд]."))
        for ln, start in zip(lyrics.lines, starts):
            ln.start, ln.end = start, None
        _spread_manual(lyrics, duration)
        return lyrics, "manual"
    if lyrics.has_manual_times and engine in ("auto", "whisper"):
        # Some lines carry a time and some do not: those are pegs, not a
        # timing. align_anchored copes without stable-ts too — each stretch is
        # laid out by loudness, still inside its own pegs — so the import must
        # not stand between the pegs and their meaning.
        try:
            import stable_whisper  # noqa: F401
            label = "whisper"
        except ImportError:
            label = "energy"
        return align_anchored(lyrics, audio_path, duration, model_name, language,
                              device, log, isolated=isolated, skip=skip), label

    if engine in ("auto", "whisper"):
        try:
            import stable_whisper  # noqa: F401
        except ImportError:
            if engine == "whisper":
                raise SystemExit(tr(
                    "The whisper engine needs dependencies:\n"
                    "    pip install stable-ts\n"
                    "Or run with --align energy (no neural nets).",
                    "Движок whisper требует зависимостей:\n"
                    "    pip install stable-ts\n"
                    "Либо запустите с --align energy (без нейросетей)."))
            log(tr("stable-ts is not installed → using the loudness engine "
                   "(`pip install stable-ts` makes it more accurate).",
                   "stable-ts не установлен → использую энергетический движок "
                   "(точнее будет с `pip install stable-ts`)."))
            engine = "energy"
        else:
            try:
                return align_whisper(lyrics, audio_path, duration, model_name,
                                     language, device, log, isolated=isolated,
                                     skip=skip), "whisper"
            except Exception as e:
                if engine == "whisper":
                    raise
                log(tr(f"Whisper could not cope ({e}) → falling back to the loudness engine.",
                       f"Whisper не справился ({e}) → откатываюсь на энергетический движок."))
                engine = "energy"

    if engine == "none":
        _fill_lines(lyrics, duration)
        return lyrics, "none"

    return align_energy(lyrics, audio_path, duration, log, skip=skip), "energy"


def _spread_manual(lyrics: Lyrics, duration: float) -> None:
    """Line starts are known — spread the words inside each line by syllable."""
    lines = lyrics.lines
    for i, ln in enumerate(lines):
        start = ln.start if ln.start is not None else (lines[i - 1].end if i else 0.0)
        end = ln.end
        if end is None:
            nxt = lines[i + 1].start if i + 1 < len(lines) else None
            end = min(nxt, duration) if nxt else min(start + 0.45 * ln.syllables, duration)
        ln.start, ln.end = start, end
        total = ln.syllables
        acc = 0.0
        for w in ln.words:
            w.start = start + (end - start) * acc / total
            acc += w.syllables
            w.end = start + (end - start) * acc / total
    _fill_lines(lyrics, duration)


def _pin_line_starts(lyrics: Lyrics, starts: List[float], duration: float) -> None:
    """Keep ready LRC line starts while retaining Whisper's word rhythm.

    Whisper may place the whole phrase a little before or after the library's
    stamp. Translate its word timings to the fixed start; if that would cross
    the next fixed line, close false pauses and shorten held tails before using
    whole-phrase compression.
    Thus ``line.start`` and the first ``word.start`` can never disagree.
    """
    for i, (ln, fixed) in enumerate(zip(lyrics.lines, starts)):
        limit = next((starts[j] for j in range(i + 1, len(starts))
                      if not lyrics.lines[j].backing), duration)
        _pin_one_line_start(ln, fixed, limit, duration)
    lyrics.fixed_line_indices = set(range(min(len(lyrics.lines), len(starts))))


def _refine_ready_starts(lyrics: Lyrics, starts: List[float],
                         log: Log = _noop) -> List[float]:
    """Correct small, credible LRC offsets without trusting Whisper jumps.

    Synced libraries are commonly late by a few hundred milliseconds, while a
    repeated verse can make forced alignment miss by seconds. One confident
    first word may adjust its line by 80--450 ms; a larger block shift up to two
    seconds needs three nearby confident lines to agree. Less certain lines may
    inherit that local consensus. Sparse/manual pegs do not use this function.
    """
    if len(starts) != len(lyrics.lines):
        return starts
    observed: List[Optional[float]] = [None] * len(starts)
    offsets: List[Optional[float]] = [None] * len(starts)
    may_inherit = [True] * len(starts)
    for i, (ln, fixed) in enumerate(zip(lyrics.lines, starts)):
        if not ln.words or ln.words[0].start is None:
            continue
        prob = ln.words[0].prob
        delta = float(ln.words[0].start) - float(fixed)
        if prob is not None and prob >= 0.55:
            may_inherit[i] = False
            if abs(delta) <= 2.0:
                observed[i] = delta
            if 0.08 <= abs(delta) <= 0.45:
                offsets[i] = delta

    refined = list(map(float, starts))
    changed = 0
    for i, fixed in enumerate(starts):
        correction = offsets[i]
        # A whole verse can be shifted in an otherwise useful LRC. Three
        # nearby confident onsets agreeing within 180 ms are strong evidence
        # of a block offset, even when it is larger than the safe per-line
        # limit. A lone one-second jump still looks like a repeated phrase and
        # remains blocked.
        nearby_observed = [(j, observed[j]) for j in range(max(0, i - 3),
                                                           min(len(starts), i + 4))
                           if observed[j] is not None and abs(observed[j]) >= 0.08]
        clusters = []
        for _, centre in nearby_observed:
            cluster = [(j, x) for j, x in nearby_observed if abs(x - centre) <= 0.18]
            if len(cluster) >= 3:
                clusters.append(cluster)
        if clusters:
            cluster = max(clusters, key=lambda c: (len(c), -max(x for _, x in c)
                                                    + min(x for _, x in c)))
            own = observed[i]
            # A confident line which contradicts the neighbours is an anchor,
            # not a hole to smear the block correction through.
            if own is None or any(j == i for j, _ in cluster):
                vals = sorted(x for _, x in cluster)
                correction = vals[len(vals) // 2]
        if correction is None and may_inherit[i]:
            nearby = [offsets[j] for j in range(max(0, i - 2),
                                                 min(len(starts), i + 3))
                      if offsets[j] is not None]
            if len(nearby) >= 2 and all(x * nearby[0] > 0 for x in nearby):
                ordered = sorted(nearby)
                median = ordered[len(ordered) // 2]
                if max(nearby) - min(nearby) <= 0.18:
                    correction = median
        if correction is None:
            continue
        candidate = float(fixed) + correction
        lower = refined[i - 1] + 0.02 if i else 0.0
        upper = float(starts[i + 1]) - 0.02 if i + 1 < len(starts) else candidate
        candidate = max(lower, min(candidate, upper))
        if abs(candidate - float(fixed)) >= 0.04:
            refined[i] = candidate
            changed += 1
    if changed:
        log(tr(f"  ready line starts refined from confident vocals: {changed}",
               f"  начал строк из готовой разметки уточнено по уверенному вокалу: {changed}"))
    return refined


def _pin_one_line_start(ln, fixed: float, limit: float, duration: float) -> None:
    """Translate one line's recognised word rhythm onto an explicit start."""
    fixed = max(0.0, min(float(fixed), duration))
    limit = max(fixed + 0.02, min(float(limit), duration))
    words = ln.words
    valid = (words and words[0].start is not None
             and words[-1].end is not None
             and words[-1].end > words[0].start)
    if not valid:
        ln.start, ln.end = fixed, limit
        _spread(words, fixed, limit)
        return
    raw_start, raw_end = words[0].start, words[-1].end
    shifted_end = fixed + (raw_end - raw_start)
    for word in words:
        word.start = fixed + (word.start - raw_start)
        word.end = fixed + (word.end - raw_start)

    overflow = shifted_end - limit
    if overflow > 1e-6:
        # A neighbouring LRC mark can be a little too early.  Scaling the whole
        # phrase used to make every syllable unnaturally fast.  Preserve the
        # recognised onsets for as long as possible: consume pauses first, then
        # shorten held word tails from right to left.  Uniform compression is a
        # last resort only for genuinely impossible intervals.
        overflow = _close_word_gaps(words, overflow)
        overflow = _shorten_word_tails(words, overflow)
        if overflow > 1e-6:
            span = max(words[-1].end - fixed, 1e-6)
            scale = max(0.01, (span - overflow) / span)
            for word in words:
                word.start = fixed + (word.start - fixed) * scale
                word.end = fixed + (word.end - fixed) * scale

    for word in words:
        word.start = min(max(word.start, fixed), limit)
        word.end = min(max(word.end, word.start + 0.01), limit)
    words[0].start = fixed
    ln.start = fixed
    ln.end = min(max(words[-1].end, fixed + 0.02), limit)


def _close_word_gaps(words: List[Word], overflow: float) -> float:
    """Remove silence between words, starting at the end of the phrase."""
    for i in range(len(words) - 2, -1, -1):
        gap = max(0.0, words[i + 1].start - words[i].end)
        take = min(gap, overflow)
        if take <= 0:
            continue
        for later in words[i + 1:]:
            later.start -= take
            later.end -= take
        overflow -= take
        if overflow <= 1e-6:
            break
    return max(0.0, overflow)


def _shorten_word_tails(words: List[Word], overflow: float) -> float:
    """Fit a tight LRC interval without speeding up the whole phrase."""
    for i in range(len(words) - 1, -1, -1):
        duration = max(0.0, words[i].end - words[i].start)
        # Keep a readable syllable onset. Long held vowels can surrender more
        # time than short consonants; no word is collapsed below 80 ms.
        floor = min(duration, max(0.08, duration * 0.35))
        take = min(max(0.0, duration - floor), overflow)
        if take <= 0:
            continue
        words[i].end -= take
        for later in words[i + 1:]:
            later.start -= take
            later.end -= take
        overflow -= take
        if overflow <= 1e-6:
            break
    return max(0.0, overflow)
