"""Unobtrusive toast notifications in the bottom-right corner of the window."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from motelmg.ui.widgets.common import set_icon

TONE_ICONS = {"success": ("check-circle", "#4ade80"), "error": ("alert-circle", "#f87171"),
              "warning": ("alert", "#fbbf24"), "info": ("info", "#7fb0ff")}


class Toast(QFrame):
    def __init__(self, parent: QWidget, message: str, tone: str):
        super().__init__(parent)
        self.setObjectName("Toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 16, 11)
        layout.setSpacing(10)
        ic = QLabel()
        name, color = TONE_ICONS.get(tone, TONE_ICONS["info"])
        set_icon(ic, name, color, 17)
        text = QLabel(message)
        text.setWordWrap(True)
        text.setMaximumWidth(360)
        # Word-wrapped labels otherwise pick a narrow width and break short messages over several lines.
        text.setMinimumWidth(min(text.fontMetrics().horizontalAdvance(message) + 4, 360))
        layout.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(text, 1)
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)
        self.adjustSize()


class ToastManager(QObject):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.toasts: list[Toast] = []
        self.enabled = True
        host.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.host and event.type() == QEvent.Type.Resize:
            self._layout()
        return False

    def show(self, message: str, tone: str = "success", duration: int = 3800) -> None:
        if not self.enabled and tone in ("info",):
            return
        toast = Toast(self.host, message, tone)
        self.toasts.append(toast)
        toast.show()
        toast.raise_()
        self._layout()
        anim = QPropertyAnimation(toast.effect, b"opacity", toast)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        # Bound to the toast so the timer dies with it (e.g. the window closed on sign-out).
        QTimer.singleShot(duration, toast, lambda: self._dismiss(toast))

    def _dismiss(self, toast: Toast) -> None:
        if toast not in self.toasts:
            return
        anim = QPropertyAnimation(toast.effect, b"opacity", toast)
        anim.setDuration(250)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)

        def done() -> None:
            if toast in self.toasts:
                self.toasts.remove(toast)
            toast.deleteLater()
            self._layout()

        anim.finished.connect(done)
        anim.start()

    def _layout(self) -> None:
        margin = 20
        y = self.host.height() - margin
        for toast in reversed(self.toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self.host.width() - toast.width() - margin, y)
            y -= 10
