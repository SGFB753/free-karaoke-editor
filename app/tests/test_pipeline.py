#!/usr/bin/env python3
"""Self-check: makes a test “song” and runs the whole pipeline over it.

    python tests/test_pipeline.py

Нужен только ffmpeg. Нейросети не задействуются.
"""

import json
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

# 6 phrases of 2.6 s with pauses between them
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
    """A vibrato tone where the phrases are, plus a quiet “instrumental”."""
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
    """An official instrumental is almost never mixed like the song itself.

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
        check("numpy is here (no voice extraction without it)", False)
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
    check("the voice was extracted though the instrumental is mixed differently", bool(got))
    if got:
        v = rd(got)
        n = min(len(v), len(voice))
        drop = 20 * math.log10(rms((band + voice)[:n], spans) / max(rms(v[:n], spans), 1e-9))
        check("the arrangement is suppressed by at least 20 dB", drop > 20, f"{drop:.1f} dB")
        sing = [(6.5, 10.5), (15.5, 19.5)]
        snr = 20 * math.log10(rms(voice[:n], sing) / max(rms(v[:n] - voice[:n], sing), 1e-9))
        check("and the voice itself is intact", snr > 15, f"{snr:.1f} dB")

    check("a foreign arrangement is refused",
          st.extract_vocals(p_mix, p_alien, 0.0, quiet, tmp, silent) is None)
    shutil_rm(tmp)


def main():
    # These checks are written against the Russian messages, and the language
    # now follows the system. Pin Russian; a check below looks at English.
    from kstudio import i18n
    i18n.set_lang("ru")

    print("Parsing the lyrics")
    lyr = L.parse(TEXT)
    check("6 lines", len(lyr.lines) == 6, f"got {len(lyr.lines)}")
    check("the meta fields", lyr.title == "Тестовая песня" and lyr.artist == "Проверка Связи")
    check("sections", [l.section for l in lyr.lines].count(None) == 4)
    check("the first line carries its section", lyr.lines[0].section == "Куплет")
    # for Russian the count is exact — by vowels
    check("syllables: 'четыре' = 3", L.count_syllables("четыре") == 3)
    check("syllables: 'ёж' = 1", L.count_syllables("ёж") == 1)
    check("syllables: 'закружилась' = 4", L.count_syllables("Закружилась") == 4)
    check("syllables: 'с' = 1", L.count_syllables("с") == 1)
    # for English it is a vowel-group heuristic; it lies on loanwords
    check("syllables: 'hello' = 2", L.count_syllables("hello") == 2)
    check("syllables: 'beautiful' = 3", L.count_syllables("beautiful") == 3)
    check("syllables: 'love' = 1 (silent -e)", L.count_syllables("love") == 1)
    # The endings that lie, and they are what a sung line trips over: an even
    # split gives “lit-tle” one beat and “walk-ed” two, both wrong.
    check("syllables: a consonant before -le makes a syllable",
          L.count_syllables("little") == 2 and L.count_syllables("people") == 2
          and L.count_syllables("table") == 2,
          f'little={L.count_syllables("little")} people={L.count_syllables("people")}')
    check("syllables: -ed is silent, except after t and d",
          L.count_syllables("walked") == 1 and L.count_syllables("danced") == 1
          and L.count_syllables("wanted") == 2 and L.count_syllables("agreed") == 2,
          f'walked={L.count_syllables("walked")} wanted={L.count_syllables("wanted")}')
    check("syllables: a plural -es does not add a beat to “makes”",
          L.count_syllables("makes") == 1 and L.count_syllables("houses") == 2
          and L.count_syllables("watches") == 2,
          f'makes={L.count_syllables("makes")} houses={L.count_syllables("houses")}')
    check("syllables: a long word still outweighs a short one",
          L.count_syllables("beautiful") > L.count_syllables("I") * 2)
    check("normalisation", L.normalize_token("«Всё!»") == "все")

    print("\nLines in brackets are backing vocals, not a heading")
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
    check("lines in brackets were not dropped", "(а это бэк-вокал)" in texts, str(texts))
    check("and neither were the sung syllables", "(ла-ла-ла)" in texts)
    check("they are marked as backing vocals",
          [ln.backing for ln in back.lines if ln.text == "(ла-ла-ла)"] == [True])
    check("an ordinary line does not count as backing",
          [ln.backing for ln in back.lines if ln.text == "Обычная строка"] == [False])
    check("brackets inside a line break nothing",
          "Припев (эхо) поётся" in texts)
    check("(Припев) stayed a section heading",
          any(ln.section == "Припев" for ln in back.lines),
          str([ln.section for ln in back.lines]))
    check("(Chorus 2) is a heading too",
          any(ln.section == "Chorus 2" for ln in back.lines))
    check("[Куплет] is still a heading", back.lines[0].section == "Куплет")
    check("the backing flag reaches the player data",
          back.lines[1].to_json().get("backing") is True)
    check("backing counts as the second voice at once",
          back.lines[1].to_json().get("voice") == 2)
    check("an ordinary line is sung by the main voice",
          [ln.voice for ln in back.lines if ln.text == "Обычная строка"] == [1])

    print("\nThe language of the program's messages")
    from kstudio import i18n as _i18n, models as _M, sysinfo as _SI, build as _B
    _i18n.set_lang("en")
    check("the engine label is in English", _B.ENGINE_LABEL.get("energy", "?") ==
          "timing by loudness", _B.ENGINE_LABEL.get("energy", "?"))
    check("the model size in MB", _M.size_label("small") == "480 MB", _M.size_label("small"))
    check("the memory advice is in English",
          "Not enough memory" in _SI.memory_advice(6.0, 2.0),
          _SI.memory_advice(6.0, 2.0)[:40])
    check("no Cyrillic in the English output",
          not re.search("[А-Яа-яЁё]", _SI.memory_advice(6.0, 2.0) + _M.load_note("small")),
          _M.load_note("small"))
    _i18n.set_lang("ru")
    check("in Russian everything comes back", _B.ENGINE_LABEL.get("energy", "?") ==
          "разметка по энергии", _B.ENGINE_LABEL.get("energy", "?"))
    check("and the model size is in МБ again", _M.size_label("small") == "480 МБ",
          _M.size_label("small"))

    print("\nReadability of the chosen colours")
    from kstudio import build as _B
    check("black on white is the limit of contrast",
          round(_B.contrast("#000000", "#ffffff"), 1) == 21.0)
    _t, _fixed = _B.readable("#0a0b14", "#e8ebf5")
    check("a good pair is left alone", _t == "#e8ebf5" and not _fixed, _t)
    _t, _fixed = _B.readable("#fdf6e3", "#f5efdc")
    check("blending letters are corrected", _fixed and _B.contrast("#fdf6e3", _t) >= 4.5,
          f"{_t} → {_B.contrast('#fdf6e3', _t):.1f}")
    _t, _ = _B.readable("#101010", "#202020")
    check("on a dark background the letters lighten", _B.contrast("#101010", _t) >= 4.5,
          f"{_t} → {_B.contrast('#101010', _t):.1f}")
    check("garbage instead of a colour breaks nothing",
          _B.theme_colors(["не цвет", None])[0]["bg"] == "не цвет")

    print("\nMarks in the text: voice and repeats")
    from kstudio.lyrics import parse as _parse
    marked = _parse(
        "title: Проба\n\n[Куплет]\nОбычная строка\n2: Эту поёт второй\n"
        "(а это подпевка)\nПрипев x3\n[голос 2]\nТеперь всё вторым\n"
        "[голос 1]\nИ снова первым\nДва слова х2\nСтрока про x-files\n")
    texts = [l.text for l in marked.lines]
    voices = [l.voice for l in marked.lines]
    check("“2:” sets the voice of a line", voices[1] == 2 and texts[1] == "Эту поёт второй",
          f"{voices[1]} «{texts[1]}»")
    check("the mark itself did not reach the text", not any(t.startswith("2:") for t in texts),
          " | ".join(texts))
    check("backing is still the second voice", voices[2] == 2)
    check("“x3” expanded into three lines",
          texts.count("Припев") == 3, " | ".join(texts))
    check("the repeats take the voice from the switch", set(voices[3:6]) == {1}, str(voices[3:6]))
    check("[голос 2] switches the lines that follow", voices[6] == 2, str(voices[6]))
    check("[голос 1] switches back", voices[7] == 1, str(voices[7]))
    check("the section is not repeated along with the line",
          [l.section for l in marked.lines].count("Куплет") == 1,
          str([l.section for l in marked.lines]))
    check("the Russian “х2” is understood too", texts.count("Два слова") == 2, " | ".join(texts))
    check("“x-files” does not count as a repeat", "Строка про x-files" in texts,
          " | ".join(texts))
    lrc = _parse("[00:10.00] Строка x2\n[00:20.00] Другая\n")
    check("with manual timings repeats are left alone",
          [l.text for l in lrc.lines] == ["Строка x2", "Другая"],
          str([l.text for l in lrc.lines]))

    print("\nExtracting the voice against a foreign master")
    _voc_checks()

    print("\nStretches the original sings")
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
    check("adjacent marked lines are glued into one stretch",
          spans == [(3.0, 7.0), (20.0, 22.0)], str(spans))
    check("a line with no length is not a stretch",
          all(b > a for a, b in spans), str(spans))
    check("without marks there are no stretches", _vid.keep_spans({"data": {"lines": [{"start": 0, "end": 2}]}}) == [])

    print("\nSettings: a colour is not a comment")
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
    check("the colours were read whole", got[got.index("--colors") + 1] == "#4de1ff,#ff8ad1",
          " ".join(got))
    check("a comment after the value is cut off",
          got[got.index("--codec") + 1] == "mp3", " ".join(got))

    print("\nEncodings of the lyrics file")
    # Notepad on a Russian Windows saves in ANSI and UTF-16 — without this the
    # program used to die with a baffling error for no visible reason
    sample = "Раз два\nтри четыре"
    for name, raw in (("UTF-8", sample.encode("utf-8")),
                      ("UTF-8 с BOM", sample.encode("utf-8-sig")),
                      ("cp1251 (ANSI)", sample.encode("cp1251")),
                      ("UTF-16", sample.encode("utf-16")),
                      ("UTF-16 BE", b"\xfe\xff" + sample.encode("utf-16-be"))):
        got = L.parse(L.decode_text(raw))
        check(f"{name} is read",
              len(got.lines) == 2 and got.lines[0].text == "Раз два",
              got.lines[0].text if got.lines else "пусто")

    print("\nMatching against the recognised text")
    # Whisper returns words with a leading space. Without trimming it not a
    # single token matches and the timing silently becomes an even blanket.
    check("a leading space is trimmed", L.normalize_token(" Раз") == "раз",
          repr(L.normalize_token(" Раз")))
    check("a non-breaking space too", L.normalize_token(" два ") == "два")

    src = L.parse("Раз два три\nчетыре пять")
    rec = [(" раз", 0.0, 0.4), (" два", 0.4, 0.8), (" три", 0.8, 1.4),
           (" четыре", 2.0, 2.6), (" пять", 2.6, 3.0)]
    rec = [(L.normalize_token(t), a, b) for t, a, b in rec]
    ratio = A._apply_recognized(src.words, rec)
    check("100 % of the words matched", ratio == 1.0, f"{ratio:.0%}")
    check("the times came from what was recognised",
          src.words[3].start == 2.0 and src.words[3].end == 2.6,
          f"{src.words[3].start}–{src.words[3].end}")

    other = L.parse("Совершенно другой текст песни")
    bad = A._apply_recognized(other.words, rec)
    check("a foreign text gives a low match rate", bad < 0.4, f"{bad:.0%}")

    # Whisper glues the pause before a phrase onto its first word
    long_first = L.parse("Раз два три")
    long_first.words[0].start, long_first.words[0].end = 0.0, 2.2
    for w, (a, b) in zip(long_first.words[1:], [(2.2, 2.5), (2.5, 2.8)]):
        w.start, w.end = a, b
    A._trim_leading_silence(long_first)
    check("the silence before the first word is trimmed",
          1.5 < long_first.words[0].start < 1.9, f"{long_first.words[0].start:.2f}s")

    held = L.parse("Раз два")
    held.words[0].start, held.words[0].end = 5.0, 5.9   # обычное слово, не трогаем
    held.words[1].start, held.words[1].end = 5.9, 6.2
    A._trim_leading_silence(held)
    check("a normal first word is left alone", held.words[0].start == 5.0)

    print("\nPutting drifted lines back together")
    # Whisper sometimes drops one word far from the rest of its line.
    # Inside a sung line there can be no multi-second gaps.
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
    check("the gaps inside lines are gone", max(gaps) < 1.2, f"max {max(gaps):.2f}s")
    check("the cluster that fits the neighbours was chosen",
          abs(broken.lines[0].start - 150.2) < 0.01, f"{broken.lines[0].start:.2f}")
    check("the lines do not overlap",
          all(a.end <= b.start + 1e-9
              for a, b in zip(broken.lines, broken.lines[1:])))
    check("the words stayed in order",
          all(a.start <= b.start + 1e-9 for a, b in zip(ws, ws[1:])))
    check("the durations are positive", all(w.end > w.start for w in ws))

    # the repair must not touch sound timing
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
    check("sound timing is left untouched",
          before == [(w.start, w.end) for w in healthy.words])

    print("\nLRC on the input")
    m = L.parse("[00:12.30]первая\n[01:05.50]вторая")
    check("the timings were recognised", m.has_manual_times)
    check("the line times", abs(m.lines[0].start - 12.3) < 1e-6 and abs(m.lines[1].start - 65.5) < 1e-6,
          f"{m.lines[0].start}, {m.lines[1].start}")

    tmp = tempfile.mkdtemp(prefix="karaoke_test_")
    song = os.path.join(tmp, "song.wav")
    print("\nGenerating the test audio…")
    make_song(song)

    try:
        AU.ffmpeg()
    except AU.AudioError as e:
        print(f"\nSkipping the audio checks: {e}")
        return 1 if failures else 0

    print("\nAlignment by loudness")
    dur = AU.duration(song)
    check("the length is 26 s", abs(dur - 26.0) < 0.2, f"{dur:.2f}")

    lyr = L.parse(TEXT)
    lyr, engine = A.align(lyr, song, dur, engine="energy")
    check("the energy engine", engine == "energy")

    worst = 0.0
    for ln, (want, _) in zip(lyr.lines, PHRASES):
        worst = max(worst, abs(ln.start - want))
        print(f"    “{ln.text[:26]:26}” {ln.start:6.2f}s  (expected {want:5.2f}s)")
    check("every line is within 0.4 s", worst < 0.4, f"worst deviation {worst:.2f}s")

    check("the words are in order",
          all(a.start <= b.start for a, b in zip(lyr.words, lyr.words[1:])))
    check("no word has zero length", all(w.end > w.start for w in lyr.words))
    check("everything is inside the track", all(0 <= w.start and w.end <= dur + 1e-6 for w in lyr.words))

    # The Whisper path differs from the loudness one in the order of steps: the
    # line bounds appear only from the words. Checked without the model itself —
    # ready word times are fed in, as Whisper would have returned them.
    print("\nThe order of steps on the Whisper path")
    wl = L.parse(TEXT)
    t = 2.0
    for line in wl.lines:
        for w in line.words:
            w.start, w.end = t, t + 0.3
            t += 0.35
        t += 0.6
    # this is exactly where it used to fail: the lines had no start/end yet
    A._trim_leading_silence(wl)
    A._fill_lines(wl, dur)
    A.repair_lines(wl)
    A.repair_order(wl)
    A._fill_lines(wl, dur)
    check("the line bounds were filled from the words",
          all(l.start is not None and l.end is not None for l in wl.lines))
    check("the lines are in order",
          all(a.start <= b.start for a, b in zip(wl.lines, wl.lines[1:])))
    check("the words are in order",
          all(a.start <= b.start + 1e-9 for a, b in zip(wl.words, wl.words[1:])))

    env, hop_env = AU.rms_envelope(song)

    print("\nBuilding the HTML")
    track = AU.encode(song, os.path.join(tmp, "a"), "mp3")
    html = os.path.join(tmp, "out.html")
    B.build_html(html, lyr, dur, {"mix": track}, engine, embed=True)
    body = open(html, encoding="utf-8").read()
    check("the file was built", os.path.getsize(html) > 50_000)
    check("the audio is embedded", "data:audio/mpeg;base64," in body)
    check("no external links", "http://" not in body and "https://" not in body)
    check("the template is filled in", "__PAYLOAD__" not in body and "__TITLE__" not in body)
    check("the lyrics are there", "Закружилась" in body)
    check("the syllables reached the player", '"s":' in body)

    lrc = os.path.join(tmp, "out.lrc")
    B.write_lrc(lrc, lyr)
    check("the LRC was written", open(lrc, encoding="utf-8").read().count("\n") >= 8)

    print("\nFeeding the timings back in")
    lyr2 = L.parse(TEXT)
    import json
    tj = os.path.join(tmp, "t.json")
    json.dump({"lines": [{"text": l.text, "start": l.start + 1.5, "end": l.end + 1.5,
                          "words": [{"w": w.text, "t": w.start + 1.5, "d": w.end - w.start}
                                    for w in l.words]} for l in lyr.lines]},
              open(tj, "w"), ensure_ascii=False)
    B.apply_timings(lyr2, tj)
    check("the shift was applied", abs(lyr2.lines[0].start - (lyr.lines[0].start + 1.5)) < 1e-6)

    print("\nHow precise the shift is when the instrumental is swapped")
    # The timing is moved along with the new track, so an error in finding the
    # shift is heard at once. The envelope step is 10 ms, the peak is refined
    # with a parabola.
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
        check(f"a shift of {ms} ms was found", abs(got - ms) < 8, f"got {got:.1f} ms")
    check("the worst error is under 8 ms", worst < 8, f"{worst:.1f} ms")
    check("on empty data the shift is zero", _studio.offset_between([], [], 0.01) == 0.0)

    print("\nThe “Check” panel: only real breakage, no matters of taste")
    from kstudio import project as PRJ
    long_note = {"lines": [{"text": "а-а-а", "start": 0.0, "end": 9.0,
                            "words": [{"w": "а-а-а", "t": 0.0, "d": 9.0, "s": 3}]}],
                 "envelope": {}}
    check("a long note does not count as an error", PRJ.problems(long_note) == [],
          str(PRJ.problems(long_note)))
    tail = {"lines": [{"text": "конец строки", "start": 0.0, "end": 6.0,
                       "words": [{"w": "конец", "t": 0.0, "d": 0.5, "s": 2},
                                 {"w": "строки", "t": 0.5, "d": 5.5, "s": 2}]}],
            "envelope": {}}
    check("a tail at the end of a line is not an error either", PRJ.problems(tail) == [],
          str(PRJ.problems(tail)))

    impossible = {"lines": [{"text": "очень много слогов подряд",
                             "start": 0.0, "end": 0.4,
                             "words": [{"w": "очень", "t": 0.0, "d": .1, "s": 2},
                                       {"w": "много", "t": 0.1, "d": .1, "s": 2},
                                       {"w": "слогов", "t": 0.2, "d": .1, "s": 2},
                                       {"w": "подряд", "t": 0.3, "d": .1, "s": 2}]}],
                  "envelope": {}}
    check("but the physically unsingable is", len(PRJ.problems(impossible)) == 1,
          str(PRJ.problems(impossible)))

    overlap = {"lines": [{"text": "первая", "start": 0.0, "end": 5.0,
                          "words": [{"w": "первая", "t": 0.0, "d": 5.0, "s": 3}]},
                         {"text": "вторая", "start": 3.0, "end": 6.0,
                          "words": [{"w": "вторая", "t": 3.0, "d": 3.0, "s": 3}]}],
               "envelope": {}}
    check("overlapping lines are still reported",
          any("налезает" in w for p2 in PRJ.problems(overlap) for w in p2["why"]),
          str(PRJ.problems(overlap)))

    torn = {"lines": [{"text": "слова врозь", "start": 0.0, "end": 6.0,
                       "words": [{"w": "слова", "t": 0.0, "d": 0.4, "s": 2},
                                 {"w": "врозь", "t": 5.0, "d": 1.0, "s": 1}]}],
            "envelope": {}}
    check("words drifted apart inside a line are reported",
          any("разъехались" in w for p2 in PRJ.problems(torn) for w in p2["why"]),
          str(PRJ.problems(torn)))

    print("\nThe report before building")
    from kstudio import report as REP

    def click_track(path, tempo, dur=24.0, sr=22050):
        """Even beats at a known tempo."""
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

    # Plain autocorrelation confidently reports half the tempo — the fast
    # tempos are checked here, because that is where it showed.
    for tempo in (90, 120, 140, 175):
        p2 = os.path.join(tmp, f"click{tempo}.wav")
        click_track(p2, tempo)
        env2, hop2 = AU.rms_envelope(p2)
        got, conf = REP.bpm(env2, hop2)
        check(f"the tempo {tempo} bpm was found",
              got is not None and abs(got - tempo) < 3.5,
              f"got {got}")
        check(f"and the confidence at {tempo} is high", conf > 0.5, f"{conf}")

    check("no tempo is invented out of silence", REP.bpm([0.0] * 400, 0.02)[0] is None)

    # Where nobody sings for a while — intro, interlude, solo. For karaoke that
    # matters more than tempo: no line belongs there.
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
    check("the long interlude was found", len(quiet) == 1, str(quiet))
    if quiet:
        check("and found where it actually is",
              abs(quiet[0]["start"] - 8) < 1.0 and abs(quiet[0]["end"] - 20) < 1.0,
              f"{quiet[0]['start']}–{quiet[0]['end']} вместо 8–20")
    check("short gaps between lines are not interludes",
          REP.quiet_stretches(env, hop_env) == [] or
          all(q["end"] - q["start"] >= 5 for q in REP.quiet_stretches(env, hop_env)),
          str(REP.quiet_stretches(env, hop_env)))
    check("an empty envelope does not crash it", REP.quiet_stretches([], 0.02) == [])

    grep = REP.build(gap_song, lyr, 30.0, genv, ghop, separate=False)
    check("the interlude reached the report", len(grep["audio"]["quiet"]) == 1,
          str(grep["audio"]["quiet"]))
    check("and it is spelled out in words",
          any("без пения" in n.lower() for n in grep["notes"]), str(grep["notes"]))
    check("the text report has it too",
          "Без пения" in REP.as_text(grep))
    check("an empty envelope does not crash it", REP.bpm([], 0.02) == (None, 0.0))

    rep = REP.build("песня.mp3", lyr, 26.0, env, hop_env,
                    model="small", separate=False, whisper=True, language="auto")
    check("the report has the length", rep["audio"]["duration"] == 26.0)
    check("the report has the text", rep["text"]["lines"] == 6 and rep["text"]["words"] == 21,
          str(rep["text"]))
    check("the sections are listed", rep["text"]["sections"] == ["Куплет", "Припев"],
          str(rep["text"]["sections"]))
    check("the language was detected and named", rep["language"]["code"] == "ru" and
          rep["language"]["auto"] is True)
    check("the time estimate is positive", rep["plan"]["seconds"] > 0)
    check("the estimate is honestly marked as rough", rep["plan"]["rough"] is True)
    check("the text form assembles", "Отчёт перед сборкой" in REP.as_text(rep))

    # The text belongs to another song: too few lines for a long recording
    short = L.parse("Одна одинокая строка")
    rep2 = REP.build("длинная.mp3", short, 300.0, env, hop_env, separate=False)
    check("few lines for a long song — the warning is there",
          any("повтор" in n or "много" in n for n in rep2["notes"]),
          str(rep2["notes"]))
    check("a bigger song is estimated to take longer",
          rep2["plan"]["seconds"] > rep["plan"]["seconds"])

    print("\nDetecting the language from the text")
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
        check(f"{LG.label(want)} is recognised", got == want, f"detected as {got}")
    check("an empty text does not crash it", LG.detect("") == "en")
    check("punctuation only does not crash it", LG.detect("... !!! ???") in LG.NAMES)
    check("“auto” becomes the language of the text",
          LG.resolve("auto", songs["uk"]) == "uk")
    check("a language set by hand is not replaced",
          LG.resolve("en", songs["ru"]) == "en")
    check("every language has a human-readable name",
          all(LG.label(c) and LG.label(c) != c for c in LG.NAMES))
    # Telling the alphabets apart is the one judgement about a text that is
    # never a guess — it is what catches “English lyrics, Russian picked”.
    check("the alphabet of a text is told apart",
          LG.text_script(songs["en"]) == "lat" and LG.text_script(songs["ru"]) == "cyr"
          and LG.text_script(songs["ja"]) == "cjk" and LG.text_script("123 …") == "",
          LG.text_script(songs["en"]) + "/" + LG.text_script(songs["ru"]))
    check("and the alphabet of a language too",
          LG.script_of("ru") == "cyr" and LG.script_of("uk") == "cyr"
          and LG.script_of("en") == "lat" and LG.script_of("zh") == "cjk")

    print("\nWhat the aligner mutters is put in the log")
    # stable-ts says the single most useful thing through the warnings module,
    # and it scrolls past in a console window nobody is watching.
    import warnings as _w
    told = []
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        _w.warn("12/34 segments failed to align.", UserWarning)
    failed = A.report_warnings(caught, 34, told.append)
    check("the warning itself reaches the log",
          any("12/34" in m for m in told), " | ".join(told)[:80])
    check("and it is explained in plain words",
          any("не расслышал" in m for m in told), " | ".join(told)[-90:])
    check("the number of unplaced lines is read out", failed == 12, str(failed))
    check("silence is not reported as a problem",
          A.report_warnings([], 34, told.append) == 0)

    print("\nLines the aligner piled in one spot")
    # Straight from a real project: Bjork — Unravel, a quiet intro. Whisper found
    # nothing to hold on to and dropped seven lines at 0:16.7 and six more at
    # 0:39.2 — a fifth of a second for the lot. In the player the karaoke leapt
    # through half the lyrics in a blink.
    rows = [("While you are away", 16.24, 17.06), ("My heart comes undone", 16.74, 17.06),
            ("Slowly unravels", 16.74, 17.22), ("In a ball of yarn", 16.74, 16.90),
            ("The devil collects it", 16.74, 16.90), ("With a grin", 16.74, 16.90),
            ("Our love", 16.74, 16.90), ("In a ball of yarn", 38.00, 39.40),
            ("He'll never return it", 39.24, 39.40), ("So, when you come back", 39.24, 39.40),
            ("We'll have to make new love", 39.24, 39.40),
            ("While you are away", 39.24, 43.66), ("My heart comes undone", 45.20, 47.80),
            ("Slowly unravels", 48.84, 53.54), ("In a ball of yarn", 54.44, 56.84)]
    piled = L.parse("\n".join(t for t, _, _ in rows))
    for ln, (_, a_, b_) in zip(piled.lines, rows):
        A._spread(ln.words, a_, b_)
        ln.start, ln.end = a_, b_

    runs = A.pile_runs(piled.lines)
    check("a pile is seen as a run, not line by line", len(runs) == 2, str(runs))
    check("the first run is the seven lines at 0:16", runs[0] == (0, 6), str(runs[0]))
    check("a sound line is not called a pile",
          all(not (a_ <= 12 <= b_) for a_, b_ in runs), str(runs))
    check("the share of piled lines is counted", 0.6 < A.pile_share(piled) < 0.95,
          f"{A.pile_share(piled):.0%}")

    words_before = [w.text for w in piled.words]
    said = []
    # The singing starts at 0:11 — the pile must not be spread over the silence
    # before it, and must not touch the lines that are timed right.
    A.repair_piles(piled, 200.02, log=said.append, floor=11.0)
    first = piled.lines[:7]
    check("the pile was spread out", said and "7" in said[0], said[0] if said else "silence")
    check("it stops right before the next sound line",
          37.0 < first[-1].end <= 38.0 + 1e-6, f"{first[-1].end:.2f}")
    # A gap can be wordless — a breath, an intro, humming. Filling all of it
    # would claim as lyrics what is not sung, so the run keeps a sung pace and
    # leaves the rest of the gap alone.
    check("the wordless part of the gap is left free",
          first[0].start > 20.0, f"the pile starts at {first[0].start:.1f}, the gap opens at 11.0")
    check("and the pace is a sung one, not a smear",
          all(0.3 < (ln.end - ln.start) / (sum(w.syllables for w in ln.words) or 1) < 0.7
              for ln in first),
          f"{(first[0].end - first[0].start) / 5:.2f} s per syllable")
    check("every line got a singable length",
          all((ln.end - ln.start) / (sum(w.syllables for w in ln.words) or 1) > 0.07
              for ln in first),
          min(f"{(ln.end - ln.start):.2f}" for ln in first))
    check("the order of the lines is intact",
          all(b_.start >= a_.start for a_, b_ in zip(piled.lines, piled.lines[1:])))
    check("the words are still the same words", [w.text for w in piled.words] == words_before)
    check("the lines that were timed right are untouched",
          abs(piled.lines[12].start - 45.20) < 1e-9 and abs(piled.lines[13].start - 48.84) < 1e-9)
    # Its neighbours contradict each other — line 8 ends at 39.40 while line 12
    # starts at 39.24. Moving that pile would stack it on a line that IS right.
    check("a pile with nowhere to go is left alone, not forced",
          any(abs(piled.lines[i].start - 39.24) < 1e-9 for i in (8, 9, 10)))
    check("and it is still reported as a pile", A.pile_share(piled) > 0.1,
          f"{A.pile_share(piled):.0%}")

    # The words are sung twice, the second pass much later. Whisper laid BOTH
    # copies of the text on the first pass, so the early copy has no audio under
    # it and a whole stretch of singing has no text. Spreading that copy over the
    # music would be inventing a performance: it is left alone and explained.
    twice = L.parse("\n".join(
        ["While you are away", "My heart comes undone", "Slowly unravels",
         "In a ball of yarn", "The devil collects it", "With a grin", "Our love"] * 2))
    for i, ln in enumerate(twice.lines):
        a_, b_ = (16.74, 16.90 + i * 0.02) if i < 7 else (39.0 + (i - 7) * 6, 43.0 + (i - 7) * 6)
        A._spread(ln.words, a_, b_)
        ln.start, ln.end = a_, b_
    was = [(ln.start, ln.end) for ln in twice.lines]
    told = []
    A.repair_piles(twice, 200.0, log=told.append, floor=11.0, untexted=60.0)
    check("a repeated block is found in what is timed",
          A.duplicate_of(twice.lines, 0, 6) == (7, 13),
          str(A.duplicate_of(twice.lines, 0, 6)))
    check("text with no audio under it is not spread over the music",
          [(ln.start, ln.end) for ln in twice.lines] == was)
    check("and the reason given is the repetition, not a stray line",
          told and "повтор" in told[-1] and "60" in told[-1],
          told[-1][:90] if told else "silence")
    told2 = []
    A.repair_piles(twice, 200.0, log=told2.append, floor=11.0, untexted=0.0)
    check("with every second of singing covered, the answer is the other one",
          told2 and "выписана больше раз" in told2[-1],
          told2[-1][:90] if told2 else "silence")

    clean = L.parse("one two three\nfour five six\nseven eight nine")
    for i, ln in enumerate(clean.lines):
        A._spread(ln.words, 10.0 + i * 4, 13.0 + i * 4)
        ln.start, ln.end = 10.0 + i * 4, 13.0 + i * 4
    check("sound timing has no piles at all", A.pile_runs(clean.lines) == [],
          str(A.pile_runs(clean.lines)))
    check("and nothing is moved in it",
          A.repair_piles(clean, 100.0) == 0 and abs(clean.lines[0].start - 10.0) < 1e-9)

    print("\nA language picked by hand that the text contradicts")
    from kstudio import report as REP
    eng = L.parse("I walked alone tonight\nThe city lights are cold\n"
                  "You said you would wait for me\nBut all the words got old")
    def notes_for(language):
        return REP.build("s.mp3", eng, 120.0, [0.5] * 600, 0.2, model="small",
                         separate=False, whisper=True, language=language)["notes"]
    said = " ".join(notes_for("ru"))
    check("an English text with “русский” picked is called out",
          "не тем алфавитом" in said, said[-120:] if said else "no notes at all")
    check("and the note names what the text looks like", "english" in said)
    check("the right language raises no such note",
          "не тем алфавитом" not in " ".join(notes_for("en")))
    check("“detect from the text” raises no such note either",
          "не тем алфавитом" not in " ".join(notes_for("auto")))
    check("a Russian text with “русский” picked is left alone",
          "не тем алфавитом" not in " ".join(
              REP.build("s.mp3", L.parse(songs["ru"]), 120.0, [0.5] * 600, 0.2,
                        model="small", separate=False, whisper=True,
                        language="ru")["notes"]))

    print("\nThe window and the log agree about the models")
    import tempfile as _tf

    from kstudio import models as MM
    fake = _tf.mkdtemp(prefix="cache_")
    old_xdg = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = fake
    try:
        wd = MM.whisper_dir()
        os.makedirs(wd, exist_ok=True)
        check("the model is not there yet", MM.whisper_ready("medium") is False)
        check("a missing one is announced as “downloading”",
              MM.load_note("medium").startswith("Скачиваю") and
              "1,5 ГБ" in MM.load_note("medium"))
        check("and the step is called downloading", "скачивание" in MM.step_label("medium"))

        with open(os.path.join(wd, "medium.pt"), "wb") as f:
            f.write(b"0" * 2_000_000)
        check("the model on disk was found", MM.whisper_ready("medium") is True)
        check("a downloaded one is not promised as a download",
              "уже на диске" in MM.load_note("medium") and
              "Скачиваю" not in MM.load_note("medium"))
        check("and the step is called loading", "загрузка" in MM.step_label("medium"))

        # a half-downloaded stub must not count as a model
        with open(os.path.join(wd, "small.pt"), "wb") as f:
            f.write(b"0" * 1000)
        check("a half-downloaded file does not count as a model",
              MM.whisper_ready("small") is False)
        check("the list for the window matches what the log says",
              MM.whisper_all()["medium"] is True and
              MM.whisper_all()["small"] is False)
    finally:
        if old_xdg is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = old_xdg
        shutil_rm(fake)

    print("\nStretches a person marked as holding no words")
    # A vocalise is voice: nothing measurable tells it from a sung line, so the
    # only source of truth is the person. Marking a stretch must keep words off
    # it — and must claim nothing about the rest of the song.
    check("a written span is read as one",
          A.spans("0:00-0:42, 3:10-3:50", 600) == [(0.0, 42.0), (190.0, 230.0)],
          A.spans("0:00-0:42, 3:10-3:50", 600))
    check("seconds, minutes and a dash all pass",
          A.spans("12-30", 600) == [(12.0, 30.0)]
          and A.spans("0:12–0:30", 600) == [(12.0, 30.0)])
    check("overlapping spans merge", A.spans([(10, 20), (15, 30)], 600) == [(10.0, 30.0)])
    check("nonsense is dropped, not guessed at", A.spans("который час", 600) == [])
    check("a span outside the song is clipped to it", A.spans("0-9999", 600) == [(0.0, 600.0)])
    check("what is left is the other side of it",
          A.keep_windows([(0.0, 42.0), (190.0, 230.0)], 600)
          == [(42.0, 190.0), (230.0, 600)])

    # …and the same thing written in the lyrics file itself
    marked = L.parse("первая строка тут\n[Соло 3:10-3:50]\nвторая строка тут\n"
                     "[нет текста 1:02–1:40]\nтретья строка тут")
    check("a heading with a time range marks a wordless stretch",
          A.spans(marked.skips, 600) == [(62.0, 100.0), (190.0, 230.0)],
          marked.skips)
    check("and it does not eat the lines around it", len(marked.lines) == 3)
    check("a heading keeps being a heading",
          marked.lines[1].section == "Соло", marked.lines[1].section)
    check("while “no text” is not shown as one",
          marked.lines[2].section in (None, ""), marked.lines[2].section)

    print("\nLines that lie where the voice is silent")
    # The aligner must put every word somewhere, and over an interlude it puts
    # them on the music: the line looks timed, and nobody sings. On the
    # separated vocal that stretch is real silence, so it can be known — and
    # where the voice is loud but wordless, the person's own mark says so.
    import wave as _wv

    def _tone_and_silence(path, spans, total=30.0, sr=8000):
        """A wav that is loud inside `spans` and silent elsewhere."""
        import math
        frames = bytearray()
        for i in range(int(total * sr)):
            t = i / sr
            loud = any(a <= t < b for a, b in spans)
            v = int(12000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
            frames += int(v).to_bytes(2, "little", signed=True)
        with _wv.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(sr)
            f.writeframes(bytes(frames))

    # Levelling the voice for the model: a screamed vocal swings from a shout
    # to a rasp, and the quiet half never reaches it. The one thing that must
    # never happen is a change in length — every timing would shift with it.
    steps = os.path.join(tmp, "loud-and-quiet.wav")
    import math as _math
    with _wv.open(steps, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        fr = bytearray()
        for i in range(8000 * 12):
            t = i / 8000
            amp = 12000 if t < 6 else 400          # a shout, then a rasp
            fr += int(amp * _math.sin(2 * _math.pi * 220 * t)).to_bytes(2, "little", signed=True)
        f.writeframes(bytes(fr))
    plain = AU.read_pcm_mono(steps, 16000)
    level = AU.read_pcm_mono(steps, 16000, af=AU.LEVEL_VOICE)
    check("levelling does not change the length by a sample",
          len(plain) == len(level), f"{len(plain)} vs {len(level)}")

    def _loudness(data, a, b):
        part = data[int(a * 16000):int(b * 16000)]
        return sum(abs(v) for v in part[::17]) / max(1, len(part[::17]))

    was = _loudness(plain, 7.0, 11.0) / max(1.0, _loudness(plain, 1.0, 5.0))
    now = _loudness(level, 7.0, 11.0) / max(1.0, _loudness(level, 1.0, 5.0))
    check("and the quiet half comes up towards the loud one", now > was * 3,
          f"{was:.3f} → {now:.3f}")

    # the loudness engine must not lay lines on a marked stretch
    tone = os.path.join(tmp, "vocalise.wav")
    _tone_and_silence(tone, [(0.0, 9.0), (12.0, 30.0)])
    lyr_e = L.parse("раз строка тут\nдва строка тут\nтри строка тут")
    A.align_energy(lyr_e, tone, 30.0, skip=[(0.0, 9.0)])
    check("the loudness engine keeps off the marked stretch",
          all(ln.start >= 8.5 for ln in lyr_e.lines),
          [round(ln.start, 1) for ln in lyr_e.lines])

    # singing at 0–8 s and 20–30 s; 8–20 s is a solo with no voice at all
    voiced_wav = os.path.join(tmp, "voiced.wav")
    _tone_and_silence(voiced_wav, [(0.0, 8.0), (20.0, 30.0)])

    # a marked stretch counts as silence even where the voice is loud:
    # 0–8 s here is a vocalise, as loud as anything, with no words in it
    msgs4 = []
    lyr_v = L.parse("раз строка тут\nдва строка тут")
    for ln, (a, b) in zip(lyr_v.lines, [(2.0, 5.0), (22.0, 26.0)]):
        A._spread(ln.words, a, b)
        ln.start, ln.end = a, b
    moved4 = A.repair_silent(lyr_v, 30.0, voiced_wav, log=msgs4.append, skip=[(0.0, 8.0)])
    check("a line on a vocalise is moved off it",
          moved4 == 1 and lyr_v.lines[0].start >= 8.0,
          f"{lyr_v.lines[0].start:.1f}")
    check("and the line that was fine is left alone", lyr_v.lines[1].start == 22.0)

    # A song loud from end to end tells us nothing about where the voice is;
    # taking that as “all silent” would drag the whole text somewhere.
    loud = os.path.join(tmp, "wall.wav")
    _tone_and_silence(loud, [(0.0, 30.0)])
    lyr_w = L.parse("раз строка тут\nдва строка тут")
    for ln, (a, b) in zip(lyr_w.lines, [(2.0, 5.0), (20.0, 24.0)]):
        A._spread(ln.words, a, b)
        ln.start, ln.end = a, b
    check("a wall of sound moves nothing",
          A.repair_silent(lyr_w, 30.0, loud) == 0 and lyr_w.lines[0].start == 2.0)

    voiced_wav = os.path.join(tmp, "voiced.wav")
    # singing at 0–8 s and 20–30 s; 8–20 s is a solo with no voice at all
    _tone_and_silence(voiced_wav, [(0.0, 8.0), (20.0, 30.0)])

    def _timed_lyrics():
        lyr = L.parse("первая строка тут\nвторая строка тут\nтретья строка тут\n"
                      "четвёртая строка тут")
        times = [(1.0, 3.0), (4.0, 6.0), (11.0, 13.0), (25.0, 28.0)]
        for ln, (a, b) in zip(lyr.lines, times):
            A._spread(ln.words, a, b)
            ln.start, ln.end = a, b
        return lyr

    msgs = []
    lyr_s = _timed_lyrics()
    n = A.repair_silent(lyr_s, 30.0, voiced_wav, log=msgs.append)
    third = lyr_s.lines[2]
    check("the line on the solo is moved", n == 1, n)
    check("and it lands where the singing is",
          third.start >= 19.5 and third.end <= 25.5,
          f"{third.start:.1f}–{third.end:.1f}")
    check("its neighbours are not touched",
          lyr_s.lines[1].end == 6.0 and lyr_s.lines[3].start == 25.0)
    check("the order of lines survives",
          all(lyr_s.lines[k].start <= lyr_s.lines[k + 1].start for k in range(3)))
    check("and the log says what happened",
          any("перенес" in m or "moved" in m for m in msgs), msgs[:1])

    # nowhere to go: the neighbours press right against the silence, and every
    # second of singing between them is already spoken for
    msgs2 = []
    lyr_n = _timed_lyrics()
    lyr_n.lines[1].start, lyr_n.lines[1].end = 5.0, 8.0
    A._spread(lyr_n.lines[1].words, 5.0, 8.0)
    lyr_n.lines[2].start, lyr_n.lines[2].end = 11.0, 13.0
    lyr_n.lines[3].start, lyr_n.lines[3].end = 20.0, 23.0
    A._spread(lyr_n.lines[3].words, 20.0, 23.0)
    n2 = A.repair_silent(lyr_n, 30.0, voiced_wav, log=msgs2.append)
    check("with no singing to move to, the lines stay put",
          n2 == 0 and lyr_n.lines[2].start == 11.0, n2)
    check("and they are named out loud",
          any("ВНИМАНИЕ" in m or "NOTE" in m for m in msgs2), msgs2[:1])

    # lines that sit on singing are never dragged anywhere
    msgs3 = []
    lyr_ok = _timed_lyrics()
    lyr_ok.lines[2].start, lyr_ok.lines[2].end = 21.0, 23.0
    A._spread(lyr_ok.lines[2].words, 21.0, 23.0)
    check("lines on the singing are left alone",
          A.repair_silent(lyr_ok, 30.0, voiced_wav, log=msgs3.append) == 0
          and lyr_ok.lines[2].start == 21.0)

    print("\nA whole song built with wordless stretches marked")
    # The road end to end, without a neural net in it: build a real project and
    # look at where the lines actually landed. The test song sings at 2.0-4.6,
    # 5.0-7.6, 8.0-10.6, 11.0-13.6, 16.0-18.6, 19.0-21.6 — mark the first two
    # phrases as wordless and nothing may be laid on them.
    from kstudio import project as P

    built_root = os.path.join(tmp, "built")
    song_for_build = os.path.join(tmp, "for-build.wav")
    text_for_build = os.path.join(tmp, "for-build.txt")
    make_song(song_for_build)
    open(text_for_build, "w", encoding="utf-8").write(TEXT)

    folder = P.create(song_for_build, text_for_build, built_root,
                      align_engine="energy", separate=False, whisper_model="medium",
                      skip="0:00-0:08")
    made = json.load(open(os.path.join(folder, "project.json"), encoding="utf-8"))
    starts = [ln["start"] for ln in made["lines"]]
    check("no line is laid on the marked stretch",
          all(st >= 7.8 for st in starts), [round(x, 1) for x in starts])
    check("and the song still holds every line",
          len(made["lines"]) == len(L.parse(TEXT).lines), len(made["lines"]))
    check("the marks are written down with the song",
          made.get("noText", "").startswith("0.0-8.0"), made.get("noText"))
    check("and so is the model it was timed with",
          made.get("model") == "medium", made.get("model"))

    # the same thing said in the lyrics file instead of the field
    text_marked = os.path.join(tmp, "for-build-marked.txt")
    open(text_marked, "w", encoding="utf-8").write(
        TEXT.replace("[Куплет]", "[Вступление 0:00-0:08]\n[Куплет]"))
    folder2 = P.create(song_for_build, text_marked, built_root,
                       align_engine="energy", separate=False)
    made2 = json.load(open(os.path.join(folder2, "project.json"), encoding="utf-8"))
    starts2 = [ln["start"] for ln in made2["lines"]]
    check("a mark inside the lyrics file works the same",
          all(st >= 7.8 for st in starts2), [round(x, 1) for x in starts2])
    check("and it does not become a line of the song",
          len(made2["lines"]) == len(made["lines"]), len(made2["lines"]))

    # and with nothing marked the same song uses its whole length
    folder3 = P.create(song_for_build, text_for_build, built_root,
                       align_engine="energy", separate=False)
    made3 = json.load(open(os.path.join(folder3, "project.json"), encoding="utf-8"))
    check("without marks the early phrases are used",
          min(ln["start"] for ln in made3["lines"]) < 7.8,
          round(min(ln["start"] for ln in made3["lines"]), 1))

    print("\nSigns of life during long steps")
    import time

    from kstudio.progress import Heartbeat, mmss
    check("the time reads correctly", (mmss(0), mmss(75)) == ("0:00", "1:15"))
    beats = []
    with Heartbeat(beats.append, "проверка", every=0.2) as hb:
        time.sleep(0.3)
        hb.progress(3, 10)
        hb.note("Demucs: 40%")
        time.sleep(0.3)
    check("the step shows signs of life", len(beats) >= 2)
    check("the fraction done is visible", any("30%" in b for b in beats))
    check("the step's note is visible", any("Demucs: 40%" in b for b in beats))
    before = len(beats)
    time.sleep(0.4)
    check("it goes quiet after leaving", len(beats) == before)

    # A sign of life must never bring the step down: if the log throws, stay quiet.
    def bad_log(_):
        raise RuntimeError("лог сломан")

    with Heartbeat(bad_log, "стойкость", every=0.1):
        time.sleep(0.3)
    check("a broken log does not bring the step down", True)

    # A counter at zero or at the very end says nothing — the fraction is hidden.
    beats2 = []
    with Heartbeat(beats2.append, "без счёта", every=0.15) as hb2:
        hb2.progress(0, 26)
        time.sleep(0.2)
    check("an empty counter is not shown", beats2 and "%" not in beats2[0])

    print("\nA song from a link")
    # Nothing here touches the internet: the downloader is a stand-in that
    # hands over a file, and the lyrics library is a stand-in next door.
    import shutil
    from kstudio import fetch as FE

    check("a name written for a page becomes a name for a song",
          FE.clean_title("Nirvana - Smells Like Teen Spirit (Official Music Video)")
          == "Nirvana - Smells Like Teen Spirit"
          and FE.clean_title("ДДТ — Что такое осень [HD]") == "ДДТ — Что такое осень")
    check("the artist and the song are told apart",
          FE.split_name("Кино - Группа крови (Remastered 2021)") == ("Кино", "Группа крови"))
    check("a name with no dash stays whole",
          FE.split_name("Плачу на техно") == ("", "Плачу на техно"))
    for bad in ("", "   ", "ftp://example.com/x", "file:///etc/passwd", "-x"):
        try:
            FE.check_url(bad)
            check(f"a link that is not a link is refused: {bad!r}", False)
        except FE.FetchError:
            check(f"a link that is not a link is refused: {bad or 'empty'}", True)

    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inbox = os.path.join(tmp, "inbox")
    stub = os.path.join(app_dir, "tests", "stub_ytdlp.py")
    os.environ["KARAOKE_YTDLP"] = stub
    os.environ["KARAOKE_STUB_AUDIO"] = song            # the test song stands in
    check("the downloader is the one we pointed at", FE.tool() == [stub] and FE.available())

    # pip on macOS writes the command into ~/Library/Python/3.x/bin, which a
    # double-clicked window has never heard of. Found there, it still works.
    hidden = os.path.join(tmp, "hidden-bin")
    os.makedirs(hidden, exist_ok=True)
    shutil.copyfile(stub, os.path.join(hidden, "yt-dlp"))
    os.chmod(os.path.join(hidden, "yt-dlp"), 0o755)
    del os.environ["KARAOKE_YTDLP"]
    was_path, was_places = os.environ.get("PATH", ""), FE.places
    os.environ["PATH"] = ""
    FE.places = lambda: [hidden]
    check("a command outside PATH is still found",
          FE.tool() == [os.path.join(hidden, "yt-dlp")], FE.tool())

    # A Python that cannot say where it lives cannot be asked to run a module:
    # handing that emptiness to the command line crashes on NoneType instead of
    # answering about the song.
    FE.places = lambda: []
    was_exe, sys.executable = sys.executable, None
    check("and with nothing to run, nothing is invented", FE.tool() is None)
    try:
        FE.download("https://example.com/watch?v=zzz123", inbox)
        check("the answer is about the downloader, not about NoneType", False)
    except FE.FetchError as e:
        check("the answer is about the downloader, not about NoneType",
              "yt-dlp" in str(e) and "NoneType" not in str(e), str(e)[:70])
    sys.executable = was_exe
    FE.places, os.environ["PATH"] = was_places, was_path
    os.environ["KARAOKE_YTDLP"] = stub

    # The same emptiness used to crash the search for ffmpeg, which is what a
    # link really tripped over: a fault of ours dressed up as a missing file.
    was_exe, sys.executable = sys.executable, None
    AU._FFMPEG = None
    try:
        AU.ffmpeg()
        check("ffmpeg is looked for without falling over", True)
    except AU.AudioError:
        check("ffmpeg is looked for without falling over", True)
    except TypeError as e:
        check("ffmpeg is looked for without falling over", False, str(e))
    sys.executable, AU._FFMPEG = was_exe, None

    # And the window opened by double-clicking has a bare PATH: ffmpeg is
    # installed and works in a terminal, while the program says it is missing.
    was_path, os.environ["PATH"] = os.environ.get("PATH", ""), ""
    AU._FFMPEG = None
    try:
        found_ff = AU.ffmpeg()
    except AU.AudioError:
        found_ff = ""
    os.environ["PATH"], AU._FFMPEG = was_path, None
    check("ffmpeg is found in the usual places, not only through PATH",
          bool(found_ff), found_ff or "not found with an empty PATH")
    got = FE.download("https://example.com/watch?v=zzz123", inbox)
    check("the sound lands next to the projects",
          os.path.isfile(got["path"]) and os.path.dirname(got["path"]) == inbox)
    check("and it is the audio, not an empty file",
          os.path.getsize(got["path"]) == os.path.getsize(song))
    check("the artist and the song came with it",
          (got["artist"], got["track"]) == ("Stub Artist", "Stub Song"),
          got["artist"] + " — " + got["track"])
    check("nothing half-downloaded is left behind",
          all(not n.startswith(".fetch-") for n in os.listdir(inbox)), os.listdir(inbox))

    # What ffmpeg is called matters to the downloader: it is handed a folder
    # and looks in it for “ffmpeg” and “ffprobe”. The copy pip installs is one
    # file named after its platform, with no ffprobe beside it — hand that over
    # and yt-dlp falls over an empty path, saying only “not NoneType”.
    odd = os.path.join(tmp, "pip-ffmpeg")
    os.makedirs(odd, exist_ok=True)
    odd_ff = os.path.join(odd, "ffmpeg-macos-arm64-v7.0.2")
    open(odd_ff, "w").close()
    os.chmod(odd_ff, 0o755)
    was_ff, was_fp = AU.ffmpeg, AU.ffprobe
    AU.ffmpeg, AU.ffprobe = (lambda: odd_ff), (lambda: None)
    bin_dir = os.path.join(tmp, "as-yt-dlp-wants")
    os.makedirs(bin_dir, exist_ok=True)
    where, can_extract = FE._tools(bin_dir)
    check("a strangely named ffmpeg is given the name yt-dlp looks for",
          where and os.path.exists(os.path.join(where, "ffmpeg")), where)
    check("and with no ffprobe the sound is not pulled out on the spot",
          can_extract is False)
    args = FE._base_args(["yt-dlp"], bin_dir)
    check("so the video comes down whole instead of failing", "-x" not in args)
    check("and the folder handed over is the one with the right names",
          args[args.index("--ffmpeg-location") + 1] == where)

    AU.ffmpeg, AU.ffprobe = was_ff, was_fp
    try:
        where2, can2 = FE._tools(bin_dir)
        check("an ordinary pair is handed over as it stands",
              can2 and where2 == os.path.dirname(AU.ffmpeg()), where2)
        check("and then the sound is pulled out at once",
              "-x" in FE._base_args(["yt-dlp"], bin_dir))
    except AU.AudioError:
        check("an ordinary pair is handed over as it stands", True, "no ffmpeg here")

    # A refusal aimed at the client, not at the video: YouTube tells one player
    # “the page needs to be reloaded” and hands the sound to the next one.
    attempts = os.path.join(tmp, "attempts.txt")
    os.environ["KARAOKE_STUB_LOG"] = attempts
    again = FE.download("https://example.com/watch?v=reload", inbox)
    tried = open(attempts, encoding="utf-8").read().splitlines()
    check("a client the site turned away is asked again as another one",
          os.path.isfile(again["path"]) and len(tried) == 2, len(tried))
    check("and the one that got through is the android player",
          "player_client=android" in tried[-1], tried[-1][-40:])
    os.remove(attempts)

    try:
        FE.download("https://example.com/watch?v=fail", inbox)
        check("a link that leads nowhere is an error, not a file", False)
    except FE.FetchError as e:
        check("a link that leads nowhere says why",
              "Video unavailable" in str(e) and "ERROR" not in str(e), str(e))
    check("and it leaves no rubbish in the folder",
          all(not n.startswith(".fetch-") for n in os.listdir(inbox)), os.listdir(inbox))
    # “This video is private” is about the video: asking again as another
    # player would only make a person wait for the same answer four times.
    check("a plain refusal is not asked again",
          len(open(attempts, encoding="utf-8").read().splitlines()) == 1
          if os.path.isfile(attempts) else False)
    del os.environ["KARAOKE_STUB_LOG"]

    # Cookies and the like: what the person adds themselves reaches the
    # downloader, whatever the program decided on its own.
    os.environ["KARAOKE_YTDLP_ARGS"] = "--cookies-from-browser chrome"
    check("what the settings add is passed on",
          FE.extra_args() == ["--cookies-from-browser", "chrome"], FE.extra_args())
    os.environ["KARAOKE_STUB_LOG"] = attempts
    FE.download("https://example.com/watch?v=cookie", inbox)
    check("and it really lands in the command line",
          "--cookies-from-browser chrome" in open(attempts, encoding="utf-8").read())
    del os.environ["KARAOKE_YTDLP_ARGS"], os.environ["KARAOKE_STUB_LOG"]
    del os.environ["KARAOKE_YTDLP"]

    print("\nThe words, looked up by the name of the song")
    import importlib.util
    import threading

    from kstudio import findlyrics as FL
    spec = importlib.util.spec_from_file_location(
        "stub_lyrics", os.path.join(app_dir, "tests", "stub_lyrics.py"))
    stub_lyrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stub_lyrics)
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), stub_lyrics.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FL.BASE = f"http://127.0.0.1:{srv.server_port}"
    try:
        check("timed words are stripped down to words",
              FL.plain({"syncedLyrics": "[00:12.34] раз\n[00:15.00] два"}) == "раз\nдва")
        found = FL.search("Stub Song", "Stub Artist", duration=21)
        check("the nearest recording comes first",
              found and found[0]["duration"] == 21, [f["duration"] for f in found])
        check("a record with no words at all is not offered",
              all(f["text"].strip() for f in found), len(found))
        check("the lines are counted for the person reading",
              found[0]["lines"] == 3, found[0]["lines"])
        check("the source is named", all(f["source"] == "LRCLIB" for f in found))
        check("a song nobody knows finds nothing", FL.search("nothing at all") == [])
        try:
            FL.search("")
            check("a search with no name is refused", False)
        except FL.LyricsError:
            check("a search with no name is refused", True)
    finally:
        srv.shutdown()
    FL.BASE = "http://127.0.0.1:9"       # a port nothing listens on
    try:
        FL.search("Stub Song")
        check("an unreachable library is an error, not a crash", False)
    except FL.LyricsError as e:
        check("an unreachable library is an error, not a crash", True, str(e)[:60])

    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
