#!/usr/bin/env python3
"""Караоке-студия — окно программы вместо возни с файлами.

    py studio.py

Открывается окно, в нём список песен и редактор. Правки пишутся на диск сразу,
пересобирать ничего не нужно. Тяжёлое (Demucs, Whisper) считается один раз при
добавлении песни.

Внутри — обычный локальный сервер: браузер служит окном, вся работа идёт в
Python, у которого есть доступ к файлам.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from kstudio import i18n
from kstudio.i18n import tr
from kstudio import __version__            # noqa: E402
from kstudio import audio as AU            # noqa: E402
from kstudio import build as B             # noqa: E402
from kstudio import lang as LG            # noqa: E402
from kstudio import project as P           # noqa: E402
from kstudio import separate as S          # noqa: E402

UI = os.path.join(ROOT, "kstudio", "studio.html")
PROJECTS = P.projects_root()
JOBS: dict = {}
JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
#  Фоновые задачи с отчётом о ходе работы
# --------------------------------------------------------------------------- #

def start_job(title: str, fn) -> str:
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "title": title, "log": [], "done": False,
                     "ok": False, "result": None, "error": None, "started": time.time()}

    def log(msg: str):
        with JOBS_LOCK:
            JOBS[jid]["log"].append(str(msg))
            del JOBS[jid]["log"][:-200]

    def run():
        try:
            res = fn(log)
            with JOBS_LOCK:
                JOBS[jid].update(done=True, ok=True, result=res)
        except Exception as e:
            from kstudio import sysinfo
            if sysinfo.is_memory_error(e):
                msg = sysinfo.memory_advice(sysinfo.NEED_DEMUCS, sysinfo.available_gb())
            else:
                msg = f"Ошибка: {e}"
                traceback.print_exc()
            for line in msg.splitlines():
                log(line)
            with JOBS_LOCK:
                JOBS[jid].update(done=True, ok=False, error=msg.splitlines()[0])

    threading.Thread(target=run, daemon=True).start()
    return jid


# --------------------------------------------------------------------------- #

def dec_path(p: str) -> str:
    """Путь из запроса в нормальный вид.

    http.server разбирает строку запроса как latin-1, поэтому русские имена
    приезжают мусором. Разворачиваем %XX в байты и читаем их как UTF-8.
    """
    s = unquote(p, encoding="latin-1", errors="replace")
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def project_dir(pid: str) -> str:
    """Только внутри папки проектов — путь из запроса наружу не выпускаем."""
    safe = os.path.basename(pid.strip().strip("/\\"))
    folder = os.path.join(PROJECTS, safe)
    if not os.path.isdir(folder) or os.path.dirname(os.path.abspath(folder)) != \
            os.path.abspath(PROJECTS):
        raise FileNotFoundError(pid)
    return folder


def capabilities() -> dict:
    have_ts = True
    try:
        import stable_whisper  # noqa: F401
    except ImportError:
        have_ts = False
    have_pil = True
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        have_pil = False
    ff = True
    try:
        AU.ffmpeg()
    except Exception:
        ff = False
    from kstudio import sysinfo
    return {"ffmpeg": ff, "whisper": have_ts, "demucs": S.available(),
            "pillow": have_pil, "version": __version__,
            "models": downloaded_models(),
            # сколько памяти свободно и сколько какой модели нужно — чтобы окно
            # могло сказать «эта для вашей машины тяжёлая» до запуска, а не после
            "freeGb": sysinfo.available_gb(),
            "needGb": dict(sysinfo.NEED_WHISPER, demucs=sysinfo.NEED_DEMUCS),
            "langs": LG.NAMES}


def reveal(path: str) -> None:
    """Открыть папку с файлом и по возможности подсветить сам файл."""
    path = os.path.abspath(path)
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if os.name == "nt":
        # /select, показывает файл выделенным — так его видно сразу
        subprocess.Popen(["explorer", "/select,", path] if os.path.isfile(path)
                         else ["explorer", folder])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path)
                         else ["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])


def ui_lang() -> str:
    """Язык надписей окна: переменная среды, потом настройки, потом «сам»."""
    val = (os.environ.get("KARAOKE_UI_LANG") or "").strip().lower()
    if val in ("en", "ru"):
        return val
    home = os.path.dirname(ROOT)
    ini = os.path.join(ROOT, "settings.ini")
    for other in (os.path.join(home, "settings.ini"),
                  os.path.join(home, "настройки.ini")):   # места из прошлых версий
        if not os.path.isfile(ini) and os.path.isfile(other):
            ini = other
    try:
        with open(ini, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, v = line.partition("=")
                if key.strip().lower() in ("надписи", "ui-lang"):
                    v = v.split("#")[0].strip().lower()
                    if v in ("en", "ru"):
                        return v
    except OSError:
        pass
    return "auto"


def make_report(audio: str, lyrics_path: str, opts: dict) -> dict:
    """Быстрый разбор пары файлов — без Demucs и Whisper, за секунду-другую."""
    import tempfile

    from kstudio import lyrics as L
    from kstudio import report as REP

    lyr = L.load(lyrics_path)
    tmp = tempfile.mkdtemp(prefix="karaoke_rep_")
    try:
        wav = AU.to_wav(audio, os.path.join(tmp, "s.wav"))
        dur = AU.duration(wav)
        try:
            env, hop = AU.rms_envelope(wav)
        except Exception:
            env, hop = [], 0.02
        whisper = opts.get("align", "auto") != "energy" and capabilities()["whisper"]
        return REP.build(audio, lyr, dur, env, hop,
                         model=opts.get("model", "small"),
                         separate=bool(opts.get("separate", True)) and S.available(),
                         whisper=whisper,
                         language=opts.get("lang", "auto"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def downloaded_models() -> dict:
    """Какие модели Whisper уже лежат на диске.

    Иначе выбор выглядит равноценным: «medium — 1,5 ГБ» ничем не отличается от
    уже скачанной small, а разница между ними — несколько минут молчания перед
    первой разметкой. Считает то же самое, что потом пишет лог сборки.
    """
    from kstudio import models as M
    return M.whisper_all()


class Handler(BaseHTTPRequestHandler):
    server_version = "KaraokeStudio/" + __version__

    def log_message(self, fmt, *args):        # тише в консоли
        pass

    # ---------------- отправка ----------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, code: int, msg: str):
        self._json({"error": msg}, code)

    def _file(self, path: str):
        """Отдаём звук с поддержкой перемотки — браузеру нужен Range."""
        if not os.path.isfile(path):
            return self._err(404, tr("no such file", "нет файла"))
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                if start >= size:
                    return self._err(416, tr("beyond the end of the file", "за пределами файла"))
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return                       # окно закрыли или перемотали
                left -= len(chunk)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _local(self) -> bool:
        """Пускаем только обращения на localhost: страница в интернете не должна
        уметь достучаться до студии через подменённое имя узла."""
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1", "")

    # ---------------- маршруты ----------------
    def do_HEAD(self):
        self.do_GET()

    def _pick_lang(self):
        """Язык окна выбирается в браузере, а сообщения собираются здесь.

        Без этого в английском окне панель «Проверить» и лог сборки оставались
        русскими: сервер про выбор в окне ничего не знал.
        """
        want = (self.headers.get("X-Karaoke-Lang") or "").strip().lower()
        if want in ("en", "ru"):
            i18n.set_lang(want)

    def do_GET(self):
        self._pick_lang()
        u = urlparse(self.path)
        if not self._local():
            return self._err(403, tr("this computer only", "только с этого компьютера"))
        path, q = dec_path(u.path), parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                # Язык надписей окна: из настроек, иначе по языку системы.
                # Выбор кнопкой в окне всё равно перебивает это значение.
                with open(UI, encoding="utf-8") as f:
                    page = f.read().replace("__UI_LANG__", ui_lang())
                return self._send(200, page.encode("utf-8"),
                                  "text/html; charset=utf-8")

            if path == "/ui.js":
                with open(os.path.join(ROOT, "kstudio", "ui.js"), "rb") as f:
                    return self._send(200, f.read(),
                                      "application/javascript; charset=utf-8")

            if path == "/api/state":
                return self._json({"projects": P.list_all(PROJECTS),
                                   "caps": capabilities(),
                                   "projectsDir": PROJECTS})

            if path == "/api/job":
                with JOBS_LOCK:
                    job = JOBS.get(q.get("id", [""])[0])
                    return self._json(job or {"error": tr("no such task", "нет такой задачи")})

            if path == "/api/browse":
                raw = q.get("path", [""])[0]
                try:
                    raw = raw.encode("latin-1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                return self._json(browse(raw, q.get("kind", ["audio"])[0]))

            m = re.match(r"^/api/project/([^/]+)$", path)
            if m:
                folder = project_dir(m.group(1))
                data = P.load(folder)
                data["problems"] = P.problems(data)
                data["quiet"] = P.quiet_spans(data)
                data["id"] = m.group(1)
                return self._json(data)

            m = re.match(r"^/api/project/([^/]+)/audio/([a-z]+)$", path)
            if m:
                folder = project_dir(m.group(1))
                tracks = P.load(folder).get("tracks") or {}
                name = tracks.get(m.group(2))
                if not name:
                    return self._err(404, tr("no such track", "нет такой дорожки"))
                return self._file(os.path.join(folder, name))

            return self._err(404, tr("not found", "не найдено"))
        except FileNotFoundError as e:
            # Не всякий пропавший файл — это пропавший проект: раньше любая
            # такая ошибка выдавала «проект не найден», и искать было негде.
            self._err(404, tr("song not found", "проект не найден") if "проект" in str(e).lower()
                      or not str(e) else f"не найдено: {e}")
        except Exception as e:
            traceback.print_exc()
            self._err(500, str(e))

    def _upload(self, q):
        """Файл, брошенный в окно. Браузер не даёт путь к нему, только содержимое,
        поэтому принимаем байты и кладём рядом с проектами."""
        raw = (q.get("name", [""])[0] or "файл")
        try:
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        name = os.path.basename(raw.replace("\\", "/"))
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip() or "файл"

        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0:
            return self._err(400, tr("empty file", "пустой файл"))
        if size > 600 * 1024 * 1024:
            return self._err(413, tr("the file is larger than 600 MB", "файл больше 600 МБ"))

        # Латиницей: кириллические имена папок ломаются на нерусских системах.
        inbox = os.path.join(PROJECTS, "_incoming")
        old_inbox = os.path.join(PROJECTS, "_входящие")
        if os.path.isdir(old_inbox) and not os.path.isdir(inbox):
            try:
                os.rename(old_inbox, inbox)      # у кого уже лежит — переедет сам
            except OSError:
                inbox = old_inbox
        os.makedirs(inbox, exist_ok=True)
        dst = os.path.join(inbox, name)
        stem, ext = os.path.splitext(dst)
        n = 2
        while os.path.exists(dst):
            dst = f"{stem}-{n}{ext}"
            n += 1

        left = size
        with open(dst, "wb") as f:
            while left > 0:
                chunk = self.rfile.read(min(262144, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left > 0:
            os.remove(dst)
            return self._err(400, tr("the file did not arrive in full", "файл дошёл не полностью"))
        return self._json({"path": dst, "name": os.path.basename(dst)})

    def do_POST(self):
        self._pick_lang()
        u = urlparse(self.path)
        if not self._local():
            return self._err(403, tr("this computer only", "только с этого компьютера"))
        path = dec_path(u.path)
        q = parse_qs(u.query)
        try:
            if path == "/api/upload":
                return self._upload(q)
            body = self._body()

            if path == "/api/reveal":
                # Показать готовый файл в проводнике. Иначе после экспорта его
                # приходится искать вручную — а лежит он рядом с исходной песней.
                target = body.get("path", "")
                if not os.path.exists(target):
                    return self._err(404, tr("the file is gone: ", "файла уже нет: ") + target)
                try:
                    reveal(target)
                    return self._json({"ok": True})
                except Exception as e:
                    return self._err(500, tr(f"could not open the folder: {e}", f"не вышло открыть папку: {e}"))

            if path == "/api/report":
                # Отчёт до сборки: что за песня, что за текст и чего ждать.
                audio, lyrics = body.get("audio", ""), body.get("lyrics", "")
                for f in (audio, lyrics):
                    if not os.path.isfile(f):
                        return self._err(400, tr(f"file not found: {f}", f"файл не найден: {f}"))
                try:
                    return self._json(make_report(audio, lyrics, body))
                except Exception as e:
                    return self._err(400, tr(f"could not make sense of the files: {e}", f"не вышло разобрать файлы: {e}"))

            if path == "/api/new":
                audio, lyrics = body.get("audio", ""), body.get("lyrics", "")
                for f in (audio, lyrics):
                    if not os.path.isfile(f):
                        return self._err(400, tr(f"file not found: {f}", f"файл не найден: {f}"))
                opts = dict(align_engine=body.get("align", "auto"),
                            whisper_model=body.get("model", "small"),
                            language=body.get("lang", "auto"),
                            separate=bool(body.get("separate", True)))
                jid = start_job("Собираю песню", lambda log: os.path.basename(
                    P.create(audio, lyrics, PROJECTS, log=log, **opts)))
                return self._json({"job": jid})

            m = re.match(r"^/api/project/([^/]+)/timings$", path)
            if m:
                folder = project_dir(m.group(1))
                lines = body.get("lines")
                if not isinstance(lines, list):
                    return self._err(400, tr("no lines", "нет строк"))
                data = P.save_lines(folder, lines, colors=body.get("colors"),
                                    theme=body.get("theme"))
                return self._json({"ok": True, "problems": P.problems(data)})

            m = re.match(r"^/api/project/([^/]+)/delete$", path)
            if m:
                P.delete(project_dir(m.group(1)))
                return self._json({"ok": True})

            m = re.match(r"^/api/project/([^/]+)/track$", path)
            if m:
                folder = project_dir(m.group(1))
                src = body.get("path", "")
                kind = body.get("track", "instrumental")
                shift = bool(body.get("shift", True))
                jid = start_job("Меняю дорожку",
                                lambda log: replace_track(folder, src, kind, shift, log))
                return self._json({"job": jid})

            m = re.match(r"^/api/project/([^/]+)/realign$", path)
            if m:
                folder = project_dir(m.group(1))
                jid = start_job("Пересчитываю разметку",
                                lambda log: realign(folder, body, log))
                return self._json({"job": jid})

            m = re.match(r"^/api/project/([^/]+)/export$", path)
            if m:
                folder = project_dir(m.group(1))
                kind = body.get("kind", "html")
                jid = start_job("Экспорт " + kind,
                                lambda log: export(folder, kind, body, log))
                return self._json({"job": jid})

            return self._err(404, tr("not found", "не найдено"))
        except FileNotFoundError as e:
            # Не всякий пропавший файл — это пропавший проект: раньше любая
            # такая ошибка выдавала «проект не найден», и искать было негде.
            self._err(404, tr("song not found", "проект не найден") if "проект" in str(e).lower()
                      or not str(e) else f"не найдено: {e}")
        except Exception as e:
            traceback.print_exc()
            self._err(500, str(e))


# --------------------------------------------------------------------------- #

AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".mp4"}
TEXT_EXT = {".txt", ".lrc"}


def browse(path: str, kind: str) -> dict:
    """Простой обзор папок — файловых диалогов у браузера для нас нет."""
    exts = AUDIO_EXT if kind == "audio" else TEXT_EXT
    if not path:
        path = os.path.expanduser("~")
    path = os.path.abspath(path)
    # Запомненная папка может исчезнуть: флешку вынули, папку переименовали.
    # Поднимаемся вверх, пока не найдём существующую, а не падаем с ошибкой.
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    if not os.path.isdir(path):
        path = os.path.expanduser("~")

    dirs, files = [], []
    try:
        for name in sorted(os.listdir(path), key=str.lower):
            full = os.path.join(path, name)
            if name.startswith("."):
                continue
            if os.path.isdir(full):
                dirs.append({"name": name, "path": full})
            elif os.path.splitext(name)[1].lower() in exts:
                files.append({"name": name, "path": full,
                              "size": os.path.getsize(full)})
    except (PermissionError, OSError):
        pass                      # нет прав или папка исчезла между проверками

    drives = []
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            d = f"{letter}:\\"
            if os.path.exists(d):
                drives.append(d)

    return {"path": path, "parent": os.path.dirname(path) or path,
            "dirs": dirs, "files": files, "drives": drives}


def realign(folder: str, opts: dict, log) -> dict:
    """Посчитать разметку заново — например, когда доставили stable-ts.
    Стемы уже лежат в проекте, так что Demucs повторно не гоняем."""
    from kstudio import align as A
    from kstudio import lyrics as L

    data = P.load(folder)
    # Текст можно подменить: правку разбивки по строкам ради удобства пения
    # делают уже после первой сборки, и гонять всё заново из-за неё незачем.
    fresh = (opts.get("lyrics") or "").strip()
    if fresh:
        if not os.path.isfile(fresh):
            raise FileNotFoundError(tr("lyrics file not found: ", "файл с текстом не найден: ") + fresh)
        src = fresh
        log(tr(f"Taking the lyrics from {os.path.basename(src)}",
               f"Беру текст из {os.path.basename(src)}"))
    else:
        src = data.get("source_lyrics")
        if not src or not os.path.isfile(src):
            raise FileNotFoundError(
                "исходный файл с текстом не найден: " + str(src) +
                ". Выберите файл кнопкой «Заменить текст».")
    lyr = L.load(src)
    was = len(data.get("lines") or [])
    if len(lyr.lines) != was:
        log(tr(f"The text now has {len(lyr.lines)} lines instead of {was} — "
               f"the timing will be worked out for the new split.",
               f"В тексте теперь {len(lyr.lines)} строк вместо {was} — "
               f"разметка будет посчитана под новую разбивку."))
    if not lyr.lines:
        raise ValueError(tr("the lyrics file has no lines at all",
                            "в файле с текстом не нашлось ни одной строки"))

    tracks = data.get("tracks") or {}
    stem = tracks.get("vocals") or tracks.get("mix") or tracks.get("instrumental")
    audio = os.path.join(folder, stem)
    AU.ensure_on_path()
    lyr, engine = A.align(lyr, audio, data["duration"],
                          opts.get("align", "auto"), opts.get("model", "small"),
                          opts.get("lang", "auto"), None, log)
    data["lines"] = [ln.to_json() for ln in lyr.lines]
    data["engine"] = engine
    data["source_lyrics"] = os.path.abspath(src)
    data["title"] = lyr.title or data.get("title") or ""
    if lyr.artist:
        data["artist"] = lyr.artist
    data["edited"] = time.time()
    P.save(folder, data)
    log(tr("The timing has been recomputed.", "Разметка пересчитана."))
    return {"kind": "realign", "engine": engine,
            "lines": len(lyr.lines), "was": was}


def offset_between(a: list, b: list, hop: float, limit: float = 12.0) -> float:
    """На сколько вторая запись сдвинута относительно первой, в секундах.

    Официальный инструментал почти всегда начинается не там же, где сведённая
    песня: другой отсчёт, другая пауза перед вступлением.

    Две тонкости, на которых прямолинейный поиск ошибается:
      • музыка повторяется, и совпадений много — на такте, на куплете. Из
        равных по качеству выбираем БЛИЖАЙШЕЕ к нулю, а не первое попавшееся:
        мы ищем несовпадение начала, а не место припева.
      • шаг огибающей грубее, чем слышно. Сначала ищем грубо и быстро, потом
        уточняем рядом и доводим вершину параболой.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    a = [x - ma for x in a]
    b = [x - mb for x in b]

    def score(sh: int, step: int = 2) -> float:
        lo, hi = max(0, -sh), min(n, n - sh)
        if hi - lo < n // 4:
            return -1e18
        s = 0.0
        for i in range(lo, hi, step):
            s += a[i] * b[i + sh]
        return s / (hi - lo)

    # 1. Грубо: смотрим каждый четвёртый сдвиг и реже перебираем отсчёты.
    span = int(limit / hop)
    coarse = max(1, int(0.04 / hop))
    rough = [(score(sh, 8), sh) for sh in range(-span, span + 1, coarse)]
    best_s = max(v for v, _ in rough)
    if best_s <= 0:
        return 0.0
    # Из всех почти таких же хороших берём ближайший к нулю.
    near = [sh for v, sh in rough if v >= best_s * 0.97]
    guess = min(near, key=abs)

    # 2. Точно: рядом с найденным, с полным шагом.
    lo, hi = guess - 2 * coarse, guess + 2 * coarse
    fine = [(score(sh), sh) for sh in range(lo, hi + 1)]
    best_s, best = max(fine)
    near = [sh for v, sh in fine if v >= best_s * 0.995]
    best = min(near, key=abs)
    best_s = dict((sh, v) for v, sh in fine)[best]

    # 3. Вершину уточняем параболой: настоящий сдвиг редко кратен шагу.
    left, right = score(best - 1), score(best + 1)
    frac = 0.0
    if left > -1e17 and right > -1e17:
        denom = left - 2 * best_s + right
        if denom != 0:
            frac = max(-0.5, min(0.5, 0.5 * (left - right) / denom))
    return round((best + frac) * hop, 4)


