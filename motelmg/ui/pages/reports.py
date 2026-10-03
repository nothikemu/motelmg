from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QListWidget,
                               QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget)

from motelmg.core import paths
from motelmg.reporting.documents import report_html
from motelmg.reporting.export import report_to_csv
from motelmg.services.reports import ReportResult
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.charts import BarChart, HBarChart, LineChart
from motelmg.ui.widgets.common import Card, EmptyState, LoadingOverlay, button, clear_layout, label
from motelmg.ui.widgets.date_range import DateRangePicker
from motelmg.ui.widgets.dialogs import show_error
from motelmg.ui.widgets.forms import spin
from motelmg.ui.widgets.table import Column, DataTable


class ReportsPage(Page):
    key = "reports"
    title = "Reports"
    icon = "chart"
    permission = "reports.view"
    topics = ()

    def __init__(self, app):
        super().__init__(app)
        self.result: ReportResult | None = None
        self.current = None
        L = self.layout_
        body = QHBoxLayout()
        body.setSpacing(16)
        L.addLayout(body, 1)
        side = Card("Reports", padding=12, spacing=6)
        side.setFixedWidth(250)
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget { border: none; background: transparent; }")
        self.list.currentItemChanged.connect(lambda *_: self._select())
        side.body.addWidget(self.list)
        body.addWidget(side)
        main = QVBoxLayout()
        main.setSpacing(14)
        body.addLayout(main, 1)
        head = Card(padding=16, spacing=10)
        title_row = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.r_title = label("", "h2")
        self.r_desc = label("", "muted", wrap=True)
        titles.addWidget(self.r_title)
        titles.addWidget(self.r_desc)
        title_row.addLayout(titles, 1)
        self.btn_csv = button("CSV", "download", on_click=self._csv, tooltip="Export to a spreadsheet")
        self.btn_pdf = button("PDF", "file", on_click=self._pdf)
        self.btn_print = button("Print", "printer", on_click=self._print, tooltip="Print (Ctrl+P)")
        for b in (self.btn_csv, self.btn_pdf, self.btn_print):
            title_row.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        head.body.addLayout(title_row)
        params = QHBoxLayout()
        params.setSpacing(10)
        self.param_stack = QStackedWidget()
        self.range = DateRangePicker(self.ctx.clock.today(), "30d")
        self.year = spin(self.ctx.clock.today().year, 2000, 2100)
        self.year.setFixedWidth(110)
        none = label("Shows the current state; no dates needed.", "faint")
        year_host = QWidget()
        year_host.setObjectName("Transparent")
        yl = QHBoxLayout(year_host)
        yl.setContentsMargins(0, 0, 0, 0)
        yl.addWidget(label("Year", "label"))
        yl.addWidget(self.year)
        yl.addStretch(1)
        for w in (self.range, year_host, none):
            self.param_stack.addWidget(w)
        params.addWidget(self.param_stack, 1)
        params.addWidget(button("Run report", "play", "primary", on_click=self.run))
        head.body.addLayout(params)
        main.addWidget(head)
        self.result_host = QWidget()
        self.result_host.setObjectName("Transparent")
        self.result_layout = QVBoxLayout(self.result_host)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(14)
        main.addWidget(self.result_host, 1)
        self.overlay = LoadingOverlay(self.result_host)
        self.range.changed.connect(lambda *_: self.run())
        self.year.valueChanged.connect(lambda *_: self.run())
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._print)
        self._populate()

    def subtitle(self) -> str:
        return "Revenue, occupancy and operational analytics"

    def _populate(self) -> None:
        self.list.clear()
        group = None
        first = None
        for report in self.ctx.reports.available():
            if report.group != group:
                group = report.group
                header = QListWidgetItem(group.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                font = header.font()
                font.setPointSizeF(8)
                font.setBold(True)
                header.setFont(font)
                self.list.addItem(header)
            item = QListWidgetItem(report.title)
            item.setData(Qt.ItemDataRole.UserRole, report.key)
            item.setToolTip(report.description)
            self.list.addItem(item)
            first = first or item
        if first:
            self.list.setCurrentItem(first)

    def _select(self) -> None:
        item = self.list.currentItem()
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not key:
            return
        self.current = next(r for r in self.ctx.reports.available() if r.key == key)
        self.r_title.setText(self.current.title)
        self.r_desc.setText(self.current.description)
        self.param_stack.setCurrentIndex({"range": 0, "year": 1, "none": 2}[self.current.params])
        self.run()

    def refresh(self) -> None:
        if self.current:
            self.run()

    def _clear(self) -> None:
        clear_layout(self.result_layout)

    def _compact_money(self, cents: float) -> str:
        symbol = self.ctx.settings.currency().symbol.strip()
        units = cents / 100
        if units >= 1_000_000:
            return f"{symbol}{units / 1_000_000:.1f}M"
        if units >= 1000:
            return f"{symbol}{units / 1000:.1f}k".replace(".0k", "k")
        return f"{symbol}{units:.0f}"

    def run(self) -> None:
        if not self.current:
            return
        params = {}
        if self.current.params == "range":
            start, end = self.range.value()
            params = {"start": start, "end": end}
        elif self.current.params == "year":
            params = {"year": self.year.value()}
        self.overlay.start("Running report…")
        QApplication.processEvents()
        try:
            self.result = self.ctx.reports.run(self.current.key, **params)
        except Exception as exc:  # noqa: BLE001
            self.overlay.stop()
            show_error(self, exc, "Report failed")
            return
        self.overlay.stop()
        self._render(self.result)

    def _render(self, r: ReportResult) -> None:
        self._clear()
        fmt = self.fmt
        if r.summary:
            row = QGridLayout()
            row.setSpacing(14)
            for i, (k, v) in enumerate(r.summary[:6]):
                tile = QFrame()
                tile.setProperty("card", True)
                tl = QVBoxLayout(tile)
                tl.setContentsMargins(16, 12, 16, 12)
                tl.setSpacing(2)
                tl.addWidget(label(k.upper(), "overline"))
                tl.addWidget(label(v, "kpi_small"))
                row.addWidget(tile, 0, i)
            self.result_layout.addLayout(row)
        if r.chart and r.chart.get("labels"):
            kind = r.chart.get("kind")
            vf = (lambda v: fmt.money(int(v))) if kind == "money" else \
                (lambda v: f"{v:.0f}%") if kind == "percent" else (lambda v: f"{v:,.0f}")
            ctype = r.chart["type"]
            chart = LineChart(vf, max_value=100 if kind == "percent" else None, min_height=230) if ctype == "line" \
                else HBarChart(vf, min_height=max(160, 30 * len(r.chart["labels"]) + 10)) if ctype == "hbar" \
                else BarChart(vf, min_height=230)
            if kind == "money":
                chart.axis_fmt = self._compact_money
            chart.set_data(r.chart["labels"], r.chart["series"], stacked=ctype == "bar" and len(r.chart["series"]) > 1
                           and r.chart.get("kind") == "money")
            card = Card(padding=14)
            card.body.addWidget(chart)
            self.result_layout.addWidget(card)
        columns = [Column(c.key, c.title, "money" if c.kind == "money" else c.kind if c.kind in
                          ("int", "percent", "date", "datetime") else "text",
                          width=max(70, min(220, len(c.title) * 9 + 30)),
                          fmt=(lambda row, k=c.key: f"{row[k]:.1f}" if isinstance(row.get(k), float) else
                               str(row.get(k, "") or "")) if c.kind == "float" else None)
                   for c in r.columns]
        if columns:
            text_cols = [i for i, c in enumerate(r.columns) if c.kind == "text" and c.title]
            columns[text_cols[-1] if text_cols else len(columns) - 1].stretch = True
        table = DataTable(columns, fmt, empty_icon="chart", empty_title="No data for this period", row_height=34)
        rows = [dict(row, id=i) for i, row in enumerate(r.rows)]
        if r.totals:
            rows.append(dict(r.totals, id=-1, _total=True))
        table.set_rows(rows)
        table.fit_columns()
        table.view.setSortingEnabled(not r.totals)
        if any("_id" in row for row in r.rows):
            table.activated.connect(lambda row: self.actions.open_reservation(row["_id"])
                                    if row.get("_id") and "reservation" in row else None)
        table.setMinimumHeight(260)
        self.result_layout.addWidget(table, 1)
        self.result_layout.addWidget(label(f"{r.subtitle} · {len(r.rows)} row(s)", "faint"))

    # -- export --------------------------------------------------------------------------------------------
    def _filename(self) -> str:
        r = self.result
        return f"{r.title.replace(' ', '-').replace('&', 'and')}-{self.ctx.clock.today().isoformat()}" if r else "report"

    def _csv(self) -> None:
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", str(paths.exports_dir() / f"{self._filename()}.csv"),
                                              "CSV files (*.csv)")
        if path:
            try:
                report_to_csv(self.result, path, self.ctx.settings.currency())
                self.app.toast(f"Exported {Path(path).name}")
            except OSError as exc:
                show_error(self, exc)

    def _html(self) -> str:
        return report_html(self.ctx, self.result, self.fmt.value)

    def _pdf(self) -> None:
        if not self.result:
            return
        from motelmg.ui.dialogs.documents import export_pdf
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", str(paths.exports_dir() / f"{self._filename()}.pdf"),
                                              "PDF files (*.pdf)")
        if path:
            try:
                export_pdf(self.ctx, self._html(), path)
                self.app.toast(f"Saved {Path(path).name}")
            except Exception as exc:  # noqa: BLE001
                show_error(self, exc)

    def _print(self) -> None:
        if not self.result:
            return
        from motelmg.ui.dialogs.documents import DocumentPreview
        DocumentPreview(self, self.app, self.result.title, self._html(), self._filename()).exec()


__all__ = ["ReportsPage", "EmptyState"]
