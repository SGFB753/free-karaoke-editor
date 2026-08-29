# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
a = Analysis([os.path.join(ROOT, "app", "updater.py")], pathex=[],
             binaries=[], datas=[], hiddenimports=[], hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name="KaraokeUpdater", debug=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=True)
