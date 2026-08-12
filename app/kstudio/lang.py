"""Language of the lyrics: the supported list and detection from the text.

Whisper aligns the text to the sound with the language in mind, and a mistake
here is expensive — the timing falls apart. There is no need to ask a person
every time: the letters almost always give the language away. So by default we
work it out ourselves, and the manual choice stays for when we got it wrong or
the language is mixed.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

# Languages Whisper handles well and that actually turn up in songs.
# The order is the order shown in the picker.
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

# Telltale letters. A strong hint, but shared across whole families: à and è
# exist in French and in Italian alike, so letters alone are not enough.
_MARKS: Tuple[Tuple[str, str], ...] = (
    ("uk", "їієґ"),
    ("ru", "ёъыэ"),
    ("pl", "ąćęłńśźż"),
    ("de", "äöüß"),
    ("tr", "ğışİ"),
    ("es", "ñ¿¡"),
    ("pt", "ãõ"),
)

# Function words separate similar languages far better than diacritics do.
# A song is full of them, and they are short, so even one verse contains some.
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
    """Language code from the text. Never raises: falls back to “en”."""
    t = (text or "").lower()
    if not t.strip():
        return "en"

    # Han characters and the kana scripts are decided by their code range alone.
    if re.search(r"[\u3040-\u30ff]", t):        # hiragana and katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", t):        # hangul
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", t):        # han characters
        return "zh"

    cyr = len(re.findall(r"[а-яёіїєґ]", t))
    lat = len(re.findall(r"[a-z\u00e0-\u00ff]", t))
    cyrillic = cyr > lat
    group = ("ru", "uk") if cyrillic else \
            ("en", "de", "fr", "es", "it", "pt", "pl", "tr")

    words = set(re.findall(r"[^\W\d_]+", t, re.UNICODE))
    score = {code: 0.0 for code in group}
    for code in group:
        # A function word scores one, a telltale letter three: there are few
        # such letters, but each of them is nearly conclusive.
        score[code] += sum(1 for w in _WORDS.get(code, ()) if w in words)
    for code, marks in _MARKS:
        if code in score:
            score[code] += 3 * min(sum(t.count(ch) for ch in marks), 2)

    best = max(score, key=lambda c: score[c])
    if score[best] > 0:
        return best
    return "ru" if cyrillic else "en"


def resolve(code: str, text: str) -> str:
    """What to hand the engine: “auto” becomes a concrete language."""
    if not code or code == "auto":
        return detect(text)
    return code if supported(code) else code      # an unknown code is passed through as is


def label(code: str) -> str:
    return NAMES.get(code, code)
