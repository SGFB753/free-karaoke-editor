"""Acoustic search windows independent of a failed forced-alignment cursor.

The transcription supplies locations, never replacement lyrics. Sequence
alignment permits missing/repeated words; failed phrases cannot move the next
phrase's search window. All coordinates here are in the supplied PCM signal.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import math
from copy import deepcopy
from types import SimpleNamespace

from .lyrics import normalize_token


@dataclass
class Heard:
    text: str
    start: float
    end: float
    probability: float = 0.0


def heard_words(result, offset=0.0):
    words = []
    for segment in getattr(result, 'segments', []) or []:
        for word in getattr(segment, 'words', []) or []:
            a, b = float(word.start)+offset, float(word.end)+offset
            if (not math.isfinite(a+b) or b <= a or
                    words and a < words[-1].start):
                continue
            key = normalize_token(word.word)
            if key:
                words.append(Heard(key, a, b, float(getattr(word, 'probability', 0) or 0)))
    return words


def phrase_anchors(lines, heard, checkpoint=None, scores=None):
    """Monotonic lexical alignment; no duration-proportional position guesses."""
    ours, owners, positions = [], [], []
    for i, line in enumerate(lines):
        for position, word in enumerate(line.words):
            key = normalize_token(word.text)
            if key:
                ours.append(key); owners.append(i); positions.append(position)
    theirs = [w.text for w in heard]
    if not ours or not theirs:
        return {}

    @lru_cache(maxsize=65536)
    def similarity(a, b):
        if a == b:
            return 1.0
        if min(len(a), len(b)) < 4 or abs(len(a)-len(b)) > max(len(a), len(b))*.5:
            return 0.0
        value = SequenceMatcher(None, a, b, autojunk=False).ratio()
        return value if value >= .74 else 0.0

    # Only two score rows; traceback takes one byte per word pair.
    width = len(theirs)+1
    trace = [bytearray(width) for _ in range(len(ours)+1)]
    previous = [-.8*j for j in range(width)]
    for i, a in enumerate(ours, 1):
        if checkpoint and i % 16 == 0:
            checkpoint()
        row = [-.8*i]+[0.0]*len(theirs)
        for j, b in enumerate(theirs, 1):
            ratio = similarity(a, b)
            diagonal = previous[j-1]+(3*ratio if ratio else -1.9)
            delete, insert = previous[j]-.8, row[j-1]-.8
            if diagonal >= max(delete, insert):
                row[j], trace[i][j] = diagonal, 1
            elif delete >= insert:
                row[j], trace[i][j] = delete, 2
            else:
                row[j], trace[i][j] = insert, 3
            # ASR often separates one written word into several tokens, e.g.
            # a compound/name or a contraction. This still supplies one
            # acoustic word span, without changing the supplied spelling.
            for count in (2, 3):
                if j < count or len(a) < 2*count+1:
                    continue
                ratio = similarity(a, ''.join(theirs[j-count:j]))
                value = previous[j-count]+3*ratio-.1*(count-1)
                if ratio >= .8 and value > row[j]:
                    row[j], trace[i][j] = value, count+2
        previous = row
    matches = {}
    i, j = len(ours), len(theirs)
    while i and j:
        step = trace[i][j]
        if step in (4, 5):
            count = step-2
            span = heard[j-count:j]
            word = Heard(ours[i-1], span[0].start, span[-1].end,
                         sum(w.probability for w in span)/count)
            matches.setdefault(owners[i-1], []).append((word, positions[i-1]))
            i -= 1; j -= count
        elif step == 1:
            if similarity(ours[i-1], theirs[j-1]):
                matches.setdefault(owners[i-1], []).append((heard[j-1], positions[i-1]))
            i -= 1; j -= 1
        elif step == 2:
            i -= 1
        else:
            j -= 1
    anchors = {}
    for index, values in matches.items():
        values.reverse()
        matched = [w for w, _ in values]
        keys = [normalize_token(w.text) for w in lines[index].words]
        # A repeated chant cannot identify which repetition we are hearing.
        if len(keys) > 3 and len(set(keys)) < 2:
            continue
        if (len(values) < 2 or len(values) < .45*len(keys)
                or sum(w.probability for w in matched)/len(matched) < .18):
            continue
        a, b = matched[0].start, matched[-1].end
        if .08 < b-a < max(12.0, 2.0*len(keys)):
            # Unrecognised edge words need context too. This padding only
            # bounds another model inference; it never becomes a word timing.
            prefix = lines[index].words[:values[0][1]]
            suffix = lines[index].words[values[-1][1]+1:]
            anchors[index] = (max(0., a-min(2.5, .25*sum(w.syllables for w in prefix))),
                              b+min(2.5, .25*sum(w.syllables for w in suffix)))
            if scores is not None:
                scores[index] = len(matched)/max(1,len(keys))*sum(w.probability for w in matched)/len(matched)
    return anchors


def merge_anchors(sources):
    """Combine complementary recordings along one chronological phrase path.

    A stem may lose one singer while the mix hides another. A wrong occurrence
    of a repeated phrase cannot displace a longer consistent chain of phrases.
    """
    candidates = sorted((index,a,b,source,1.+scores.get(index,0.))
                        for source,(anchors,scores) in enumerate(sources)
                        for index,(a,b) in anchors.items())
    totals, previous = [], []
    for i,(index,a,b,source,weight) in enumerate(candidates):
        score, parent = weight, None
        for j,(old_index,old_a,old_b,_,_) in enumerate(candidates[:i]):
            if old_index < index and old_a+old_b < a+b and totals[j]+weight > score:
                score, parent = totals[j]+weight, j
        totals.append(score); previous.append(parent)
    if not totals:
        return {}, {}
    at = max(range(len(totals)), key=totals.__getitem__)
    anchors, origins = {}, {}
    while at is not None:
        index,a,b,source,_ = candidates[at]
        anchors[index], origins[index] = (a,b), source
        at = previous[at]
    return anchors, origins


def search_windows(count, anchors, lo, hi, min_seconds=0.0):
    """Keep unheard gaps between known phrases, bounded by their neighbours."""
    cuts = {0: lo, count: hi}
    for index, (a, b) in sorted(anchors.items()):
        a, b = max(lo, a), min(hi, b)
        if not (lo <= a < b <= hi):
            continue
        previous, following = anchors.get(index-1), anchors.get(index+1)
        if index and (previous is None or previous[1] <= a):
            cuts[index] = ((previous[1]+a)/2 if previous else max(lo, a-.2))
        if index+1 < count and (following is None or b <= following[0]):
            cuts[index+1] = ((b+following[0])/2 if following else min(hi, b+.2))
    ordered = [(0, lo)]
    for index, at in sorted(cuts.items()):
        if index in (0, count):
            continue
        if ordered[-1][1]+.05 < at < hi-.05:
            ordered.append((index, at))
    ordered.append((count, hi))
    windows = [(a, b, start, end) for (a, start), (b, end) in zip(ordered, ordered[1:])]
    # Subsecond isolated audio can produce invalid model timestamps. Include
    # neighbouring *text and audio* as context, rather than stretching words.
    index = 0
    while index < len(windows) and len(windows) > 1:
        a,b,start,end = windows[index]
        if end-start >= min_seconds:
            index += 1
        elif index+1 < len(windows):
            _,next_b,_,next_end = windows.pop(index+1)
            windows[index] = (a,next_b,start,next_end)
        else:
            prev_a,_,prev_start,_ = windows[index-1]
            windows[index-1:] = [(prev_a,b,prev_start,end)]
            break
    return windows


def recover(lines, signal, model, language, first, offset, whole, log, sources=None):
    """Re-enter after a sound prefix using independently recognised phrases.

    Return None when the model cannot transcribe or has insufficient evidence.
    Invalid results are kept outside timed lyrics, never pushed to the outro.
    """
    from . import align as A, jobcontrol as JC
    from .i18n import tr
    from .progress import Heartbeat
    if not callable(getattr(model, 'transcribe', None)):
        return None
    JC.checkpoint()
    log(tr('Alignment lost its place: recognising independent phrase locations…',
           'Разметка потеряла место: ищу независимые опорные фразы в записи…'))
    sample_rate = 16000
    best = None
    signals = sources or [signal]
    observations = [({}, {}) for _ in signals]
    for source_index, source in enumerate(signals):
        JC.checkpoint()
        try:
            with Heartbeat(log, tr('finding phrase locations', 'поиск опорных фраз'), every=10):
                transcript = model.transcribe(source[int(max(0., offset-.5)*sample_rate):],
                    language=language, condition_on_previous_text=False, fp16=False, verbose=None)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            log(tr(f'Could not recognise this recovery source: {exc}',
                   f'Не удалось распознать запасной источник: {exc}'))
            continue
        JC.checkpoint()
        heard = [w for w in heard_words(transcript, max(0., offset-.5)) if w.end > offset]
        scores = {}
        with Heartbeat(log, tr('matching recognised phrases', 'сопоставление опорных фраз'), every=10):
            found = phrase_anchors(lines[first:], heard, JC.checkpoint, scores)
        observations[source_index] = found,scores
        score = sum(len(lines[first+i].words) for i in found)
        log(tr(f'Independent phrase locations found: {len(found)}.',
               f'Найдено независимых опорных фраз: {len(found)}.'))
        if best is None or score > best[0]:
            best = score, source_index
    anchors, origins = merge_anchors(observations)
    if best is None or len(anchors) < max(2, .15*(len(lines)-first)):
        log(tr('Too few independently recognised phrases; preserving the usable prefix.',
               'Независимых опорных фраз недостаточно; сохраняю пригодное начало.'))
        return None
    windows = [(a+first, b+first, lo, hi) for a,b,lo,hi in
               search_windows(len(lines)-first, anchors, offset, len(signal)/sample_rate, min_seconds=1.0)]
    log(tr(f'Retrying {len(windows)} bounded phrase windows; later phrases keep their own locations.',
           f'Повторяю разметку по коротким окнам: {len(windows)}; следующие фразы не сдвигаются из-за пропусков.'))
    failed = set()
    for number, (a,b,lo,hi) in enumerate(windows, 1):
        JC.checkpoint()
        if number == 1 or number % 5 == 0:
            log(tr(f'Phrase recovery {number}/{len(windows)}: lines {a+1}–{b}.',
                   f'Восстановление фраз {number}/{len(windows)}: строки {a+1}–{b}.'))
        target = lines[a:b]
        # Use the recording which actually supplied this window's anchors;
        # a quiet phrase missing from a stem must not be forced against it.
        votes = [sum(1 for index, origin in origins.items()
                     if a-first <= index < b-first and origin == source)
                 for source in range(len(signals))]
        if not any(votes):
            votes = [sum(1 for index, origin in origins.items()
                         if max(0,a-first-1) <= index <= b-first and origin == source)
                     for source in range(len(signals))]
        eligible = [i for i,s in enumerate(signals) if len(s) >= int(hi*sample_rate)]
        source_index = max(eligible or [0], key=lambda i:(votes[i], i == best[1]))
        inference_signal = signals[source_index]
        for line in target:
            line.start = line.end = None
            for word in line.words:
                word.start = word.end = word.prob = None
        try:
            with Heartbeat(log, tr('recovering phrase timing', 'восстановление таймингов фразы'), every=10):
                result = model.align(inference_signal[int(lo*sample_rate):int(hi*sample_rate)],
                    '\n'.join(line.text for line in target), language=language,
                    original_split=True, verbose=False)
        except (RuntimeError, ValueError) as exc:
            log(tr(f'Phrase recovery failed for lines {a+1}–{b}: {exc}',
                   f'Не удалось восстановить строки {a+1}–{b}: {exc}'))
            result = None
        records = []
        for segment in getattr(result, 'segments', []) or []:
            for word in segment.words or []:
                key = normalize_token(word.word)
                x, y = float(word.start), float(word.end)
                if not key or not (math.isfinite(x+y) and -.01 <= x <= y <= hi-lo+.05):
                    continue
                probability = getattr(word, 'probability', None)
                records.append((key, whole(lo+max(0., x)), whole(lo+min(hi-lo, y)),
                                float(probability) if probability is not None else None))
        if records:
            A._apply_recognized([w for line in target for w in line.words], records)
        for index, line in enumerate(target, a):
            words = line.words
            usable = words and all(w.start is not None and w.end is not None for w in words)
            if usable:
                usable = words[-1].end-words[0].start > .03 and \
                         sum(w.end-w.start > .005 for w in words) >= len(words)*.5
            if not usable:
                failed.add(index)
            else:
                line.start, line.end = words[0].start, words[-1].end
                line.timing_review = sum(w.prob or 0 for w in words)/len(words) < .2
    prefix = [(0, first, 0., offset)] if first else []
    return SimpleNamespace(windows=[(a,b,whole(lo),whole(hi)) for a,b,lo,hi in prefix+windows],
                           guide=deepcopy(lines), failed=failed)
