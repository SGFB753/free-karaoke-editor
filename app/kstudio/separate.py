"""Splitting into an instrumental and a vocal with Demucs."""

from __future__ import annotations

import os
import subprocess
import sys
from . import winproc as WP
from .i18n import tr
from typing import Callable, List, Optional, Tuple

Log = Callable[[str], None]


def available() -> bool:
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def explain_failure(out: str) -> List[str]:
    """Turn a Demucs crash into a plain reason and a piece of advice.

    Three troubles are the common ones: no package for writing audio, the
    model did not download, there was not enough memory. In all three cases
    Demucs prints a traceback that means nothing to an ordinary person.
    """
    from . import sysinfo
    low = (out or "").lower()

    if "find appropriate backend" in low or "no audio i/o backend" in low:
        return [tr("No instrumental: the package that writes audio is missing.",
                   "Минусовка не вышла: нет пакета для записи звука."),
                tr("  One command fixes it:  pip install soundfile",
                   "  Лечится одной командой:  pip install soundfile"),
                tr("  (torchaudio 2.x cannot write WAV itself, and Demucs does "
                   "not pull this dependency in)",
                   "  (torchaudio с версии 2.x сам писать WAV не умеет, "
                   "а Demucs эту зависимость за собой не тянет)"),
                tr("  Carrying on without an instrumental.",
                   "  Продолжаю без минусовки.")]

    net = ("urlerror", "connectionerror", "max retries", "getaddrinfo",
           "failed to download", "temporary failure in name resolution",
           "httperror", "connection refused", "network is unreachable",
           "ssl", "timed out")
    if any(k in low for k in net):
        return [tr("No instrumental: could not download the Demucs model (~80 MB).",
                   "Минусовка не вышла: не удалось скачать модель Demucs (~80 МБ)."),
                tr("  Check this machine's internet and try again — the model "
                   "downloads once.",
                   "  Проверьте интернет на этой машине, затем повторите — "
                   "модель качается один раз."),
                tr("  To fetch it beforehand, one command:",
                   "  Скачать заранее, одной командой:"),
                "    python -c \"from demucs.pretrained import get_model; "
                "get_model('htdemucs')\"",
                tr("  Carrying on without an instrumental.",
                   "  Продолжаю без минусовки.")]

    if "checksum" in low or "corrupt" in low or "unexpected eof" in low:
        return [tr("No instrumental: the model file was damaged while downloading.",
                   "Минусовка не вышла: файл модели побился при загрузке."),
                tr("  Delete the cache and try again:  rm -rf ~/.cache/torch/hub/checkpoints",
                   "  Удалите кэш и повторите:  rm -rf ~/.cache/torch/hub/checkpoints"),
                tr("  Carrying on without an instrumental.",
                   "  Продолжаю без минусовки.")]

    if sysinfo.is_memory_error(Exception(out or "")):
        return [tr("Not enough memory for the instrumental — carrying on without it.",
                   "Не хватило памяти на минусовку — продолжаю без неё."),
                sysinfo.memory_advice(sysinfo.NEED_DEMUCS, sysinfo.available_gb())]

    tail = "\n  ".join((out or "").strip().splitlines()[-6:])
    return [tr("Demucs failed, carrying on without an instrumental:",
                   "Demucs завершился с ошибкой, продолжаю без минусовки:"), "  " + tail]


class _Done:
    """The run result in the same shape subprocess.run returns."""

    def __init__(self, returncode: int, stdout: str):
        self.returncode, self.stdout = returncode, stdout


def _run_with_pulse(cmd: List[str], log: Log) -> "_Done":
    """Run Demucs while showing that it is alive.

    Demucs draws its own progress bar with carriage returns. In a console that
    looks fine, but in the studio window nothing shows at all: several minutes
    of silence after “this is the longest part”. We read its output as it
    arrives, pull the last percentage out and pass it to the log along with the
    elapsed time.
    """
    import re

    from .progress import Heartbeat

    proc = WP.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, errors="replace")
    chunks: List[str] = []
    pct = re.compile(r"(\d{1,3})%")

    with Heartbeat(log, tr("separating the tracks", "разделение дорожек"), every=20.0) as hb:
        assert proc.stdout is not None
        # readline would stop at \r and wait for a newline until the very end
        while True:
            piece = proc.stdout.read(256)
            if not piece:
                break
            chunks.append(piece)
            found = pct.findall(piece)
            if found:
                hb.note(f"Demucs: {found[-1]}%")
        proc.wait()

    return _Done(proc.returncode, "".join(chunks))


def separate(wav_path: str, out_dir: str, model: str = "htdemucs",
             device: Optional[str] = None,
             log: Log = lambda m: None) -> Tuple[Optional[str], Optional[str]]:
    """→ (instrumental_path, vocals_path). (None, None) if Demucs is unavailable."""
    if not available():
        log(tr("Demucs is not installed — there will be no instrumental "
               "(`pip install demucs` adds it).",
               "Demucs не установлен — минусовки не будет "
               "(`pip install demucs` добавит её)."))
        return None, None

    # Check before starting: otherwise Demucs spends a minute separating and
    # only then falls over while writing the result.
    try:
        import soundfile  # noqa: F401
    except ImportError:
        log(tr("No instrumental: the soundfile package is missing, and without "
               "it Demucs cannot write the result.",
               "Минусовки не будет: нет пакета soundfile, без него Demucs "
               "не сможет записать результат."))
        log(tr("  One command fixes it:  pip install soundfile",
               "  Лечится одной командой:  pip install soundfile"))
        return None, None

    # --segment cuts the track into chunks: without it Demucs keeps the whole
    # song in memory and runs out of it on a weak machine.
    runner = ([sys.executable, "--internal-demucs"]
              if getattr(sys, "frozen", False)
              else [sys.executable, "-m", "demucs"])
    cmd = runner + ["-n", model, "--two-stems", "vocals",
           "--segment", "7", "-j", "1", "-o", out_dir, wav_path]
    if device:
        cmd += ["-d", device]

    log(tr(f"Separating the vocal from the instrumental ({model}) — the longest part…",
           f"Отделяю вокал от инструментала ({model}) — это самая долгая часть…"))
    proc = _run_with_pulse(cmd, log)
    if proc.returncode != 0:
        out = proc.stdout or ""
        # some Demucs builds do not understand --segment: try without it
        if "segment" in out.lower() and "--segment" in cmd:
            log(tr("This Demucs version did not understand --segment, trying without it…",
                "Эта версия Demucs не поняла --segment, пробую без него…"))
            cmd = [c for c in cmd if c not in ("--segment", "7")]
            proc = _run_with_pulse(cmd, log)
            out = proc.stdout or ""

    if proc.returncode != 0:
        for line in explain_failure(proc.stdout or ""):
            log(line)
        return None, None

    stem = os.path.splitext(os.path.basename(wav_path))[0]
    base = os.path.join(out_dir, model, stem)
    instrumental = os.path.join(base, "no_vocals.wav")
    vocals = os.path.join(base, "vocals.wav")

    if not (os.path.exists(instrumental) and os.path.exists(vocals)):
        # in case a newer demucs lays its folders out differently
        found = {}
        for root, _, files in os.walk(out_dir):
            for f in files:
                if f in ("no_vocals.wav", "vocals.wav"):
                    found[f] = os.path.join(root, f)
        instrumental = found.get("no_vocals.wav")
        vocals = found.get("vocals.wav")

    if instrumental and vocals:
        log(tr("The instrumental is ready.", "Минусовка готова."))
    return instrumental, vocals
