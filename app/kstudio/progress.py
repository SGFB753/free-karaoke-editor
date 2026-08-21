"""Signs of life during long steps.

Demucs and Whisper stay silent for minutes: the model loads, the separation is
computed, and the last line of the log just hangs there. From outside that is
indistinguishable from a freeze — a person does not know whether to wait or to
close the window.

There is one tool here: every few seconds say “running, this much has passed”
and, if the step can measure itself, add the share that is done.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .i18n import tr

Log = Callable[[str], None]


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Heartbeat:
    """A context manager: while inside, every `every` seconds it reports that
    the step is still running.

        with Heartbeat(log, "alignment") as hb:
            model.align(..., progress_callback=hb.progress)

    A step that cannot measure itself still gets the elapsed time.
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
        gone = time.time() - self._t0
        s = "  …" + self._what + tr(": running ", ": идёт ") + mmss(gone)
        # Show the fraction only when it means something: a counter at zero or
        # at the very end says no more than no counter at all.
        if total > 0 and 0 < done < total:
            share = done / total
            s += tr(", done ", ", готово ") + f"{share * 100:.0f}%"
            # How long is left, at the pace this very machine has been keeping.
            # An estimate, and an honest one: it is measured, not guessed at.
            left = gone / share - gone
            if left > 5:
                s += tr(", about ", ", осталось примерно ") + mmss(left) + tr(" left", "")
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
