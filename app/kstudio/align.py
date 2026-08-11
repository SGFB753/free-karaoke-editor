"""Выравнивание текста по звуку — расстановка таймингов для каждого слова.

Два движка:
  whisper — forced alignment моделью Whisper (stable-ts). Точно, но нужен torch.
  energy  — без нейросетей: слова распределяются по «массе» вокальной энергии.
            Работает всегда, паузы и проигрыши учитывает, но по словам грубее.
"""

from __future__ import annotations

import difflib
import sys
from typing import Callable, List, Optional

from .i18n import tr
from .lyrics import Lyrics, Word, normalize_token

Log = Callable[[str], None]


def _noop(msg: str) -> None:
    pass


# --------------------------------------------------------------------------- #
#  Энергетический движок: ищем вокальные фразы и раскладываем строки по ним
# --------------------------------------------------------------------------- #

def _phrases(env: List[float], dt: float, min_dur: float = 0.18,
             max_gap: float = 0.32) -> List[List[float]]:
    """Участки вокальной активности [начало, конец] по порогу с гистерезисом."""
    if not env:
        return []
    ordered = sorted(env)
    floor = ordered[int(len(ordered) * 0.15)]
    peak = ordered[min(int(len(ordered) * 0.98), len(ordered) - 1)]
    rng = max(peak - floor, 1e-6)
    on, off = floor + 0.20 * rng, floor + 0.11 * rng

    lead = max(int(0.20 / dt), 1)        # насколько отступаем назад к тихому началу фразы
    segs, start, active = [], 0, False
    for i, e in enumerate(env):
        if not active and e >= on:
            active, start = True, i
            # порог срабатывает уже на разгоне звука; отходим к настоящему началу,
            # чтобы строка загоралась чуть раньше, а не после того, как её запели
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


GAP_PENALTY = 1.5      # во сколько раз пауза внутри строки «дороже» ошибки длительности


def _limit_phrases(segs: List[List[float]], target: int) -> List[List[float]]:
    """Слишком дробную нарезку склеиваем по самым узким паузам (иначе DP медленный)."""
    while len(segs) > target:
        gaps = [(segs[i + 1][0] - segs[i][1], i) for i in range(len(segs) - 1)]
        _, i = min(gaps)
        segs[i][1] = segs[i + 1][1]
        del segs[i + 1]
    return segs


