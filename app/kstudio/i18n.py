"""Язык сообщений программы.

Надписи окна лежат в словаре внутри ui.js, а всё, что программа печатает в
консоль и в лог сборки, живёт прямо в коде. Заводить для этого файлы переводов
незачем: сообщений немного, и рядом с кодом видно оба варианта сразу.

    log(tr("Preparing the audio…", "Готовлю звук…"))

Язык берётся из KARAOKE_UI_LANG, потом из settings.ini, потом из языка системы.
Английский — если ничего не подошло.
"""

from __future__ import annotations

import os

_LANG = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Настройки и песни лежат не в папке программы, а рядом с ней: в корне видно
# только то, что нужно человеку.
HOME = os.path.dirname(ROOT)


def _from_settings() -> str:
    for path in (os.path.join(ROOT, "settings.ini"),
                 os.path.join(HOME, "settings.ini"),
                 os.path.join(HOME, "настройки.ini")):
        try:
            with open(path, encoding="utf-8-sig") as f:
                for raw in f:
                    line = raw.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    if key.strip().lower() in ("надписи", "ui-lang", "language"):
                        val = val.split("#")[0].strip().lower()
                        if val in ("ru", "en"):
                            return val
        except OSError:
            continue
    return ""


def _from_system() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = (os.environ.get(var) or "").lower()
        if val.startswith("ru"):
            return "ru"
        if val:
            return "en"
    if os.name == "nt":                       # на Windows переменных обычно нет
        try:
            import ctypes
            lang = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "ru" if lang == 0x19 else "en"
        except Exception:
            pass
    return "en"


def lang() -> str:
    global _LANG
    if _LANG is None:
        val = (os.environ.get("KARAOKE_UI_LANG") or "").strip().lower()
        if val not in ("ru", "en"):
            val = _from_settings() or _from_system()
        _LANG = val if val in ("ru", "en") else "en"
    return _LANG


def set_lang(code: str) -> None:
    """Задать язык вручную — этим пользуется ключ --ui-lang и проверки."""
    global _LANG
    _LANG = code if code in ("ru", "en") else None


def tr(en: str, ru: str) -> str:
    return ru if lang() == "ru" else en
