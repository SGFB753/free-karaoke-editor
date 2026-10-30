"""Optional Qwen forced alignment: ready lyrics in, word timings out.

Qwen does not return Whisper probabilities. Independent recovery retains its
own measured confidence and never supplies invented Qwen confidence. Long songs
use bounded search windows, never an oversized model input.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import unicodedata
from copy import deepcopy

from .i18n import tr
from . import models as M

LANGUAGES = {"ru": "Russian", "en": "English", "de": "German", "fr": "French",
             "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ja": "Japanese",
             "ko": "Korean", "zh": "Chinese", "yue": "Cantonese"}
MAX_SECONDS = 300.0
BLOCK_SECONDS = 45.0
BLOCK_LINES = 16


class RecoveryUnavailable(ValueError):
    """Optional Whisper code/weights could not be loaded, not bad Qwen input."""


def unplaced_warning(whisper_review=True):
    if not whisper_review:
        return tr("Qwen could not place these lyrics. Whisper review is disabled; the project and untimed text are saved for manual editing.",
                  "Qwen не смог привязать эти строки. Перепроверка Whisper отключена; проект и текст без таймингов сохранены для ручной правки.")
    return tr("Qwen could not place these lyrics and optional Whisper recovery is unavailable. The project and text are preserved for manual timing; no timing was invented.",
              "Qwen не смог привязать эти строки, а резервная проверка Whisper недоступна. Проект и текст сохранены для ручной разметки; выдуманные тайминги не добавлялись.")


def prepare_import():
    """DyNet's Japanese tokenizer uses ANSI file paths on Windows.

    Import nagisa through an existing 8.3 alias when the venv path contains
    Cyrillic. Neither dependencies nor the user's project are rewritten.
    """
    if os.name != "nt" or "nagisa" in sys.modules:
        return
    spec = importlib.util.find_spec("nagisa")
    if spec is None or not spec.origin or spec.origin.isascii():
        return
    import ctypes
    folder = os.path.dirname(spec.origin)
    short = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(folder, short, len(short)) or not short.value.isascii():
        raise RuntimeError(tr("Qwen's nagisa dependency needs an ASCII installation path on this Windows system.",
                              "Зависимости nagisa для Qwen нужен путь установки без кириллицы на этой Windows."))
    alias = importlib.util.spec_from_file_location(
        "nagisa", os.path.join(short.value, "__init__.py"), submodule_search_locations=[short.value])
    module = importlib.util.module_from_spec(alias)
    sys.modules["nagisa"] = module
    try:
        alias.loader.exec_module(module)
    except Exception:
        sys.modules.pop("nagisa", None)
        raise


def available() -> bool:
    return importlib.util.find_spec("qwen_asr") is not None


def _key(text):
    return "".join(c for c in unicodedata.normalize("NFKC", str(text)).casefold().replace("ё", "е")
                   if unicodedata.category(c)[0] in "LN")


def assign_words(words, items, offset, whole, limit, whole_end=None, timestamp_step=None,
                 repaired=None, probabilities=None):
    """Match by ordered characters, including hyphens and CJK token splitting.

    The supplied lyrics must survive unchanged. A tokenizer mismatch is an
    explicit error, not an excuse to evenly spread a whole verse.
    """
    rec, at = [], 0
    for item_index, item in enumerate(items):
        key = _key(item.text)
        if not key:
            continue
        a, b = float(item.start_time), float(item.end_time)
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a <= b <= limit + 0.1):
            raise ValueError(tr("Qwen returned invalid word timestamps.",
                                "Qwen вернул некорректные тайминги слов."))
        end_map = whole_end or whole
        # The official wrapper interpolates invalid timestamp runs. Off-grid
        # values reveal such synthetic times; they are not measured onsets.
        inferred = bool((repaired is not None and repaired[item_index]) or timestamp_step and any(
            abs(t - round(t / timestamp_step) * timestamp_step) > .0015 for t in (a, b)))
        prob = probabilities[item_index] if probabilities is not None else None
        rec.append((at, at + len(key), key, whole(offset + a), end_map(offset + min(b, limit)), inferred, prob))
        at += len(key)
    if not rec or "".join(_key(w.text) for w in words) != "".join(r[2] for r in rec):
        raise ValueError(tr("Qwen's tokens could not be matched to the supplied lyrics.",
                            "Не удалось сопоставить слова Qwen с загруженным текстом."))
    at, cursor = 0, 0
    for word in words:
        length = len(_key(word.text))
        if not length:
            word.start = word.end = rec[max(cursor - 1, 0)][4]
            word.qwen_interpolated = False
            word.prob = None
        else:
            while cursor < len(rec) - 1 and rec[cursor][1] <= at:
                cursor += 1
            last = cursor
            while last < len(rec) - 1 and rec[last][1] < at + length:
                last += 1
            word.start, word.end = rec[cursor][3], rec[last][4]
            word.qwen_interpolated = any(r[5] for r in rec[cursor:last + 1])
            probs = [r[6] for r in rec[cursor:last + 1] if r[6] is not None]
            word.prob = min(probs) if probs else None
        at += length


def _model_alignment(model, **kwargs):
    """Observe the wrapper's repairs, including replacements back on its grid.

    The hook belongs to this inference's model instance and is always restored.
    It observes output only; it does not change model predictions or its repair.
    """
    processor = getattr(model, 'aligner_processor', None)
    original = getattr(processor, 'fix_timestamp', None)
    if original is None:
        return model.align(**kwargs)[0], None
    changes = []

    def capture(raw):
        fixed = original(raw)
        changes.append([abs(float(a) - float(b)) > .5 for a, b in zip(raw, fixed)])
        return fixed

    processor.fix_timestamp = capture
    try:
        items = model.align(**kwargs)[0]
    finally:
        processor.fix_timestamp = original
    flags = None
    if len(changes) == 1 and len(changes[0]) == 2 * len(items):
        flags = [a or b for a, b in zip(changes[0][::2], changes[0][1::2])]
    return items, flags


def _jobs(lines, duration, audio_path, log, skip=None):
    """Respect manual anchors; use coarse timing ONLY to bound long searches."""
    from . import align as A, lyrics as L
    anchors = [(i, float(ln.start)) for i, ln in enumerate(lines) if ln.start is not None]
    boundaries = [(0, 0.0)] if not anchors or anchors[0][0] else []
    boundaries += anchors + [(len(lines), duration)]
    jobs = []
    for (i, start), (j, end) in zip(boundaries, boundaries[1:]):
        if j <= i:
            continue
        if end <= start:
            raise ValueError(tr("Manual line timestamps must increase.",
                                "Ручные тайминги строк должны идти по возрастанию."))
        if end - start <= MAX_SECONDS:
            jobs.append((lines[i:j], start, end))
            continue
        # No lyric-free audio/text proportional cut: a long intro would shift
        # every word. Vocal-energy phrase anchors give bounded overlapping
        # windows; their approximate nature is stated in the log.
        coarse = L.Lyrics(lines=deepcopy(lines[i:j]))
        for ln in coarse.lines:
            ln.start = ln.end = None
            for w in ln.words:
                w.start = w.end = None
        outside = [(0.0, start), (end, duration)] + list(skip or [])
        A.align_energy(coarse, audio_path, duration, skip=outside)
        log(tr("Long song: approximate phrase anchors bound Qwen's search windows; check block boundaries.",
               "Длинная песня: приблизительные границы фраз ограничивают окна Qwen; проверьте стыки блоков."))
        first = 0
        while first < len(coarse.lines):
            lo = max(start, coarse.lines[first].start - 12)
            last = first + 1
            while last < len(coarse.lines) and coarse.lines[last].end - lo < 230:
                last += 1
            hi = min(end, max(coarse.lines[last - 1].end + 12, lo + 0.1))
            if hi - lo > MAX_SECONDS or hi <= lo:
                raise ValueError(tr("This long phrase needs a manual timing anchor before Qwen can align it.",
                                    "Для этой длинной фразы нужна ручная отметка времени перед разметкой Qwen."))
            jobs.append((lines[i + first:i + last], lo, hi))
            first = last
    return jobs


def _compressed_words(words):
    """Judge the editable duration, including subsequent overlap clipping."""
    starts = [word.start for word in words]
    # _fill_lines opens coincident starts backwards to make short words
    # draggable. Account for that opening too: a collapsed preposition can
    # otherwise steal the end of the preceding, apparently healthy word.
    for i in range(len(words) - 1, 0, -1):
        if starts[i] - starts[i - 1] < .05:
            starts[i - 1] = max(0, starts[i] - max(.02, .07 * words[i - 1].syllables))
    for i, word in enumerate(words):
        end = min(word.end, starts[i + 1]) if i + 1 < len(words) else word.end
        if word.syllables >= 2 and (word.end - word.start <= .005 or
                                   end - starts[i] < max(.065, .04 * word.syllables)):
            yield word


def _faults(lines, holes=()):
    """Structural warnings, NOT model confidence or a rule to erase pauses.

    Inspect the raw output before _fill_lines opens collapsed words. A long
    held note is not a fault. An explicit no-lyrics interval may divide a line.
    """
    scores = []
    for i, ln in enumerate(lines):
        words = [w for w in ln.words if _key(w.text)]
        score = sum(3 for w in words if w.end - w.start <= .005)
        score += sum(2 for w in words if getattr(w, "qwen_interpolated", False))
        # A three-syllable word squeezed into 90 ms used to pass the fixed
        # 65 ms check. Flag severe per-syllable compression for a fresh inference,
        # not for proportional redistribution. Short function words and long
        # sung vowels remain valid; this is a warning, not a duration floor.
        score += sum(2 for _ in _compressed_words(words))
        if words:
            span = words[-1].end - words[0].start
            if span <= 0 or span / max(ln.syllables, 1) < .07:
                score += 10
        for left, right in zip(words, words[1:]):
            gap = right.start - left.end
            # Only the part NOT explained by an explicit pause is suspect.
            gap -= sum(max(0, min(right.start, b) - max(left.end, a)) for a, b in holes)
            if gap > 3:
                score += 5 + min(gap, 30)
        if i and words and lines[i - 1].words and ln.voice == lines[i - 1].voice:
            if lines[i - 1].words[-1].end > words[0].start + .05:
                score += 6
        scores.append(score)
    return scores


def trim_same_voice_tails(lyrics, fixed=()):
    """Resolve adjacent phrase tails, not duet overlaps or manual anchors.

    Only trim the last word when the next onset falls inside that word.
    An overlap covering earlier words is an uncertain phrase placement and
    must remain visible for review rather than erase a whole phrase.
    """
    changed = 0
    leads = [ln for ln in lyrics.lines if not ln.backing and ln.words]
    for left, right in zip(leads, leads[1:]):
        if (left.voice != right.voice or left.voice not in (1, 2)
                or left.lock or left.keep or id(left) in fixed):
            continue
        tail, onset = left.words[-1], right.words[0].start
        if tail.start + .06 <= onset < tail.end:
            tail.end = onset
            left.end = onset
            changed += 1
    return changed


def _safe_proposal(lines, proposal, holes=()):
    """Roll back retries that create/worsen an overlap, including after rollback.

    A constant overlap penalty alone allows a ten-second reversal to replace
    a minor overlap. Compare the actual overlap as well as warning scores.
    """
    before = _faults(lines, holes)
    while True:
        after = _faults(proposal, holes)
        reject = set()
        for i, (old, new) in enumerate(zip(lines, proposal)):
            if after[i] > before[i]:
                reject.update(j for j in (i - 1, i) if j >= 0 and proposal[j] is not lines[j])
            if not i or new.voice != proposal[i - 1].voice:
                continue
            overlap = proposal[i - 1].words[-1].end - new.words[0].start
            previous = lines[i - 1].words[-1].end - old.words[0].start
            if overlap > max(.05, previous) + .001:
                reject.update(j for j in (i - 1, i) if proposal[j] is not lines[j])
        if not reject:
            return proposal
        for i in reject:
            proposal[i] = lines[i]


def _core_bounds(line):
    """A compact cluster bounds a search; it never supplies word timestamps.

    A single stray 'I' before an interlude must not anchor the next chorus.
    Select by character coverage, rather than stretching that stray word.
    """
    words = [w for w in line.words if _key(w.text) and w.end - w.start > .005
             and not getattr(w, "qwen_interpolated", False)]
    if not words:
        return None
    clusters = [[]]
    for w in words:
        if clusters[-1] and w.start - clusters[-1][-1].end > 3:
            clusters.append([])
        clusters[-1].append(w)
    cluster = max(clusters, key=lambda ws: sum(len(_key(w.text)) for w in ws))
    return cluster[0].start, cluster[-1].end


def _failed_placement(lines):
    """Reject mass timestamp collapse before editable minimum widths hide it.

    No song names, reference timestamps or duration-proportional lyric cuts.
    Individual short words, long held vowels and duets are not a mass failure.
    """
    words = [w for ln in lines for w in ln.words if _key(w.text)]
    if any(w.start is None or w.end is None for w in words):
        return True
    if len(words) >= 8 and sum(w.end - w.start <= .005 for w in words) >= len(words) * .5:
        return True
    failed = 0
    for ln in lines:
        ws = [w for w in ln.words if _key(w.text)]
        bad = bool(len(ws) >= 3 and (ws[-1].end - ws[0].start <= .08 * max(ln.syllables, 1)))
        failed = failed + 1 if bad else 0
        if failed >= 3:
            return True
    return False


def _independent_jobs(lines, audio_path, duration, lo, hi, language, device, log, holes, model_name):
    """Speech alignment supplies search bounds, never final Qwen word times.

    Used only after a mass failure: failed Qwen predictions cannot serve as
    their own recovery anchors. No fallback to energy/proportional splitting.
    """
    from . import align as A, lyrics as L
    guide = L.Lyrics(lines=deepcopy(lines))
    for ln in guide.lines:
        ln.start = ln.end = None
        for w in ln.words:
            w.start = w.end = w.prob = None
    log(tr(f"Qwen placement failed: obtaining independent phrase bounds with Whisper ({model_name}).",
           f"Qwen потерял привязку: получаю независимые границы фраз через Whisper ({model_name})."))
    try:
        A.align_whisper(guide, audio_path, duration, model_name, language, device, log,
                        skip=list(holes) + [(0, lo), (hi, duration)])
    except (ImportError, OSError, RuntimeError) as exc:
        raise RecoveryUnavailable(tr(
            f"Optional Whisper recovery is unavailable: {exc}",
            f"Резервная проверка Whisper недоступна: {exc}")) from exc
    unplaced_start = None
    if _failed_placement(guide.lines):
        # A cut/shorter recording can leave a suffix of supplied text without
        # any acoustic match. Preserve it separately, never squeeze it into
        # the outro or discard the otherwise independently timed song.
        for a, b in A.pile_runs(guide.lines):
            prefix = guide.lines[:a]
            words = [w for ln in prefix for w in ln.words]
            if (b == len(lines) - 1 and a >= 3 and a >= len(lines) / 2
                    and guide.lines[a].start >= hi - 2
                    and not _failed_placement(prefix) and words
                    and sum((w.prob or 0) >= .4 for w in words) >= len(words) * .5):
                unplaced_start = a
                guide.lines = prefix
                break
    if _failed_placement(guide.lines):
        raise ValueError(tr("Independent phrase alignment also failed. Check the lyrics and add manual anchors or choose Whisper.",
                            "Независимая привязка фраз тоже не удалась. Проверьте текст, добавьте ручные отметки или выберите Whisper."))
    cuts = [(0, lo)]
    for i in range(1, len(guide.lines)):
        first = cuts[-1][0]
        left, right = guide.lines[i - 1], guide.lines[i]
        if i - first < 6 and left.end - guide.lines[first].start < 25:
            continue
        left_core, right_core = _core_bounds(left), _core_bounds(right)
        # A guide's own synthesized/low-confidence timing cannot anchor Qwen.
        confident = all(ln.words and sum((w.prob or 0) for w in ln.words) / len(ln.words) >= .4
                        for ln in (left, right))
        if confident and left_core and right_core and left_core[1] <= right_core[0]:
            seam = (left_core[1] + right_core[0]) / 2
            if cuts[-1][1] + .1 < seam < hi - .1:
                cuts.append((i, seam))
    cuts.append((len(guide.lines), hi))
    if len(cuts) <= 2 and unplaced_start is None:
        raise ValueError(tr("No reliable independent phrase boundaries found. Add manual line anchors or choose Whisper.",
                            "Не найдены надёжные независимые границы фраз. Добавьте ручные отметки строк или выберите Whisper."))
    class Windows(list):
        pass
    windows = Windows((a, b, start, end) for (a, start), (b, end) in zip(cuts, cuts[1:]))
    windows.guide = guide.lines
    windows.unplaced_start = unplaced_start
    return windows


def _retry_jobs(lines, lo, hi):
    """Bound local retries by observed neighbouring phrases and headings.

    Never divide lyrics in proportion to audio duration: intros and repeated
    choruses invalidate that assumption. If a seam has no usable anchors,
    leave the groups together rather than guess a time for it.
    """
    cuts = [(0, lo)]
    for i in range(1, len(lines)):
        first = cuts[-1][0]
        left, right = _core_bounds(lines[i - 1]), _core_bounds(lines[i])
        origin = _core_bounds(lines[first])
        too_long = origin and left and left[1] - origin[0] >= BLOCK_SECONDS
        if not (lines[i].section or i - first >= BLOCK_LINES or too_long):
            continue
        if left and right and right[0] >= left[1] - .05:
            seam = (left[1] + right[0]) / 2
            if cuts[-1][1] + .1 < seam < hi - .1:
                cuts.append((i, seam))
    cuts.append((len(lines), hi))
    return [(a, b, start, end) for (a, start), (b, end) in zip(cuts, cuts[1:])]


def timing_source(original, vocals=None, engine="auto"):
    """Qwen benefits from a stem; Whisper must keep its complete recording."""
    return (vocals, True) if engine == "qwen" and vocals else (original, False)


def extend_sustained_tails(lyrics, audio, duration, holes=(), fixed=(), log=lambda msg: None,
                           next_onsets=None):
    """Recover a truncated last vowel ONLY on an isolated vocal signal.

    Require voice already continuing at the model edge and stop at the first
    sustained drop. Never cross a pause, another lyric, a manual anchor or a
    no-lyrics mark. This changes the last word's end, never its start or rhythm.
    """
    import numpy as np
    from .vocal_tails import HarmonicTails
    hop = .02
    size = 320
    n = len(audio) // size * size
    if not n:
        return 0
    env = np.sqrt(np.mean(audio[:n].reshape(-1, size) ** 2, axis=1))
    peak = float(env.max())
    if peak <= 0:
        return 0
    count = 0
    tones = HarmonicTails(audio)
    for i, line in enumerate(lyrics.lines):
        if (id(line) in fixed or i in lyrics.fixed_line_indices or line.lock or line.keep
                or line.backing or not line.words):
            continue
        word = line.words[-1]
        if word.start is None or word.end is None or word.end - word.start < .12:
            continue
        boundary = max(0, int(word.end / hop))
        onset = max(0, int(max(word.start, word.end - .4) / hop))
        local = env[onset:boundary]
        if len(local) < 3 or float(local.max()) < peak * .05:
            continue
        threshold = max(float(np.quantile(local, .75)) * .23, peak * .015)
        # An edge already followed by silence is a real pause, not a clipped
        # vowel. Three of the next four frames must still contain the voice.
        after = env[boundary:boundary + 4]
        if len(after) < 4 or np.count_nonzero(after >= threshold) < 3:
            continue
        limit = min(duration, word.end + 8)
        next_onset = (next_onsets or {}).get(id(line))
        if next_onset is not None:
            limit = min(limit, next_onset)
        for following in lyrics.lines[i + 1:]:
            if following.words and following.words[0].start is not None:
                next_onset = following.words[0].start
                limit = min(limit, following.words[0].start)
                break
        for a, b in holes:
            if b > word.end:
                limit = min(limit, max(word.end, a))
        end_frame = min(len(env), int(limit / hop))
        quiet = 0
        last_voice = boundary - 1
        stopped = False
        for j in range(boundary, end_frame):
            if env[j] >= threshold:
                last_voice, quiet = j, 0
            else:
                quiet += 1
                if quiet >= 8:  # 160 ms of silence: do not swallow a breath
                    stopped = True
                    break
        # Prefer an observed quiet ending, including unvoiced consonants that
        # follow the vowel. Use the tonal check only when that check could not
        # find an ending before the next phrase.
        minimum_extension = .20
        if not stopped:
            if line.timing_review or (word.prob is not None and word.prob < .15):
                continue
            end = tones.end(word.start, word.end, limit,
                            next_phrase=next_onset is not None and abs(limit - next_onset) < .001)
            if end is None:
                continue
            # Without an actual quiet boundary, leave short ambiguous tails
            # alone. This pass targets clearly clipped held notes.
            minimum_extension = .35
        else:
            end = min(limit, (last_voice + 1) * hop + .04)
        if end - word.end >= minimum_extension:
            word.end = end
            line.end = end
            count += 1
    if count:
        log(tr(f"Held vocal endings extended: {count}.",
               f"Продлены протяжные вокальные окончания: {count}."))
    return count


def align_qwen(lyrics, audio_path, duration, language="auto", device=None,
               log=lambda msg: None, isolated=False, skip=None, model=None,
               fallback_audio=None, guide_model="small", whisper_review=True):
    from . import align as A, audio as AU, lang as LG
    from .progress import Heartbeat
    import numpy as np

    code = LG.resolve(language, lyrics.plain_text())
    if code not in LANGUAGES:
        raise ValueError(tr(f"Qwen forced alignment does not support {LG.label(code)}. Choose Whisper.",
                            f"Qwen не поддерживает разметку языка «{LG.label(code)}». Выберите Whisper."))
    if model is None and not available():
        raise RuntimeError(tr("Qwen is not installed. Install app/requirements-qwen.txt in the app's Python environment.",
                              "Qwen не установлен. Установите app/requirements-qwen.txt в Python-окружение программы."))
    log(tr(f"Qwen forced alignment, language: {LG.label(code)}",
           f"Разметка Qwen, язык: {LG.label(code)}"))
    # Do not level the stem: quiet onsets and genuine pauses are evidence,
    # not background to amplify. Keep exactly the signal used in the A/B test.
    pcm = AU.read_pcm_mono(audio_path, 16000)
    audio = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
    main = [ln for ln in lyrics.lines if not ln.backing] or lyrics.lines
    fixed = {id(ln): float(ln.start) for ln in main
             if lyrics.has_manual_times and ln.start is not None}
    # Only real LRC/manual anchors constrain the model, not old word timings.
    planning = deepcopy(main)
    if not lyrics.has_manual_times:
        for ln in planning:
            ln.start = ln.end = None
    holes = A.spans(skip, duration)
    kept_duration = sum(b - a for a, b in A.keep_windows(holes, duration)) if holes else duration
    planned = ([(planning, 0.0, duration)] if not fixed and kept_duration <= MAX_SECONDS
               else _jobs(planning, duration, audio_path, log, holes))
    jobs, at = [], 0
    for lines, lo, hi in planned:
        jobs.append((main[at:at + len(lines)], lo, hi))
        at += len(lines)
    lent = model is not None
    try:
        if model is None:
            import torch
            prepare_import()
            from qwen_asr import Qwen3ForcedAligner
            from huggingface_hub import snapshot_download
            ready = M.qwen_ready()
            log(tr("Loading Qwen from disk…" if ready else "Downloading Qwen weights (about 1.8 GB), once only…",
                   "Загружаю Qwen с диска…" if ready else "Скачиваю веса Qwen (около 1,8 ГБ), один раз…"))
            with Heartbeat(log, tr("loading Qwen", "загрузка Qwen"), every=10):
                if not ready:
                    try:
                        snapshot_download(M.QWEN_MODEL, revision=M.QWEN_REVISION, local_dir=M.qwen_dir(),
                                          allow_patterns=["*.json", "*.safetensors", "*.txt", "*.tiktoken"])
                    except Exception as exc:
                        raise RuntimeError(tr(
                            f"Could not download Qwen from Hugging Face. Check the connection and VPN/proxy routing. Original error: {exc}",
                            f"Не удалось скачать Qwen с Hugging Face. Проверьте подключение и маршрутизацию VPN/прокси. Исходная ошибка: {exc}")) from exc
                target = device or ("cuda" if torch.cuda.is_available() else "cpu")
                model = Qwen3ForcedAligner.from_pretrained(
                    M.qwen_dir(), device_map=target,
                    dtype=torch.float32 if target == "cpu" else torch.float16,
                    attn_implementation="sdpa")
        fallback = None
        recovery_anchors = {}
        unplaced_ids = set()
        source_indices = {id(ln): i + 1 for i, ln in enumerate(lyrics.lines)}
        whisper_unavailable = not whisper_review

        def original_signal():
            nonlocal fallback, fallback_audio
            if not fallback_audio or fallback_audio == audio_path:
                return None
            if fallback is None:
                try:
                    raw = AU.read_pcm_mono(fallback_audio, 16000)
                    fallback = np.frombuffer(raw.tobytes(), dtype="<i2").astype("float32") / 32768.0
                    if abs(len(fallback) - len(audio)) > 16000 * .25:
                        raise ValueError("original and vocal durations differ")
                except (OSError, RuntimeError, ValueError) as exc:
                    log(tr(f"Qwen: original-audio retry unavailable: {exc}",
                           f"Qwen: перепроверка по исходному треку недоступна: {exc}"))
                    fallback_audio = None
                    fallback = None
            return fallback

        def infer(lines, lo, hi, signal):
            keep = [(max(lo, a), min(hi, b)) for a, b in A.keep_windows(holes, duration)
                    if min(hi, b) > max(lo, a)] if holes else [(lo, hi)]
            if not keep:
                raise ValueError(tr("No audio remains outside the 'no lyrics' marks.",
                                    "Не осталось звука вне отметок «нет текста»."))
            pieces = [signal[int(a * 16000):int(b * 16000)] for a, b in keep]
            stitched = np.concatenate(pieces)
            def whole(t, end=False):
                for a, b in keep:
                    if t < b - a or (end and t <= b - a):
                        return a + t
                    t -= b - a
                return keep[-1][1]
            text = "\n".join(ln.text for ln in lines)
            with Heartbeat(log, tr("Qwen alignment", "разметка Qwen"), every=10):
                if len(stitched) / 16000 > MAX_SECONDS + 0.001:
                    raise ValueError(tr("Qwen search window exceeds five minutes.",
                                        "Окно разметки Qwen превышает пять минут."))
                items, repaired = _model_alignment(model, audio=(stitched, 16000), text=text, language=LANGUAGES[code])
            assign_words([w for ln in lines for w in ln.words], items,
                         0.0, whole, len(stitched) / 16000, whole_end=lambda t:whole(t, end=True),
                         timestamp_step=(getattr(model, "timestamp_segment_time", 0) or 0) / 1000,
                         repaired=repaired)

        for n, (lines, lo, hi) in enumerate(jobs, 1):
            if holes and not any(min(hi, b) > max(lo, a) for a, b in A.keep_windows(holes, duration)):
                raise ValueError(tr("No audio remains outside the 'no lyrics' marks.",
                                    "Не осталось звука вне отметок «нет текста»."))
            log(tr(f"Qwen: block {n}/{len(jobs)} ({A.mmss(lo)}–{A.mmss(hi)})",
                   f"Qwen: блок {n}/{len(jobs)} ({A.mmss(lo)}–{A.mmss(hi)})"))
            invalid = False
            try:
                infer(lines, lo, hi, audio)
            except ValueError as exc:
                invalid = True
                log(tr(f"Qwen initial result rejected: {exc}", f"Начальный результат Qwen отклонён: {exc}"))
            if invalid or _failed_placement(lines):
                try:
                    if whisper_unavailable:
                        raise RecoveryUnavailable("Whisper recovery is unavailable for this job")
                    guided = _independent_jobs(lines, fallback_audio or audio_path, duration,
                                               lo, hi, code, device, log, holes, guide_model)
                except RecoveryUnavailable as exc:
                    whisper_unavailable = True
                    if whisper_review:
                        log(str(exc))
                    candidate = deepcopy(lines)
                    signal = original_signal()
                    restored = False
                    if signal is not None:
                        log(tr("Qwen: retrying placement against the original audio without Whisper.",
                               "Qwen: повторяю привязку по исходному звуку без Whisper."))
                        try:
                            infer(candidate, lo, hi, signal)
                            restored = not _failed_placement(candidate)
                        except ValueError:
                            pass
                    if restored:
                        for original, recovered in zip(lines, candidate):
                            for word, got in zip(original.words, recovered.words):
                                word.start, word.end = got.start, got.end
                                word.qwen_interpolated = getattr(got, 'qwen_interpolated', False)
                        invalid = False
                    else:
                        first = source_indices[id(lines[0])]
                        last = source_indices[id(lines[-1])]
                        following = next((source_indices[id(ln)] for ln in main if source_indices[id(ln)] > last), len(lyrics.lines) + 1)
                        for ln in lyrics.lines:
                            if first <= source_indices[id(ln)] < following:
                                unplaced_ids.add(id(ln))
                                lyrics.unplaced_lyrics.append({'text': ln.text, 'line': source_indices[id(ln)],
                                                               'reason': 'whisper-unavailable' if whisper_review else 'whisper-disabled'})
                        log(unplaced_warning(whisper_review))
                        continue
                    guided = None
                if guided is not None:
                    cut = getattr(guided, 'unplaced_start', None)
                    if cut is not None:
                        if not lyrics.allow_unplaced_ending or lines[-1] is not main[-1]:
                            raise ValueError(tr("Independent alignment failed inside the song. Check the lyrics and manual anchors.",
                                                "Независимая привязка потеряна внутри песни. Проверьте текст и ручные отметки."))
                        first_unplaced = source_indices[id(lines[cut])]
                        tail = [ln for ln in lyrics.lines if source_indices[id(ln)] >= first_unplaced]
                        if any(id(ln) in fixed or ln.lock or
                               (lyrics.has_manual_times and ln.start is not None) for ln in tail):
                            raise ValueError(tr("Unmatched lyrics include manually anchored or locked lines. Check the lyrics and anchors.",
                                                "Среди непривязанных строк есть закреплённые или отмеченные вручную. Проверьте текст и отметки."))
                        for ln in tail:
                            unplaced_ids.add(id(ln))
                            lyrics.unplaced_lyrics.append({'text': ln.text, 'line': source_indices[id(ln)],
                                                           'reason': 'unmatched-ending'})
                        lines = lines[:cut]
                        log(tr(f"The last {len(tail)} lines could not be matched to this recording. They are kept separately in the project for review; no timings were invented.",
                               f"Последние {len(tail)} строк не удалось привязать к этой записи. Они сохранены отдельно в проекте для проверки; выдуманные тайминги не добавлялись."))
                    candidate = deepcopy(lines)
                    recovery_anchors.update({id(ln): guide for ln, guide in
                                             zip(lines, getattr(guided, 'guide', []))})
                    for a, b, start, end in guided:
                        infer(candidate[a:b], start, end, audio)
                    if not _failed_placement(candidate) and (invalid or sum(_faults(candidate, holes)) < sum(_faults(lines, holes))):
                        # After a mass failure even individually plausible raw
                        # phrases can belong to the wrong repetition. Replace the
                        # whole failed block using the independent search bounds.
                        for original, recovered in zip(lines, candidate):
                            for w, got in zip(original.words, recovered.words):
                                w.start, w.end = got.start, got.end
                                w.qwen_interpolated = getattr(got, 'qwen_interpolated', False)
                    elif invalid:
                        raise ValueError(tr("Qwen returned invalid timings even after independent recovery; the result will not be saved.",
                                            "Qwen вернул некорректные тайминги даже после независимой перепроверки; результат не будет сохранён."))
            if not any(_faults(lines, holes)):
                continue
            retry_jobs = _retry_jobs(lines, lo, hi)
            # A broad phrase block can repeat a bad internal word split. Give
            # only severely compressed words one shorter, neighbour-bounded
            # phrase inference. No time can be borrowed from another line.
            for i, ln in enumerate(lines):
                if not any(_compressed_words(ln.words)):
                    continue
                start = max(lo, ln.words[0].start - .25)
                end = min(hi, ln.words[-1].end + .25)
                if i and lines[i - 1].words:
                    start = max(start, lines[i - 1].words[-1].end)
                if i + 1 < len(lines) and lines[i + 1].words:
                    end = min(end, lines[i + 1].words[0].start)
                if end - start >= .2:
                    retry_jobs.append((i, i + 1, start, end))
            for a, b, start, end in retry_jobs:
                old_scores = _faults(lines, holes)
                if not any(old_scores[a:b]):
                    continue
                # The coarse pass only finds search windows. Never repeatedly
                # call the identical model with the identical input.
                sources = []
                if len(retry_jobs) > 1:
                    sources.append(audio)
                original = original_signal()
                if original is not None:
                    sources.append(original)
                for signal in sources:
                    log(tr(f"Qwen: checking phrases {a + 1}–{b} inside {A.mmss(start)}–{A.mmss(end)}",
                           f"Qwen: перепроверяю фразы {a + 1}–{b} в пределах {A.mmss(start)}–{A.mmss(end)}"))
                    candidate = deepcopy(lines[a:b])
                    try:
                        infer(candidate, start, end, signal)
                    except ValueError as exc:
                        log(tr(f"Qwen local retry rejected: {exc}", f"Повторная разметка Qwen отклонена: {exc}"))
                        continue
                    proposal = list(lines)
                    # Compare each phrase in its full neighbour context. Leave
                    # healthy phrases byte-for-byte alone, including pauses.
                    context = list(lines)
                    context[a:b] = candidate
                    new_scores = _faults(context, holes)
                    for i in range(a, b):
                        if old_scores[i] and new_scores[i] <= old_scores[i]:
                            proposal[i] = candidate[i - a]
                    proposal = _safe_proposal(lines, proposal, holes)
                    if sum(_faults(proposal, holes)) < sum(old_scores):
                        for i in range(a, b):
                            if proposal[i] is not lines[i]:
                                for word, got in zip(lines[i].words, proposal[i].words):
                                    word.start, word.end = got.start, got.end
                                    word.qwen_interpolated = getattr(got, "qwen_interpolated", False)
                        old_scores = _faults(lines, holes)
                    if not any(old_scores[a:b]):
                        break
        if unplaced_ids:
            main = [ln for ln in main if id(ln) not in unplaced_ids]
            lyrics.lines = [ln for ln in lyrics.lines if id(ln) not in unplaced_ids]
        if not whisper_unavailable and any(_faults(main, holes)):
            from .qwen_recovery import recover
            recover(main, fallback_audio or audio_path, duration, code, device, log,
                    holes, fixed, guide_model, vocal_path=audio_path if isolated else None,
                    anchors=recovery_anchors)
        suspect = [i + 1 for i, score in enumerate(_faults(main, holes)) if score]
        for i, ln in enumerate(main):
            ln.timing_review = i + 1 in suspect
        if suspect:
            numbers = ", ".join(map(str, suspect))
            log(tr(f"Qwen: check phrase/word placement on lines {numbers}; local retries could not resolve every warning.",
                   f"Qwen: проверьте привязку фраз и слов в строках {numbers}; повторная разметка устранила не все подозрительные тайминги."))
        if _failed_placement(main):
            raise ValueError(tr("Qwen could not place the lyrics reliably; this result will not be saved. Check the lyrics, add manual line anchors or choose Whisper.",
                                "Qwen не смог надёжно привязать текст; результат не будет сохранён. Проверьте текст, добавьте ручные отметки строк или выберите Whisper."))
        A._fill_lines(lyrics, duration, min_word=0.02)
        if isolated:
            extend_sustained_tails(lyrics, audio, duration, holes, fixed, log)
        if fixed:
            for i, ln in enumerate(lyrics.lines):
                if id(ln) in fixed:
                    limit = next((fixed[id(nxt)] for nxt in lyrics.lines[i + 1:] if id(nxt) in fixed), duration)
                    A._pin_one_line_start(ln, fixed[id(ln)], limit, duration)
            lyrics.fixed_line_indices = {i for i, ln in enumerate(lyrics.lines) if id(ln) in fixed}
            lyrics.fixed_line_starts = len(fixed) == len(main)
        if len(main) != len(lyrics.lines):
            A.place_backing(lyrics, duration, log=log)
            log(tr("Backing-vocal timing is approximate — check it in the editor.",
                   "Разметка бэков приблизительная — проверьте в редакторе."))
        if holes:
            # A line may legitimately have words on both sides of an interlude.
            # Whisper's whole-line mark repairs would re-spread such a line and
            # destroy Qwen's measured word times. Constrain actual words only.
            windows = A.keep_windows(holes, duration)
            for word in lyrics.words:
                if not any(word.start < b and word.end > a for a, b in holes):
                    continue
                choices = [(max(word.start, a), min(word.end, b)) for a, b in windows
                           if min(word.end, b) > max(word.start, a)]
                if not choices:
                    raise ValueError(tr("A Qwen word falls entirely inside a 'no lyrics' mark. Check the marks and manual anchors.",
                                        "Слово Qwen целиком попало в отметку «нет текста». Проверьте отметки и ручные тайминги."))
                word.start, word.end = max(choices, key=lambda span:span[1] - span[0])
        # Make word edges editable without preserving false overlaps. Do not
        # apply Whisper's confidence/phrase-length heuristics to Qwen results.
        for ln in lyrics.lines:
            for left, right in zip(ln.words, ln.words[1:]):
                if left.end > right.start:
                    left.end = max(left.start, right.start)
            if ln.words:
                ln.start, ln.end = ln.words[0].start, ln.words[-1].end
        trim_same_voice_tails(lyrics, fixed)
        if isolated:
            # Qwen can assign a whole interlude to the first/last word. Unlike
            # a duration cap, measured silence preserves genuinely held notes.
            # Only move an edge inside its existing word; never redistribute
            # the phrase, or change locked/manually anchored lines or the mix.
            A.refine_leading_silence(lyrics, audio_path, log=log, max_shift=duration)
            A.refine_trailing_silence(lyrics, audio_path, log=log)
        return lyrics
    finally:
        if not lent and model is not None:
            del model
            import gc
            gc.collect()
