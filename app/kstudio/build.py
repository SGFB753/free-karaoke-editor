"""Сборка автономной HTML-страницы: текст + тайминги + звук в одном файле."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Dict, Optional
from urllib.parse import quote

from . import __version__
from .lyrics import Lyrics
from .i18n import tr

TEMPLATE = os.path.join(os.path.dirname(__file__), "player.html")

def ENGINE_NAME(engine: str) -> str:
    return {
        "whisper": tr("Whisper timing", "разметка Whisper"),
        "energy":  tr("timing by loudness", "разметка по энергии"),
        "manual":  tr("timings from the text", "тайминги из текста"),
        "json":    tr("timings from a file", "тайминги из файла"),
        "none":    tr("no timing", "без разметки"),
    }.get(engine, engine)


class _EngineLabel(dict):
    """ENGINE_LABEL.get(x, x) — привычный вид, но перевод берётся на месте."""

    def get(self, key, default=None):
        return ENGINE_NAME(key) if key in ("whisper", "energy", "manual",
                                           "json", "none") else default


ENGINE_LABEL = _EngineLabel()


def _data_uri(path: str, mime: str) -> str:
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode("ascii"))


def _rel(path: str, html_path: str) -> str:
    rel = os.path.relpath(path, os.path.dirname(os.path.abspath(html_path)) or ".")
    # имена файлов бывают кириллические и с пробелами — в src их надо экранировать
    return quote(rel.replace(os.sep, "/"))



# --------------------------------------------------------------------------- #
# Цвета оформления

def _rgb(color: str):
    """«#rgb» или «#rrggbb» → (r, g, b) в 0..255. Непонятное — None."""
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return None
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _lum(rgb) -> float:
    """Яркость по мерке WCAG — та, по которой считают читаемость."""
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """Во сколько раз одно светлее другого: 1 — неразличимо, 21 — предел."""
    ra, rb = _rgb(a), _rgb(b)
    if not ra or not rb:
        return 21.0
    la, lb = _lum(ra), _lum(rb)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable(bg: str, text: str, need: float = 4.5):
    """Подправить цвет текста, чтобы он не сливался с фоном.

    Менять цвет человеку никто не запрещает, но буквы, которые не читаются на
    своём фоне, — это не оформление, а испорченная страница. Поэтому оттенок
    оставляем как выбрали, а светлоту двигаем в сторону от фона, пока текст
    не станет различим.
    """
    rgb_t, rgb_b = _rgb(text), _rgb(bg)
    if not rgb_t or not rgb_b:
        return text, False
    if contrast(bg, text) >= need:
        return text, False
    up = _lum(rgb_b) < 0.5                     # фон тёмный — текст осветляем
    r, g, b = rgb_t
    for _ in range(64):
        r, g, b = ((min(255, int(v + (255 - v) * 0.08 + 2)) if up
                    else max(0, int(v - v * 0.08 - 2))) for v in (r, g, b))
        got = "#%02x%02x%02x" % (r, g, b)
        if contrast(bg, got) >= need:
            return got, True
    return ("#ffffff" if up else "#000000"), True


def theme_colors(theme):
    """Пара «фон, текст» из настроек — с проверкой на читаемость."""
    bg, text = (list(theme or []) + [None, None])[:2]
    bg = bg or "#0a0b14"
    text = text or "#e8ebf5"
    text, fixed = readable(bg, text)
    return {"bg": bg, "text": text}, fixed


