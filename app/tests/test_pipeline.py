#!/usr/bin/env python3
"""Самопроверка: генерирует тестовую «песню» и прогоняет через неё весь конвейер.

    python tests/test_pipeline.py

Нужен только ffmpeg. Нейросети не задействуются.
"""

import math
import os
import re
import struct
import sys
import tempfile
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kstudio import align as A
from kstudio import audio as AU
from kstudio import build as B
from kstudio import lyrics as L

# 6 фраз по 2,6 с с паузами между ними
PHRASES = [(2.0, 4.6), (5.0, 7.6), (8.0, 10.6), (11.0, 13.6), (16.0, 18.6), (19.0, 21.6)]
TEXT = """title: Тестовая песня
artist: Проверка Связи

[Куплет]
Раз два три четыре пять
Начинаем проверять
Как ложатся тут слова
Закружилась голова

[Припев]
Синий ветер над рекой
Забери меня с собой
"""

failures = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + (f" — {extra}" if extra else ""))
    if not cond:
        failures.append(name)


def make_song(path, dur=26.0, sr=22050):
    """Тон с вибрато на месте фраз + тихий «инструментал» фоном."""
    frames = bytearray()
    for i in range(int(sr * dur)):
        t = i / sr
        v = 0.06 * math.sin(2 * math.pi * 110 * t) + 0.04 * math.sin(2 * math.pi * 220 * t + 1)
        for a, b in PHRASES:
            if a <= t < b:
                f = 300 + 120 * math.sin(2 * math.pi * 0.9 * (t - a))
                env = min(1.0, (t - a) / 0.08, (b - t) / 0.12)
                v += 0.42 * env * math.sin(2 * math.pi * f * t)
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
    w = wave.open(path, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(bytes(frames)); w.close()


def shutil_rm(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)



def _voc_checks():
    """Официальный инструментал почти всегда сведён иначе, чем песня.

    Проверяем на собранной паре: одна и та же аранжировка, но у «официального»
    минуса другой уровень и другая эквализация. Одной громкостью такое не
    гасится — должно спасать выравнивание по частотам. И, наоборот, чужая
    аранжировка приниматься не должна.
    """
    import importlib.util
    import math
    import tempfile
    import wave
    try:
        import numpy as np
    except ImportError:
        check("numpy есть (без него голос не выделить)", False)
        return

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sp = importlib.util.spec_from_file_location("studio", os.path.join(here, "studio.py"))
    st = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(st)

    tmp = tempfile.mkdtemp(prefix="karaoke_voc_")
    sr = 44100
    t = np.arange(int(sr * 24.0)) / sr
    rng = np.random.default_rng(7)

    click = ((t * 4) % 1 < 0.02).astype(np.float32)
    band = (0.35 * np.sin(2 * np.pi * 82.4 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * t))
            + 0.22 * np.sin(2 * np.pi * 220 * t) + 0.18 * np.sin(2 * np.pi * 329.6 * t)
            + 0.25 * click * rng.standard_normal(len(t))).astype(np.float32)
    voice = np.zeros_like(t, dtype=np.float32)
    for a, b in ((6.0, 11.0), (15.0, 20.0)):
        m = (t >= a) & (t < b)
        tt = t[m] - a
        voice[m] = (0.30 * np.sin(2 * np.pi * (196 + 18 * np.sin(2 * np.pi * 1.3 * tt)) * tt)
                    + 0.12 * np.sin(2 * np.pi * 392 * tt)).astype(np.float32)

    def other_master(x):
        X = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1 / sr)
        g = 1.6 / (1 + (f / 180) ** 2) ** 0.5 + 0.5 + 0.9 * np.exp(-((f - 3000) / 2500) ** 2)
        return (0.8 * np.fft.irfft(X * g, n=len(x))).astype(np.float32)

    def wr(name, x):
        path = os.path.join(tmp, name)
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
        return path

    def rd(path):
        with wave.open(path, "rb") as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768

    def rms(x, spans):
        m = np.zeros(len(x), dtype=bool)
        for a, b in spans:
            m[int(a * sr):int(b * sr)] = True
        return float(np.sqrt((x[m] ** 2).mean()))

    p_mix = wr("mix.wav", band + voice)
    p_off = wr("official.wav", other_master(band))
    alien = (0.3 * np.sin(2 * np.pi * 147 * t) + 0.2 * np.sin(2 * np.pi * 311 * t)
             + 0.05 * rng.standard_normal(len(t))).astype(np.float32)
    p_alien = wr("alien.wav", alien)

    quiet = [{"start": 0.5, "end": 5.5}, {"start": 11.5, "end": 14.5},
             {"start": 20.5, "end": 23.5}]
    spans = [(q["start"], q["end"]) for q in quiet]
    silent = lambda m: None

    got = st.extract_vocals(p_mix, p_off, 0.0, quiet, tmp, silent)
    check("голос выделен, хотя минус сведён иначе", bool(got))
    if got:
        v = rd(got)
        n = min(len(v), len(voice))
        drop = 20 * math.log10(rms((band + voice)[:n], spans) / max(rms(v[:n], spans), 1e-9))
        check("аранжировка подавлена не меньше чем на 20 дБ", drop > 20, f"{drop:.1f} дБ")
        sing = [(6.5, 10.5), (15.5, 19.5)]
        snr = 20 * math.log10(rms(voice[:n], sing) / max(rms(v[:n] - voice[:n], sing), 1e-9))
        check("сам голос при этом цел", snr > 15, f"{snr:.1f} дБ")

    check("чужая аранжировка отвергается",
          st.extract_vocals(p_mix, p_alien, 0.0, quiet, tmp, silent) is None)
    shutil_rm(tmp)