def _fit_lines_to_phrases(lines, segs) -> None:
    """Оптимально разложить строки по фразам (DP) и проставить start/end."""
    N, M = len(lines), len(segs)
    voiced = [e - s for s, e in segs]
    pre = [0.0]
    for v in voiced:
        pre.append(pre[-1] + v)
    total_voiced = pre[-1] or 1.0
    total_syl = sum(ln.syllables for ln in lines) or 1
    want = [total_voiced * ln.syllables / total_syl for ln in lines]

    INF = float("inf")

    # без ограничения на размер группы DP растёт как O(N·M²) и на длинном тексте
    # считается десятки секунд; строка почти никогда не занимает много фраз подряд
    span_cap = max(8, 2 * -(-M // N), 2 * -(-N // M))

    if M >= N:
        # каждой строке — непрерывная группа из одной или нескольких фраз
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
                    inner = (segs[j - 1][1] - segs[k][0]) - gv   # паузы внутри группы
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
        # фраз меньше, чем строк: в одну фразу помещаем несколько строк
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


def align_energy(lyrics: Lyrics, audio_path: str, duration: float,
                 log: Log = _noop) -> Lyrics:
    """Разложить строки по вокальным фразам, слова внутри строки — по слогам."""
    from . import audio as A

    log(tr("Looking for sung phrases by loudness…", "Ищу вокальные фразы по громкости…"))
    try:
        env, dt = A.rms_envelope(audio_path)
    except Exception as e:                              # pragma: no cover
        log(tr(f"  did not work ({e}) — spreading evenly", f"  не вышло ({e}) — раскладываю равномерно"))
        env, dt = [], 0.02

    lines = [ln for ln in lyrics.lines if ln.words]
    segs = _phrases(env, dt)
    if not segs or not lines:
        log(tr("  no phrases stood out — spreading the text evenly",
            "  фразы не выделились — раскладываю текст равномерно"))
        segs = [[0.0, duration]]
    segs = _limit_phrases(segs, max(3 * len(lines) + 8, 24))
    log(tr(f"  phrases found: {len(segs)}, lines of text: {len(lines)}",
           f"  найдено фраз: {len(segs)}, строк текста: {len(lines)}"))

    if lines:
        _fit_lines_to_phrases(lines, segs)

    # слова внутри строки — пропорционально слогам.
    # Расширять span нельзя: на плотном тексте строки бывают короче любого порога,
    # и растянутые слова заезжали бы на следующую строку, ломая порядок.
    for ln in lines:
        span = max(ln.end - ln.start, 1e-3)
        acc = 0.0
        for w in ln.words:
            w.start = ln.start + span * acc / ln.syllables
            acc += w.syllables
            w.end = ln.start + span * acc / ln.syllables

    _fill_lines(lyrics, duration)
    return lyrics


# --------------------------------------------------------------------------- #
#  Whisper forced alignment
# --------------------------------------------------------------------------- #

def align_whisper(lyrics: Lyrics, audio_path: str, duration: float,
                  model_name: str = "medium", language: str = "ru",
                  device: Optional[str] = None, log: Log = _noop) -> Lyrics:
    import stable_whisper

    from . import sysinfo
    ok, note = sysinfo.check(sysinfo.NEED_WHISPER.get(model_name, 2.2))
    if not ok:
        log("  " + note + tr(" If it crashes, take a smaller model.",
                          " Если упадёт — возьмите модель поменьше."))

    from . import lang as LG
    from . import models as M
    from .progress import Heartbeat

    # «auto» — не «пусть Whisper угадает», а «определим по тексту сами»:
    # так результат предсказуем и его видно в логе.
    if not language or language == "auto":
        language = LG.detect(lyrics.plain_text())
        log(tr(f"Language of the lyrics: {LG.label(language)} (worked out from the text)",
           f"Язык текста: {LG.label(language)} (определён по тексту)"))

    # Говорим по факту: если модель на диске, обещать скачивание нельзя — окно
    # рядом честно пишет «уже скачана», и получалось, что одно из двух врёт.
    log(M.load_note(model_name))
    try:
        # medium весит полтора гигабайта: и загрузка с диска, и первое скачивание
        # идут молча по несколько минут, и окно выглядит зависшим.
        need = sysinfo.NEED_WHISPER.get(model_name, 2.2)
        with Heartbeat(log, M.step_label(model_name), every=10.0,
                       slow_after=90.0,
                       slow_note=(f"дольше обычного. Модели «{model_name}» нужно около "
                                  f"{need:.0f} ГБ памяти; если её мало, система "
                                  f"перекладывает данные на диск, и шаг растягивается "
                                  f"в разы. Помогает модель поменьше: "
                                  f"medium → small → base.")):
            model = stable_whisper.load_model(model_name, device=device)
    except Exception as e:
        # Отдельно ловим неудачу скачивания: «Connection refused» сам по себе
        # ничего не объясняет, а причина почти всегда в интернете на машине.
        low = str(e).lower()
        net = ("urlopen", "connection", "getaddrinfo", "timed out", "ssl",
               "max retries", "name resolution", "unreachable", "httperror")
        if any(k in low for k in net):
            raise RuntimeError(
                f"не удалось скачать модель Whisper «{model_name}». "
                f"Проверьте интернет на этой машине — модель качается один раз "
                f"и потом лежит в ~/.cache/whisper. Исходная ошибка: {e}")
        if "checksum" in low or "sha256" in low:
            raise RuntimeError(
                f"файл модели «{model_name}» побился при загрузке. Удалите "
                f"~/.cache/whisper и повторите. Исходная ошибка: {e}")
        raise

    # Whisper, получив путь к файлу, зовёт `ffmpeg` по имени через PATH. Если ffmpeg
    # поставлен через imageio-ffmpeg, он называется иначе и не находится — Windows
    # отвечает «WinError 2». Поэтому декодируем сами и отдаём готовые отсчёты:
    # 16 кГц моно float32 в диапазоне [-1, 1] — ровно то, что ждёт модель.
    audio_input = audio_path
    try:
        import numpy as np
        from . import audio as A
        pcm = A.read_pcm_mono(audio_path, 16000)
        audio_input = np.frombuffer(pcm.tobytes(), dtype="<i2").astype("float32") / 32768.0
        log(tr(f"  audio decoded with our own ffmpeg ({len(audio_input) / 16000:.0f} s)",
               f"  звук декодирован своим ffmpeg ({len(audio_input) / 16000:.0f} с)"))
    except Exception as e:
        log(tr(f"  could not decode in advance ({e}) — handing Whisper the file path",
               f"  не вышло декодировать заранее ({e}) — отдаю Whisper путь к файлу"))

    log(tr("Lining the text up with the audio…", "Выравниваю текст по звуку…"))
    try:
        # Самый долгий шаг после минусовки. stable-ts умеет докладывать, сколько
        # секунд записи уже разобрано, — отдаём это в лог, а не в консольный
        # прогрессбар, которого в окне студии всё равно не видно.
        with Heartbeat(log, "выравнивание", slow_after=600.0,
                       slow_note=("идёт долго. На процессоре medium считает примерно "
                                  "впятеро дольше small, а при нехватке памяти — ещё "
                                  "дольше. Прервать можно, разметка пересчитается "
                                  "с другой моделью.")) as hb:
            try:
                result = model.align(audio_input, lyrics.plain_text(),
                                     language=language, original_split=True,
                                     progress_callback=hb.progress, verbose=None)
            except TypeError:
                # у старых сборок stable-ts этих параметров нет — отсчёт времени
                # всё равно останется, он идёт из самого Heartbeat
                result = model.align(audio_input, lyrics.plain_text(),
                                     language=language, original_split=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Whisper не смог запустить ffmpeg ({e}). Поставьте его в систему: "
            f"winget install Gyan.FFmpeg — и перезапустите командную строку."
        )

    rec: List[tuple] = []
    probs: List[float] = []
    for seg in result.segments:
        for w in (seg.words or []):
            key = normalize_token(w.word)
            if key:
                rec.append((key, float(w.start), float(w.end)))
                p = getattr(w, "probability", None)
                if p is not None:
                    probs.append(float(p))
    if not rec:
        raise RuntimeError(tr("Whisper returned no timed words at all",
                              "Whisper не вернул ни одного слова с таймингом"))

    matched = _apply_recognized(lyrics.words, rec)
    # Это НЕ проверка «тот ли текст»: align() натягивает переданный текст на звук
    # принудительно, поэтому слова всегда те же самые. Проверка ловит расхождение
    # в токенизации между нашим разбором и разбором Whisper — если её нет, такой
    # сбой молча превращает разметку в равномерную «простыню».
    if matched < 0.4:
        raise RuntimeError(tr(
            f"the words could not be matched to Whisper's output "
            f"({matched:.0%} matched) — looks like an incompatible stable-ts version",
            f"слова не удалось сопоставить с выводом Whisper (совпало {matched:.0%}) — "
            f"похоже на несовместимую версию stable-ts"))

    # А вот низкая уверенность уже намекает, что текст к записи не подходит
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

    # модель весит гигабайты — отпускаем её сразу, дальше она не нужна
    del result, model
    import gc
    gc.collect()

    _trim_leading_silence(lyrics)
    # Границы строк берутся из слов — без этого шага у строк ещё нет времён,
    # и чинилки сравнивали бы пустоту с пустотой.
    _fill_lines(lyrics, duration)
    repair_lines(lyrics, log=log)      # Whisper иногда роняет слово далеко от строки
    repair_order(lyrics, log=log)
    _fill_lines(lyrics, duration)      # после правок границы могли выйти за трек
    return lyrics


def _apply_recognized(words: List[Word], rec: List[tuple]) -> float:
    """Сопоставить наши слова с распознанными. Возвращает долю точных совпадений."""
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
        elif tag == "replace" and (i2 - i1) and (j2 - j1):
            # растягиваем найденный отрезок на наши слова пропорционально слогам
            t0, t1 = rec[j1][1], rec[j2 - 1][2]
            chunk = words[i1:i2]
            total = sum(w.syllables for w in chunk) or 1
            acc = 0.0
            for w in chunk:
                w.start = t0 + (t1 - t0) * acc / total
                acc += w.syllables
                w.end = t0 + (t1 - t0) * acc / total

    _interpolate_gaps(words)
    return exact / len(words) if words else 0.0


def _trim_leading_silence(lyrics: Lyrics, factor: float = 3.0) -> None:
    """Whisper приклеивает паузу перед фразой к её первому слову — подрезаем.

    Трогаем только первое слово строки и только когда оно неправдоподобно
    длинное: долгие распевы в середине и в конце строки остаются как есть.
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


def _interpolate_gaps(words: List[Word]) -> None:
    """Слова, которым не досталось времени (вставки в тексте), заполняем между соседями."""
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
    """Собрать обратно строки, у которых слова разъехались по времени.

    Внутри одной спетой строки многосекундных провалов между словами не бывает.
    Если такой есть — это промах выравнивания: слово улетело далеко от своих.
    Берём самое «весомое» скопление слов как настоящее место строки, а отбившиеся
    слова подтягиваем вплотную к нему, не трогая хорошо легшую середину.
    """
    fixed = 0
    for idx, ln in enumerate(lyrics.lines):
        ws = ln.words
        # времена могут быть ещё не проставлены — тогда чинить нечего
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

        # Какое скопление считать настоящим местом строки. Одного веса по слогам
        # мало: соседние строки задают окно, в которое эта обязана попасть.
        # Иначе можно подтянуть верное слово к ошибочным, а не наоборот.
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


def _spread(words: List[Word], start: float, end: float) -> None:
    total = sum(w.syllables for w in words) or 1
    span = max(end - start, 0.05)
    acc = 0.0
    for w in words:
        w.start = start + span * acc / total
        acc += w.syllables
        w.end = start + span * acc / total


def repair_order(lyrics: Lyrics, log: Log = _noop) -> int:
    """Убрать наложение строк друг на друга: конец строки не должен заходить
    за начало следующей, иначе подсветка перескакивает и путается."""
    fixed = conflicts = 0
    lines = [ln for ln in lyrics.lines
             if ln.words and ln.start is not None and ln.end is not None]
    for a, b in zip(lines, lines[1:]):
        if b.start < a.start:
            conflicts += 1        # строки идут не по порядку — подрезать бессмысленно
            continue
        if a.end <= b.start:
            continue
        last_word_end = a.words[-1].end if a.words else a.start
        new_end = b.start - 0.05
        # подрезаем только если это не рассечёт слова: калечить разметку нельзя
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
    """Границы строк из слов + санитария таймингов."""
    prev_end = 0.0
    for w in lyrics.words:
        if w.start is None:
            w.start = prev_end
        if w.end is None or w.end <= w.start:
            w.end = w.start + max(min_word, 0.16 * w.syllables)
        # Держим слово внутри трека. Порядок важен: сначала ограничиваем начало
        # так, чтобы осталось место на минимальную длительность, и только потом
        # конец — иначе растяжка до min_word вылезает за конец песни.
        w.start = min(max(w.start, 0.0), max(duration - min_word, 0.0))
        w.end = min(max(w.end, w.start + min_word), duration)
        if w.end <= w.start:
            w.end = min(w.start + min_word, duration)
        prev_end = w.end

    for ln in lyrics.lines:
        if not ln.words:
            continue
        ln.start = ln.words[0].start
        ln.end = ln.words[-1].end


def align(lyrics: Lyrics, audio_path: str, duration: float, engine: str = "auto",
          model_name: str = "medium", language: str = "ru",
          device: Optional[str] = None, log: Log = _noop) -> tuple:
    """Возвращает (lyrics, использованный_движок)."""
    if lyrics.has_manual_times:
        log(tr("The text already has [mm:ss.dd] timings — skipping alignment.",
            "В тексте уже есть тайминги [мм:сс.дд] — выравнивание пропускаю."))
        _spread_manual(lyrics, duration)
        return lyrics, "manual"

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
                                     language, device, log), "whisper"
            except Exception as e:
                if engine == "whisper":
                    raise
                log(tr(f"Whisper could not cope ({e}) → falling back to the loudness engine.",
                       f"Whisper не справился ({e}) → откатываюсь на энергетический движок."))
                engine = "energy"

    if engine == "none":
        _fill_lines(lyrics, duration)
        return lyrics, "none"

    return align_energy(lyrics, audio_path, duration, log), "energy"


def _spread_manual(lyrics: Lyrics, duration: float) -> None:
    """Есть время начала строк — раскидать слова внутри строки по слогам."""
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
