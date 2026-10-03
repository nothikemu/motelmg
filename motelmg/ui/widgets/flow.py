"""Flow layout: places widgets left-to-right, wrapping to new lines."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, spacing: int = 10, *, line_hint: bool = False):
        """``line_hint``: prefer laying everything out on one line (sizeHint is the single-line width) and
        wrap only when the parent can't give that much room, e.g. a row of filter chips in a toolbar."""
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self._line_hint = line_hint
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        if not self._line_hint:
            return self.minimumSize()
        hints = [item.sizeHint() for item in self._items if not self._skipped(item)]
        m = self.contentsMargins()
        width = sum(h.width() for h in hints) + self._spacing * max(len(hints) - 1, 0)
        height = max((h.height() for h in hints), default=0)
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    @staticmethod
    def _skipped(item: QLayoutItem) -> bool:
        widget = item.widget()
        return widget is not None and widget.isHidden() and \
            widget.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)  # explicitly hidden by the caller

    @staticmethod
    def _grows(item: QLayoutItem) -> bool:
        """Only widgets that are themselves horizontally expanding (search boxes) and spacers grow;
        a group widget is not stretched just because something inside it could expand."""
        widget = item.widget()
        if widget is not None:
            return bool(widget.sizePolicy().horizontalPolicy().value & QSizePolicy.PolicyFlag.ExpandFlag.value)
        return bool(item.expandingDirections() & Qt.Orientation.Horizontal)

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines: list[list[tuple[QLayoutItem, QSize]]] = []
        line: list[tuple[QLayoutItem, QSize]] = []
        x = effective.x()
        for item in self._items:
            if self._skipped(item):
                continue
            hint = item.sizeHint()
            if line and x + hint.width() > effective.right() + 1:
                lines.append(line)
                line, x = [], effective.x()
            line.append((item, hint))
            x += hint.width() + self._spacing
        if line:
            lines.append(line)
        y = effective.y()
        for line in lines:
            line_height = max(h.height() for _, h in line)
            growers: list[QLayoutItem] = []
            share = 0
            if self._line_hint:
                # Toolbar mode: expanding items (search boxes, stretches) share the spare room on their line.
                growers = [it for it, _ in line if self._grows(it)]
                used = sum(h.width() for _, h in line) + self._spacing * (len(line) - 1)
                share = max(effective.width() - used, 0) // len(growers) if growers else 0
            x = effective.x()
            for item, hint in line:
                width = hint.width() + (share if item in growers else 0)
                if not test_only:
                    top = y + (line_height - hint.height()) // 2 if self._line_hint else y
                    item.setGeometry(QRect(QPoint(x, top), QSize(width, hint.height())))
                x += width + self._spacing
            y += line_height + self._spacing
        height = y - self._spacing if lines else y
        return height - rect.y() + m.bottom()


__all__ = ["FlowLayout", "QSizePolicy"]
