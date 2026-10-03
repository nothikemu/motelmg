"""Locations of the application's data, logs and backups.

The data directory is resolved in this order:

1. ``--data-dir`` command line option (set via :func:`set_data_dir_override`)
2. ``MOTELMG_DATA_DIR`` environment variable (useful for testing)
3. A ``data`` folder next to the executable when a ``portable.txt`` marker
   file exists there (portable installs on a USB drive)
4. The per-user application data folder of the operating system
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from motelmg import APP_NAME

_override: Path | None = None


def set_data_dir_override(path: str | os.PathLike | None) -> None:
    global _override
    _override = Path(path).expanduser().resolve() if path else None


def _platform_data_root() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Local" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def executable_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    if _override is not None:
        path = _override
    elif os.environ.get("MOTELMG_DATA_DIR"):
        path = Path(os.environ["MOTELMG_DATA_DIR"]).expanduser()
    elif (executable_dir() / "portable.txt").exists():
        path = executable_dir() / "data"
    else:
        path = _platform_data_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "motelmg.db"


def default_backup_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    path = Path.home() / "Documents"
    if not path.exists():
        path = Path.home()
    return path


def resource_path(*parts: str) -> Path:
    """Path to a bundled resource, working both from source and PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1].parent))
    candidate = base / "motelmg" / "resources" / Path(*parts)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parents[1] / "resources" / Path(*parts)
