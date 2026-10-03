"""Small reusable building blocks: buttons, cards, badges, empty states..."""

from __future__ import annotations

import hashlib
import weakref
from typing import Any, Callable

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from motelmg.ui.icons import icon, pixmap
from motelmg.ui.theme import theme, theme_manager
from motelmg.ui.widgets.flow import FlowLayout

# -- themed icons ------------------------------------------------------------------------------
_themed: "weakref.WeakKeyDictionary[QWidget, tuple[str, str, int]]" = weakref.WeakKeyDictionary()


def _resolve(color_key: str) -> str:
    c = theme().c
    if color_key.startswith("#"):
        return color_key
    if color_key in c:
        return c[color_key]
    return theme().accent(color_key)


def _apply_icon(widget: QWidget, name: str, color_key: str, size: int) -> None:
    color = _resolve(color_key)
    if isinstance(widget, QAbstractButton):
        widget.setIcon(icon(name, color, size))
        widget.setIconSize(QSize(size, size))
    elif isinstance(widget, QLabel):
        widget.setPixmap(pixmap(name, color, size))
    elif isinstance(widget, QLineEdit):
        pass


def set_icon(widget: QWidget, name: str, color_key: str = "text_muted", size: int = 16) -> None:
    """Set an icon that automatically recolours when the theme changes."""
    _themed[widget] = (name, color_key, size)
    _apply_icon(widget, name, color_key, size)


def _refresh_icons() -> None:
    for widget, (name, color_key, size) in list(_themed.items()):
        try:
            _apply_icon(widget, name, color_key, size)
        except RuntimeError:  # widget deleted on the C++ side
            pass


theme_manager.changed.connect(_refresh_icons)


