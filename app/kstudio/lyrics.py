"""Разбор текста песни: строки, слова, слоги, секции, готовые LRC-тайминги."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

VOWELS_RU = set("аеёиоуыэюя")
VOWELS_EN = set("aeiouy")

# [00:12.34] текст строки  (классический LRC)
LRC_RE = re.compile(r"^\s*\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]\s*(.*)$")
# [Припев] — заголовок секции, отдельной строкой. Квадратные скобки для этого
# и служат по общему обычаю.
SECTION_RE = re.compile(r"^\s*\[\s*([^\]]{1,40}?)\s*\]\s*$")
# (Припев) — тоже заголовок, но ТОЛЬКО если внутри и правда название раздела.
# Круглые скобки в тексте песни почти всегда означают бэк-вокал или подпевку —
# «(о-о-о)», «(не уходи)», — и выбрасывать такие строки из пения нельзя.
ROUND_RE = re.compile(r"^\s*\(\s*([^)]{1,40}?)\s*\)\s*$")
SECTION_WORDS = (
    "куплет", "припев", "бридж", "проигрыш", "вступление", "концовка", "кода",
    "предприпев", "соло", "инструментал", "речитатив", "читка",
    "verse", "chorus", "bridge", "intro", "outro", "pre-chorus", "prechorus",
    "hook", "refrain", "solo", "interlude", "breakdown", "instrumental",
)


# «2: строка» — этой строкой поёт второй голос. «[голос 2]» / «[voice 2]» —
# переключатель для всех следующих строк, пока не сказано иначе.
VOICE_LINE_RE = re.compile(r"^\s*([12])\s*[:>]\s+(.+)$")
VOICE_DIR_RE = re.compile(r"^\s*(?:voice|голос|вокал)\s*([12])\s*$", re.I)
# «Припев x4» — строку поют четыре раза подряд. Выписывать её руками четырежды
# незачем: программа разложит повторы сама.
REPEAT_RE = re.compile(r"^(.*?)\s*[\(\[]?\s*[x×хХ]\s*(\d{1,2})\s*[\)\]]?\s*$", re.I)


def _split_repeat(text: str):
    """«строка x3» → («строка», 3). Без пометки — (строка, 1)."""
    m = REPEAT_RE.match(text)
    if not m:
        return text, 1
    body, times = m.group(1).strip(), int(m.group(2))
    if not body or times < 2 or times > 99:
        return text, 1
    if not _split_words(body):            # «x4» само по себе — не строка
        return text, 1
    return body, times


def _is_section_name(text: str) -> bool:
    """«Припев 2» — заголовок, «не уходи» — строка песни."""
    first = re.sub(r"[^\w-]+", " ", text.lower()).split()
    return bool(first) and first[0] in SECTION_WORDS
# Метаданные в шапке файла: "title: ...", "# artist: ..."
META_RE = re.compile(r"^\s*#?\s*(title|artist|название|исполнитель)\s*[:=]\s*(.+)$", re.I)

_PUNCT = "«»\"'“”„‘’()[]{}—–-…!?.,;:*~/\\|"
# пробелы обязательно: Whisper отдаёт слова с ведущим пробелом (' раз'),
# без их удаления не совпадёт ни один токен и выравнивание молча развалится
_STRIP = _PUNCT + " \t\n\r   "


def normalize_token(word: str) -> str:
    """Ключ для сопоставления слова с распознанным: без пунктуации, ё→е, нижний регистр."""
    w = word.lower().replace("ё", "е").replace("’", "'")
    return w.strip(_STRIP).replace("'", "")


def count_syllables(word: str) -> int:
    """Грубая оценка длительности слова в слогах (ru + en)."""
    w = normalize_token(word)
    if not w:
        return 0
    n = sum(1 for ch in w if ch in VOWELS_RU)
    if n:
        return n
    # английская эвристика: группы гласных = один слог
    n, prev_vowel = 0, False
    for ch in w:
        is_vowel = ch in VOWELS_EN
        if is_vowel and not prev_vowel:
            n += 1
        prev_vowel = is_vowel
    if w.endswith("e") and n > 1:
        n -= 1
    return max(n, 1)


@dataclass
class Word:
    text: str
    syllables: int = 0
    start: Optional[float] = None
    end: Optional[float] = None

    def __post_init__(self):
        if not self.syllables:
            self.syllables = count_syllables(self.text)

    def to_json(self):
        # "s" нужен редактору в плеере: по слогам он раскладывает слова внутри строки
        return {"w": self.text, "t": round(self.start or 0.0, 3),
                "d": round(max((self.end or 0.0) - (self.start or 0.0), 0.0), 3),
                "s": self.syllables}


@dataclass
class Line:
    text: str
    words: List[Word] = field(default_factory=list)
    section: Optional[str] = None      # заголовок секции, начинающейся с этой строки
    start: Optional[float] = None      # из LRC, если был задан вручную
    end: Optional[float] = None
    backing: bool = False              # строка целиком в скобках — подпевка
    voice: int = 1                     # 1 или 2: второй голос красится иначе
    keep: bool = False                 # оставить оригинальный голос на этом куске

    @property
    def syllables(self) -> int:
        return sum(w.syllables for w in self.words) or 1

    def to_json(self):
        return {
            "text": self.text,
            "backing": self.backing,
            "voice": self.voice,
            "keep": self.keep,
            "start": round(self.start or 0.0, 3),
            "end": round(self.end or 0.0, 3),
            "section": self.section,
            "words": [w.to_json() for w in self.words],
        }


@dataclass
class Lyrics:
    lines: List[Line] = field(default_factory=list)
    title: Optional[str] = None
    artist: Optional[str] = None
    has_manual_times: bool = False

    @property
    def words(self) -> List[Word]:
        return [w for ln in self.lines for w in ln.words]

    def plain_text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def _split_words(text: str) -> List[Word]:
    """Разбить строку на слова, ничего не потеряв.

    Знак сам по себе — тире, многоточие — не слово: спеть его нельзя, и
    отдельной подсветки он не заслуживает. Но и выбрасывать нельзя: на экране
    строка должна выглядеть так, как её написали. Поэтому такой знак
    прилипает к соседнему слову.
    """
    out: List[Word] = []
    pending = ""
    for tok in text.split():
        if normalize_token(tok):
            out.append(Word((pending + " " + tok).strip() if pending else tok))
            pending = ""
        elif out:
            out[-1] = Word(out[-1].text + " " + tok)     # знак после слова
        else:
            pending = tok                                # знак в начале строки
    if pending and not out:
        out.append(Word(pending))
    return out


def _parse_lrc_time(m: re.Match) -> float:
    mm = int(m.group(1))
    ss = float(m.group(2).replace(":", "."))
    return mm * 60 + ss


def parse(raw: str) -> Lyrics:
    """Текст → Lyrics. Понимает LRC-тайминги, секции в скобках и мета-заголовки."""
    lyr = Lyrics()
    pending_section: Optional[str] = None
    saw_content = False
    cur_voice = 1                  # каким голосом поют, пока не сказано иначе

    for raw_line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()

        if not line:
            continue

        if not saw_content:
            m = META_RE.match(line)
            if m:
                key = m.group(1).lower()
                if key in ("title", "название"):
                    lyr.title = m.group(2).strip()
                else:
                    lyr.artist = m.group(2).strip()
                continue

        m = LRC_RE.match(line)
        start = None
        if m:
            start = _parse_lrc_time(m)
            line = m.group(3).strip()
            if not line:
                continue

        backing = False
        voice = None
        if start is None:
            m = SECTION_RE.match(line)
            if m and _split_words(m.group(1)):
                d = VOICE_DIR_RE.match(m.group(1))
                if d:                       # [голос 2] — переключатель, не заголовок
                    cur_voice = int(d.group(1))
                    continue
                # строка вида [Припев] — это заголовок для следующих строк
                pending_section = m.group(1).strip()
                continue
            m = ROUND_RE.match(line)
            if m and _split_words(m.group(1)):
                if _is_section_name(m.group(1)):
                    pending_section = m.group(1).strip()
                    continue
                # всё прочее в круглых скобках — подпевка, её поют
                backing = True
            m = VOICE_LINE_RE.match(line)
            if m and _split_words(m.group(2)):
                voice = int(m.group(1))     # «2: строка» — голос только этой строки
                line = m.group(2).strip()

        # «строка x4» — повтор. Тайминги из LRC ставятся вручную, там повторы
        # не раскрываем: у каждой строки своё время.
        times = 1
        if start is None:
            line, times = _split_repeat(line)

        words = _split_words(line)
        if not words:
            continue

        saw_content = True
        if start is not None:
            lyr.has_manual_times = True
        # Подпевка по умолчанию считается вторым голосом: обычно её и поёт
        # кто-то другой, и на экране ей полезен свой цвет.
        for k in range(times):
            lyr.lines.append(Line(text=line, words=_split_words(line),
                                  section=pending_section if k == 0 else None,
                                  start=start, backing=backing,
                                  voice=voice or (2 if backing else cur_voice)))
        pending_section = None

    # если тайминги заданы вручную — конец строки = начало следующей
    if lyr.has_manual_times:
        for i, ln in enumerate(lyr.lines):
            if ln.start is None:
                continue
            nxt = next((l for l in lyr.lines[i + 1:] if l.start is not None), None)
            ln.end = nxt.start if nxt else None

    return lyr


def decode_text(raw: bytes) -> str:
    """Определить кодировку файла с текстом.

    Блокнот на русской Windows до сих пор умеет сохранять в ANSI (cp1251) и в
    UTF-16, поэтому одной UTF-8 недостаточно — иначе программа падает с
    невразумительной ошибкой на ровном месте.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8", "cp1251", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load(path: str) -> Lyrics:
    with open(path, "rb") as f:
        return parse(decode_text(f.read()))