def shift_audio(path: str, seconds: float, tmp: str) -> str:
    """Сдвинуть запись во времени: положительное — позже, отрицательное — раньше."""
    out = os.path.join(tmp, "shifted.wav")
    if seconds >= 0:
        ms = int(round(seconds * 1000))
        flt = f"adelay={ms}|{ms}"
    else:
        flt = f"atrim=start={abs(seconds):.3f},asetpts=PTS-STARTPTS"
    p = subprocess.run([AU.ffmpeg(), "-y", "-loglevel", "error", "-i", path,
                        "-af", flt, out], capture_output=True, text=True)
    if p.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError((p.stderr or tr("ffmpeg could not cope", "ffmpeg не справился")).strip()[:200])
    return out


def _best_gain(mix: str, instr: str, spans: list) -> float:
    """Во сколько раз усилить инструментал, чтобы он лучше всего гасил оригинал.

    Считаем по настоящим отсчётам, а не по огибающей: огибающая нормирована
    на собственный максимум каждой записи, и отношение по ней ничего не значит.
    Решение простое: k = <микс·инструментал> / <инструментал·инструментал> —
    та величина, при которой разность самая тихая.
    """
    sr = 16000
    a = AU.read_pcm_mono(mix, sr)
    b = AU.read_pcm_mono(instr, sr)
    n = min(len(a), len(b))
    if not n:
        return 1.0
    idx = []
    for x, y in (spans or [(0, n / sr)]):
        idx.append((max(0, int(x * sr)), min(n, int(y * sr))))
    num = den = 0.0
    for lo, hi in idx:
        for i in range(lo, hi, 4):          # каждый четвёртый: точности хватает
            av, bv = a[i], b[i]
            num += av * bv
            den += bv * bv
    if den <= 0:
        return 1.0
    return max(0.1, min(10.0, num / den))