def clear_layout(layout) -> None:
    """Remove and delete every item of ``layout`` immediately (recursively)."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


ICON_COLORS = {"primary": "on_primary", "danger": "#ffffff", "soft": "primary", "danger-outline": "danger",
               "link": "primary"}


def button(text: str = "", icon_name: str | None = None, variant: str | None = None, *, small: bool = False,
           tooltip: str | None = None, on_click: Callable | None = None, parent: QWidget | None = None) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        btn.setProperty("variant", variant)
    if small:
        btn.setProperty("size", "small")
    if icon_name:
        set_icon(btn, icon_name, ICON_COLORS.get(variant or "", "text"), 15 if small else 16)
    if tooltip:
        btn.setToolTip(tooltip)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    return btn


def icon_button(icon_name: str, tooltip: str, on_click: Callable | None = None, *, size: int = 18,
                color: str = "text_muted") -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("IconButton")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setAutoRaise(True)
    set_icon(btn, icon_name, color, size)
    if on_click:
        btn.clicked.connect(lambda *_: on_click())
    return btn


def label(text: str = "", role: str | None = None, *, wrap: bool = False, selectable: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            layout.addStretch(1)
        if w is None:
            layout.addStretch(1)
        elif isinstance(w, QWidget):
            layout.addWidget(w)
        else:
            layout.addLayout(w)
    if stretch_at is not None and stretch_at >= len(widgets):
        layout.addStretch(1)
    return layout


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            layout.addStretch(1)
        elif isinstance(w, QWidget):
            layout.addWidget(w)
        else:
            layout.addLayout(w)
    return layout


class ElidedLabel(QLabel):
    """Single-line label that shortens itself with "…" instead of forcing its parent wider."""

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(min(super().minimumSizeHint().width(), 40), super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:  # noqa: N802
        text = self.text()
        elided = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.contentsRect().width())
        self.setToolTip(text if elided != text else "")
        painter = QPainter(self)
        self.style().drawItemText(painter, self.contentsRect(), int(self.alignment()), self.palette(),
                                  self.isEnabled(), elided, self.foregroundRole())


class Divider(QFrame):
    def __init__(self, vertical: bool = False):
        super().__init__()
        self.setObjectName("VDivider" if vertical else "Divider")


class Card(QFrame):
    """White rounded panel with optional header (title, subtitle, actions)."""

    def __init__(self, title: str | None = None, subtitle: str | None = None, *, padding: int = 18,
                 spacing: int = 12, icon_name: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(padding, padding - 2, padding, padding)
        outer.setSpacing(spacing)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label: QLabel | None = None
        self.subtitle_label: QLabel | None = None
        if title is not None:
            if icon_name:
                ic = QLabel()
                set_icon(ic, icon_name, "text_muted", 16)
                self.header.addWidget(ic)
            titles = QVBoxLayout()
            titles.setSpacing(0)
            self.title_label = label(title, "cardtitle")
            titles.addWidget(self.title_label)
            if subtitle:
                self.subtitle_label = label(subtitle, "faint")
                titles.addWidget(self.subtitle_label)
            self.header.addLayout(titles)
            self.header.addStretch(1)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(spacing)
        self.body.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self.body)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def set_title(self, text: str) -> None:
        if self.title_label:
            self.title_label.setText(text)


class Badge(QLabel):
    """Rounded status pill."""

    def __init__(self, text: str = "", tone: str = "gray", *, small: bool = False):
        super().__init__(text)
        self._tone = tone
        self._small = small
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._apply()
        theme_manager.changed.connect(self._apply)

    def set(self, text: str, tone: str | None = None) -> None:
        self.setText(text)
        if tone:
            self._tone = tone
        self._apply()
        self.setVisible(bool(text))

    def _apply(self) -> None:
        try:
            fg, bg = theme().tone(self._tone)
            pad = "2px 8px" if self._small else "3px 10px"
            size = "11px" if self._small else "11.5px"
            self.setStyleSheet(f"QLabel {{ color: {fg}; background: {bg}; border-radius: 9px; padding: {pad};"
                               f" font-size: {size}; font-weight: 600; }}")
        except RuntimeError:
            pass


class Avatar(QLabel):
    PALETTE = ["#2563eb", "#7c3aed", "#0d9488", "#ea580c", "#db2777", "#0891b2", "#4f46e5", "#16a34a"]

    def __init__(self, name: str = "", size: int = 34):
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self.set_name(name)

    def set_name(self, name: str) -> None:
        parts = [p for p in name.split() if p]
        initials = "".join(p[0] for p in parts[:2]).upper() or "?"
        color = self.PALETTE[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(self.PALETTE)]
        self.setText(initials)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"QLabel {{ background: {color}; color: white; border-radius: {self._size // 2}px;"
                           f" font-weight: 700; font-size: {max(10, self._size // 3)}px; }}")


class IconTile(QLabel):
    """Square tinted tile holding an icon (used by stat cards and lists)."""

    def __init__(self, icon_name: str, tone: str = "blue", size: int = 38):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon, self._tone, self._size = icon_name, tone, size
        self._apply()
        theme_manager.changed.connect(self._apply)

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._apply()

    def _apply(self) -> None:
        try:
            fg, bg = theme().tone(self._tone)
            self.setStyleSheet(f"QLabel {{ background: {bg}; border-radius: 10px; }}")
            self.setPixmap(pixmap(self._icon, fg, int(self._size * 0.5)))
        except RuntimeError:
            pass


class StatCard(Card):
    clicked = Signal()

    def __init__(self, title: str, icon_name: str, tone: str = "blue"):
        super().__init__(padding=16, spacing=6)
        self.tile = IconTile(icon_name, tone)
        self.title = label(title, "overline")
        self.title.setWordWrap(True)  # wraps instead of clipping on narrow screens
        self.value = label("—", "kpi")
        self.sub = label("", "faint")
        self.sub.setWordWrap(True)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.title, 1, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)
        self.body.addWidget(self.value)
        self.body.addWidget(self.sub)
        self.setMinimumWidth(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set(self, value: str, sub: str = "", tone: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        if tone:
            self.tile.set_tone(tone)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CardGrid(QWidget):
    """Row of stat cards that drops to two rows (then one) when the cards would get too narrow."""

    def __init__(self, cards: list[QWidget], min_card_width: int = 175, spacing: int = 14):
        super().__init__()
        self.setObjectName("Transparent")
        self.cards = cards
        self.min_card_width = min_card_width
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.columns = 0
        self._arrange(len(cards))

    def _columns_for(self, width: int) -> int:
        n = len(self.cards)
        spacing = self.grid.spacing()
        for columns in sorted({n, (n + 1) // 2, (n + 2) // 3, 2, 1}, reverse=True):
            if columns <= n and columns * self.min_card_width + (columns - 1) * spacing <= width:
                return columns
        return 1

    def _arrange(self, columns: int) -> None:
        if columns == self.columns:
            return
        self.columns = columns
        for card in self.cards:
            self.grid.removeWidget(card)
        for c in range(len(self.cards)):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.min_card_width, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._arrange(self._columns_for(event.size().width()))
        super().resizeEvent(event)


class EmptyState(QWidget):
    action = Signal()

    def __init__(self, icon_name: str = "inbox", title: str = "Nothing here yet", text: str = "",
                 action_text: str | None = None, compact: bool = False):
        super().__init__()
        self.setObjectName("Transparent")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18 if compact else 36, 20, 18 if compact else 36)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        set_icon(self.icon, icon_name, "text_faint", 30 if compact else 40)
        self.title = label(title, "h3")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = label(text, "muted", wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setMaximumWidth(420)
        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        self.button = None
        if action_text:
            self.button = button(action_text, "plus", "soft", on_click=self.action.emit)
            layout.addSpacing(6)
            layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_text(self, title: str, text: str = "") -> None:
        self.title.setText(title)
        self.text.setText(text)


class SearchField(QLineEdit):
    """Search box with an icon and a debounced ``search`` signal."""

    search = Signal(str)

    def __init__(self, placeholder: str = "Search…", delay: int = 220):
        super().__init__()
        self.setObjectName("SearchField")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(180)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay)
        self._timer.timeout.connect(lambda: self.search.emit(self.text().strip()))
        self.textChanged.connect(lambda *_: self._timer.start())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        pm = pixmap("search", theme().c["text_faint"], 15)
        painter.drawPixmap(10, (self.height() - 15) // 2, pm)
        painter.end()


def toolbar(spacing: int = 10) -> tuple[QWidget, FlowLayout]:
    """A row of filters/buttons that wraps onto a second line when the window is narrow.
    Search boxes take up the spare room on their line, as in a normal toolbar."""
    host = QWidget()
    host.setObjectName("Transparent")
    return host, FlowLayout(host, spacing, line_hint=True)


class ChipGroup(QWidget):
    """Row of exclusive filter chips."""

    changed = Signal(object)

    def __init__(self, items: list[tuple[str, Any]] | None = None):
        super().__init__()
        self.setObjectName("Transparent")
        self._layout = FlowLayout(self, 6, line_hint=True)  # wraps onto a second line on narrow screens
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._data: dict[int, Any] = {}
        self._buttons: dict[int, QPushButton] = {}
        for text, data in items or []:
            self.add(text, data)
        self._group.idClicked.connect(lambda i: self.changed.emit(self._data[i]))

    def add(self, text: str, data: Any) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("chip", True)
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        idx = len(self._data)
        self._data[idx] = data
        self._buttons[idx] = btn
        self._group.addButton(btn, idx)
        self._layout.addWidget(btn)
        if idx == 0:
            btn.setChecked(True)
        return btn

    def current(self) -> Any:
        return self._data.get(self._group.checkedId())

    def set_current(self, data: Any, emit: bool = False) -> None:
        for idx, value in self._data.items():
            if value == data:
                self._buttons[idx].setChecked(True)
                if emit:
                    self.changed.emit(value)
                return

    def set_label(self, data: Any, text: str) -> None:
        for idx, value in self._data.items():
            if value == data:
                self._buttons[idx].setText(text)


class Banner(QFrame):
    """Inline message box (errors in dialogs, warnings, tips)."""

    ICONS = {"error": "alert-circle", "warning": "alert", "info": "info", "success": "check-circle"}
    COLORS = {"error": "danger", "warning": "warning", "info": "primary", "success": "success"}

    def __init__(self, text: str = "", tone: str = "info", *, closable: bool = False):
        super().__init__()
        self.setObjectName("Banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.text = label("", wrap=True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(False)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)
        if closable:
            layout.addWidget(icon_button("x", "Dismiss", self.hide, size=14), 0, Qt.AlignmentFlag.AlignTop)
        self.set(text, tone)

    def set(self, text: str, tone: str = "info") -> None:
        set_prop(self, "tone", tone)
        set_icon(self.icon, self.ICONS.get(tone, "info"), self.COLORS.get(tone, "primary"), 17)
        self.text.setText(text)
        self.setVisible(bool(text))


class KeyValueGrid(QWidget):
    """Two column list of ``label: value`` pairs."""

    def __init__(self, columns: int = 1):
        super().__init__()
        self.setObjectName("Transparent")
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        self.columns = columns
        self._count = 0
        self._values: dict[str, QLabel] = {}

    def add(self, key: str, title: str, value: str = "") -> QLabel:
        row, col = divmod(self._count, self.columns)
        self._count += 1
        t = label(title, "label")
        val = label(value, "value", wrap=True, selectable=True)
        self.grid.addWidget(t, row, col * 2, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(val, row, col * 2 + 1, Qt.AlignmentFlag.AlignTop)
        self.grid.setColumnStretch(col * 2 + 1, 1)
        self._values[key] = val
        return val

    def set(self, key: str, value: str) -> None:
        self._values[key].setText(value or "—")


class LoadingOverlay(QWidget):
    """Semi-transparent overlay with a spinner shown while work is running."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._angle = 0
        self._text = "Loading…"
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def start(self, text: str = "Loading…") -> None:
        self._text = text
        self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(theme().c["bg"])
        bg.setAlpha(190)
        p.fillRect(self.rect(), bg)
        cx, cy = self.width() / 2, self.height() / 2 - 10
        pen = QPen(QColor(theme().c["border_strong"]), 4)
        p.setPen(pen)
        p.drawEllipse(QRectF(cx - 16, cy - 16, 32, 32))
        pen.setColor(QColor(theme().c["primary"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx - 16, cy - 16, 32, 32), -self._angle * 16, 90 * 16)
        p.setPen(QColor(theme().c["text_muted"]))
        font = QFont(self.font())
        font.setPointSizeF(10)
        p.setFont(font)
        p.drawText(QRectF(0, cy + 26, self.width(), 24), Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()