def build_html(out_path: str, lyrics: Lyrics, duration: float,
               tracks: Dict[str, tuple], engine: str = "energy",
               embed: bool = True, title: Optional[str] = None,
               artist: Optional[str] = None, ui_lang: str = "auto",
               colors=None, theme=None) -> str:
    """tracks: {'mix'|'instrumental'|'vocals': (путь, mime)} → путь к готовому HTML."""
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        tpl = f.read()

    audio = {}
    for name, (path, mime) in tracks.items():
        if not path:
            continue
        audio[name] = _data_uri(path, mime) if embed else _rel(path, out_path)

    title = title or lyrics.title or os.path.splitext(os.path.basename(out_path))[0]

    # Ключ хранения правок в браузере. В нём обязаны участвовать сами тайминги:
    # иначе пересобранная страница с новой разметкой получит прежний ключ и молча
    # подтянет старые правки поверх свежего выравнивания.
    sig = "|".join([title, str(round(duration, 1))] +
                   [f"{ln.start or 0:.2f}" for ln in lyrics.lines])
    payload = {
        # плеер лежит внутри страницы, поэтому обновление программы не меняет уже
        # собранные файлы — по этой метке видно, какой код внутри
        "player": __version__,
        # Язык надписей страницы: «auto» — по языку браузера того, кто откроет.
        # Страница уходит к людям, у которых родной язык может быть любым.
        "uiLang": ui_lang,
        # Два цвета подсветки: основной голос и второй (подпевка, иная манера).
        "colors": list(colors or ("#4de1ff", "#ff8ad1")),
        # Фон и текст. Нечитаемую пару поправляем: буквы, слившиеся с фоном, —
        # это не оформление, а испорченная страница.
        "theme": theme_colors(theme)[0],
        "id": hashlib.sha1(sig.encode("utf-8")).hexdigest()[:12],
        "engineLabel": ENGINE_LABEL.get(engine, engine),
        "audio": audio,
        "data": {
            "title": title,
            "artist": artist or lyrics.artist or "",
            "duration": round(duration, 3),
            "lines": [ln.to_json() for ln in lyrics.lines],
        },
    }

    blob = json.dumps(payload, ensure_ascii=False)
    # чтобы содержимое не сломало <script>…</script>
    blob = blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    html = tpl.replace("__TITLE__", _esc(title + (" — " + artist if artist else "")))
    # lang в <html> ставим сразу: до запуска скрипта его читают переводчики
    # и программы чтения с экрана.
    html = html.replace("__LANG__", ui_lang if ui_lang in ("ru", "en") else "en")
    html = html.replace("__PAYLOAD__", blob)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


_PAYLOAD_RE = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)


def read_payload(html_path: str) -> dict:
    """Достать текст, тайминги и звук из собранной страницы."""
    with open(html_path, encoding="utf-8") as f:
        m = _PAYLOAD_RE.search(f.read())
    if not m:
        raise SystemExit(f"{html_path} — не похоже на страницу, собранную этой программой.")
    raw = (m.group(1).replace("\\u003c", "<").replace("\\u003e", ">")
           .replace("\\u0026", "&"))
    return json.loads(raw)


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


# --------------------------------------------------------------------------- #
#  Тайминги из внешнего JSON (экспорт из редактора в плеере)
# --------------------------------------------------------------------------- #

def apply_timings(lyrics: Lyrics, path: str, verbose: bool = True) -> Lyrics:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    src = data.get("lines", data if isinstance(data, list) else [])
    if len(src) != len(lyrics.lines):
        raise SystemExit(
            f"В {path} {len(src)} строк, а в тексте {len(lyrics.lines)}. "
            "Возьмите тот же файл с текстом, из которого делали разметку."
        )
    for ln, s in zip(lyrics.lines, src):
        ln.start, ln.end = float(s.get("start", 0)), float(s.get("end", 0))
        ws = s.get("words") or []
        for w, sw in zip(ln.words, ws):
            w.start = float(sw.get("t", ln.start))
            w.end = w.start + float(sw.get("d", 0.3))

    # Готовый JSON тоже чиним: в нём могли остаться разъехавшиеся строки из
    # прошлой разметки — иначе они молча переедут в новую страницу.
    from .align import repair_lines, repair_order
    log = print if verbose else (lambda m: None)
    repair_lines(lyrics, log=log)
    repair_order(lyrics, log=log)
    return lyrics


def write_lrc(path: str, lyrics: Lyrics) -> str:
    def ts(t: float) -> str:
        t = max(t or 0.0, 0.0)
        return "[%02d:%05.2f]" % (int(t // 60), t % 60)

    out = []
    if lyrics.title:
        out.append("[ti:%s]" % lyrics.title)
    if lyrics.artist:
        out.append("[ar:%s]" % lyrics.artist)
    out += [ts(ln.start) + ln.text for ln in lyrics.lines]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return path