def main():
    # Проверки написаны по русским сообщениям, а язык теперь выбирается по
    # системе. Фиксируем русский, а отдельная проверка ниже смотрит английский.
    from kstudio import i18n
    i18n.set_lang("ru")

    print("Проверка разбора текста")
    lyr = L.parse(TEXT)
    check("6 строк", len(lyr.lines) == 6, f"получено {len(lyr.lines)}")
    check("мета-поля", lyr.title == "Тестовая песня" and lyr.artist == "Проверка Связи")
    check("секции", [l.section for l in lyr.lines].count(None) == 4)
    check("секция у первой строки", lyr.lines[0].section == "Куплет")
    # для русского счёт точный — по гласным
    check("слоги: 'четыре' = 3", L.count_syllables("четыре") == 3)
    check("слоги: 'ёж' = 1", L.count_syllables("ёж") == 1)
    check("слоги: 'закружилась' = 4", L.count_syllables("Закружилась") == 4)
    check("слоги: 'с' = 1", L.count_syllables("с") == 1)
    # для английского — эвристика по группам гласных, на заимствованиях врёт
    check("слоги: 'hello' = 2", L.count_syllables("hello") == 2)
    check("слоги: 'beautiful' = 3", L.count_syllables("beautiful") == 3)
    check("слоги: 'love' = 1 (немая -e)", L.count_syllables("love") == 1)
    check("нормализация", L.normalize_token("«Всё!»") == "все")

    print("\nПроверка строк в скобках — это подпевка, а не заголовок")
    back = L.parse("""[Куплет]
Обычная строка
(а это бэк-вокал)
Припев (эхо) поётся
(ла-ла-ла)
(Припев)
Строка припева
(Chorus 2)
Ещё одна""")
    texts = [ln.text for ln in back.lines]
    check("строки в скобках не выброшены", "(а это бэк-вокал)" in texts, str(texts))
    check("и звукоподражания тоже", "(ла-ла-ла)" in texts)
    check("они помечены как подпевка",
          [ln.backing for ln in back.lines if ln.text == "(ла-ла-ла)"] == [True])
    check("обычная строка подпевкой не считается",
          [ln.backing for ln in back.lines if ln.text == "Обычная строка"] == [False])
    check("скобки внутри строки ничего не ломают",
          "Припев (эхо) поётся" in texts)
    check("(Припев) остался заголовком раздела",
          any(ln.section == "Припев" for ln in back.lines),
          str([ln.section for ln in back.lines]))
    check("(Chorus 2) тоже заголовок",
          any(ln.section == "Chorus 2" for ln in back.lines))
    check("[Куплет] по-прежнему заголовок", back.lines[0].section == "Куплет")
    check("признак подпевки попадает в данные плеера",
          back.lines[1].to_json().get("backing") is True)
    check("подпевка сразу считается вторым голосом",
          back.lines[1].to_json().get("voice") == 2)
    check("обычная строка поётся основным голосом",
          [ln.voice for ln in back.lines if ln.text == "Обычная строка"] == [1])

    print("\nПроверка языка сообщений программы")
    from kstudio import i18n as _i18n, models as _M, sysinfo as _SI, build as _B
    _i18n.set_lang("en")
    check("подпись движка по-английски", _B.ENGINE_LABEL.get("energy", "?") ==
          "timing by loudness", _B.ENGINE_LABEL.get("energy", "?"))
    check("размер модели в MB", _M.size_label("small") == "480 MB", _M.size_label("small"))
    check("совет про память по-английски",
          "Not enough memory" in _SI.memory_advice(6.0, 2.0),
          _SI.memory_advice(6.0, 2.0)[:40])
    check("в английском выводе нет кириллицы",
          not re.search("[А-Яа-яЁё]", _SI.memory_advice(6.0, 2.0) + _M.load_note("small")),
          _M.load_note("small"))
    _i18n.set_lang("ru")
    check("по-русски всё возвращается", _B.ENGINE_LABEL.get("energy", "?") ==
          "разметка по энергии", _B.ENGINE_LABEL.get("energy", "?"))
    check("и размер модели снова в МБ", _M.size_label("small") == "480 МБ",
          _M.size_label("small"))

    print("\nПроверка читаемости выбранных цветов")
    from kstudio import build as _B
    check("чёрное на белом — предел различимости",
          round(_B.contrast("#000000", "#ffffff"), 1) == 21.0)
    _t, _fixed = _B.readable("#0a0b14", "#e8ebf5")
    check("хорошую пару не трогаем", _t == "#e8ebf5" and not _fixed, _t)
    _t, _fixed = _B.readable("#fdf6e3", "#f5efdc")
    check("сливающиеся буквы правим", _fixed and _B.contrast("#fdf6e3", _t) >= 4.5,
          f"{_t} → {_B.contrast('#fdf6e3', _t):.1f}")
    _t, _ = _B.readable("#101010", "#202020")
    check("на тёмном фоне буквы светлеют", _B.contrast("#101010", _t) >= 4.5,
          f"{_t} → {_B.contrast('#101010', _t):.1f}")
    check("мусор вместо цвета ничего не ломает",
          _B.theme_colors(["не цвет", None])[0]["bg"] == "не цвет")

    print("\nПроверка пометок в тексте: голос и повторы")
    from kstudio.lyrics import parse as _parse
    marked = _parse(
        "title: Проба\n\n[Куплет]\nОбычная строка\n2: Эту поёт второй\n"
        "(а это подпевка)\nПрипев x3\n[голос 2]\nТеперь всё вторым\n"
        "[голос 1]\nИ снова первым\nДва слова х2\nСтрока про x-files\n")
    texts = [l.text for l in marked.lines]
    voices = [l.voice for l in marked.lines]
    check("«2:» задаёт голос строке", voices[1] == 2 and texts[1] == "Эту поёт второй",
          f"{voices[1]} «{texts[1]}»")
    check("сама пометка в текст не попала", not any(t.startswith("2:") for t in texts),
          " | ".join(texts))
    check("подпевка по-прежнему второй голос", voices[2] == 2)
    check("«x3» разложилось в три строки",
          texts.count("Припев") == 3, " | ".join(texts))
    check("у повторов голос от переключателя", set(voices[3:6]) == {1}, str(voices[3:6]))
    check("[голос 2] переключает следующие", voices[6] == 2, str(voices[6]))
    check("[голос 1] возвращает обратно", voices[7] == 1, str(voices[7]))
    check("раздел не размножается вместе с повторами",
          [l.section for l in marked.lines].count("Куплет") == 1,
          str([l.section for l in marked.lines]))
    check("русская «х2» тоже понимается", texts.count("Два слова") == 2, " | ".join(texts))
    check("«x-files» повтором не считается", "Строка про x-files" in texts,
          " | ".join(texts))
    lrc = _parse("[00:10.00] Строка x2\n[00:20.00] Другая\n")
    check("при ручных таймингах повторы не раскрываются",
          [l.text for l in lrc.lines] == ["Строка x2", "Другая"],
          str([l.text for l in lrc.lines]))

    print("\nПроверка выделения голоса под чужой мастеринг")
    _voc_checks()

    print("\nПроверка кусков, которые поёт оригинал")
    import importlib.util as _iu0
    _here0 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sp0 = _iu0.spec_from_file_location("video", os.path.join(_here0, "tools", "video.py"))
    _vid = _iu0.module_from_spec(_sp0); _sp0.loader.exec_module(_vid)
    pay = {"data": {"lines": [
        {"start": 1.0, "end": 3.0},
        {"start": 3.0, "end": 5.0, "keep": True},
        {"start": 5.1, "end": 7.0, "keep": True},   # рядом — это один кусок
        {"start": 20.0, "end": 22.0, "keep": True},
        {"start": 9.0, "end": 9.0, "keep": True},   # пустая — не кусок
    ]}}
    spans = _vid.keep_spans(pay)
    check("соседние отмеченные строки склеены в один кусок",
          spans == [(3.0, 7.0), (20.0, 22.0)], str(spans))
    check("строка без длины куском не считается",
          all(b > a for a, b in spans), str(spans))
    check("без пометок кусков нет", _vid.keep_spans({"data": {"lines": [{"start": 0, "end": 2}]}}) == [])

    print("\nПроверка настроек: цвет — не примечание")
    import importlib.util as _iu
    import tempfile as _tf
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _sp = _iu.spec_from_file_location("auto", os.path.join(here, "tools", "auto.py"))
    _auto = _iu.module_from_spec(_sp); _sp.loader.exec_module(_auto)
    ini = os.path.join(_tf.mkdtemp(prefix="karaoke_ini_"), "settings.ini")
    open(ini, "w", encoding="utf-8").write(
        "# примечание целой строкой\n"
        "цвета = #4de1ff,#ff8ad1\n"
        "кодек = mp3   # а это уже примечание\n")
    _auto.SETTINGS = ini
    got = _auto.read_settings()
    check("цвета прочитаны целиком", got[got.index("--colors") + 1] == "#4de1ff,#ff8ad1",
          " ".join(got))
    check("примечание после значения отрезано",
          got[got.index("--codec") + 1] == "mp3", " ".join(got))

    print("\nПроверка кодировок файла с текстом")
    # Блокнот на русской Windows умеет сохранять в ANSI и UTF-16 — без этого
    # программа падала с невразумительной ошибкой на ровном месте
    sample = "Раз два\nтри четыре"
    for name, raw in (("UTF-8", sample.encode("utf-8")),
                      ("UTF-8 с BOM", sample.encode("utf-8-sig")),
                      ("cp1251 (ANSI)", sample.encode("cp1251")),
                      ("UTF-16", sample.encode("utf-16")),
                      ("UTF-16 BE", b"\xfe\xff" + sample.encode("utf-16-be"))):
        got = L.parse(L.decode_text(raw))
        check(f"читается {name}",
              len(got.lines) == 2 and got.lines[0].text == "Раз два",
              got.lines[0].text if got.lines else "пусто")

    print("\nПроверка сопоставления с распознанным текстом")
    # Whisper отдаёт слова с ведущим пробелом. Если его не срезать, не совпадёт
    # ни один токен, и разметка молча выродится в равномерную раскладку.
    check("ведущий пробел срезается", L.normalize_token(" Раз") == "раз",
          repr(L.normalize_token(" Раз")))
    check("неразрывный пробел тоже", L.normalize_token(" два ") == "два")

    src = L.parse("Раз два три\nчетыре пять")
    rec = [(" раз", 0.0, 0.4), (" два", 0.4, 0.8), (" три", 0.8, 1.4),
           (" четыре", 2.0, 2.6), (" пять", 2.6, 3.0)]
    rec = [(L.normalize_token(t), a, b) for t, a, b in rec]
    ratio = A._apply_recognized(src.words, rec)
    check("совпало 100 % слов", ratio == 1.0, f"{ratio:.0%}")
    check("время взято из распознанного",
          src.words[3].start == 2.0 and src.words[3].end == 2.6,
          f"{src.words[3].start}–{src.words[3].end}")

    other = L.parse("Совершенно другой текст песни")
    bad = A._apply_recognized(other.words, rec)
    check("чужой текст даёт низкую долю совпадений", bad < 0.4, f"{bad:.0%}")

    # Whisper приклеивает паузу перед фразой к её первому слову
    long_first = L.parse("Раз два три")
    long_first.words[0].start, long_first.words[0].end = 0.0, 2.2
    for w, (a, b) in zip(long_first.words[1:], [(2.2, 2.5), (2.5, 2.8)]):
        w.start, w.end = a, b
    A._trim_leading_silence(long_first)
    check("тишина перед первым словом подрезана",
          1.5 < long_first.words[0].start < 1.9, f"{long_first.words[0].start:.2f}с")

    held = L.parse("Раз два")
    held.words[0].start, held.words[0].end = 5.0, 5.9   # обычное слово, не трогаем
    held.words[1].start, held.words[1].end = 5.9, 6.2
    A._trim_leading_silence(held)
    check("нормальное первое слово не трогаем", held.words[0].start == 5.0)

    print("\nПроверка сборки разъехавшихся строк")
    # Whisper иногда роняет одно слово далеко от остальных слов своей строки.
    # Внутри спетой строки многосекундных провалов быть не может.
    broken = L.parse("Первая строка тут одна\nВторая строка потом")
    for w, (t, d) in zip(broken.lines[0].words,
                         [(150.2, 0.12), (165.8, 0.8), (166.6, 0.4), (167.0, 0.6)]):
        w.start, w.end = t, t + d
    broken.lines[0].start, broken.lines[0].end = 150.2, 167.6
    for w, (t, d) in zip(broken.lines[1].words,
                         [(152.8, 0.6), (153.4, 0.5), (154.0, 0.3)]):
        w.start, w.end = t, t + d
    broken.lines[1].start, broken.lines[1].end = 152.8, 154.3

    A.repair_lines(broken)
    A.repair_order(broken)
    ws = [w for ln in broken.lines for w in ln.words]
    gaps = [b.start - a.end for ln in broken.lines
            for a, b in zip(ln.words, ln.words[1:])]
    check("провалы внутри строк убраны", max(gaps) < 1.2, f"макс {max(gaps):.2f}с")
    check("выбрано скопление, подходящее по соседям",
          abs(broken.lines[0].start - 150.2) < 0.01, f"{broken.lines[0].start:.2f}")
    check("строки не налезают друг на друга",
          all(a.end <= b.start + 1e-9
              for a, b in zip(broken.lines, broken.lines[1:])))
    check("слова остались по порядку",
          all(a.start <= b.start + 1e-9 for a, b in zip(ws, ws[1:])))
    check("длительности положительные", all(w.end > w.start for w in ws))

    # здоровую разметку чинилка трогать не должна
    healthy = L.parse("Раз два три\nчетыре пять")
    for w, (t, d) in zip(healthy.lines[0].words, [(1.0, .4), (1.4, .4), (1.8, .4)]):
        w.start, w.end = t, t + d
    healthy.lines[0].start, healthy.lines[0].end = 1.0, 2.2
    for w, (t, d) in zip(healthy.lines[1].words, [(3.0, .5), (3.5, .5)]):
        w.start, w.end = t, t + d
    healthy.lines[1].start, healthy.lines[1].end = 3.0, 4.0
    before = [(w.start, w.end) for w in healthy.words]
    A.repair_lines(healthy)
    A.repair_order(healthy)
    check("здоровая разметка не тронута",
          before == [(w.start, w.end) for w in healthy.words])

    print("\nПроверка LRC на входе")
    m = L.parse("[00:12.30]первая\n[01:05.50]вторая")
    check("тайминги распознаны", m.has_manual_times)
    check("время строк", abs(m.lines[0].start - 12.3) < 1e-6 and abs(m.lines[1].start - 65.5) < 1e-6,
          f"{m.lines[0].start}, {m.lines[1].start}")

    tmp = tempfile.mkdtemp(prefix="karaoke_test_")
    song = os.path.join(tmp, "song.wav")
    print("\nГенерирую тестовый звук…")
    make_song(song)

    try:
        AU.ffmpeg()
    except AU.AudioError as e:
        print(f"\nПропускаю проверки звука: {e}")
        return 1 if failures else 0

    print("\nПроверка выравнивания по энергии")
    dur = AU.duration(song)
    check("длительность 26 с", abs(dur - 26.0) < 0.2, f"{dur:.2f}")

    lyr = L.parse(TEXT)
    lyr, engine = A.align(lyr, song, dur, engine="energy")
    check("движок energy", engine == "energy")

    worst = 0.0
    for ln, (want, _) in zip(lyr.lines, PHRASES):
        worst = max(worst, abs(ln.start - want))
        print(f"    «{ln.text[:26]:26}» {ln.start:6.2f}с  (ожидалось {want:5.2f}с)")
    check("все строки точнее 0,4 с", worst < 0.4, f"худшее отклонение {worst:.2f}с")

    check("слова идут по порядку",
          all(a.start <= b.start for a, b in zip(lyr.words, lyr.words[1:])))
    check("ни одно слово не нулевой длины", all(w.end > w.start for w in lyr.words))
    check("всё внутри трека", all(0 <= w.start and w.end <= dur + 1e-6 for w in lyr.words))

    # Путь Whisper отличается от энергетического порядком шагов: границы строк
    # там появляются только из слов. Проверяем без самой модели — подсовываем
    # готовые времена слов, как их отдал бы Whisper.
    print("\nПроверка порядка шагов на пути Whisper")
    wl = L.parse(TEXT)
    t = 2.0
    for line in wl.lines:
        for w in line.words:
            w.start, w.end = t, t + 0.3
            t += 0.35
        t += 0.6
    # именно здесь раньше падало: у строк ещё не было start/end
    A._trim_leading_silence(wl)
    A._fill_lines(wl, dur)
    A.repair_lines(wl)
    A.repair_order(wl)
    A._fill_lines(wl, dur)
    check("границы строк заполнены из слов",
          all(l.start is not None and l.end is not None for l in wl.lines))
    check("строки по порядку",
          all(a.start <= b.start for a, b in zip(wl.lines, wl.lines[1:])))
    check("слова по порядку",
          all(a.start <= b.start + 1e-9 for a, b in zip(wl.words, wl.words[1:])))

    env, hop_env = AU.rms_envelope(song)

    print("\nПроверка сборки HTML")
    track = AU.encode(song, os.path.join(tmp, "a"), "mp3")
    html = os.path.join(tmp, "out.html")
    B.build_html(html, lyr, dur, {"mix": track}, engine, embed=True)
    body = open(html, encoding="utf-8").read()
    check("файл собран", os.path.getsize(html) > 50_000)
    check("звук встроен", "data:audio/mpeg;base64," in body)
    check("нет внешних ссылок", "http://" not in body and "https://" not in body)
    check("шаблон заполнен", "__PAYLOAD__" not in body and "__TITLE__" not in body)
    check("текст на месте", "Закружилась" in body)
    check("слоги переданы в плеер", '"s":' in body)

    lrc = os.path.join(tmp, "out.lrc")
    B.write_lrc(lrc, lyr)
    check("LRC записан", open(lrc, encoding="utf-8").read().count("\n") >= 8)

    print("\nПроверка обратной подстановки таймингов")
    lyr2 = L.parse(TEXT)
    import json
    tj = os.path.join(tmp, "t.json")
    json.dump({"lines": [{"text": l.text, "start": l.start + 1.5, "end": l.end + 1.5,
                          "words": [{"w": w.text, "t": w.start + 1.5, "d": w.end - w.start}
                                    for w in l.words]} for l in lyr.lines]},
              open(tj, "w"), ensure_ascii=False)
    B.apply_timings(lyr2, tj)
    check("сдвиг применился", abs(lyr2.lines[0].start - (lyr.lines[0].start + 1.5)) < 1e-6)

    print("\nПроверка точности сдвига при подмене минусовки")
    # Разметку двигают вслед за новой дорожкой, поэтому ошибка в поиске сдвига
    # сразу слышна. Шаг огибающей 10 мс, вершину уточняем параболой.
    import importlib
    import subprocess as _sp
    _studio = importlib.import_module("studio")
    worst = 0.0
    for ms in (250, 507, 1503):
        moved = os.path.join(tmp, f"сдвиг{ms}.wav")
        _sp.run(["ffmpeg", "-y", "-loglevel", "error", "-i", song,
                 "-af", f"adelay={ms}|{ms}", moved], check=True)
        ea, ha = AU.rms_envelope(song, hop_ms=10)
        eb, _hb = AU.rms_envelope(moved, hop_ms=10)
        got = _studio.offset_between(ea, eb, ha) * 1000
        worst = max(worst, abs(got - ms))
        check(f"сдвиг {ms} мс найден", abs(got - ms) < 8, f"получилось {got:.1f} мс")
    check("худшая ошибка меньше 8 мс", worst < 8, f"{worst:.1f} мс")
    check("на пустых данных сдвиг нулевой", _studio.offset_between([], [], 0.01) == 0.0)

    print("\nПроверка панели «Проверить»: только поломки, не вкусовщина")
    from kstudio import project as PRJ
    long_note = {"lines": [{"text": "а-а-а", "start": 0.0, "end": 9.0,
                            "words": [{"w": "а-а-а", "t": 0.0, "d": 9.0, "s": 3}]}],
                 "envelope": {}}
    check("долгая нота не считается ошибкой", PRJ.problems(long_note) == [],
          str(PRJ.problems(long_note)))
    tail = {"lines": [{"text": "конец строки", "start": 0.0, "end": 6.0,
                       "words": [{"w": "конец", "t": 0.0, "d": 0.5, "s": 2},
                                 {"w": "строки", "t": 0.5, "d": 5.5, "s": 2}]}],
            "envelope": {}}
    check("хвост в конце строки — тоже не ошибка", PRJ.problems(tail) == [],
          str(PRJ.problems(tail)))

    impossible = {"lines": [{"text": "очень много слогов подряд",
                             "start": 0.0, "end": 0.4,
                             "words": [{"w": "очень", "t": 0.0, "d": .1, "s": 2},
                                       {"w": "много", "t": 0.1, "d": .1, "s": 2},
                                       {"w": "слогов", "t": 0.2, "d": .1, "s": 2},
                                       {"w": "подряд", "t": 0.3, "d": .1, "s": 2}]}],
                  "envelope": {}}
    check("а физически неспетое — ошибка", len(PRJ.problems(impossible)) == 1,
          str(PRJ.problems(impossible)))

    overlap = {"lines": [{"text": "первая", "start": 0.0, "end": 5.0,
                          "words": [{"w": "первая", "t": 0.0, "d": 5.0, "s": 3}]},
                         {"text": "вторая", "start": 3.0, "end": 6.0,
                          "words": [{"w": "вторая", "t": 3.0, "d": 3.0, "s": 3}]}],
               "envelope": {}}
    check("налезающие строки по-прежнему видны",
          any("налезает" in w for p2 in PRJ.problems(overlap) for w in p2["why"]),
          str(PRJ.problems(overlap)))

    torn = {"lines": [{"text": "слова врозь", "start": 0.0, "end": 6.0,
                       "words": [{"w": "слова", "t": 0.0, "d": 0.4, "s": 2},
                                 {"w": "врозь", "t": 5.0, "d": 1.0, "s": 1}]}],
            "envelope": {}}
    check("разъехавшиеся слова внутри строки видны",
          any("разъехались" in w for p2 in PRJ.problems(torn) for w in p2["why"]),
          str(PRJ.problems(torn)))

    print("\nПроверка отчёта перед сборкой")
    from kstudio import report as REP

    def click_track(path, tempo, dur=24.0, sr=22050):
        """Ровные удары с известным темпом."""
        period, frames = 60.0 / tempo, bytearray()
        for i in range(int(sr * dur)):
            t = i / sr
            v = 0.03 * math.sin(2 * math.pi * 70 * t)
            d = t - round(t / period) * period
            if 0 <= d < 0.06:
                v += 0.8 * math.exp(-d * 60) * math.sin(2 * math.pi * 900 * t)
            frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
        w = wave.open(path, "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(bytes(frames)); w.close()

    # Автокорреляция сама по себе уверенно выдаёт вдвое медленнее — проверяем
    # именно быстрые темпы, на них это и вылезало.
    for tempo in (90, 120, 140, 175):
        p2 = os.path.join(tmp, f"click{tempo}.wav")
        click_track(p2, tempo)
        env2, hop2 = AU.rms_envelope(p2)
        got, conf = REP.bpm(env2, hop2)
        check(f"темп {tempo} уд/мин найден",
              got is not None and abs(got - tempo) < 3.5,
              f"получилось {got}")
        check(f"и уверенность у {tempo} высокая", conf > 0.5, f"{conf}")

    check("на тишине темп не выдумывается", REP.bpm([0.0] * 400, 0.02)[0] is None)

    # Где долго не поют — вступление, проигрыш, соло. Для караоке это важнее
    # темпа: туда строки попадать не должны.
    gap_song = os.path.join(tmp, "с_проигрышем.wav")
    old_phrases = list(A.__dict__.get("_", []))    # ничего не трогаем, просто пишем свой файл
    import wave as _w
    with _w.open(gap_song, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
        buf = bytearray()
        for i in range(int(22050 * 30)):
            t2 = i / 22050
            v = 0.02 * math.sin(2 * math.pi * 80 * t2)          # тихий фон
            singing = t2 < 8 or t2 > 20                          # с 8 по 20 — проигрыш
            if singing:
                v += 0.5 * math.sin(2 * math.pi * 350 * t2)
            buf += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
        f.writeframes(bytes(buf))
    genv, ghop = AU.rms_envelope(gap_song)
    quiet = REP.quiet_stretches(genv, ghop)
    check("длинный проигрыш найден", len(quiet) == 1, str(quiet))
    if quiet:
        check("и найден там, где он есть",
              abs(quiet[0]["start"] - 8) < 1.0 and abs(quiet[0]["end"] - 20) < 1.0,
              f"{quiet[0]['start']}–{quiet[0]['end']} вместо 8–20")
    check("короткие паузы между строками проигрышем не считаются",
          REP.quiet_stretches(env, hop_env) == [] or
          all(q["end"] - q["start"] >= 5 for q in REP.quiet_stretches(env, hop_env)),
          str(REP.quiet_stretches(env, hop_env)))
    check("на пустой огибающей не падает", REP.quiet_stretches([], 0.02) == [])

    grep = REP.build(gap_song, lyr, 30.0, genv, ghop, separate=False)
    check("проигрыш попал в отчёт", len(grep["audio"]["quiet"]) == 1,
          str(grep["audio"]["quiet"]))
    check("и о нём сказано словами",
          any("без пения" in n.lower() for n in grep["notes"]), str(grep["notes"]))
    check("в текстовом отчёте он тоже есть",
          "Без пения" in REP.as_text(grep))
    check("на пустой огибающей не падает", REP.bpm([], 0.02) == (None, 0.0))

    rep = REP.build("песня.mp3", lyr, 26.0, env, hop_env,
                    model="small", separate=False, whisper=True, language="auto")
    check("в отчёте есть длина", rep["audio"]["duration"] == 26.0)
    check("в отчёте есть текст", rep["text"]["lines"] == 6 and rep["text"]["words"] == 21,
          str(rep["text"]))
    check("разделы перечислены", rep["text"]["sections"] == ["Куплет", "Припев"],
          str(rep["text"]["sections"]))
    check("язык определён и назван", rep["language"]["code"] == "ru" and
          rep["language"]["auto"] is True)
    check("оценка времени положительная", rep["plan"]["seconds"] > 0)
    check("оценка честно помечена грубой", rep["plan"]["rough"] is True)
    check("текстовый вид собирается", "Отчёт перед сборкой" in REP.as_text(rep))

    # Текст не от этой песни: строк мало на длинную запись — это надо сказать
    short = L.parse("Одна одинокая строка")
    rep2 = REP.build("длинная.mp3", short, 300.0, env, hop_env, separate=False)
    check("мало строк на долгую песню — предупреждение есть",
          any("повтор" in n or "много" in n for n in rep2["notes"]),
          str(rep2["notes"]))
    check("время на большую песню считается больше",
          rep2["plan"]["seconds"] > rep["plan"]["seconds"])

    print("\nПроверка определения языка по тексту")
    from kstudio import lang as LG
    songs = {
        "ru": "Раз два три четыре пять\nНачинаем проверять",
        "uk": "Ой у лузі червона калина\nПохилилася додолу",
        "en": "Yesterday all my troubles seemed so far away",
        "de": "Über den Wolken muss die Freiheit wohl grenzenlos sein",
        "fr": "Non, je ne regrette rien\nNi le bien qu'on m'a fait",
        "es": "Bésame, bésame mucho\nComo si fuera esta noche",
        "it": "Nel blu dipinto di blu\nfelice di stare lassù",
        "pl": "Hej, sokoły! Omijajcie góry, lasy, doły",
        "ja": "上を向いて歩こう",
        "ko": "아리랑 아리랑 아라리요",
        "zh": "月亮代表我的心",
    }
    for want, text in songs.items():
        got = LG.detect(text)
        check(f"{LG.label(want)} узнаётся", got == want, f"определилось как {got}")
    check("пустой текст не роняет", LG.detect("") == "en")
    check("только знаки препинания не роняют", LG.detect("... !!! ???") in LG.NAMES)
    check("«auto» превращается в язык текста",
          LG.resolve("auto", songs["uk"]) == "uk")
    check("заданный руками язык не подменяется",
          LG.resolve("en", songs["ru"]) == "en")
    check("у каждого языка есть человеческое название",
          all(LG.label(c) and LG.label(c) != c for c in LG.NAMES))

    print("\nПроверка: окно и лог одинаково знают про модели")
    import tempfile as _tf

    from kstudio import models as MM
    fake = _tf.mkdtemp(prefix="cache_")
    old_xdg = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = fake
    try:
        wd = MM.whisper_dir()
        os.makedirs(wd, exist_ok=True)
        check("модели ещё нет", MM.whisper_ready("medium") is False)
        check("про отсутствующую сказано «скачиваю»",
              MM.load_note("medium").startswith("Скачиваю") and
              "1,5 ГБ" in MM.load_note("medium"))
        check("и шаг называется скачиванием", "скачивание" in MM.step_label("medium"))

        with open(os.path.join(wd, "medium.pt"), "wb") as f:
            f.write(b"0" * 2_000_000)
        check("модель на диске найдена", MM.whisper_ready("medium") is True)
        check("про скачанную не обещают качать",
              "уже на диске" in MM.load_note("medium") and
              "Скачиваю" not in MM.load_note("medium"))
        check("и шаг называется загрузкой", "загрузка" in MM.step_label("medium"))

        # огрызок недокачанного файла моделью считаться не должен
        with open(os.path.join(wd, "small.pt"), "wb") as f:
            f.write(b"0" * 1000)
        check("недокачанный файл за модель не считается",
              MM.whisper_ready("small") is False)
        check("список для окна совпадает с тем, что скажет лог",
              MM.whisper_all()["medium"] is True and
              MM.whisper_all()["small"] is False)
    finally:
        if old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = old_xdg
        shutil_rm(fake)

    print("\nПроверка признаков жизни на долгих шагах")
    import time

    from kstudio.progress import Heartbeat, mmss
    check("время читается", (mmss(0), mmss(75)) == ("0:00", "1:15"))
    beats = []
    with Heartbeat(beats.append, "проверка", every=0.2) as hb:
        time.sleep(0.3)
        hb.progress(3, 10)
        hb.note("Demucs: 40%")
        time.sleep(0.3)
    check("шаг подаёт признаки жизни", len(beats) >= 2)
    check("доля сделанного видна", any("30%" in b for b in beats))
    check("приписка шага видна", any("Demucs: 40%" in b for b in beats))
    before = len(beats)
    time.sleep(0.4)
    check("после выхода молчит", len(beats) == before)

    # Признак жизни не имеет права уронить сам шаг: если лог падает — молчим.
    def bad_log(_):
        raise RuntimeError("лог сломан")

    with Heartbeat(bad_log, "стойкость", every=0.1):
        time.sleep(0.3)
    check("сломанный лог не роняет шаг", True)

    # Нулевой и полный счётчик не сообщают ничего — долю тогда не показываем.
    beats2 = []
    with Heartbeat(beats2.append, "без счёта", every=0.15) as hb2:
        hb2.progress(0, 26)
        time.sleep(0.2)
    check("пустой счётчик не показывается", beats2 and "%" not in beats2[0])

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("ПРОВАЛЕНО: " + ", ".join(failures) if failures else "Все проверки пройдены"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
