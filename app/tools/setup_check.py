#!/usr/bin/env python3
"""One-time setup: checks ffmpeg and offers to install everything else."""

from __future__ import annotations

import importlib
import os
import site
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kstudio.i18n import tr          # noqa: E402

MARK = "# --- the copy starts below this line ---\n"


def ffmpeg_advice() -> str:
    """The command that actually exists on this system."""
    if os.name == "nt":
        return "winget install Gyan.FFmpeg"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return "sudo apt install ffmpeg"


def see_new_packages() -> None:
    """Let this very process see what pip has just put on the disk.

    pip installs into the user's site-packages, and on macOS that folder often
    does not exist yet when the interpreter starts — so it is not in sys.path
    at all, and the import one line below still fails. The import machinery
    also remembers the folder listings it has already read.
    """
    importlib.invalidate_caches()
    user = site.getusersitepackages()
    for path in [user] if isinstance(user, str) else list(user):
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)


def installed(module: str) -> bool:
    """Ask a fresh Python, not this one.

    This process may have started before the package existed; a new one reads
    the folders as they are now. That is the difference between "the setup
    goes on to the next step" and "start it again to get there".
    """
    return subprocess.call([sys.executable, "-c", "import " + module],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL) == 0


def pip_install(*pkgs) -> bool:
    print(tr(f"\nInstalling: {' '.join(pkgs)}\n", f"\nСтавлю: {' '.join(pkgs)}\n") + "-" * 60)
    code = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])
    print("-" * 60)
    if code == 0:
        see_new_packages()
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
    missing = ""
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
                    # It is on the disk; this window simply began before it was
                    # there. The next run finds it — and the steps below have
                    # nothing to do with ffmpeg, so they go on now.
                    print(tr("   It is installed, but this window started before it "
                             "appeared — the program will find it.",
                             "   Он установлен, но это окно запущено раньше, чем он "
                             "появился, — программа его найдёт."))
                    missing = tr("ffmpeg — start the setup once more to make sure",
                                 "ffmpeg — запустите настройку ещё раз, чтобы убедиться")
            else:
                missing = tr(f"ffmpeg — install it by hand: {ffmpeg_advice()}",
                             f"ffmpeg — поставьте вручную: {ffmpeg_advice()}")
        else:
            print(tr(f"   Install it yourself: {ffmpeg_advice()}",
                      f"   Поставьте сами: {ffmpeg_advice()}"))
            missing = tr(f"ffmpeg — nothing works without it: {ffmpeg_advice()}",
                         f"ffmpeg — без него ничего не работает: {ffmpeg_advice()}")

    print(tr("\n2. Word-by-word timing (stable-ts, the Whisper neural net)",
                  "\n2. Точная разметка по словам (stable-ts, нейросеть Whisper)"))
    if installed("stable_whisper"):
        print(tr("   Already installed.", "   Уже стоит."))
    else:
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
    if installed("demucs"):
        if installed("soundfile"):
            print(tr("   Already installed.", "   Уже стоит."))
        else:
            print(tr("   Demucs is there but soundfile is missing — without it the "
                      "instrumental crashes.",
                      "   Demucs стоит, но не хватает soundfile — без него минусовка падает."))
            if ask(tr("   Add soundfile?", "   Доставить soundfile?")):
                pip_install("soundfile")
    else:
        print(tr("   Not installed. Without it there is no “Voice” slider and no "
                      "instrumental.",
                      "   Не установлен. Без него не будет регулятора «Голос» и минусовки."))
        if ask(tr("   Install it?", "   Поставить?"), default_yes=False):
            # soundfile is required: without it Demucs runs and then dies on write
            pip_install("demucs", "soundfile")

    print(tr("\n4. Rendering an MP4 for YouTube (pillow)",
                  "\n4. Рендер ролика в MP4 для YouTube (pillow)"))
    if installed("PIL"):
        print(tr("   Already installed.", "   Уже стоит."))
    else:
        print(tr("   Not installed. Only needed for tools/video.py, and it is small.",
                      "   Не установлена. Нужна только для tools/video.py, весит немного."))
        if ask(tr("   Install it?", "   Поставить?")):
            pip_install("pillow")

    print(tr("\n5. Faster loudness analysis (numpy)",
                  "\n5. Ускорение разбора громкости (numpy)"))
    if installed("numpy"):
        print(tr("   Already installed.", "   Уже стоит."))
    else:
        if ask(tr("   Install numpy (small, and noticeably faster)?",
                  "   Поставить numpy (небольшой, заметно ускоряет)?")):
            pip_install("numpy")

    print(tr("\n6. Your own settings file", "\n6. Свой файл настроек"))
    # settings.ini belongs to whoever runs the program: it is not in the
    # repository, so an update can never overwrite what they chose. The example
    # next to it is the reference, and this is the copy made from it.
    ini = os.path.join(ROOT, "settings.ini")
    example = os.path.join(ROOT, "settings.example.ini")
    if os.path.isfile(ini):
        print(tr(f"   Already there: {ini}", f"   Уже есть: {ini}"))
    elif os.path.isfile(example):
        try:
            text = open(example, encoding="utf-8").read()
            # Everything above the marker explains what the example is; in the
            # copy that would only confuse, so it stays behind.
            _, sep, body = text.partition(MARK)
            with open(ini, "w", encoding="utf-8") as f:
                f.write((body if sep else text).lstrip("\n"))
            print(tr(f"   Made from the example: {ini}",
                     f"   Сделал из примера: {ini}"))
        except OSError as e:
            print(tr(f"   Could not make it ({e}) — the program will use the defaults.",
                     f"   Не смог создать ({e}) — программа возьмёт значения по умолчанию."))
    else:
        print(tr("   No example next to the program — the defaults will be used.",
                 "   Примера рядом с программой нет — возьмутся значения по умолчанию."))

    print("\n" + "=" * 60)
    print(tr("Setup finished.", "Настройка закончена."))
    if missing:
        print(tr("\nOne thing is still open:", "\nОстался один вопрос:"))
        print("  " + missing)
    starter = "Studio.bat" if os.name == "nt" else "studio.command"
    dragged = "Make-karaoke.bat" if os.name == "nt" else "make-karaoke.command"
    print(tr(f"\nNow open {starter} and drag a song file and a lyrics file",
             f"\nТеперь откройте {starter} и перетащите в окно аудиофайл и файл с текстом"))
    print(tr(f"into the window — or drop them both onto {dragged}.",
             f"— или бросьте оба на «{dragged}»."))
    print("=" * 60)
    return 1 if missing else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(tr("\nCancelled.", "\nОтменено."))
        sys.exit(130)
