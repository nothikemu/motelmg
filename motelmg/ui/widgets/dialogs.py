"""Dialog framework: consistent header/body/footer layout, inline error
handling for service errors, and helper dialogs (confirm, ask, error)."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from motelmg.core.errors import MotelError, ValidationError
from motelmg.ui.widgets.common import Banner, IconTile, button, label
from motelmg.ui.widgets.forms import FormGrid

log = logging.getLogger(__name__)


class BaseDialog(QDialog):
    """Dialog with a title header, scrollable body and a button footer."""

    def __init__(self, parent: QWidget | None, title: str, subtitle: str = "", *, icon_name: str | None = None,
                 tone: str = "blue", width: int = 560, scroll: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("DialogHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(12)
        if icon_name:
            hl.addWidget(IconTile(icon_name, tone, 36), 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogTitle")
        titles.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("DialogSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        titles.addWidget(self.subtitle_label)
        hl.addLayout(titles, 1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(6)
        hl.addLayout(self.header_actions)
        outer.addWidget(header)

        body_host = QWidget()
        body_host.setObjectName("DialogBody")
        self.body = QVBoxLayout(body_host)
        self.body.setContentsMargins(22, 18, 22, 18)
        self.body.setSpacing(14)
        self.banner = Banner("", "error", closable=True)
        self.body.addWidget(self.banner)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(body_host)
            wrapper = QWidget()
            wrapper.setObjectName("DialogBody")
            wl = QVBoxLayout(wrapper)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.addWidget(area)
            outer.addWidget(wrapper, 1)
        else:
            outer.addWidget(body_host, 1)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        self.footer = QHBoxLayout(footer)
        self.footer.setContentsMargins(22, 12, 22, 12)
        self.footer.setSpacing(8)
        self.footer_left = QHBoxLayout()
        self.footer_left.setSpacing(8)
        self.footer.addLayout(self.footer_left)
        self.footer.addStretch(1)
        outer.addWidget(footer)
        self.forms: list[FormGrid] = []
        self._scroll = scroll
        self._stretched = False

    def showEvent(self, event) -> None:  # noqa: N802
        if self._scroll and not self._stretched:
            self.body.addStretch(1)  # keep cards at their natural height inside the scroll area
            self._stretched = True
        super().showEvent(event)

    def add_footer_button(self, text: str, callback: Callable | None = None, variant: str | None = None, *,
                          icon_name: str | None = None, default: bool = False, left: bool = False) -> QPushButton:
        btn = button(text, icon_name, variant)
        if callback:
            btn.clicked.connect(lambda *_: callback())
        if default:
            btn.setDefault(True)
            btn.setAutoDefault(True)
        else:
            btn.setAutoDefault(False)
        (self.footer_left if left else self.footer).addWidget(btn)
        return btn

    def add_cancel(self, text: str = "Cancel") -> QPushButton:
        return self.add_footer_button(text, self.reject)

    def register_form(self, form: FormGrid) -> FormGrid:
        self.forms.append(form)
        return form

    def clear_errors(self) -> None:
        self.banner.hide()
        for form in self.forms:
            form.clear_errors()

    def show_error(self, exc: Exception) -> None:
        if isinstance(exc, ValidationError):
            matched = False
            for form in self.forms:
                matched = form.set_errors(exc.field_errors) or matched
            unmatched = [m for k, m in exc.field_errors.items()
                         if not any(k in f.fields for f in self.forms)]
            if unmatched or not matched:
                self.banner.set(unmatched[0] if unmatched else exc.message, "error")
            else:
                self.banner.set("Please correct the highlighted fields.", "error")
        elif isinstance(exc, MotelError):
            self.banner.set(exc.message, "error")
        else:
            log.exception("Unexpected error in dialog", exc_info=exc)
            self.banner.set(f"Something went wrong: {exc}. The details were written to the log file.", "error")

    def attempt(self, fn: Callable[[], Any], *, accept: bool = True) -> Any:
        """Run a service call, showing errors inline; closes the dialog on success."""
        self.clear_errors()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            QApplication.restoreOverrideCursor()
            self.show_error(exc)
            return None
        QApplication.restoreOverrideCursor()
        if accept:
            self.result_value = result
            self.accept()
        return result if result is not None else True


class MessageDialog(BaseDialog):
    def __init__(self, parent, title: str, text: str, *, icon_name: str = "info", tone: str = "blue",
                 confirm_text: str | None = None, cancel_text: str | None = "Cancel", danger: bool = False,
                 details: str | None = None, width: int = 460):
        super().__init__(parent, title, icon_name=icon_name, tone=tone, width=width)
        self.banner.hide()
        body = label(text, wrap=True)
        body.setTextFormat(Qt.TextFormat.RichText if "<" in text else Qt.TextFormat.PlainText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(body)
        if details:
            box = QPlainTextEdit(details)
            box.setReadOnly(True)
            box.setFixedHeight(130)
            box.setVisible(False)
            toggle = button("Show details", variant="link")
            toggle.clicked.connect(lambda: (box.setVisible(not box.isVisible()),
                                            toggle.setText("Hide details" if box.isVisible() else "Show details")))
            copy = button("Copy details", variant="link")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(details))
            self.body.addLayout(_row(toggle, copy))
            self.body.addWidget(box)
        if cancel_text:
            self.add_footer_button(cancel_text, self.reject)
        if confirm_text:
            self.add_footer_button(confirm_text, self.accept, "danger" if danger else "primary", default=True)


def _row(*widgets) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(12)
    for w in widgets:
        layout.addWidget(w)
    layout.addStretch(1)
    return layout


def confirm(parent, title: str, text: str, confirm_text: str = "Confirm", *, danger: bool = False,
            cancel_text: str = "Cancel") -> bool:
    dlg = MessageDialog(parent, title, text, icon_name="alert" if danger else "help",
                        tone="red" if danger else "blue", confirm_text=confirm_text, cancel_text=cancel_text,
                        danger=danger)
    return dlg.exec() == QDialog.DialogCode.Accepted


def inform(parent, title: str, text: str, *, tone: str = "blue", icon_name: str = "info") -> None:
    MessageDialog(parent, title, text, icon_name=icon_name, tone=tone, confirm_text="OK", cancel_text=None).exec()


def show_error(parent, exc: BaseException, title: str | None = None) -> None:
    if isinstance(exc, MotelError):
        MessageDialog(parent, title or exc.title, exc.message, icon_name="alert-circle", tone="red",
                      confirm_text="OK", cancel_text=None, details=exc.details).exec()
    else:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log.error("Unexpected error: %s", details)
        MessageDialog(parent, title or "Unexpected error",
                      "Something went wrong while performing this action. Your data is safe - the action was not "
                      "completed. If this keeps happening, send the details below to your support contact.",
                      icon_name="alert-circle", tone="red", confirm_text="OK", cancel_text=None,
                      details=details).exec()


def guarded(parent, fn: Callable[[], Any], success: str | None = None, toast: Callable | None = None) -> Any:
    """Run ``fn`` showing any error in a dialog. Returns the result or ``None``."""
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        QApplication.restoreOverrideCursor()
        show_error(parent, exc)
        return None
    QApplication.restoreOverrideCursor()
    if success and toast:
        toast(success)
    return result if result is not None else True


class AskTextDialog(BaseDialog):
    def __init__(self, parent, title: str, prompt: str, *, placeholder: str = "", multiline: bool = False,
                 required: bool = True, confirm_text: str = "OK", danger: bool = False, text: str = "",
                 icon_name: str = "edit"):
        super().__init__(parent, title, icon_name=icon_name, tone="red" if danger else "blue", width=440)
        self.required = required
        self.body.addWidget(label(prompt, wrap=True))
        if multiline:
            self.edit = QPlainTextEdit(text)
            self.edit.setFixedHeight(90)
            self.edit.setPlaceholderText(placeholder)
            self.edit.setTabChangesFocus(True)
        else:
            from PySide6.QtWidgets import QLineEdit
            self.edit = QLineEdit(text)
            self.edit.setPlaceholderText(placeholder)
        self.body.addWidget(self.edit)
        self.add_cancel()
        self.add_footer_button(confirm_text, self._ok, "danger" if danger else "primary", default=True)
        self.edit.setFocus()

    def value(self) -> str:
        if isinstance(self.edit, QPlainTextEdit):
            return self.edit.toPlainText().strip()
        return self.edit.text().strip()

    def _ok(self) -> None:
        if self.required and not self.value():
            self.banner.set("This field is required.", "error")
            return
        self.accept()


def ask_text(parent, title: str, prompt: str, **kwargs) -> str | None:
    dlg = AskTextDialog(parent, title, prompt, **kwargs)
    return dlg.value() if dlg.exec() == QDialog.DialogCode.Accepted else None


def add_escape_close(dialog: QDialog) -> None:
    QShortcut(QKeySequence(Qt.Key.Key_Escape), dialog, activated=dialog.reject)
