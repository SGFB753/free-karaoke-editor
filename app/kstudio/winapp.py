"""Windows taskbar identity for a Studio hosted by python.exe/WebView2."""

from __future__ import annotations

import ctypes
import os
import sys
import time
import uuid
from ctypes import wintypes


def app_id() -> str:
    """Return a process-specific taskbar identity.

    Frozen (production) and source (dev) builds must never share an ID:
    Windows groups taskbar pins by AppUserModelId, so sharing one would
    let a pinned Studio.bat overwrite a frozen EXE's relaunch command.
    """
    return (
        "KaraokeStudio.Desktop.App"
        if getattr(sys, "frozen", False)
        else "KaraokeStudio.Desktop.Dev"
    )


_APP_FMTID = "9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3"
_IID_PROPERTY_STORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
_VT_LPWSTR = 31


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT),
                ("wReserved1", wintypes.USHORT),
                ("wReserved2", wintypes.USHORT),
                ("wReserved3", wintypes.USHORT),
                ("value", ctypes.c_wchar_p)]


def _guid(value: str) -> _GUID:
    raw = uuid.UUID(value)
    return _GUID(raw.time_low, raw.time_mid, raw.time_hi_version,
                 (ctypes.c_ubyte * 8).from_buffer_copy(raw.bytes[8:]))


def set_process_identity() -> bool:
    """Separate Studio.bat from the python.exe group before any UI exists."""
    if os.name != "nt":
        return False
    try:
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = (ctypes.c_wchar_p,)
        set_id.restype = ctypes.c_long
        return set_id(app_id()) == 0
    except Exception:
        return False


def relaunch_details(root: str) -> tuple[str, str, str]:
    """Command, display name and icon Windows should pin for this window."""
    if getattr(sys, "frozen", False):
        target = os.path.abspath(sys.executable)
        command = f'"{target}"'
        icon = target + ",0"
    else:
        target = os.path.abspath(os.path.join(os.path.dirname(root), "Studio.bat"))
        command = f'"{target}"'
        icon = os.path.abspath(os.path.join(root, "kstudio", "favicon.ico")) + ",0"
    return command, "Karaoke Studio", icon


def _window_handle(window, timeout: float = 5.0) -> int:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None) if native is not None else None
        if handle is not None:
            try:
                return int(handle.ToInt64())
            except Exception:
                try:
                    return int(handle)
                except Exception:
                    pass
        time.sleep(0.05)
    return 0


def set_window_identity(window, root: str) -> bool:
    """Tell taskbar pinning how to relaunch the Studio, not python.exe."""
    if os.name != "nt":
        return False
    hwnd = _window_handle(window)
    if not hwnd:
        return False

    ole = ctypes.windll.ole32
    ole.CoInitialize.argtypes = (ctypes.c_void_p,)
    ole.CoInitialize.restype = ctypes.c_long
    initialized = ole.CoInitialize(None) in (0, 1)  # S_OK or S_FALSE
    store = ctypes.c_void_p()
    shell = ctypes.windll.shell32
    get_store = shell.SHGetPropertyStoreForWindow
    get_store.argtypes = (wintypes.HWND, ctypes.POINTER(_GUID),
                          ctypes.POINTER(ctypes.c_void_p))
    get_store.restype = ctypes.c_long
    iid = _guid(_IID_PROPERTY_STORE)
    if get_store(hwnd, ctypes.byref(iid), ctypes.byref(store)) != 0 or not store:
        if initialized:
            ole.CoUninitialize()
        return False

    # IPropertyStore: IUnknown (0..2), GetCount/GetAt/GetValue (3..5),
    # SetValue (6), Commit (7).
    table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                  ctypes.POINTER(_PROPERTYKEY),
                                  ctypes.POINTER(_PROPVARIANT))(table[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(table[7])
    fmtid = _guid(_APP_FMTID)
    command, display, icon = relaunch_details(root)
    values = ((5, app_id()), (2, command), (4, display), (3, icon))
    try:
        for pid, text in values:
            key = _PROPERTYKEY(fmtid, pid)
            value = _PROPVARIANT(_VT_LPWSTR, 0, 0, 0, text)
            if set_value(store, ctypes.byref(key), ctypes.byref(value)) != 0:
                return False
        return commit(store) == 0
    finally:
        release(store)
        if initialized:
            ole.CoUninitialize()
