from __future__ import annotations

import re
from typing import Any

from motelmg.data.database import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db


def like(text: str) -> str:
    """Escape a user search string for a ``LIKE ? ESCAPE '\\'`` clause."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value or "")]


def in_clause(values: list | tuple | set) -> tuple[str, list]:
    items = list(values)
    if not items:
        return "(NULL)", []
    return "(" + ", ".join("?" for _ in items) + ")", items
