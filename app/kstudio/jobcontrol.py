"""Thread-scoped cancellation, with a non-cancellable atomic commit phase."""
import sys
import threading
from contextlib import contextmanager


class Cancelled(BaseException):
    """Not an inference failure: do not retry with another model."""


class Control:
    def __init__(self):
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.committing = False
        self.children = []

    def cancel(self):
        with self.lock:
            if self.committing:
                return False
            self.event.set()
            for child in self.children:
                if child.poll() is None:
                    try:
                        child.terminate()
                    except OSError:
                        pass
            return True


_local = threading.local()


def current():
    return getattr(_local, 'control', None)


def checkpoint():
    control = current()
    if control and control.event.is_set():
        raise Cancelled()


def commit():
    control = current()
    if control:
        with control.lock:
            checkpoint()
            control.committing = True


def register_child(child):
    control = current()
    if control:
        with control.lock:
            control.children.append(child)
            if control.event.is_set() and child.poll() is None:
                child.terminate()


@contextmanager
def scope(control):
    previous = current()
    previous_trace = sys.gettrace()
    _local.control = control

    def trace(frame, event, arg):
        # Interrupt Python inference loops, never project-file writes. A native
        # CUDA/CPU operation returns before its next Python cancellation point.
        path = frame.f_code.co_filename.replace('\\', '/').lower()
        if any(part in path for part in ('/torch/', '/whisper/', '/qwen_asr/',
                                        '/kstudio/align.py', '/kstudio/qwen.py')):
            # Let first-time imports finish: interrupting module initialization
            # can leave shared dependencies partially initialized for next jobs.
            if getattr(frame.f_globals.get('__spec__'), '_initializing', False):
                return None
            checkpoint()
            return trace
        return None

    try:
        checkpoint()
        sys.settrace(trace)
        yield
        checkpoint()
    finally:
        sys.settrace(previous_trace)
        _local.control = previous
