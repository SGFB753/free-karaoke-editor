"""Что из моделей уже лежит на диске.

Один источник правды для окна и для лога: окно писало «уже скачана», а лог тут
же сообщал «первый раз — качается из сети». Одно из двух всегда врало.
"""

from __future__ import annotations

import os
from typing import Dict, Optional
from .i18n import tr

# Размеры для сообщений: человеку важно понимать, ждать секунду или полчаса.
_SIZE_MB = {"tiny": 75, "base": 140, "small": 480,
            "medium": 1500, "large-v3": 3000, "large-v2": 3000, "large": 3000}


def size_label(name: str) -> str:
    """«480 MB» / «480 МБ» — единицы тоже пишутся на языке сообщений."""
    mb = _SIZE_MB.get(name)
    if not mb:
        return ""
    if mb < 1000:
        return f"{mb} " + tr("MB", "МБ")
    return (f"{mb / 1000:.1f}".replace(".0", "") + " " + tr("GB", "ГБ")
            if tr("en", "ru") == "en"
            else f"{mb / 1000:.1f}".replace(".", ",").replace(",0", "") + " ГБ")
_MIN_BYTES = 1_000_000          # недокачанный огрызок моделью не считаем


def whisper_dir() -> str:
    """Куда Whisper кладёт модели — ровно та же логика, что у него внутри."""
    default = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(os.getenv("XDG_CACHE_HOME", default), "whisper")


def whisper_ready(name: str) -> bool:
    path = os.path.join(whisper_dir(), name + ".pt")
    try:
        return os.path.isfile(path) and os.path.getsize(path) > _MIN_BYTES
    except OSError:
        return False


def whisper_all() -> Dict[str, bool]:
    return {n: whisper_ready(n) for n in
            ("tiny", "base", "small", "medium", "large-v3")}


def load_note(name: str) -> str:
    """Строка для лога — по факту, а не наугад."""
    size = size_label(name)
    if whisper_ready(name):
        return tr(f"Loading the Whisper model “{name}” — it is already on disk…",
                  f"Загружаю модель Whisper «{name}» — она уже на диске…")
    return (tr(f"Downloading the Whisper model “{name}”",
               f"Скачиваю модель Whisper «{name}»")
            + (f" ({size})" if size else "")
            + tr(" — once only, after that it is taken from disk…",
                 " — это один раз, дальше она берётся с диска…"))


def step_label(name: str) -> str:
    """Как назвать шаг в отсчёте времени."""
    return (tr(f"loading the “{name}” model", f"загрузка модели «{name}»")
            if whisper_ready(name)
            else tr(f"downloading the “{name}” model", f"скачивание модели «{name}»"))
