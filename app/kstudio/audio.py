"""Audio through ffmpeg: finding the binary, decoding to PCM, re-encoding."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from .i18n import tr
from array import array
from typing import List, Optional, Tuple

_FFMPEG: Optional[str] = None
_FFPROBE: Optional[str] = None

CODECS = {
    # name: (ffmpeg args, extension, mime)
    "mp3": (["-c:a", "libmp3lame", "-q:a", "5"], ".mp3", "audio/mpeg"),
    "opus": (["-c:a", "libopus", "-b:a", "64k", "-vbr", "on"], ".ogg", "audio/ogg"),
    "aac": (["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"], ".m4a", "audio/mp4"),
}


class AudioError(RuntimeError):
    pass


def _probe_candidates(name: str):
    yield os.environ.get(f"KARAOKE_{name.upper()}")
    yield shutil.which(name)
    try:  # pip install imageio-ffmpeg — a fallback without a system install
        import imageio_ffmpeg
        if name == "ffmpeg":
            yield imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    yield os.path.join(os.path.dirname(sys.executable), name)


def ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        for c in _probe_candidates("ffmpeg"):
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                _FFMPEG = c
                break
        else:
            raise AudioError(
                tr("ffmpeg was not found. Install it:\n",
                   "Не найден ffmpeg. Установите его:\n")
                + "  Linux:   sudo apt install ffmpeg   (or dnf install ffmpeg)\n"
                  "  macOS:   brew install ffmpeg\n"
                  "  Windows: winget install Gyan.FFmpeg\n"
                + tr("  Or without administrator rights: pip install imageio-ffmpeg",
                     "  Либо без прав администратора: pip install imageio-ffmpeg")
            )
    return _FFMPEG


def ffprobe() -> Optional[str]:
    global _FFPROBE
    if _FFPROBE is None:
        for c in _probe_candidates("ffprobe"):
            if c and os.path.exists(c) and os.access(c, os.X_OK):
                _FFPROBE = c
                break
        else:
            _FFPROBE = ""
    return _FFPROBE or None


_ON_PATH = False


def ensure_on_path() -> None:
    """Make ffmpeg visible to third-party libraries that look it up by name.

    imageio-ffmpeg кладёт бинарник внутрь пакета под именем вроде
    ffmpeg-win64-v4.2.2.exe. Наш код его находит, а openai-whisper зовёт просто
    «ffmpeg» через PATH и падает с WinError 2. Кладём рядом копию с нужным именем.
    """
    global _ON_PATH
    if _ON_PATH:
        return
    _ON_PATH = True

    try:
        exe = ffmpeg()
    except AudioError:
        return

    want = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if os.path.basename(exe).lower() == want:
        os.environ["PATH"] = os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", "")
        return

    if shutil.which("ffmpeg"):
        return                                   # the system one is already there

    import tempfile
    shim_dir = os.path.join(tempfile.gettempdir(), "karaoke_ffmpeg_shim")
    os.makedirs(shim_dir, exist_ok=True)
    dst = os.path.join(shim_dir, want)
    if not os.path.exists(dst):
        try:
            os.link(exe, dst)                    # a hard link — no copying
        except Exception:
            try:
                shutil.copy2(exe, dst)
            except Exception:
                return
    os.environ["PATH"] = shim_dir + os.pathsep + os.environ.get("PATH", "")


def _run(cmd: List[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)


def duration(path: str) -> float:
    probe = ffprobe()
    if probe:
        p = _run([probe, "-v", "error", "-show_entries", "format=duration",
                  "-of", "json", path])
        if p.returncode == 0:
            try:
                return float(json.loads(p.stdout)["format"]["duration"])
            except Exception:
                pass
    # fallback: parse "Duration: 00:03:24.15" out of ffmpeg's output
    p = _run([ffmpeg(), "-i", path])
    m = re.search(rb"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    raise AudioError(tr(f"Could not work out the length of the file: {path}",
                        f"Не удалось определить длительность файла: {path}"))


def to_wav(src: str, dst: str, sample_rate: int = 44100, mono: bool = False) -> str:
    """Bring any input to WAV (demucs needs it, and it is a common denominator)."""
    cmd = [ffmpeg(), "-y", "-i", src, "-vn", "-ar", str(sample_rate),
           "-ac", "1" if mono else "2", "-c:a", "pcm_s16le", dst]
    p = _run(cmd)
    if p.returncode != 0:
        raise AudioError(tr(f"ffmpeg could not read {src}:", f"ffmpeg не смог прочитать {src}:")
                         + "\n" + p.stderr.decode(errors="replace")[-800:])
    return dst


def encode(src: str, dst_base: str, codec: str = "mp3", sample_rate: int = 44100) -> Tuple[str, str]:
    """Compress for the web. Returns (path, mime).

    Частоту дискретизации задаём явно: минусовка и вокал играют в браузере
    двумя разными элементами, и если у них разойдётся частота, одна дорожка
    поедет быстрее другой.
    """
    if codec not in CODECS:
        raise AudioError(tr(f"Unknown codec {codec}. Available: {', '.join(CODECS)}",
                            f"Неизвестный кодек {codec}. Доступны: {', '.join(CODECS)}"))
    args, ext, mime = CODECS[codec]
    dst = dst_base + ext
    p = _run([ffmpeg(), "-y", "-i", src, "-vn", "-ac", "2",
              "-ar", str(sample_rate), *args, dst])
    if p.returncode != 0:
        raise AudioError(f"ffmpeg не смог закодировать {src} в {codec}:\n"
                         f"{p.stderr.decode(errors='replace')[-800:]}")
    return dst, mime


def read_pcm_mono(path: str, sample_rate: int = 16000) -> array:
    """Decode to mono int16 through a pipe. Returns array(\'h\')."""
    cmd = [ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1",
           "-ar", str(sample_rate), "-f", "s16le", "-"]
    p = _run(cmd)
    if p.returncode != 0:
        raise AudioError(tr(f"Could not decode {path}:", f"Не удалось декодировать {path}:")
                         + "\n" + p.stderr.decode(errors="replace")[-500:])
    data = array("h")
    data.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    return data


def rms_envelope(path: str, hop_ms: int = 20, sample_rate: int = 16000):
    """Loudness envelope: (list of RMS in [0..1], step in seconds)."""
    samples = read_pcm_mono(path, sample_rate)
    hop = max(int(sample_rate * hop_ms / 1000), 1)
    try:
        import numpy as np
        x = np.frombuffer(samples.tobytes(), dtype="<i2").astype("float32") / 32768.0
        n = len(x) // hop * hop
        if n == 0:
            return [], hop / sample_rate
        frames = x[:n].reshape(-1, hop)
        env = np.sqrt((frames ** 2).mean(axis=1))
        peak = float(env.max()) or 1.0
        return (env / peak).tolist(), hop / sample_rate
    except ImportError:
        env, peak = [], 1e-9
        for i in range(0, len(samples) - hop, hop):
            acc = 0
            for j in range(i, i + hop):
                v = samples[j] / 32768.0
                acc += v * v
            r = (acc / hop) ** 0.5
            peak = max(peak, r)
            env.append(r)
        return [e / peak for e in env], hop / sample_rate
