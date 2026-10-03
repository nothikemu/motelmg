"""Build a distributable package for the current operating system.

    python packaging/build.py

Windows : dist/MotelMG-Setup-<version>.exe   (Inno Setup installer; falls back to a .zip)
macOS   : dist/MotelMG-<version>-macos-<arch>.dmg (drag-to-Applications disk image)
Linux   : dist/MotelMG-<version>-x86_64.AppImage (falls back to a .tar.gz)

The result is self-contained: end users need no Python, no database server
and no configuration.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
sys.path.insert(0, str(ROOT))

from motelmg import __version__  # noqa: E402

APPIMAGETOOL_URL = ("https://github.com/AppImage/appimagetool/releases/download/continuous/"
                    "appimagetool-x86_64.AppImage")


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def icons() -> None:
    icon_dir = ROOT / "motelmg" / "resources" / "icons"
    if not (icon_dir / "app.ico").exists() or not (icon_dir / "app.png").exists():
        run([sys.executable, str(ROOT / "packaging" / "make_icons.py")])


def pyinstaller() -> Path:
    shutil.rmtree(DIST / "MotelMG", ignore_errors=True)
    shutil.rmtree(DIST / "MotelMG.app", ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(BUILD), str(ROOT / "packaging" / "motelmg.spec")])
    return DIST / "MotelMG"


def windows_installer(app_dir: Path) -> Path:
    iscc = shutil.which("iscc") or next((str(p) for p in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe") if p.exists()), None)
    if iscc:
        run([iscc, f"/DAppVersion={__version__}", str(ROOT / "packaging" / "windows" / "motelmg.iss")])
        return DIST / f"MotelMG-Setup-{__version__}.exe"
    print("Inno Setup not found - creating a portable .zip instead")
    (app_dir / "portable.txt").write_text("Delete this file to store data in %LOCALAPPDATA%\\MotelMG instead.\n")
    archive = shutil.make_archive(str(DIST / f"MotelMG-{__version__}-windows-portable"), "zip", DIST, "MotelMG")
    return Path(archive)


def macos_dmg() -> Path:
    app = DIST / "MotelMG.app"
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / "MotelMG.app", symlinks=True)
    os.symlink("/Applications", staging / "Applications")
    target = DIST / f"MotelMG-{__version__}-macos-{platform.machine()}.dmg"
    target.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", "MotelMG", "-srcfolder", str(staging), "-ov", "-format", "UDZO",
         str(target)])
    return target


def linux_package(app_dir: Path) -> Path:
    appdir = BUILD / "MotelMG.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    (appdir / "usr" / "lib").mkdir(parents=True)
    shutil.copytree(app_dir, appdir / "usr" / "lib" / "MotelMG", symlinks=True)
    shutil.copy2(ROOT / "packaging" / "linux" / "AppRun", appdir / "AppRun")
    os.chmod(appdir / "AppRun", 0o755)
    shutil.copy2(ROOT / "packaging" / "linux" / "motelmg.desktop", appdir / "motelmg.desktop")
    shutil.copy2(ROOT / "motelmg" / "resources" / "icons" / "app-256.png", appdir / "motelmg.png")
    tool = shutil.which("appimagetool")
    if not tool:
        candidate = BUILD / "appimagetool-x86_64.AppImage"
        if not candidate.exists() and platform.machine() in ("x86_64", "AMD64"):
            try:
                print(f"Downloading appimagetool from {APPIMAGETOOL_URL}")
                urllib.request.urlretrieve(APPIMAGETOOL_URL, candidate)
                os.chmod(candidate, 0o755)
            except OSError as exc:
                print(f"Could not download appimagetool: {exc}")
        tool = str(candidate) if candidate.exists() else None
    if tool:
        target = DIST / f"MotelMG-{__version__}-x86_64.AppImage"
        env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
        try:
            run([tool, "--no-appstream", str(appdir), str(target)], env=env)
            return target
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"appimagetool failed ({exc}); falling back to a tar.gz")
    target = DIST / f"MotelMG-{__version__}-linux-x86_64.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        tar.add(app_dir, arcname="MotelMG")
        tar.add(ROOT / "packaging" / "linux" / "motelmg.desktop", arcname="MotelMG/motelmg.desktop")
    return target


def main() -> int:
    DIST.mkdir(exist_ok=True)
    icons()
    app_dir = pyinstaller()
    if sys.platform.startswith("win"):
        artifact = windows_installer(app_dir)
    elif sys.platform == "darwin":
        artifact = macos_dmg()
    else:
        artifact = linux_package(app_dir)
    print(f"\nBuilt {artifact} ({artifact.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
