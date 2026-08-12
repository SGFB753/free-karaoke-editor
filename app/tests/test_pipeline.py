#!/usr/bin/env python3
"""Self-check: makes a test “song” and runs the whole pipeline over it.

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
    check("it starts where the singing does, not at zero",
          abs(first[0].start - 11.0) < 0.01, f"{first[0].start:.2f}")
    check("and it stops before the next sound line",
          first[-1].end <= 38.0 + 1e-6, f"{first[-1].end:.2f}")
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

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
