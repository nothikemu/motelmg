"""Availability calendar ("tape chart"): rooms x days with reservation bars."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QToolTip, QVBoxLayout, QWidget

from motelmg.core.enums import ReservationStatus, ServiceStatus
from motelmg.ui.pages.base import Page
from motelmg.ui.theme import theme, theme_manager
from motelmg.ui.widgets.common import button, icon_button, label
from motelmg.ui.widgets.forms import DateEdit, combo

ROW_H = 38
LEFT_W = 150
STATUS_TONE = {"confirmed": "purple", "checked_in": "blue", "checked_out": "gray"}


class _Grid:
    def __init__(self):
        self.start = date.today()
        self.days = 14
        self.rooms: list = []
        self.bars: list[dict] = []
        self.today = date.today()

    def day_width(self, width: int) -> float:
        return max((width - LEFT_W) / max(self.days, 1), 36)


class TapeHeader(QWidget):
    def __init__(self, grid: _Grid):
        super().__init__()
        self.grid = grid
        self.setFixedHeight(46)
        theme_manager.changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme().c
        g = self.grid
        p.fillRect(self.rect(), QColor(c["surface_alt"]))
        body = getattr(self, "body", None)
        dw = g.day_width(body.width() if body is not None else self.width())
        font = QFont(self.font())
        for i in range(g.days):
            d = g.start + timedelta(days=i)
            x = LEFT_W + i * dw
            rect = QRectF(x, 0, dw, self.height())
            if d == g.today:
                p.fillRect(rect, QColor(c["primary_soft"]))
            elif d.weekday() >= 5:
                shade = QColor(c["grid"])
                p.fillRect(rect, shade)
            font.setPointSizeF(7.5)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(QColor(c["primary"] if d == g.today else c["text_faint"]))
            p.drawText(QRectF(x, 5, dw, 14), Qt.AlignmentFlag.AlignCenter, d.strftime("%a").upper())
            font.setPointSizeF(11)
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            p.setPen(QColor(c["primary"] if d == g.today else c["text"]))
            p.drawText(QRectF(x, 19, dw, 22), Qt.AlignmentFlag.AlignCenter, str(d.day))
            p.setPen(QPen(QColor(c["border"]), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        font.setPointSizeF(9)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(c["text_muted"]))
        end = g.start + timedelta(days=g.days - 1)
        p.drawText(QRectF(14, 0, LEFT_W - 14, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   f"{g.start:%b %d} – {end:%b %d}")
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(QPointF(0, self.height() - 1), QPointF(self.width(), self.height() - 1))
        p.end()


class TapeBody(QWidget):
    open_reservation = Signal(int)
    new_reservation = Signal(int, object)

    def __init__(self, grid: _Grid):
        super().__init__()
        self.grid = grid
        self.setMouseTracking(True)
        theme_manager.changed.connect(self.update)

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(800, len(self.grid.rooms) * ROW_H + 2)

    def refresh(self) -> None:
        self.setMinimumHeight(len(self.grid.rooms) * ROW_H + 2)
        self.update()

    def _bar_rect(self, bar: dict, dw: float) -> QRectF | None:
        g = self.grid
        try:
            row = next(i for i, r in enumerate(g.rooms) if r.id == bar["room_id"])
        except StopIteration:
            return None
        start = (bar["check_in"] - g.start).days + 0.5
        end = (bar["check_out"] - g.start).days + 0.5
        start, end = max(start, 0.0), min(end, float(g.days))
        if end <= 0 or start >= g.days:
            return None
        return QRectF(LEFT_W + start * dw + 2, row * ROW_H + 6, (end - start) * dw - 4, ROW_H - 12)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c, t = theme().c, theme()
        g = self.grid
        dw = g.day_width(self.width())
        p.fillRect(self.rect(), QColor(c["surface"]))
        font = QFont(self.font())
        for i in range(g.days):
            d = g.start + timedelta(days=i)
            x = LEFT_W + i * dw
            if d == g.today:
                p.fillRect(QRectF(x, 0, dw, self.height()), QColor(c["primary_soft"]))
            elif d.weekday() >= 5:
                p.fillRect(QRectF(x, 0, dw, self.height()), QColor(c["surface_alt"]))
            p.setPen(QPen(QColor(c["grid"]), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for row, room in enumerate(g.rooms):
            y = row * ROW_H
            p.setPen(QPen(QColor(c["grid"]), 1))
            p.drawLine(QPointF(0, y + ROW_H), QPointF(self.width(), y + ROW_H))
            font.setPointSizeF(10)
            font.setWeight(QFont.Weight.Bold)
            p.setFont(font)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(14, y, 60, ROW_H), Qt.AlignmentFlag.AlignVCenter, room.number)
            font.setPointSizeF(8)
            font.setWeight(QFont.Weight.Normal)
            p.setFont(font)
            p.setPen(QColor(c["text_faint"]))
            p.drawText(QRectF(64, y, LEFT_W - 70, ROW_H), Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(room.type_name, Qt.TextElideMode.ElideRight, LEFT_W - 72))
            if room.service_status != ServiceStatus.IN_SERVICE:
                until = room.service_until
                end_idx = g.days if until is None else min((until - g.start).days, g.days)
                start_idx = max((g.today - g.start).days, 0)
                if end_idx > start_idx:
                    rect = QRectF(LEFT_W + start_idx * dw, y + 3, (end_idx - start_idx) * dw, ROW_H - 6)
                    brush = QBrush(QColor(t.accent("orange") if room.service_status == "maintenance"
                                          else t.accent("slate")), Qt.BrushStyle.BDiagPattern)
                    p.fillRect(rect, brush)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(QPointF(LEFT_W, 0), QPointF(LEFT_W, self.height()))
        for bar in g.bars:
            rect = self._bar_rect(bar, dw)
            if rect is None:
                continue
            tone = STATUS_TONE.get(bar["status"], "gray")
            fg, bg = t.tone(tone)
            path = QPainterPath()
            path.addRoundedRect(rect, 7, 7)
            p.fillPath(path, QColor(bg))
            p.setPen(QPen(QColor(t.accent(tone)), 1.4))
            p.drawPath(path)
            p.fillRect(QRectF(rect.x(), rect.y() + 4, 3.5, rect.height() - 8), QColor(t.accent(tone)))
            font.setPointSizeF(8.5)
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            p.setPen(QColor(fg))
            text = bar["guest"]
            p.drawText(rect.adjusted(10, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 16)))
        p.end()

    def _bar_at(self, pos) -> dict | None:
        dw = self.grid.day_width(self.width())
        for bar in self.grid.bars:
            rect = self._bar_rect(bar, dw)
            if rect and rect.contains(pos):
                return bar
        return None

    def _cell_at(self, pos):
        g = self.grid
        if pos.x() < LEFT_W:
            return None
        row = int(pos.y() // ROW_H)
        col = int((pos.x() - LEFT_W) // g.day_width(self.width()))
        if 0 <= row < len(g.rooms) and 0 <= col < g.days:
            return g.rooms[row], g.start + timedelta(days=col)
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        bar = self._bar_at(event.position())
        if bar:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{bar['guest']}\n{bar['conf']} · {ReservationStatus.LABELS[bar['status']]}\n"
                              f"{bar['check_in']:%b %d} → {bar['check_out']:%b %d} ({bar['nights']} nights)", self)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            cell = self._cell_at(event.position())
            if cell and cell[1] >= self.grid.today:
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"Room {cell[0].number} · {cell[1]:%a %b %d}\nDouble-click to book", self)
            else:
                QToolTip.hideText()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            bar = self._bar_at(event.position())
            if bar:
                self.open_reservation.emit(bar["id"])

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._bar_at(event.position()):
            return
        cell = self._cell_at(event.position())
        if cell and cell[1] >= self.grid.today:
            self.new_reservation.emit(cell[0].id, cell[1])


class CalendarPage(Page):
    key = "calendar"
    title = "Calendar"
    icon = "calendar"
    permission = "reservations.view"
    topics = ("reservations", "rooms")

    def __init__(self, app):
        super().__init__(app)
        self.grid = _Grid()
        self.grid.today = self.ctx.clock.today()
        self.grid.start = self.grid.today - timedelta(days=2)
        L = self.layout_
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(icon_button("chevron-left", "Earlier", lambda: self._shift(-1), size=18))
        bar.addWidget(button("Today", on_click=self._today))
        bar.addWidget(icon_button("chevron-right", "Later", lambda: self._shift(1), size=18))
        self.picker = DateEdit(self.grid.start)
        self.picker.dateChanged.connect(lambda *_: self._picked())
        bar.addWidget(self.picker)
        self.span = combo([("7 days", 7), ("14 days", 14), ("21 days", 21), ("30 days", 30)], 14)
        self.span.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.span)
        self.type_filter = combo([("All room types", None)])
        self.type_filter.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.type_filter)
        bar.addStretch(1)
        for status, text in (("confirmed", "Confirmed"), ("checked_in", "In house"), ("checked_out", "Checked out")):
            dot = label("")
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {theme().accent(STATUS_TONE[status])}; border-radius: 5px;")
            bar.addWidget(dot)
            bar.addWidget(label(text, "faint"))
        L.addLayout(bar)
        frame = QWidget()
        frame.setObjectName("Transparent")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        frame.setStyleSheet("")
        self.header = TapeHeader(self.grid)
        self.body = TapeBody(self.grid)
        self.header.body = self.body
        self.body.open_reservation.connect(lambda rid: self.actions.open_reservation(rid))
        self.body.new_reservation.connect(lambda room_id, d: self.actions.new_reservation(room_id=room_id, arrival=d))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        card = QWidget()
        card.setObjectName("Transparent")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.header)
        cl.addWidget(scroll, 1)
        from motelmg.ui.widgets.common import Card
        holder = Card(padding=0, spacing=0)
        holder.body.addWidget(card)
        L.addWidget(holder, 1)
        L.addWidget(label("Click a booking to open it · double-click an empty day to create a reservation · "
                          "hatched cells are out of order", "faint"))

    def subtitle(self) -> str:
        return "Room availability and bookings over time"

    def _shift(self, direction: int) -> None:
        step = max(self.span.currentData() // 2, 3)
        self.grid.start += timedelta(days=direction * step)
        self.picker.blockSignals(True)
        self.picker.set_value(self.grid.start)
        self.picker.blockSignals(False)
        self.mark_stale()

    def _today(self) -> None:
        self.grid.start = self.ctx.clock.today() - timedelta(days=2)
        self.picker.blockSignals(True)
        self.picker.set_value(self.grid.start)
        self.picker.blockSignals(False)
        self.mark_stale()

    def _picked(self) -> None:
        self.grid.start = self.picker.value()
        self.mark_stale()

    def refresh(self) -> None:
        g = self.grid
        g.today = self.ctx.clock.today()
        g.days = self.span.currentData()
        current = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("All room types", None)
        for t in self.ctx.rooms.list_types():
            self.type_filter.addItem(t.name, t.id)
        self.type_filter.setCurrentIndex(max(self.type_filter.findData(current), 0))
        self.type_filter.blockSignals(False)
        rooms = self.ctx.rooms.list_rooms()
        if current:
            rooms = [r for r in rooms if r.room_type_id == current]
        g.rooms = rooms
        end = g.start + timedelta(days=g.days)
        reservations = self.ctx.repo_res.search(statuses=["confirmed", "checked_in", "checked_out"],
                                                stay_from=g.start, stay_to=end)
        g.bars = [{"id": r.id, "room_id": r.room_id, "check_in": r.check_in_date, "check_out": r.check_out_date,
                   "status": r.status, "guest": r.guest_name, "conf": r.confirmation_no, "nights": r.nights}
                  for r in reservations]
        self.header.update()
        self.body.refresh()
