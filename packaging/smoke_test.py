"""Run the packaged application's built-in --self-test (used by CI after building)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "dist"


def executable() -> Path:
    if sys.platform.startswith("win"):
        return DIST / "MotelMG" / "MotelMG.exe"
    if sys.platform == "darwin":
        return DIST / "MotelMG.app" / "Contents" / "MacOS" / "MotelMG"
    return DIST / "MotelMG" / "MotelMG"


def main() -> int:
    exe = executable()
    if not exe.exists():
        print(f"Packaged executable not found: {exe}")
        return 1
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([str(exe), "--self-test"], env=env, timeout=600)
    print(f"Self-test exit code: {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
