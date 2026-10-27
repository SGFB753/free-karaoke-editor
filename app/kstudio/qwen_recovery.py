"""Independent word timing for locally failed Qwen phrases.

Candidates are raw Whisper alignments, before editor minimum widths and phrase
redistribution. Only structurally valid, heard phrases may replace failed ones.
"""
from copy import deepcopy
import math
from types import SimpleNamespace

from . import qwen as Q
from .i18n import tr


def _windows(lines, wanted, duration, anchors=None):
    """Include a healthy neighbour as audible/text context, not as a target."""
    groups = []
    for i in sorted(wanted):
        if groups and i <= groups[-1][-1] + 2:
            groups[-1].append(i)
        else:
            groups.append([i])
    bounds = [(anchors or {}).get(id(ln), ln) for ln in lines]
    bounded = []
    for group in groups:
        chunk = []
        for i in group:
            if chunk and (i - chunk[0] >= 8 or
                          bounds[i].words[-1].end - bounds[chunk[0]].words[0].start > 25):
                bounded.append(chunk)
                chunk = []
            chunk.append(i)
        bounded.append(chunk)
    for group in bounded:
        a, b = max(0, group[0] - 1), min(len(lines), group[-1] + 2)
        lo = max(0., bounds[a].words[0].start - .5) if a < group[0] else 0.
        hi = min(duration, bounds[b - 1].words[-1].end + .5) if b > group[-1] + 1 else duration
        if hi > lo:
            yield a, b, lo, hi, set(group)


def _heard(line):
    words = [w for w in line.words if Q._key(w.text)]
    if not words or Q._faults([line])[0]:
        return False
    if any(left.end > right.start + .005 for left, right in zip(words, words[1:])):
        return False
    probs = [w.prob or 0. for w in words]
    return (all(math.isfinite(p) for p in probs)
            and sum(probs) / len(probs) >= .35
            and sum(p >= .15 for p in probs) >= len(probs) * .5)


def recover(lines, audio_path, duration, language, device, log, holes=(), fixed=(),
            model_name='small', vocal_path=None, aligner=None, anchors=None):
    from . import audio as AU, align as A, lyrics as L, models as M, jobcontrol as JC
    from .progress import Heartbeat
    import numpy as np

    scores = Q._faults(lines, holes)
    wanted = {i for i, score in enumerate(scores) if score and id(lines[i]) not in fixed
              and not (lines[i].lock or lines[i].keep or lines[i].backing)}
    if not wanted:
        return 0
    changed = 0
    try:
        JC.checkpoint()
        if aligner is None:
            import stable_whisper
            log(tr(f"Checking uncertain Qwen phrases with Whisper ({model_name})…",
                   f"Проверяю сомнительные фразы Qwen через Whisper ({model_name})…"))
            log(M.load_note(model_name))
            with Heartbeat(log, tr('loading recovery model', 'загрузка резервной модели'), every=10):
                aligner = stable_whisper.load_model(model_name, device=device,
                                                    download_root=M.whisper_dir())
        sources = [audio_path]
        if vocal_path and vocal_path != audio_path:
            sources.append(vocal_path)
        for source in sources:
            if not wanted:
                break
            if source != audio_path:
                log(tr('Checking remaining phrases against isolated vocals…',
                       'Перепроверяю оставшиеся фразы по выделенному вокалу…'))
            raw = AU.read_pcm_mono(source, 16000)
            audio = np.frombuffer(raw.tobytes(), dtype='<i2').astype('float32') / 32768.
            for a, b, lo, hi, targets in _windows(lines, wanted, duration, anchors):
                JC.checkpoint()
                keep = [(max(lo, s), min(hi, e)) for s, e in A.keep_windows(holes, duration)
                        if min(hi, e) > max(lo, s)]
                if not keep:
                    continue
                signal = np.concatenate([audio[int(s * 16000):int(e * 16000)] for s, e in keep])

                def whole(t, end=False):
                    for s, e in keep:
                        if t < e - s or (end and t <= e - s):
                            return s + t
                        t -= e - s
                    return keep[-1][1]

                candidate = L.Lyrics(lines=deepcopy(lines[a:b]))
                log(tr(f"Whisper: checking lines {a + 1}–{b} ({A.mmss(lo)}–{A.mmss(hi)})",
                       f"Whisper: проверяю строки {a + 1}–{b} ({A.mmss(lo)}–{A.mmss(hi)})"))
                with Heartbeat(log, tr('checking word timing', 'перепроверка таймингов слов'), every=10):
                    result = aligner.align(signal, '\n'.join(ln.text for ln in candidate.lines),
                                           language=language, original_split=True, verbose=False)
                if result is None:
                    continue
                tokens = [w for seg in result.segments for w in (seg.words or [])]
                items = [SimpleNamespace(text=w.word, start_time=w.start, end_time=w.end) for w in tokens]
                try:
                    Q.assign_words(candidate.words, items, 0., whole, len(signal) / 16000,
                                   whole_end=lambda t: whole(t, end=True),
                                   probabilities=[getattr(w, 'probability', None) for w in tokens])
                except ValueError as exc:
                    log(tr(f"Whisper candidate rejected: {exc}", f"Резервная разметка отклонена: {exc}"))
                    continue
                for ln in candidate.lines:
                    ln.start, ln.end = ln.words[0].start, ln.words[-1].end
                if vocal_path:
                    # Evidence from separated vocals can shorten a leading silence,
                    # but never fill collapsed words or distribute them by length.
                    A.refine_leading_silence(candidate, vocal_path, log=log, max_shift=duration)
                    A.refine_trailing_silence(candidate, vocal_path, log=log)
                proposal = list(lines)
                eligible = set()
                for i in targets:
                    ln = candidate.lines[i - a]
                    if not _heard(ln):
                        continue
                    if any(w.start < s and w.end > s or s <= w.start < e
                           for w in ln.words for s, e in holes):
                        continue
                    proposal[i] = ln
                    eligible.add(i)
                proposal = Q._safe_proposal(lines, proposal, holes)
                for i in sorted(eligible):
                    if proposal[i] is lines[i]:
                        continue
                    for old, fresh in zip(lines[i].words, proposal[i].words):
                        old.start, old.end, old.prob = fresh.start, fresh.end, fresh.prob
                        old.qwen_interpolated = False
                    lines[i].start, lines[i].end = proposal[i].start, proposal[i].end
                    wanted.discard(i)
                    changed += 1
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        log(tr(f"Independent word recovery unavailable: {exc}. Uncertain phrases remain marked for review.",
               f"Резервная проверка слов недоступна: {exc}. Сомнительные фразы останутся отмечены для проверки."))
    finally:
        del aligner
    if changed:
        log(tr(f"Whisper recovered word timing on {changed} Qwen phrases.",
               f"Whisper восстановил тайминги слов в {changed} фразах после Qwen."))
    return changed
