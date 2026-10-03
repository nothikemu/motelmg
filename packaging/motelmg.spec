# PyInstaller specification for MotelMG.
# Build with:  python packaging/build.py   (or: pyinstaller --noconfirm packaging/motelmg.spec)
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is provided by PyInstaller
sys.path.insert(0, str(ROOT))
from motelmg import __version__  # noqa: E402

ICONS = ROOT / "motelmg" / "resources" / "icons"
icon = str(ICONS / ("app.ico" if sys.platform.startswith("win") else "app.icns" if sys.platform == "darwin"
                    else "app.png"))

a = Analysis(  # noqa: F821
    [str(ROOT / "motelmg" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "motelmg" / "resources"), "motelmg/resources")],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtPrintSupport"],
    excludes=["tkinter", "unittest", "pydoc", "pytest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork",
              "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDBus", "PySide6.QtOpenGLWidgets", "PySide6.QtHelp",
              "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtConcurrent"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MotelMG",
    console=False,
    icon=icon,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MotelMG")  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="MotelMG.app",
        icon=icon,
        bundle_identifier="app.motelmg.desktop",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "MotelMG",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.business",
        },
    )
