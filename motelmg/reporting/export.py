"""CSV export of tabular data (reports, lists)."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from motelmg.core.money import CurrencyFormat
from motelmg.services.reports import ReportResult


def plain_value(value: Any, kind: str, currency: CurrencyFormat) -> str:
    """Spreadsheet-friendly representation (no currency symbols, ISO dates)."""
    if value is None or value == "":
        return ""
    if kind == "money" and isinstance(value, int):
        return currency.plain(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def write_csv(path: Path | str, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> Path:
    path = Path(path)
    # utf-8-sig so Excel detects the encoding correctly
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
    return path


def report_to_csv(report: ReportResult, path: Path | str, currency: CurrencyFormat) -> Path:
    headers = [c.title or c.key for c in report.columns]
    rows = [[plain_value(r.get(c.key), c.kind, currency) for c in report.columns] for r in report.rows]
    if report.totals:
        rows.append([plain_value(report.totals.get(c.key), c.kind, currency) for c in report.columns])
    return write_csv(path, headers, rows)
