#!/usr/bin/env python3
"""One-time setup: checks ffmpeg and offers to install everything else."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio.i18n import tr          # noqa: E402


def pip_install(*pkgs) -> bool:
    print(tr(f"\nInstalling: {' '.join(pkgs)}\n", f"\nСтавлю: {' '.join(pkgs)}\n") + "-" * 60)
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])
    print("-" * 60)
    if code == 0:
        print(tr("Done.", "Готово."))
        return True
    print(tr("It did not work. Check the internet or your access rights.",
                  "Не получилось. Проверьте интернет или права доступа."))
    return False


def ask(question: str, default_yes: bool = True) -> bool:
    hint = (tr("[Enter = yes, n = no]", "[Enter = да, н = нет]") if default_yes
            else tr("[y = yes, Enter = no]", "[д = да, Enter = нет]"))
    try:
        ans = input(f"{question} {hint}: ").strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    # Both alphabets answer: y/yes and д/да, plus a bare 1.
    return ans[0] in "yдd1"


def main() -> int:
    print("=" * 60)
    print(tr("  Setting up Karaoke", "  Настройка программы «Караоке»"))
    print("=" * 60)
    print(f"\nPython: {sys.version.split()[0]}  ({sys.executable})")
    if sys.version_info < (3, 8):
        print(tr("Python 3.8 or newer is needed. Get it from python.org",
                  "Нужен Python 3.8 или новее. Скачайте с python.org"))
        return 1

    print(tr("\n1. Checking ffmpeg (nothing works without it)…",
                  "\n1. Проверяю ffmpeg (без него никак)…"))
    from kstudio import audio as AU
    try:
        print(tr(f"   Found: {AU.ffmpeg()}", f"   Нашёл: {AU.ffmpeg()}"))
    except AU.AudioError:
        print(tr("   Not found.", "   Не найден."))
        if ask(tr("   Install ffmpeg with pip (no administrator rights needed)?",
                  "   Поставить ffmpeg через pip (не требует прав администратора)?")):
            if pip_install("imageio-ffmpeg"):
                AU._FFMPEG = None
                try:
                    print(tr(f"   Now there is: {AU.ffmpeg()}", f"   Теперь есть: {AU.ffmpeg()}"))
                except AU.AudioError:
                    print(tr("   Still no ffmpeg. Install it by hand: "
                             "winget install Gyan.FFmpeg",
                             "   Всё ещё не вижу ffmpeg. Поставьте вручную: "
                             "winget install Gyan.FFmpeg"))
                    return 1
        else:
            print(tr("   Install it yourself: winget install Gyan.FFmpeg",
                      "   Поставьте сами: winget install Gyan.FFmpeg"))
            return 1

    print(tr("\n2. Word-by-word timing (stable-ts, the Whisper neural net)",
                  "\n2. Точная разметка по словам (stable-ts, нейросеть Whisper)"))
    try:
        import stable_whisper  # noqa: F401
        print(tr("   Already installed.", "   Уже стоит."))
    except ImportError:
        print(tr("   Not installed. It pulls PyTorch in — that is 1–2 GB,",
                      "   Не установлена. Она тянет PyTorch — это 1–2 ГБ,"))
        print(tr("   plus the model downloads on first run (140 MB to 1.5 GB).",
                      "   плюс при первом запуске качается модель (от 140 МБ до 1,5 ГБ)."))
        print(tr("   It works without it, but the timing will be by lines, not by words.",
                      "   Без неё программа работает, но разметка будет по строкам, не по словам."))
        if ask(tr("   Install it?", "   Поставить?"), default_yes=False):
            pip_install("stable-ts")

    print(tr("\n3. The instrumental — separating the vocal (demucs)",
                  "\n3. Минусовка — отделение вокала (demucs)"))
    try:
        import demucs  # noqa: F401
        try:
            import soundfile  # noqa: F401
            print(tr("   Already installed.", "   Уже стоит."))
        except ImportError:
            print(tr("   Demucs is there but soundfile is missing — without it the "
                      "instrumental crashes.",
                      "   Demucs стоит, но не хватает soundfile — без него минусовка падает."))
            if ask(tr("   Add soundfile?", "   Доставить soundfile?")):
                pip_install("soundfile")
    except ImportError:
        print(tr("   Not installed. Without it there is no “Voice” slider and no "
                      "instrumental.",
                      "   Не установлен. Без него не будет регулятора «Голос» и минусовки."))
        if ask(tr("   Install it?", "   Поставить?"), default_yes=False):
            # soundfile is required: without it Demucs runs and then dies on write
            pip_install("demucs", "soundfile")

    print(tr("\n4. Rendering an MP4 for YouTube (pillow)",
                  "\n4. Рендер ролика в MP4 для YouTube (pillow)"))
    try:
        import PIL  # noqa: F401
        print(tr("   Already installed.", "   Уже стоит."))
    except ImportError:
        print(tr("   Not installed. Only needed for tools/video.py, and it is small.",
                      "   Не установлена. Нужна только для tools/video.py, весит немного."))
        if ask(tr("   Install it?", "   Поставить?")):
            pip_install("pillow")

    print(tr("\n5. Faster loudness analysis (numpy)",
                  "\n5. Ускорение разбора громкости (numpy)"))
    try:
        import numpy  # noqa: F401
        print(tr("   Already installed.", "   Уже стоит."))
    except ImportError:
        if ask(tr("   Install numpy (small, and noticeably faster)?",
                  "   Поставить numpy (небольшой, заметно ускоряет)?")):
            pip_install("numpy")

    print("\n" + "=" * 60)
    print(tr("Setup finished.", "Настройка закончена."))
    print(tr("\nNow drag a song file and a lyrics file",
                  "\nТеперь перетащите аудиофайл и файл с текстом"))
    print(tr("onto Make-karaoke.bat — and it builds itself.",
                  "на «Make-karaoke.bat» — и всё соберётся само."))
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(tr("\nCancelled.", "\nОтменено."))
        sys.exit(130)
