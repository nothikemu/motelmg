"""Lightweight themed charts drawn with QPainter (bar, horizontal bar, line, donut)."""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from motelmg.ui.theme import theme, theme_manager


def _series_colors() -> list[str]:
    c = theme().c
    return [c["chart_1"], c["chart_2"], c["chart_3"], c["chart_4"]]


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        top = step * magnitude
        if top >= value:
            return float(top)
    return float(value)


class ChartBase(QWidget):
    def __init__(self, value_fmt: Callable[[float], str] | None = None, *, min_height: int = 220):
        super().__init__()
        self.labels: list[str] = []
        self.series: list[tuple[str, list[float]]] = []
        self.value_fmt = value_fmt or (lambda v: f"{v:,.0f}")
        self.axis_fmt: Callable[[float], str] = self.value_fmt
        self.stacked = False
        self.setMinimumHeight(min_height)
        self.setMouseTracking(True)
        self._hits: list[tuple[QRectF, str]] = []
        theme_manager.changed.connect(self.update)

    def set_data(self, labels: list[str], series: list[tuple[str, list[float]]], *, stacked: bool = False) -> None:
        self.labels = list(labels)
        self.series = [(name, [float(v or 0) for v in values]) for name, values in series]
        self.stacked = stacked
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        for rect, text in self._hits:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), text, self)
                return
        QToolTip.hideText()

    def _font(self, size: float = 8.5, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(size)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        return font

    def _legend(self, p: QPainter, x: float, y: float) -> None:
        if len(self.series) < 2:
            return
        colors = _series_colors()
        p.setFont(self._font(8.5))
        for i, (name, _) in enumerate(self.series):
            p.setBrush(QColor(colors[i % len(colors)]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y + 3, 10, 10), 3, 3)
            p.setPen(QColor(theme().c["text_muted"]))
            p.drawText(QPointF(x + 15, y + 12), name)
            x += 26 + p.fontMetrics().horizontalAdvance(name)

    def _empty(self, p: QPainter) -> bool:
        if not self.labels or not self.series or not any(any(v for v in vals) for _, vals in self.series):
            p.setPen(QColor(theme().c["text_faint"]))
            p.setFont(self._font(9.5))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data for this period")
            return True
        return False


class BarChart(ChartBase):
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        if self._empty(p):
            return
        c = theme().c
        colors = _series_colors()
        legend_h = 22 if len(self.series) > 1 else 4
        left, right, top, bottom = 58, 10, legend_h + 6, 26
        w, h = self.width() - left - right, self.height() - top - bottom
        n = len(self.labels)
        if self.stacked:
            peak = max(sum(vals[i] for _, vals in self.series) for i in range(n))
        else:
            peak = max(max(vals) for _, vals in self.series)
        top_value = _nice_max(peak)
        p.setFont(self._font(8))
        for step in range(5):
            y = top + h - h * step / 4
            p.setPen(QPen(QColor(c["grid"]), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(c["text_faint"]))
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.axis_fmt(top_value * step / 4))
        slot = w / n
        groups = 1 if self.stacked else len(self.series)
        bar_w = max(min(slot * 0.7 / groups, 34), 2)
        label_every = max(1, math.ceil(n / max(w / 58, 1)))
        for i, text in enumerate(self.labels):
            x0 = left + slot * i + (slot - bar_w * groups) / 2
            base = top + h
            for s, (name, vals) in enumerate(self.series):
                value = vals[i]
                bh = h * value / top_value if top_value else 0
                if self.stacked:
                    rect = QRectF(x0, base - bh, bar_w, bh)
                    base -= bh
                else:
                    rect = QRectF(x0 + s * bar_w, top + h - bh, bar_w - (2 if groups > 1 else 0), bh)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(colors[s % len(colors)]))
                path = QPainterPath()
                radius = min(4, rect.width() / 2, rect.height())
                path.addRoundedRect(rect, radius, radius)
                p.drawPath(path)
                self._hits.append((QRectF(left + slot * i, top, slot, h),
                                   f"{text}\n" + "\n".join(f"{nm}: {self.value_fmt(vs[i])}" for nm, vs in self.series)))
            if i % label_every == 0:
                p.setPen(QColor(c["text_faint"]))
                p.drawText(QRectF(left + slot * i - 10, top + h + 4, slot + 20, 18), Qt.AlignmentFlag.AlignHCenter,
                           text)
        self._legend(p, left, 2)
        p.end()