def _rms_at(path: str, spans: list) -> float:
    """Настоящая громкость записи в указанных промежутках, без нормировки."""
    sr = 16000
    x = AU.read_pcm_mono(path, sr)
    total = cnt = 0.0
    for a, b in (spans or [(0, len(x) / sr)]):
        for i in range(max(0, int(a * sr)), min(len(x), int(b * sr)), 4):
            total += float(x[i]) ** 2
            cnt += 1
    return (total / cnt) ** 0.5 if cnt else 0.0


def _spectral_vocals(mix: str, instr: str, spans: list, out: str, log) -> Optional[str]:
    """Вычесть инструментал по частотам, а не одной громкостью.

    Официальный инструментал почти никогда не совпадает с тем, что лежит под
    голосом в песне: другой мастеринг, другая эквализация, другой уровень.
    Одним множителем такое не гасится — часть аранжировки остаётся в «голосе»
    и звучит рядом с минусовкой как вторая, чужая запись.

    Поэтому множитель ищем свой для каждой частоты. По кускам без пения, где
    обе дорожки должны быть одинаковыми, считаем H(f) = <M·conj(I)> / <|I|²> —
    то самое усиление и сдвиг фазы, которыми инструментал превращается в свою
    же копию из песни. Дальше вычитаем уже исправленный инструментал.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    if not spans:
        return None

    sr = 44100
    a = np.frombuffer(AU.read_pcm_mono(mix, sr).tobytes(), dtype="<i2").astype(np.float32) / 32768.0
    b = np.frombuffer(AU.read_pcm_mono(instr, sr).tobytes(), dtype="<i2").astype(np.float32) / 32768.0
    n = min(len(a), len(b))
    N, hop = 4096, 1024                  # окно 93 мс, перекрытие 75 %
    if n < N * 4:
        return None
    a, b = a[:n], b[:n]
    win = np.hanning(N + 1)[:N].astype(np.float32)
    frames = 1 + (n - N) // hop
    idx = np.arange(N)[None, :] + hop * np.arange(frames)[:, None]

    A = np.fft.rfft(a[idx] * win, axis=1)
    B = np.fft.rfft(b[idx] * win, axis=1)

    # кадры, целиком попавшие в места без пения
    mask = np.zeros(frames, dtype=bool)
    for lo, hi in spans:
        i0 = max(0, int((lo * sr) // hop))
        i1 = min(frames, int(((hi * sr) - N) // hop) + 1)
        if i1 > i0:
            mask[i0:i1] = True
    if int(mask.sum()) < 12:             # мерить не на чем
        return None

    num = (A[mask] * np.conj(B[mask])).sum(axis=0)
    den = (np.abs(B[mask]) ** 2).sum(axis=0)
    quiet_bins = den < den.max() * 1e-9  # там, где инструментала нет, гасить нечего
    H = num / np.where(den > 0, den, 1.0)
    H[quiet_bins] = 0.0

    # Сглаживаем по частоте: соседние полосы не могут отличаться втрое, а по
    # одному куску без пения оценка шумит.
    k = 5
    pad = np.r_[H[:k][::-1], H, H[-k:][::-1]]
    H = np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    mag = np.abs(H)
    H = np.where(mag > 4.0, H / np.maximum(mag, 1e-9) * 4.0, H)

    V = A - H[None, :] * B
    frag = np.fft.irfft(V, n=N, axis=1).astype(np.float32) * win
    voice = np.zeros(n, dtype=np.float32)
    norm = np.zeros(n, dtype=np.float32)
    w2 = win ** 2
    for i in range(frames):
        j = i * hop
        voice[j:j + N] += frag[i]
        norm[j:j + N] += w2
    voice /= np.maximum(norm, 1e-6)

    import wave
    pcm = np.clip(voice, -1.0, 1.0)
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    log(tr("  the instrumental was matched per frequency, not by one volume",
           "  инструментал выровнен по частотам, а не одной громкостью"))
    return out


def extract_vocals(mix: str, instr: str, off: float, quiet: list, tmp: str,
                   log) -> Optional[str]:
    """Голос ≈ оригинал минус инструментал.

    Когда инструментал взят у того же исполнителя и от той же записи, разница
    двух дорожек — это и есть вокал. Иначе «голосом» остаётся весь оригинал,
    и поверх нового минуса играет вторая аранжировка: именно это и слышно как
    «голос не совпадает».

    Возвращает путь к дорожке или None, если вычитание не сработало.
    """
    # 1. Приводим оригинал в то же время, что и новый инструментал.
    aligned = mix if abs(off) < 0.005 else shift_audio(mix, off, tmp)

    # 2. Подбираем громкость: у инструментала она почти всегда другая.
    #    Меряем там, где не поют — там обе дорожки должны звучать одинаково.
    spans = [(q["start"], q["end"]) for q in quiet] or None
    k = _best_gain(aligned, instr, spans)
    log(tr(f"  instrumental volume matched: ×{k:.2f}",
            f"  громкость инструментала подобрана: ×{k:.2f}"))

    # 3. Вычитаем. amerge сводит две записи в два канала, pan берёт их разность.
    out = os.path.join(tmp, "voice.wav")
    flt = (f"[1:a]volume={k:.4f}[i];[0:a][i]amerge=inputs=2,"
           f"pan=mono|c0=c0-c1[out]")
    p = subprocess.run([AU.ffmpeg(), "-y", "-loglevel", "error",
                        "-i", aligned, "-i", instr,
                        "-filter_complex", flt, "-map", "[out]", out],
                       capture_output=True, text=True)
    if p.returncode != 0 or not os.path.isfile(out):
        log(tr(f"  subtracting the instrumental failed ({(p.stderr or '').strip()[:80]})",
               f"  вычесть инструментал не вышло ({(p.stderr or '').strip()[:80]})"))
        return None

    # 3б. То же самое, но с поправкой на каждую частоту. Обычно выходит заметно
    #     чище; берём тот вариант, где в местах без пения тише.
    spec = _spectral_vocals(aligned, instr, spans, os.path.join(tmp, "voice_f.wav"), log)
    if spec and spans:
        r_plain, r_spec = _rms_at(out, spans), _rms_at(spec, spans)
        if r_spec < r_plain * 0.9:
            gain = 20 * math.log10(max(r_spec, 1e-9) / max(r_plain, 1e-9))
            log(tr(f"  per frequency, {-gain:.0f} dB less of the arrangement is left",
                   f"  по частотам аранжировки осталось на {-gain:.0f} дБ меньше"))
            out = spec
        else:
            log(tr("  plain subtraction was no worse — taking that",
                   "  простое вычитание оказалось не хуже — беру его"))

    # 4. Проверяем, что стало тише именно там, где не поют. Если нет —
    #    инструментал не от этой записи, и подсовывать мусор нельзя.
    if spans:
        before, after = _rms_at(aligned, spans), _rms_at(out, spans)
        if before > 1e-6:
            drop = 20 * math.log10(max(after, 1e-9) / before)
            log(tr(f"  where nobody sings it got {-drop:.0f} dB quieter",
                   f"  в местах без пения стало тише на {-drop:.0f} дБ"))
            if drop > -4.0:
                log(tr("  the instrumental does not match the original — not extracting the voice",
                       "  инструментал не совпал с оригиналом — голос не выделяю"))
                return None
    return out


def replace_track(folder: str, src: str, kind: str, shift: bool, log) -> dict:
    """Подменить дорожку в готовом проекте, оставив разметку на месте.

    Смысл: разметка уже выверена руками, а минусовку хочется настоящую —
    ту, что выпустил исполнитель. Пересчитывать ничего не надо, меняется
    только звук.
    """
    if kind not in ("instrumental", "vocals", "mix"):
        raise ValueError(tr(f"unknown track: {kind}", f"неизвестная дорожка: {kind}"))
    if not os.path.isfile(src):
        raise FileNotFoundError(src)

    data = P.load(folder)
    tracks = dict(data.get("tracks") or {})
    old_name = tracks.get(kind)

    import tempfile
    tmp = tempfile.mkdtemp(prefix="karaoke_track_")
    try:
        AU.ffmpeg(); AU.ensure_on_path()
        log(tr(f"Preparing {os.path.basename(src)}…", f"Готовлю {os.path.basename(src)}…"))
        wav = AU.to_wav(src, os.path.join(tmp, "new.wav"))
        new_dur = AU.duration(wav)
        old_dur = float(data.get("duration") or 0)
        log(tr(f"Length of the new track: {int(new_dur//60)}:{int(new_dur%60):02d}"
               f" (in the song {int(old_dur//60)}:{int(old_dur%60):02d})",
               f"Длина новой дорожки: {int(new_dur//60)}:{int(new_dur%60):02d}"
               f" (в проекте {int(old_dur//60)}:{int(old_dur%60):02d})"))

        # Сдвиг ищем по той дорожке, что уже лежит в проекте.
        off = 0.0
        ref = old_name or tracks.get("mix") or tracks.get("vocals")
        if ref:
            try:
                # Мельче шаг — точнее сдвиг. 10 мс это ещё быстро, а ошибка
                # вдвое меньше, чем на стандартных 20.
                ea, ha = AU.rms_envelope(os.path.join(folder, ref), hop_ms=10)
                eb, _ = AU.rms_envelope(wav, hop_ms=10)
                off = offset_between(ea, eb, ha)
            except Exception as e:                        # pragma: no cover
                log(tr(f"  could not work out the shift ({e})", f"  сдвиг определить не вышло ({e})"))
        if abs(off) >= 0.05:
            log(tr(f"The new track runs {'later' if off > 0 else 'earlier'} than the "
                   f"old one by {abs(off):.2f} s.",
                   f"Новая дорожка идёт {'позже' if off > 0 else 'раньше'} прежней "
                   f"на {abs(off):.2f} с."))
        else:
            log(tr("The start matches the previous track.", "Начало совпадает с прежней дорожкой."))

        log(tr("Encoding…", "Кодирую…"))
        name = os.path.basename(AU.encode(wav, os.path.join(folder, kind + "_new"),
                                          "mp3")[0])
        tracks[kind] = name
        made_voice = False
        if kind == "instrumental" and "mix" in tracks:
            # Был один общий звук. Оставлять его «голосом» нельзя: поверх нового
            # минуса заиграет вторая аранжировка. Пробуем получить настоящий
            # голос вычитанием — оригинал минус инструментал.
            from kstudio import report as REP
            mix_path = os.path.join(folder, tracks["mix"])
            log(tr("Trying to extract the voice: the original minus your instrumental…",
                "Пробую выделить голос: оригинал минус ваш инструментал…"))
            try:
                menv, mhop = AU.rms_envelope(mix_path)
                quiet = REP.quiet_stretches(menv, mhop)
            except Exception:
                quiet = []
            voice = extract_vocals(mix_path, wav, off, quiet, tmp, log)
            if voice:
                tracks["vocals"] = os.path.basename(
                    AU.encode(voice, os.path.join(folder, "vocals_sub"), "mp3")[0])
                try:
                    os.remove(mix_path)
                except OSError:
                    pass
                tracks.pop("mix", None)
                data["envelope"] = P.build_envelope(voice, log)
                made_voice = True
                log(tr("The voice was extracted — that is what you sing to, and the waveform "
                       "comes from it.",
                       "Голос выделен — под него и поётся, волна на дорожке от него же."))
            else:
                # Не вышло — честнее убрать голосовую дорожку совсем, чем
                # подсовывать вместо неё целую песню.
                try:
                    os.remove(mix_path)
                except OSError:
                    pass
                tracks.pop("mix", None)
                log(tr("There will be no voice: only your instrumental plays.",
                       "Голоса не будет: играет только ваша минусовка."))

        moved = 0.0
        if shift and abs(off) >= 0.02:
            for ln in data.get("lines") or []:
                ln["start"] += off; ln["end"] += off
                for w in ln.get("words") or []:
                    w["t"] += off
            moved = off
            log(tr(f"The timing was shifted by {off:+.3f} s along with the track.",
                f"Разметку сдвинул на {off:+.3f} с вслед за дорожкой."))

            # И голос тоже: он остался в старом времени, а минус теперь в новом.
            # Без этого вокал звучит невпопад с новой минусовкой.
            voc = None if made_voice else tracks.get("vocals")
            if voc:
                try:
                    shifted = shift_audio(os.path.join(folder, voc), off, tmp)
                    new_voc = os.path.basename(
                        AU.encode(shifted, os.path.join(folder, "vocals_new"), "mp3")[0])
                    old_voc = os.path.join(folder, voc)
                    tracks["vocals"] = new_voc
                    if os.path.basename(old_voc) != new_voc:
                        try:
                            os.remove(old_voc)
                        except OSError:
                            pass
                    log(tr("The voice was moved by the same amount — it is in time with the "
                           "instrumental now.",
                           "Голос подвинут на столько же — теперь он в такт с минусовкой."))
                    data["envelope"] = P.build_envelope(shifted, log)
                except Exception as e:
                    log(tr(f"  could not move the voice ({e}) — turn it down with the slider",
                           f"  голос подвинуть не вышло ({e}) — приглушите его ползунком"))

        data["tracks"] = tracks
        data["duration"] = round(max(old_dur, new_dur), 3)
        data["edited"] = time.time()
        P.save(folder, data)

        if old_name and old_name != name:
            try:
                os.remove(os.path.join(folder, old_name))
            except OSError:
                pass
        log(tr("Done.", "Готово."))
        return {"kind": "track", "track": kind, "offset": off, "shifted": moved,
                "duration": data["duration"], "lengthDiff": round(new_dur - old_dur, 2)}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def export(folder: str, kind: str, opts: dict, log) -> dict:
    """Экспорт: автономная HTML-страница или ролик MP4."""
    data = P.load(folder)
    lyr = _lyrics_from(data)
    tracks = {}
    for name, fname in (data.get("tracks") or {}).items():
        path = os.path.join(folder, fname)
        mime = mimetypes.guess_type(path)[0] or "audio/mpeg"
        tracks[name] = (path, mime)

    out_dir = os.path.dirname(data.get("source_audio") or folder) or folder
    base = P.slugify(data.get("title") or "караоке")

    if kind == "html":
        # Имя латиницей: файл уедет к людям, у которых кириллица в именах
        # превращается в крякозябры.
        out = os.path.join(out_dir, base + "_karaoke.html")
        log(tr("Building the standalone page…", "Собираю автономную страницу…"))
        B.build_html(out, lyr, data["duration"], tracks, data.get("engine", ""),
                     embed=True, title=data.get("title"), artist=data.get("artist"),
                     colors=data.get("colors"), theme=data.get("theme"))
        log(tr(f"Done: {out}", f"Готово: {out}"))
        return {"kind": "html", "path": out}

    if kind == "mp4":
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "video", os.path.join(ROOT, "tools", "video.py"))
        video = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(video)

        tmp_html = os.path.join(folder, "_render.html")
        B.build_html(tmp_html, lyr, data["duration"], tracks, data.get("engine", ""),
                     embed=True, title=data.get("title"), artist=data.get("artist"),
                     colors=data.get("colors"), theme=data.get("theme"))
        out = os.path.join(out_dir, base + ".mp4")

        class Args:
            pass
        a = Args()
        a.width = int(opts.get("width", 1920)); a.height = int(opts.get("height", 1080))
        a.fps = int(opts.get("fps", 30)); a.crf = int(opts.get("crf", 20))
        a.preset = opts.get("preset", "medium"); a.font = opts.get("font")
        a.start = 0.0; a.seconds = float(opts.get("seconds", 0) or 0)
        a.audio = opts.get("audio", "minus"); a.timings = None; a.output = out

        log(tr("Drawing the frames…", "Рисую кадры…"))
        payload = B.read_payload(tmp_html)
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="karaoke_render_")
        try:
            wav = video.extract_audio(payload, tmp_html, tmpdir, a.audio)
            last = [""]
            def prog(msg):
                if msg != last[0]:
                    last[0] = msg
                    log(msg)
            video.render(payload, wav, out, a, on_progress=prog)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
            try:
                os.remove(tmp_html)
            except OSError:
                pass
        log(tr(f"Done: {out}", f"Готово: {out}"))
        return {"kind": "mp4", "path": out}

    raise ValueError(tr(f"unknown export kind: {kind}", f"неизвестный вид экспорта: {kind}"))


def _lyrics_from(data: dict):
    """Собрать объект текста из сохранённой разметки — для экспорта."""
    from kstudio.lyrics import Line, Lyrics, Word
    lyr = Lyrics(title=data.get("title"), artist=data.get("artist"))
    for l in data.get("lines") or []:
        words = []
        for w in l.get("words") or []:
            wd = Word(w["w"], syllables=w.get("s") or 1)
            wd.start = float(w["t"])
            wd.end = wd.start + float(w["d"])
            words.append(wd)
        ln = Line(text=l.get("text", ""), words=words, section=l.get("section"),
                  backing=bool(l.get("backing")), voice=int(l.get("voice") or 1),
                  keep=bool(l.get("keep")))
        ln.start, ln.end = float(l.get("start", 0)), float(l.get("end", 0))
        lyr.lines.append(ln)
    return lyr


# --------------------------------------------------------------------------- #

def free_port(preferred: int = 8770) -> int:
    for port in range(preferred, preferred + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def open_window(url: str) -> None:
    """Окно приложения: без адресной строки и вкладок, если найдётся Chrome/Edge."""
    if os.name == "nt":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for exe in candidates:
            if os.path.isfile(exe):
                try:
                    subprocess.Popen([exe, f"--app={url}",
                                      "--window-size=1280,860"])
                    return
                except Exception:
                    pass
    webbrowser.open(url)


def parse_args(argv):
    """Разбор ключей. Раньше их не было вовсе: --port молча игнорировался, порт
    выбирался сам, и было непонятно, куда всё уехало."""
    port, no_browser = None, False
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("--no-browser", "-n"):
            no_browser = True
        elif a in ("--port", "-p"):
            if not args or not args[0].isdigit():
                raise SystemExit(tr("--port needs a port number, for example: --port 8770",
                                    "После --port нужен номер порта, например: --port 8770"))
            port = int(args.pop(0))
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
        elif a in ("-h", "--help"):
            print("py studio.py [--port 8770] [--no-browser]")
            raise SystemExit(0)
        else:
            raise SystemExit(tr(f"Unknown option: {a}", f"Не понял ключ: {a}"))
    return port, no_browser


def main(argv=None) -> int:
    want, no_browser = parse_args(sys.argv[1:] if argv is None else argv)
    if want is None:
        port = free_port()
        if not port:
            print(tr("Could not find a free port.", "Не нашёл свободный порт."), file=sys.stderr)
            return 1
    else:
        # Порт назвали явно — значит, на него и рассчитывают. Тихо переехать на
        # соседний нельзя: обращаться будут по названному, и попадут в пустоту
        # или в чужую студию, которая этот порт и занимает.
        port = want
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                print(tr(f"Port {port} is taken — the studio may already be running.",
                         f"Порт {port} уже занят — возможно, студия уже запущена."),
                      file=sys.stderr)
                print(tr(f"Open http://127.0.0.1:{port}/ or pick another port: "
                         f"--port {port + 1}",
                         f"Откройте http://127.0.0.1:{port}/ или укажите другой "
                         f"порт: --port {port + 1}"), file=sys.stderr)
                return 1
    url = f"http://127.0.0.1:{port}/"

    caps = capabilities()
    print("=" * 58)
    print(tr("  KARAOKE STUDIO", "  КАРАОКЕ-СТУДИЯ"), __version__)
    print("=" * 58)
    print(tr(f"Songs: {PROJECTS}", f"Проекты: {PROJECTS}"))
    if not caps["ffmpeg"]:
        print(tr("\nffmpeg was not found — nothing works without it.",
                  "\nffmpeg не найден — без него ничего не заработает."))
        print(tr("Run Install.bat (install.command on macOS)\n",
                  "Запустите Install.bat\n"))
    print(tr(f"Window: {url}", f"Окно: {url}"))
    print(tr("To finish, close this console window or press Ctrl+C.\n",
                  "Чтобы закончить — закройте это окно консоли или нажмите Ctrl+C.\n"))

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if not no_browser:
        threading.Timer(0.6, lambda: open_window(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(tr("\nClosing the studio.", "\nЗакрываю студию."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
