"""Сколько памяти доступно — чтобы предупредить заранее, а не падать на середине.

Demucs и Whisper — прожорливые. На машине с малым файлом подкачки они валятся
с системными кодами вроде WinError 1455, по которым непонятно, что делать.
"""

from __future__ import annotations

import os
import re
import sys
from .i18n import tr
from typing import Optional, Tuple

# Грубые оценки пиковой потребности, гигабайты
NEED_DEMUCS = 4.0
NEED_WHISPER = {"tiny": 1.0, "base": 1.3, "small": 2.2, "medium": 4.5, "large-v3": 8.0}


def available_gb() -> Optional[float]:
    """Сколько памяти реально можно занять прямо сейчас. None — если не выяснить."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None
            # Считаем по файлу подкачки: именно его нехватка даёт WinError 1455
            return st.ullAvailPageFile / (1024 ** 3)
        except Exception:
            return None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            info = f.read()
        m = re.search(r"MemAvailable:\s+(\d+) kB", info)
        if m:
            return int(m.group(1)) / (1024 ** 2)
    except Exception:
        pass
    return None


def is_memory_error(exc: BaseException) -> bool:
    """Похоже ли исключение на нехватку памяти — под разными обличьями."""
    if isinstance(exc, MemoryError):
        return True
    text = str(exc).lower()
    return (getattr(exc, "winerror", None) == 1455
            or "1455" in text and "подкачки" in text
            or "not enough memory" in text
            or "cannot allocate memory" in text
            or "defaultcpuallocator" in text
            or "файл подкачки" in text)


def memory_advice(need_gb: float, free_gb: Optional[float]) -> str:
    """Что делать пользователю. Без системных кодов и без воды."""
    have = (tr(f"About {free_gb:.1f} GB is free", f"Свободно около {free_gb:.1f} ГБ")
            if free_gb else tr("There was not enough memory", "Памяти не хватило"))
    # Первый совет — самый действенный, но он у Windows и Linux разный,
    # а показывать «Параметры → Система» на сервере просто некуда идти.
    if sys.platform.startswith("win"):
        first = tr(
            "  1. Grow the Windows page file: Settings → System → About → "
            "Advanced system settings → Performance →\n"
            "     Settings → Advanced → Virtual memory → Change.\n"
            "     Choose “System managed size”, or 16384 MB by hand.\n",
            "  1. Увеличить файл подкачки Windows: Параметры → Система → "
            "О системе → Дополнительные параметры системы → Быстродействие →\n"
            "     Параметры → Дополнительно → Виртуальная память → Изменить.\n"
            "     Поставьте «Размер по выбору системы» или вручную 16384 МБ.\n")
    else:
        first = (tr("  1. Add a swap file (root rights needed):\n",
                    "  1. Добавить файл подкачки (нужны права root):\n")
                 + "     sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile\n"
                 "     sudo mkswap /swapfile && sudo swapon /swapfile\n"
                 + tr("     To survive a reboot:\n",
                      "     Чтобы пережил перезагрузку:\n")
                 + "     echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab\n")
    return (
        tr(f"Not enough memory. {have}, and about {need_gb:.0f} GB is needed.\n"
           "What helps, most effective first:\n",
           f"Не хватило памяти. {have}, а нужно примерно {need_gb:.0f} ГБ.\n"
           "Что помогает, по убыванию действенности:\n")
        + first
        + tr("  2. Close the browser and other heavy programs.\n"
             "  3. Turn the instrumental off — it is the hungriest step.\n"
             "  4. Take a smaller model: small → base → tiny.",
             "  2. Закрыть браузер и другие тяжёлые программы.\n"
             "  3. Отключить минусовку — она самая прожорливая.\n"
             "  4. Взять модель поменьше: small → base → tiny.")
    )


def check(need_gb: float) -> Tuple[bool, str]:
    """(хватит ли, пояснение). Не запрещаем, а предупреждаем: оценка приблизительная."""
    free = available_gb()
    if free is None:
        return True, ""
    if free >= need_gb:
        return True, ""
    return False, tr(
        f"About {free:.1f} GB of memory is free, and this step usually needs "
        f"~{need_gb:.0f} GB. It may not be enough.",
        f"Свободной памяти около {free:.1f} ГБ, а для этого шага обычно "
        f"нужно ~{need_gb:.0f} ГБ. Может не хватить.")