class LineChart(ChartBase):
    def __init__(self, *args, max_value: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_value = max_value

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        if self._empty(p):
            return
        c = theme().c
        colors = _series_colors()
        left, right, top, bottom = 50, 14, 14, 26
        w, h = self.width() - left - right, self.height() - top - bottom
        n = len(self.labels)
        peak = self.max_value or _nice_max(max(max(v) for _, v in self.series))
        p.setFont(self._font(8))
        for step in range(5):
            y = top + h - h * step / 4
            p.setPen(QPen(QColor(c["grid"]), 1))
            p.drawLine(QPointF(left, y), QPointF(left + w, y))
            p.setPen(QColor(c["text_faint"]))
            p.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.axis_fmt(peak * step / 4))
        step_x = w / max(n - 1, 1)
        for s, (name, vals) in enumerate(self.series):
            color = QColor(colors[s % len(colors)])
            points = [QPointF(left + step_x * i, top + h - h * min(v, peak) / peak) for i, v in enumerate(vals)]
            fill = QPainterPath()
            fill.moveTo(QPointF(points[0].x(), top + h))
            for pt in points:
                fill.lineTo(pt)
            fill.lineTo(QPointF(points[-1].x(), top + h))
            area = QColor(color)
            area.setAlpha(36)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(area)
            p.drawPath(fill)
            pen = QPen(color, 2.4)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(points[0])
            for pt in points[1:]:
                path.lineTo(pt)
            p.drawPath(path)
            if n <= 40:
                p.setBrush(QColor(c["surface"]))
                for pt in points:
                    p.drawEllipse(pt, 3, 3)
            for i, pt in enumerate(points):
                self._hits.append((QRectF(pt.x() - step_x / 2, top, step_x, h),
                                   f"{self.labels[i]}: {self.value_fmt(vals[i])}"))
        label_every = max(1, math.ceil(n / max(w / 64, 1)))
        p.setPen(QColor(c["text_faint"]))
        for i, text in enumerate(self.labels):
            if i % label_every == 0:
                p.drawText(QRectF(left + step_x * i - 30, top + h + 4, 60, 18), Qt.AlignmentFlag.AlignHCenter, text)
        p.end()


class HBarChart(ChartBase):
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        if self._empty(p):
            return
        c = theme().c
        name, vals = self.series[0]
        peak = max(vals) or 1
        p.setFont(self._font(8.5))
        label_w = min(max(p.fontMetrics().horizontalAdvance(t) for t in self.labels) + 12, self.width() * 0.4)
        row_h = min(30, (self.height() - 8) / max(len(self.labels), 1))
        value_w = 86
        bar_space = self.width() - label_w - value_w - 8
        for i, (text, value) in enumerate(zip(self.labels, vals)):
            y = 4 + i * row_h
            p.setPen(QColor(c["text_muted"]))
            p.drawText(QRectF(0, y, label_w - 8, row_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(label_w - 10)))
            track = QRectF(label_w, y + row_h * 0.22, bar_space, row_h * 0.56)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(c["grid"]))
            p.drawRoundedRect(track, 4, 4)
            bar = QRectF(track.x(), track.y(), max(bar_space * value / peak, 2), track.height())
            p.setBrush(QColor(_series_colors()[i % 4] if len(self.labels) <= 4 else c["chart_1"]))
            p.drawRoundedRect(bar, 4, 4)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(label_w + bar_space + 6, y, value_w, row_h),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.value_fmt(value))
            self._hits.append((QRectF(0, y, self.width(), row_h), f"{text}: {self.value_fmt(value)}"))
        p.end()


class DonutChart(QWidget):
    """Donut with a legend (used for the room status breakdown)."""

    def __init__(self, size: int = 150):
        super().__init__()
        self.items: list[tuple[str, int, str]] = []  # label, value, tone
        self.center_text = ""
        self.center_sub = ""
        self.ring = size
        self.setMinimumHeight(size + 10)
        theme_manager.changed.connect(self.update)

    def set_data(self, items: list[tuple[str, int, str]], center: str = "", sub: str = "") -> None:
        self.items = items
        self.center_text, self.center_sub = center, sub
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme().c
        size = min(self.ring, self.height() - 10)
        rect = QRectF(6, (self.height() - size) / 2, size, size)
        total = sum(v for _, v, _ in self.items)
        pen_w = size * 0.16
        inner = rect.adjusted(pen_w / 2, pen_w / 2, -pen_w / 2, -pen_w / 2)
        p.setPen(QPen(QColor(c["grid"]), pen_w))
        p.drawEllipse(inner)
        if total:
            start = 90 * 16
            for _, value, tone in self.items:
                if not value:
                    continue
                span = -int(360 * 16 * value / total)
                pen = QPen(QColor(theme().accent(tone)), pen_w)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pen)
                p.drawArc(inner, start, span)
                start += span
        font = QFont(self.font())
        font.setPointSizeF(16)
        font.setWeight(QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(c["text"]))
        p.drawText(QRectF(rect.x(), rect.center().y() - 18, rect.width(), 26), Qt.AlignmentFlag.AlignCenter,
                   self.center_text)
        font.setPointSizeF(8)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor(c["text_muted"]))
        p.drawText(QRectF(rect.x(), rect.center().y() + 6, rect.width(), 18), Qt.AlignmentFlag.AlignCenter,
                   self.center_sub)
        # legend
        x = rect.right() + 22
        y = max(8, (self.height() - len(self.items) * 22) / 2)
        font.setPointSizeF(9)
        p.setFont(font)
        for text, value, tone in self.items:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme().accent(tone)))
            p.drawRoundedRect(QRectF(x, y + 5, 10, 10), 3, 3)
            p.setPen(QColor(c["text_muted"]))
            p.drawText(QRectF(x + 16, y, self.width() - x - 60, 20), Qt.AlignmentFlag.AlignVCenter, text)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(self.width() - 46, y, 40, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       str(value))
            y += 22
        p.end()
