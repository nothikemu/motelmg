from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QFrame, QScrollArea, QVBoxLayout, QWidget

from motelmg.core import paths
from motelmg.reporting.export import write_csv
from motelmg.ui.widgets.dialogs import show_error

log = logging.getLogger(__name__)


class Page(QWidget):
    """Base class: lazy refresh when data changes, consistent margins."""

    key = ""
    title = ""
    icon = "grid"
    permission = ""
    topics: tuple[str, ...] = ()
    scrollable = False

    def __init__(self, app):
        super().__init__()
        self.setObjectName("Page")
        self.app = app
        self.ctx = app.ctx
        self.fmt = app.fmt
        self.actions = app.actions
        self._stale = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QWidget()
        content.setObjectName("PageBody")
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(24, 20, 24, 24)
        self.layout_.setSpacing(16)
        if self.scrollable:
            scroll = QScrollArea()
            scroll.setObjectName("PageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(content)
            outer.addWidget(scroll)
        else:
            outer.addWidget(content)

    @classmethod
    def allowed(cls, ctx) -> bool:
        return not cls.permission or ctx.can(cls.permission)

    def subtitle(self) -> str:
        return ""

    def refresh(self) -> None:  # pragma: no cover - overridden
        pass

    def safe_refresh(self) -> None:
        try:
            self.refresh()
            self._stale = False
        except Exception as exc:  # noqa: BLE001 - keep the app usable
            log.exception("Refreshing %s failed", self.key)
            show_error(self, exc, "Could not load this view")

    def mark_stale(self) -> None:
        self._stale = True
        if self.isVisible():
            self.safe_refresh()

    def on_show(self, **kwargs) -> None:
        if self._stale:
            self.safe_refresh()

    def export_table(self, table, default_name: str) -> None:
        headers, rows = table.export_rows()
        if not rows:
            self.app.toast("Nothing to export", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to CSV", str(paths.exports_dir() / f"{default_name}.csv"),
                                              "CSV files (*.csv)")
        if not path:
            return
        try:
            write_csv(path, headers, rows)
        except OSError as exc:
            show_error(self, exc)
            return
        self.app.toast(f"Exported {len(rows)} rows to {Path(path).name}")
