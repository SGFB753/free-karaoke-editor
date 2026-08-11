"""Проект песни на диске: стемы, разметка, огибающая вокала.

Смысл в том, чтобы тяжёлое считалось один раз. Demucs и Whisper отрабатывают
при создании проекта, дальше правки — это просто запись в project.json.
Ни пересборок, ни ручных сохранений.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
from typing import Callable, Dict, List, Optional

from . import __version__
from .i18n import tr
from . import align as A
from . import audio as AU
from . import build as B
from . import lyrics as L
from . import separate as S

Log = Callable[[str], None]
PROJECT_FILE = "project.json"
ENVELOPE_HOP = 0.02          # шаг огибающей вокала, секунды


def _noop(msg: str) -> None:
    pass


# Кириллица латиницей: имена папок и готовых файлов должны читаться на любой
# системе. «Мамины Усы» → «maminy-usy», а не крякозябры в чужом проводнике.
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g", "ў": "u",
}


def translit(name: str) -> str:
    out = []
    for ch in name:
        low = ch.lower()
        if low in TRANSLIT:
            rep = TRANSLIT[low]
            out.append(rep.upper() if ch.isupper() and rep else rep)
        else:
            out.append(ch)
    return "".join(out)


def slugify(name: str) -> str:
    s = translit(name)
    s = re.sub(r"[^A-Za-z0-9\s-]", "", s).strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60].lower() or "song"


def projects_root(base: Optional[str] = None) -> str:
    # KARAOKE_PROJECTS позволяет держать песни не в папке программы: это нужно
    # проверкам, чтобы не лезть в настоящие проекты, и удобно, если песни лежат
    # на другом диске.
    # На уровень выше папки программы: в корне у человека только его файлы.
    home = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root = base or os.environ.get("KARAOKE_PROJECTS")
    if not root:
        root = os.path.join(home, "projects")
        # Папка называлась «проекты». У кого она уже есть с песнями — работаем
        # в ней, чтобы разметка не потерялась при обновлении.
        old_ru = os.path.join(home, "проекты")
        if not os.path.isdir(root) and os.path.isdir(old_ru):
            root = old_ru
    os.makedirs(root, exist_ok=True)
    return root


# --------------------------------------------------------------------------- #

def encode_envelope(values: List[float]) -> str:
    """Огибающая как base64 из байтов 0..255 — в JSON это в разы компактнее списка."""
    return base64.b64encode(bytes(min(255, max(0, int(v * 255))) for v in values)).decode()


def build_envelope(path: str, log: Log = _noop) -> Dict:
    """Громкость вокала по времени — по ней рисуется волна и ищутся начала фраз."""
    try:
        env, dt = AU.rms_envelope(path, hop_ms=int(ENVELOPE_HOP * 1000))
    except Exception as e:                                   # pragma: no cover
        log(tr(f"  could not work out the waveform ({e})",
            f"  огибающую посчитать не вышло ({e})"))
        return {"hop": ENVELOPE_HOP, "data": ""}
    return {"hop": dt, "data": encode_envelope(env)}


# --------------------------------------------------------------------------- #

def create(audio_path: str, lyrics_path: str, root: str, *,
           align_engine: str = "auto", whisper_model: str = "small",
           language: str = "ru", separate: bool = True,
           device: Optional[str] = None, codec: str = "mp3",
           log: Log = _noop) -> str:
    """Собрать проект. Возвращает путь к его папке."""
    lyr = L.load(lyrics_path)
    if not lyr.lines:
        raise ValueError(tr("The lyrics file has no lines at all.",
                        "В файле с текстом не нашлось ни одной строки."))
    log(tr(f"Lyrics: {len(lyr.lines)} lines, {len(lyr.words)} words.",
           f"Текст: {len(lyr.lines)} строк, {len(lyr.words)} слов."))

    title = lyr.title or os.path.splitext(os.path.basename(audio_path))[0]
    folder = os.path.join(root, slugify(title))
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(root, f"{slugify(title)}-{n}")
        n += 1
    os.makedirs(folder)

    tmp = os.path.join(folder, "tmp")
    os.makedirs(tmp, exist_ok=True)
    try:
        AU.ffmpeg()
        AU.ensure_on_path()

        from . import sysinfo
        need = sysinfo.NEED_DEMUCS if (separate and S.available()) else \
            sysinfo.NEED_WHISPER.get(whisper_model, 2.2)
        ok, note = sysinfo.check(need)
        if not ok:
            log(tr("NOTE: ", "ВНИМАНИЕ: ") + note)

        log(tr("Preparing the audio…", "Готовлю звук…"))
        work = AU.to_wav(audio_path, os.path.join(tmp, "source.wav"))
        dur = AU.duration(work)
        log(tr(f"Length: {int(dur // 60)}:{int(dur % 60):02d}",
           f"Длительность: {int(dur // 60)}:{int(dur % 60):02d}"))

        instrumental = vocals = None
        if separate:
            instrumental, vocals = S.separate(work, os.path.join(tmp, "stems"),
                                              device=device, log=log)

        align_src = vocals or work
        lyr, engine = A.align(lyr, align_src, dur, align_engine,
                              whisper_model, language, device, log)
        log(tr(f"Timing ready ({B.ENGINE_LABEL.get(engine, engine)}).",
           f"Разметка готова ({B.ENGINE_LABEL.get(engine, engine)})."))

        log(tr("Working out the vocal waveform…", "Считаю волну вокала…"))
        envelope = build_envelope(align_src, log)

        log(tr("Saving the tracks…", "Сохраняю дорожки…"))
        tracks = {}
        if instrumental and vocals:
            tracks["instrumental"] = os.path.basename(
                AU.encode(instrumental, os.path.join(folder, "instrumental"), codec)[0])
            tracks["vocals"] = os.path.basename(
                AU.encode(vocals, os.path.join(folder, "vocals"), codec)[0])
        else:
            tracks["mix"] = os.path.basename(
                AU.encode(work, os.path.join(folder, "mix"), codec)[0])

        data = {
            "version": __version__,
            "title": title,
            "artist": lyr.artist or "",
            "duration": round(dur, 3),
            "engine": engine,
            "source_audio": os.path.abspath(audio_path),
            "source_lyrics": os.path.abspath(lyrics_path),
            "created": time.time(),
            "tracks": tracks,
            "envelope": envelope,
            "lines": [ln.to_json() for ln in lyr.lines],
        }
        save(folder, data)
        log(tr("The song is ready.", "Проект готов."))
        return folder
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def save(folder: str, data: Dict) -> None:
    """Пишем через временный файл: обрыв на середине не испортит проект."""
    path = os.path.join(folder, PROJECT_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def load(folder: str) -> Dict:
    with open(os.path.join(folder, PROJECT_FILE), encoding="utf-8") as f:
        return json.load(f)


def save_lines(folder: str, lines: List[Dict], colors=None, theme=None) -> Dict:
    data = load(folder)
    data["lines"] = lines
    if colors:
        data["colors"] = list(colors)[:2]
    if theme:
        data["theme"] = list(theme)[:2]
    data["edited"] = time.time()
    save(folder, data)
    return data


def list_all(root: str) -> List[Dict]:
    out = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isfile(os.path.join(folder, PROJECT_FILE)):
            continue
        try:
            d = load(folder)
        except Exception:
            continue
        out.append({
            "id": name,
            "title": d.get("title") or name,
            "artist": d.get("artist") or "",
            "duration": d.get("duration") or 0,
            "lines": len(d.get("lines") or []),
            "engine": d.get("engine") or "",
            "stems": "vocals" in (d.get("tracks") or {}),
            "edited": d.get("edited") or d.get("created") or 0,
        })
    out.sort(key=lambda x: -x["edited"])
    return out


def delete(folder: str) -> None:
    shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
#  Поиск сомнительных строк — чтобы не искать промахи на слух
# --------------------------------------------------------------------------- #

def decode_envelope(env: Dict) -> List[float]:
    raw = base64.b64decode(env.get("data") or "")
    return [b / 255.0 for b in raw]


def quiet_spans(data: Dict) -> List[Dict]:
    """Где в песне долго не поют — по той же огибающей, что рисует волну.

    Это вступление, проигрыши и соло. Видеть их на дорожке важно: строки туда
    попадать не должны, а разметка по громкости именно там и промахивается.
    """
    from . import report as R
    env = decode_envelope(data.get("envelope") or {})
    hop = (data.get("envelope") or {}).get("hop") or ENVELOPE_HOP
    return R.quiet_stretches(env, hop)


def problems(data: Dict) -> List[Dict]:
    """Список строк, которые стоит проверить, с причиной."""
    lines = data.get("lines") or []
    env = decode_envelope(data.get("envelope") or {})
    hop = (data.get("envelope") or {}).get("hop") or ENVELOPE_HOP
    floor = 0.0
    if env:
        ordered = sorted(env)
        floor = ordered[int(len(ordered) * 0.55)]

    def voiced_at(t: float) -> float:
        if not env:
            return 1.0
        i = int(t / hop)
        lo, hi = max(0, i - 4), min(len(env), i + 12)
        return max(env[lo:hi], default=0.0)

    out = []
    for i, ln in enumerate(lines):
        ws = ln.get("words") or []
        why = []

        gaps = [ws[k + 1]["t"] - (ws[k]["t"] + ws[k]["d"]) for k in range(len(ws) - 1)]
        if gaps and max(gaps) > 1.2:
            why.append(tr(f"words drift apart by {max(gaps):.1f} s",
                          f"слова разъехались на {max(gaps):.1f} с"))

        if i and lines[i - 1]["end"] > ln["start"] + 1e-6:
            why.append(tr("overlaps the previous line", "налезает на предыдущую"))

        # Про «тянется слишком долго» здесь раньше была жалоба — и зря:
        # долгая нота, распевка, хвост в конце строки это нормальная музыка,
        # а не ошибка разметки. Решает тот, кто слушает песню.
        # Осталась только невозможность: столько слогов физически не спеть.
        syl = sum((w.get("s") or 1) for w in ws) or 1
        span = ln["end"] - ln["start"]
        if span > 0 and syl and span / syl < 0.07:
            why.append(tr(f"{syl} syllables in {span:.1f} s — nobody sings that fast",
                          f"{syl} слогов за {span:.1f} с — столько не спеть"))

        if env and voiced_at(ln["start"]) < floor * 1.05:
            why.append(tr("starts where no vocal is heard", "начинается там, где вокала не слышно"))

        if why:
            out.append({"line": i, "text": ln.get("text", ""),
                        "start": ln["start"], "why": why})
    return out
