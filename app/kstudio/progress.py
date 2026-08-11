"""Signs of life during long steps.

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
    """A context manager: while inside, every `every` seconds it reports that
    the step is still running.

        with Heartbeat(log, "выравнивание") as hb:
            model.align(..., progress_callback=hb.progress)

    Шаг, который считать себя не умеет, всё равно получит отсчёт времени.
    """

    def __init__(self, log: Log, what: str, every: float = 15.0,
                 slow_after: float = 0.0, slow_note: str = ""):
        self._log = log
        self._what = what
        self._every = every
        # A step that drags on explains nothing by itself: all one sees is the
        # seconds going up, with no idea whether to keep waiting.
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

    # --- what the caller uses ----------------------------------------------
    def progress(self, done: float, total: float) -> None:
        """Callback for steps that know their size (seconds, chunks, percent)."""
        with self._lock:
            self._done, self._total = float(done or 0), float(total or 0)

    def note(self, text: str) -> None:
        """A note for the next beat: for example, Demucs\'s own percentage."""
        with self._lock:
            self._extra = text

    # --- machinery ---------------------------------------------------------
    def _line(self) -> str:
        with self._lock:
            done, total, extra = self._done, self._total, self._extra
        s = f"  …{self._what}: идёт {mmss(time.time() - self._t0)}"
        # Show the fraction only when it means something: a counter at zero or
        # at the very end says no more than no counter at all.
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
                # A sign of life must never bring the step down with it.
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
