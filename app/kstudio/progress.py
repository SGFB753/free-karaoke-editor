"""Признаки жизни на долгих шагах.

Demucs и Whisper молчат минутами: модель грузится, разделение считается, а в
логе последняя строка так и висит. Со стороны это неотличимо от зависания —
человек не знает, ждать ему или закрывать окно.

Здесь один инструмент: раз в несколько секунд сказать «идёт, прошло столько-то»
и, если шаг умеет считать себя, добавить долю сделанного.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

Log = Callable[[str], None]


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Heartbeat:
    """Контекст: пока внутри — раз в `every` секунд пишет, что шаг ещё идёт.

        with Heartbeat(log, "выравнивание") as hb:
            model.align(..., progress_callback=hb.progress)

    Шаг, который считать себя не умеет, всё равно получит отсчёт времени.
    """

    def __init__(self, log: Log, what: str, every: float = 15.0,
                 slow_after: float = 0.0, slow_note: str = ""):
        self._log = log
        self._what = what
        self._every = every
        # Затянувшийся шаг сам по себе ничего не объясняет: человек видит только
        # растущие секунды и не знает, ждать ему или это уже беда.
        self._slow_after = slow_after
        self._slow_note = slow_note
        self._said_slow = False
        self._t0 = time.time()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._done = 0.0
        self._total = 0.0
        self._extra = ""

    # --- то, что зовут снаружи ---------------------------------------------
    def progress(self, done: float, total: float) -> None:
        """Колбэк для шагов, которые знают свой объём (секунды, куски, проценты)."""
        with self._lock:
            self._done, self._total = float(done or 0), float(total or 0)

    def note(self, text: str) -> None:
        """Приписка к следующему удару: например, процент от самого Demucs."""
        with self._lock:
            self._extra = text

    # --- механика ----------------------------------------------------------
    def _line(self) -> str:
        with self._lock:
            done, total, extra = self._done, self._total, self._extra
        s = f"  …{self._what}: идёт {mmss(time.time() - self._t0)}"
        # Долю показываем, только если она осмысленная: нулевой или полный
        # счётчик сообщает не больше, чем его отсутствие.
        if total > 0 and 0 < done < total:
            s += f", готово {done / total * 100:.0f}%"
        if extra:
            s += f" ({extra})"
        return s

    def _run(self) -> None:
        while not self._stop.wait(self._every):
            try:
                self._log(self._line())
                if (self._slow_note and not self._said_slow and self._slow_after
                        and time.time() - self._t0 > self._slow_after):
                    self._said_slow = True
                    self._log("  " + self._slow_note)
            except Exception:
                # Признак жизни не имеет права уронить сам шаг.
                return

    def __enter__(self) -> "Heartbeat":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        return None
