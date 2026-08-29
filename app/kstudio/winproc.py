"""Start command-line helpers without flashing a Windows console window.

The Studio executable is a GUI application.  Its children (ffmpeg, Whisper's
ffmpeg, Demucs and yt-dlp) are console programs, however, so CreateProcess
otherwise gives each of them a short-lived black window.  Keep the policy in
one place and leave genuine GUI children such as Explorer and the browser
alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict


def hidden_kwargs(values: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Return subprocess keyword arguments suitable for a background tool."""
    out = dict(values or {})
    if os.name != "nt" or os.environ.get("KARAOKE_SHOW_CHILD_CONSOLES") == "1":
        return out

    flags = int(out.get("creationflags", 0) or 0)
    new_console = int(getattr(subprocess, "CREATE_NEW_CONSOLE", 0) or 0)
    if not new_console or not flags & new_console:
        out["creationflags"] = flags | int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)

    # CREATE_NO_WINDOW is sufficient on current Windows, while SW_HIDE also
    # covers older launchers which ignore it.  Preserve caller-supplied setup.
    if "startupinfo" not in out and hasattr(subprocess, "STARTUPINFO"):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
        startup.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
        out["startupinfo"] = startup
    return out


def run(args, **kwargs):
    """subprocess.run for a command-line helper, hidden on Windows."""
    return subprocess.run(args, **hidden_kwargs(kwargs))


def Popen(args, **kwargs):
    """subprocess.Popen for a command-line helper, hidden on Windows."""
    return subprocess.Popen(args, **hidden_kwargs(kwargs))


def install_frozen_policy() -> None:
    """Hide redirected children launched inside third-party libraries.

    openai-whisper invokes ffmpeg itself, outside our wrappers.  In the
    windowed frozen build, wrap Popen once and hide only processes whose I/O is
    redirected.  Explorer, the browser, the updater and the relaunched Studio
    have no redirected streams and therefore retain their normal GUI windows.
    """
    if (os.name != "nt" or not getattr(sys, "frozen", False)
            or os.environ.get("KARAOKE_SHOW_CHILD_CONSOLES") == "1"
            or getattr(subprocess.Popen, "_karaoke_hidden_policy", False)):
        return

    original = subprocess.Popen

    class QuietPopen(original):
        _karaoke_hidden_policy = True

        def __init__(self, args, *popen_args, **kwargs):
            redirected = any(kwargs.get(name) is not None
                             for name in ("stdin", "stdout", "stderr"))
            if redirected:
                kwargs = hidden_kwargs(kwargs)
            super().__init__(args, *popen_args, **kwargs)

    subprocess.Popen = QuietPopen
