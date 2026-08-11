"""Язык текста песни: список поддерживаемых и определение по самому тексту.

Whisper выравнивает текст по звуку с оглядкой на язык, и ошибка тут стоит
дорого — разметка расползается. Спрашивать язык у человека каждый раз незачем:
по буквам он виден почти всегда. Поэтому по умолчанию определяем сами, а выбор
руками остаётся на случай, когда мы ошиблись или язык смешанный.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

# Языки, которые Whisper знает хорошо и которые реально встречаются в песнях.
# Порядок — как показывать в списке.
NAMES: Dict[str, str] = {
    "auto": "определить по тексту",
    "ru": "русский",
    "uk": "українська",
    "en": "english",
    "de": "deutsch",
    "fr": "français",
    "es": "español",
    "it": "italiano",
    "pl": "polski",
    "pt": "português",
    "tr": "türkçe",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
}

# Буквы-приметы. Сильный признак, но общий для целых групп: à и è есть и во
# французском, и в итальянском, поэтому одних букв мало.
_MARKS: Tuple[Tuple[str, str], ...] = (
    ("uk", "їієґ"),
    ("ru", "ёъыэ"),
    ("pl", "ąćęłńśźż"),
    ("de", "äöüß"),
    ("tr", "ğışİ"),
    ("es", "ñ¿¡"),
    ("pt", "ãõ"),
)

# Служебные слова — то, что различает похожие языки надёжнее любых значков.
# В песне их всегда много, и они короткие, поэтому попадают даже в куплет.
_WORDS: Dict[str, Tuple[str, ...]] = {
    "ru": ("не", "что", "как", "меня", "тебя", "мне", "всё", "это", "был", "она"),
    "uk": ("не", "що", "як", "мене", "тебе", "мені", "все", "це", "був", "вона"),
    "en": ("the", "and", "you", "that", "with", "have", "was", "are", "not", "for"),
    "de": ("der", "die", "das", "und", "ich", "nicht", "ein", "mit", "ist", "wir"),
    "fr": ("je", "ne", "pas", "le", "les", "des", "qui", "que", "vous", "est",
           "une", "dans", "pour", "moi", "toi"),
    "es": ("que", "los", "las", "del", "con", "por", "para", "como", "más",
           "esta", "este", "muy", "mi", "te"),
    "it": ("che", "non", "per", "con", "sono", "questo", "gli", "della", "di",
           "nel", "come", "più", "sempre", "mi"),
    "pt": ("que", "não", "com", "para", "uma", "você", "meu", "mais", "tudo"),
    "pl": ("nie", "jest", "się", "tak", "jak", "mnie", "ciebie", "wszystko"),
    "tr": ("bir", "ve", "ben", "sen", "çok", "için", "gibi", "ama"),
}


def supported(code: str) -> bool:
    return code in NAMES


def detect(text: str) -> str:
    """Код языка по тексту. Никогда не падает: в крайнем случае вернёт «en»."""
    t = (text or "").lower()
    if not t.strip():
        return "en"

    # Иероглифы и слоговые азбуки определяются однозначно по диапазону.
    if re.search(r"[\u3040-\u30ff]", t):        # хирагана и катакана
        return "ja"
    if re.search(r"[\uac00-\ud7af]", t):        # хангыль
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", t):        # китайские иероглифы
        return "zh"

    cyr = len(re.findall(r"[а-яёіїєґ]", t))
    lat = len(re.findall(r"[a-z\u00e0-\u00ff]", t))
    cyrillic = cyr > lat
    group = ("ru", "uk") if cyrillic else \
            ("en", "de", "fr", "es", "it", "pt", "pl", "tr")

    words = set(re.findall(r"[^\W\d_]+", t, re.UNICODE))
    score = {code: 0.0 for code in group}
    for code in group:
        # Служебное слово весит единицу, буква-примета — три: букв мало,
        # но каждая почти однозначна.
        score[code] += sum(1 for w in _WORDS.get(code, ()) if w in words)
    for code, marks in _MARKS:
        if code in score:
            score[code] += 3 * min(sum(t.count(ch) for ch in marks), 2)

    best = max(score, key=lambda c: score[c])
    if score[best] > 0:
        return best
    return "ru" if cyrillic else "en"


def resolve(code: str, text: str) -> str:
    """Что отдавать движку: «auto» превращаем в конкретный язык."""
    if not code or code == "auto":
        return detect(text)
    return code if supported(code) else code      # чужой код пропускаем как есть


def label(code: str) -> str:
    return NAMES.get(code, code)
