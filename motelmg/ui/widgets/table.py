"""Sortable, filterable data table with status badges, empty state and CSV export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRect, QRectF, QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QAction, QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QMenu, QStackedLayout, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget)

from motelmg.ui.theme import theme
from motelmg.ui.widgets.common import EmptyState


@dataclass
class Column:
    key: str
    title: str
    kind: str = "text"  # text | money | int | date | datetime | badge | bool | percent
    width: int | None = None
    stretch: bool = False
    align: str | None = None  # left | right | center
    fmt: Callable[[dict], str] | None = None  # custom display text from the row
    tone: Callable[[dict], str] | None = None  # badge tone / text colour from the row
    sort: Callable[[dict], Any] | None = None
    tooltip: Callable[[dict], str] | None = None
    bold: bool = False


SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_ROLE = Qt.ItemDataRole.UserRole + 2
TONE_ROLE = Qt.ItemDataRole.UserRole + 3


class RowModel(QAbstractTableModel):
    def __init__(self, columns: list[Column], formatter):
        super().__init__()
        self.columns = columns
        self.rows: list[dict] = []
        self.fmt = formatter

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            col = self.columns[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return col.title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return self._alignment(col)
        return None

    def _alignment(self, col: Column):
        if col.align == "right" or (col.align is None and col.kind in ("money", "int", "percent")):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if col.align == "center":
            return int(Qt.AlignmentFlag.AlignCenter)
        return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def display(self, row: dict, col: Column) -> str:
        if col.fmt:
            return col.fmt(row)
        value = row.get(col.key)
        if value is None:
            return ""
        if col.kind == "money":
            return self.fmt.money(value)
        if col.kind == "date":
            return self.fmt.date(value)
        if col.kind == "datetime":
            return self.fmt.datetime(value)
        if col.kind == "bool":
            return "Yes" if value else ""
        if col.kind == "percent":
            return f"{value:.1f}%"
        if col.kind == "int":
            return f"{value:,}" if isinstance(value, int) else str(value)
        return str(value)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.display(row, col)
        if role == SORT_ROLE:
            if col.sort:
                return col.sort(row)
            value = row.get(col.key)
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            if value is None:
                return ""
            if isinstance(value, str):
                return value.lower()
            return value
        if role == ROW_ROLE:
            return row
        if role == TONE_ROLE:
            return col.tone(row) if col.tone else None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(col)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col.tooltip:
                return col.tooltip(row)
            text = self.display(row, col)
            return text if len(text) > 28 else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if col.tone and col.kind != "badge":
                tone = col.tone(row)
                if tone:
                    return QColor(theme().tone(tone)[0])
            if col.kind == "money":
                value = row.get(col.key)
                if isinstance(value, int) and value < 0:
                    return QColor(theme().c["danger"])
        if role == Qt.ItemDataRole.FontRole and col.bold:
            font = QFont()
            font.setWeight(QFont.Weight.DemiBold)
            return font
        return None


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.setSortRole(SORT_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._text = ""
        self._predicate: Callable[[dict], bool] | None = None

    def _change_filter(self, apply: Callable[[], None]) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.9
            self.beginFilterChange()
            apply()
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # pragma: no cover - older Qt
            apply()
            self.invalidateFilter()

    def set_text(self, text: str) -> None:
        self._change_filter(lambda: setattr(self, "_text", text.lower().strip()))

    def set_predicate(self, predicate: Callable[[dict], bool] | None) -> None:
        self._change_filter(lambda: setattr(self, "_predicate", predicate))

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model: RowModel = self.sourceModel()  # type: ignore[assignment]
        row = model.rows[source_row]
        if self._predicate and not self._predicate(row):
            return False
        if not self._text:
            return True
        haystack = " ".join(model.display(row, c) for c in model.columns).lower()
        return all(part in haystack for part in self._text.split())

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        a = left.data(SORT_ROLE)
        b = right.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class BadgeDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        tone = index.data(TONE_ROLE) or "gray"
        fg, bg = theme().tone(tone)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(option.font)
        font.setPointSizeF(max(option.font.pointSizeF() - 1, 7.5))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 18
        height = metrics.height() + 6
        rect = option.rect
        x = rect.x() + 8
        y = rect.y() + (rect.height() - height) // 2
        pill = QRectF(x, y, min(width, rect.width() - 12), height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor(fg))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                                                                  int(pill.width()) - 10))
        painter.restore()


class DataTable(QWidget):
    """Table + empty state. ``activated`` fires with the row dict on double-click/Enter."""

    activated = Signal(dict)
    selection_changed = Signal()

    def __init__(self, columns: list[Column], formatter, *, empty_icon: str = "inbox",
                 empty_title: str = "No records found", empty_text: str = "", empty_action: str | None = None,
                 multi_select: bool = False, row_height: int = 40):
        super().__init__()
        self.setObjectName("Transparent")
        self.columns = columns
        self.model = RowModel(columns, formatter)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multi_select
                                   else QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setAlternatingRowColors(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(row_height)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._activated)
        self.view.activated.connect(self._activated)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self.selection_changed.emit())
        header = self.view.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # keep the query order until the user sorts
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(50)
        header.setSectionsMovable(False)
        header.setStretchLastSection(False)
        self._badge = BadgeDelegate(self.view)
        any_stretch = any(c.stretch for c in columns)
        for i, col in enumerate(columns):
            if col.kind == "badge":
                self.view.setItemDelegateForColumn(i, self._badge)
            if col.stretch:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                header.resizeSection(i, col.width or 120)
        if not any_stretch and columns:
            header.setStretchLastSection(True)
        self.empty = EmptyState(empty_icon, empty_title, empty_text, empty_action)
        self.stack = QStackedLayout()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.stack)
        self._menu_builder: Callable[[dict], list] | None = None
        self.proxy.rowsInserted.connect(self._update_empty)
        self.proxy.rowsRemoved.connect(self._update_empty)
        self.proxy.modelReset.connect(self._update_empty)
        self.proxy.layoutChanged.connect(self._update_empty)

    # -- data ----------------------------------------------------------------------------
    def set_rows(self, rows: list[dict], keep_selection: bool = True) -> None:
        key = None
        selected = self.selected_row()
        if keep_selection and selected is not None:
            key = selected.get("id")
        sort_col = self.view.horizontalHeader().sortIndicatorSection()
        sort_order = self.view.horizontalHeader().sortIndicatorOrder()
        self.model.set_rows(rows)
        if 0 <= sort_col < len(self.columns) and self.view.isSortingEnabled():
            self.proxy.sort(sort_col, sort_order)
        else:
            self.proxy.sort(-1)
        if key is not None:
            self.select_id(key)
        self._update_empty()

    def fit_columns(self, maximum: int = 340) -> None:
        """Size columns to their content (capped), stretching the flexible one."""
        header = self.view.horizontalHeader()
        for i, col in enumerate(self.columns):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.view.resizeColumnToContents(i)
            header.resizeSection(i, min(max(header.sectionSize(i) + 10, 56), maximum))
        header.setStretchLastSection(True)

    def sort_by(self, key: str, descending: bool = False) -> None:
        for i, col in enumerate(self.columns):
            if col.key == key:
                self.view.sortByColumn(i, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
                return

    def rows(self) -> list[dict]:
        return self.model.rows

    def visible_rows(self) -> list[dict]:
        return [self.proxy.index(r, 0).data(ROW_ROLE) for r in range(self.proxy.rowCount())]

    def set_filter_text(self, text: str) -> None:
        self.proxy.set_text(text)
        self._update_empty()

    def set_predicate(self, predicate: Callable[[dict], bool] | None) -> None:
        self.proxy.set_predicate(predicate)
        self._update_empty()

    def _update_empty(self, *_) -> None:
        self.stack.setCurrentIndex(0 if self.proxy.rowCount() else 1)

    def set_empty(self, title: str, text: str = "") -> None:
        self.empty.set_text(title, text)

    # -- selection --------------------------------------------------------------------------
    def selected_row(self) -> dict | None:
        indexes = self.view.selectionModel().selectedRows()
        if not indexes:
            return None
        return indexes[0].data(ROW_ROLE)

    def selected_rows(self) -> list[dict]:
        return [i.data(ROW_ROLE) for i in self.view.selectionModel().selectedRows()]

    def select_id(self, row_id: Any) -> bool:
        for r in range(self.proxy.rowCount()):
            row = self.proxy.index(r, 0).data(ROW_ROLE)
            if row and row.get("id") == row_id:
                self.view.selectRow(r)
                self.view.scrollTo(self.proxy.index(r, 0))
                return True
        return False

    def _activated(self, index: QModelIndex) -> None:
        row = index.data(ROW_ROLE)
        if row is not None:
            self.activated.emit(row)

    # -- context menu --------------------------------------------------------------------------
    def set_menu_builder(self, builder: Callable[[dict], list]) -> None:
        """``builder(row)`` returns a list of ``(text, callback)`` / ``None`` (separator)."""
        self._menu_builder = builder

    def _context_menu(self, pos) -> None:
        if not self._menu_builder:
            return
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        self.view.selectRow(index.row())
        row = index.data(ROW_ROLE)
        entries = self._menu_builder(row)
        if not entries:
            return
        menu = QMenu(self)
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            text, callback, *rest = entry
            action = QAction(text, menu)
            action.setEnabled(bool(rest[0]) if rest else True)
            action.triggered.connect(lambda _=False, cb=callback: cb())
            menu.addAction(action)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    # -- export ----------------------------------------------------------------------------------
    def export_rows(self) -> tuple[list[str], list[list[Any]]]:
        headers = [c.title for c in self.columns]
        out = []
        for row in self.visible_rows():
            values = []
            for col in self.columns:
                value = row.get(col.key)
                if col.kind == "money" and isinstance(value, int):
                    values.append(f"{value / 100:.2f}")
                elif isinstance(value, datetime):
                    values.append(value.strftime("%Y-%m-%d %H:%M"))
                elif isinstance(value, date):
                    values.append(value.isoformat())
                else:
                    values.append(self.model.display(row, col))
            out.append(values)
        return headers, out


__all__ = ["Column", "DataTable", "QRect"]
