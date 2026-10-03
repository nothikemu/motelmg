"""Print preview for invoices, receipts, registration cards and reports, with
printing and PDF/HTML export."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtWidgets import QDialog, QFileDialog, QTextBrowser

from motelmg.core import paths
from motelmg.ui.widgets.dialogs import BaseDialog, show_error

log = logging.getLogger(__name__)


def _page_size(ctx) -> QPageSize:
    return QPageSize(QPageSize.PageSizeId.A4 if ctx.settings.get_str("invoice.paper_size") == "A4"
                     else QPageSize.PageSizeId.Letter)


def make_document(html: str) -> QTextDocument:
    doc = QTextDocument()
    doc.setHtml(html)
    return doc


def export_pdf(ctx, html: str, path: str | Path) -> Path:
    from PySide6.QtGui import QPdfWriter
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setPageSize(_page_size(ctx))
    writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Unit.Millimeter)
    writer.setTitle(path.stem)
    writer.setCreator("MotelMG")
    make_document(html).print_(writer)
    return path


def print_html(parent, ctx, html: str) -> bool:
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except ImportError as exc:  # pragma: no cover - printing support missing
        show_error(parent, exc)
        return False
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageSize(_page_size(ctx))
    printer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Unit.Millimeter)
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("Print")
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    make_document(html).print_(printer)
    return True


class DocumentPreview(BaseDialog):
    def __init__(self, parent, app, title: str, html: str, filename: str):
        super().__init__(parent, title, "Preview — print it or save a PDF copy for the guest.",
                         icon_name="printer", width=820)
        self.app = app
        self.html = html
        self.filename = filename
        self.banner.hide()
        view = QTextBrowser()
        view.setHtml(html)
        view.setMinimumHeight(520)
        view.setStyleSheet("QTextBrowser { background: #ffffff; color: #111827; border-radius: 8px; padding: 18px; }")
        self.body.addWidget(view, 1)
        self.resize(860, 820)
        self.add_footer_button("Save HTML", self._save_html, "ghost", icon_name="file", left=True)
        self.add_footer_button("Close", self.reject)
        self.add_footer_button("Save PDF", self._save_pdf, icon_name="download")
        self.add_footer_button("Print…", self._print, "primary", icon_name="printer", default=True)

    def _save_pdf(self) -> None:
        default = str(paths.exports_dir() / f"{self.filename}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", default, "PDF files (*.pdf)")
        if not path:
            return
        try:
            export_pdf(self.app.ctx, self.html, path)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.app.toast(f"Saved {Path(path).name}")

    def _save_html(self) -> None:
        default = str(paths.exports_dir() / f"{self.filename}.html")
        path, _ = QFileDialog.getSaveFileName(self, "Save HTML", default, "HTML files (*.html)")
        if path:
            try:
                Path(path).write_text(self.html, encoding="utf-8")
                self.app.toast(f"Saved {Path(path).name}")
            except OSError as exc:
                show_error(self, exc)

    def _print(self) -> None:
        if print_html(self, self.app.ctx, self.html):
            self.app.toast("Sent to printer")
