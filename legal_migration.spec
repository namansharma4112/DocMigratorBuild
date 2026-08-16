# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds dist/LegalDocMigration/LegalDocMigration.exe"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
here = os.path.abspath(os.getcwd())

datas = []
vendor = os.path.join(here, "vendor")
if os.path.isdir(vendor):
    for root, _dirs, files in os.walk(vendor):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(root, here)
            datas.append((full, rel))
    print("[spec] Bundling OCR binaries from ./vendor")
else:
    print("[spec] No vendor/ folder found -> building WITHOUT bundled OCR.")

hiddenimports = []
hiddenimports += collect_submodules("sklearn")
hiddenimports += collect_submodules("pdfplumber")
hiddenimports += ["pytesseract", "pdf2image", "PIL", "dateutil", "openpyxl"]
hiddenimports += collect_submodules("legal_pipeline")
datas += collect_data_files("sklearn")

_version = "version_info.txt" if os.path.exists(os.path.join(here, "version_info.txt")) else None
_icon = None
for _cand in ("app.ico", "app_icon.ico"):
    if os.path.exists(os.path.join(here, _cand)):
        _icon = os.path.join(here, _cand)
        break

a = Analysis(
    ["app_gui.py"],
    pathex=[here],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "notebook", "IPython", "PyQt5", "PySide2"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LegalDocMigration",
    console=False,
    upx=False,
    icon=_icon,
    version=_version,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    upx=False,
    name="LegalDocMigration",
)
