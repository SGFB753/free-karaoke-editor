# -*- mode: python ; coding: utf-8 -*-
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
a = Analysis([os.path.join(ROOT, "app", "updater.py")], pathex=[],
             binaries=[], datas=[], hiddenimports=[], hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="KaraokeUpdater", debug=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=True,
          icon=os.path.join(ROOT, "app", "packaging", "KaraokeStudio.ico"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               upx_exclude=[], name="KaraokeUpdater")
