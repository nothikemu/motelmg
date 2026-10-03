"""Room board: every room at a glance, colour-coded by state, with a detail
panel offering all room actions."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from motelmg.core.enums import HKStatus, RoomState, ServiceStatus, TaskType
from motelmg.services.rooms import RoomBoardItem
from motelmg.ui.pages.base import Page
from motelmg.ui.theme import theme
from motelmg.ui.widgets.common import (Badge, Banner, ChipGroup, Divider, EmptyState, KeyValueGrid, SearchField,
                                       button, clear_layout, icon_button, label, set_icon)
from motelmg.ui.widgets.dialogs import confirm, guarded
from motelmg.ui.widgets.flow import FlowLayout
from motelmg.ui.widgets.forms import combo

FILTERS = [
    ("All", "all"), ("Ready", RoomState.AVAILABLE), ("Occupied", "occupied"), ("Arriving", RoomState.RESERVED),
    ("Due out", "due"), ("Needs cleaning", RoomState.VACANT_DIRTY), ("Out of order", "ooo"),
]
HK_ICON = {HKStatus.DIRTY: ("alert-circle", "amber"), HKStatus.CLEANING: ("sparkles", "cyan"),
           HKStatus.CLEAN: ("check", "green"), HKStatus.INSPECTED: ("check-circle", "teal")}


def matches(item: RoomBoardItem, key: str) -> bool:
    s = item.state
    if key == "all":
        return True
    if key == "occupied":
        return s in (RoomState.OCCUPIED, RoomState.DUE_OUT, RoomState.OVERDUE)
    if key == "due":
        return s in (RoomState.DUE_OUT, RoomState.OVERDUE)
    if key == "ooo":
        return s in (RoomState.MAINTENANCE, RoomState.OUT_OF_SERVICE)
    return s == key


class RoomTile(QFrame):
    clicked = Signal(int)
    menu_requested = Signal(int, object)

    def __init__(self, item: RoomBoardItem, fmt):
        super().__init__()
        self.setObjectName("Tile")
        self.room_id = item.room.id
        self.item = item
        self.setFixedSize(176, 118)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menu_requested.emit(self.room_id,
                                                                                     self.mapToGlobal(pos)))
        tone = RoomState.TONES[item.state]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 12, 10)
        layout.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        num = QLabel(item.room.number)
        num.setStyleSheet("font-size: 21px; font-weight: 700; background: transparent;")
        top.addWidget(num)
        top.addWidget(label(item.room.type_code, "faint"), 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch(1)
        if item.open_tickets:
            t = QLabel()
            set_icon(t, "tool", "orange", 14)
            t.setToolTip(f"{item.open_tickets} open maintenance ticket(s)")
            top.addWidget(t)
        if item.flags:
            f = QLabel()
            set_icon(f, "alert", "red", 14)
            f.setToolTip({"conflict": "Booking conflict", "arrival_dirty": "Arrival today but room not clean",
                          "arrival_blocked": "Arrival today but the room is still occupied"}.get(item.flags[0], ""))
            top.addWidget(f)
        layout.addLayout(top)
        state = QLabel(RoomState.LABELS[item.state])
        fg = theme().tone(tone)[0]
        state.setStyleSheet(f"color: {fg}; font-weight: 600; font-size: 12px; background: transparent;")
        layout.addWidget(state)
        res = item.in_house or item.arrival
        if res:
            who = label(res.guest_name, "muted")
            sub = f"until {fmt.short_date(res.check_out_date)}" if item.in_house else \
                f"{res.nights} night{'s' if res.nights != 1 else ''}"
            who.setToolTip(f"{res.guest_name} · {res.confirmation_no}")
            layout.addWidget(who)
            layout.addWidget(label(sub, "faint"))
        elif item.room.service_status != ServiceStatus.IN_SERVICE:
            layout.addWidget(label(item.room.service_reason[:28] or "Not available", "muted"))
            layout.addWidget(label(f"until {fmt.short_date(item.room.service_until)}" if item.room.service_until
                                   else "", "faint"))
        elif item.next_reservation:
            layout.addWidget(label(f"Next: {fmt.relative_day(item.next_reservation.check_in_date)}", "faint"))
            layout.addStretch(1)
        else:
            layout.addWidget(label(f"{fmt.money(item.room.effective_rate)} / night", "faint"))
            layout.addStretch(1)
        layout.addStretch(1)
        bottom = QHBoxLayout()
        bottom.setSpacing(5)
        hk_icon = QLabel()
        name, color = HK_ICON[item.room.hk_status]
        set_icon(hk_icon, name, color, 13)
        bottom.addWidget(hk_icon)
        hk_text = HKStatus.LABELS[item.room.hk_status]
        if item.open_task_status == "in_progress":
            hk_text = "Being cleaned"
        elif item.open_task_type and item.open_task_assignee:
            hk_text += f" · {item.open_task_assignee.split()[0]}"
        bottom.addWidget(label(hk_text, "faint"))
        bottom.addStretch(1)
        layout.addLayout(bottom)
        self._accent = theme().accent(tone)
        self.setToolTip(self._tooltip(fmt))

    def _tooltip(self, fmt) -> str:
        item = self.item
        lines = [f"Room {item.room.number} — {item.room.type_name}", RoomState.LABELS[item.state],
                 f"Housekeeping: {HKStatus.LABELS[item.room.hk_status]}"]
        if item.in_house:
            lines.append(f"Guest: {item.in_house.guest_name} until {fmt.date(item.in_house.check_out_date)}")
        if item.arrival:
            lines.append(f"Arriving: {item.arrival.guest_name}")
        return "\n".join(lines)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(1, 1, 5, self.height() - 2, 2.5, 2.5)
        p.fillPath(path, QColor(self._accent))
        p.end()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.room_id)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.room_id)


class RoomsPage(Page):
    key = "rooms"
    title = "Room Board"
    icon = "grid"
    permission = "rooms.view"
    topics = ("rooms", "reservations", "housekeeping", "maintenance")

    def __init__(self, app):
        super().__init__(app)
        self.items: list[RoomBoardItem] = []
        self.selected: int | None = None
        L = self.layout_
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.chips = ChipGroup(FILTERS)
        self.chips.changed.connect(lambda *_: self._render())
        bar.addWidget(self.chips)
        bar.addStretch(1)
        self.type_filter = combo([("All types", None)])
        self.type_filter.currentIndexChanged.connect(lambda *_: self._render())
        bar.addWidget(self.type_filter)
        self.search = SearchField("Room or guest…")
        self.search.setMinimumWidth(180)
        self.search.search.connect(lambda *_: self._render())
        bar.addWidget(self.search)
        if self.ctx.can("rooms.manage"):
            bar.addWidget(button("Manage rooms", "settings", on_click=lambda: app.navigate("settings",
                                                                                          section="rooms")))
        L.addLayout(bar)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.board = QWidget()
        self.board.setObjectName("PageBody")
        self.board_layout = QVBoxLayout(self.board)
        self.board_layout.setContentsMargins(0, 0, 6, 0)
        self.board_layout.setSpacing(10)
        self.scroll.setWidget(self.board)
        body.addWidget(self.scroll, 1)
        self.drawer = QFrame()
        self.drawer.setProperty("card", True)
        self.drawer.setFixedWidth(348)
        self.drawer_layout = QVBoxLayout(self.drawer)
        self.drawer_layout.setContentsMargins(18, 16, 18, 16)
        self.drawer_layout.setSpacing(10)
        drawer_scroll = QScrollArea()
        drawer_scroll.setWidgetResizable(True)
        drawer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        drawer_scroll.setWidget(self.drawer)
        drawer_scroll.setFixedWidth(360)
        drawer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.drawer_scroll = drawer_scroll
        body.addWidget(drawer_scroll)
        L.addLayout(body, 1)
        self.legend = QHBoxLayout()
        self.legend.setSpacing(16)
        for state in (RoomState.AVAILABLE, RoomState.OCCUPIED, RoomState.RESERVED, RoomState.DUE_OUT,
                      RoomState.OVERDUE, RoomState.VACANT_DIRTY, RoomState.MAINTENANCE, RoomState.OUT_OF_SERVICE):
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {theme().accent(RoomState.TONES[state])}; border-radius: 5px;")
            self.legend.addWidget(dot)
            self.legend.addWidget(label(RoomState.LABELS[state], "faint"))
        self.legend.addStretch(1)
        L.addLayout(self.legend)

    def subtitle(self) -> str:
        if not self.items:
            return ""
        ready = sum(1 for i in self.items if i.state == RoomState.AVAILABLE)
        occ = sum(1 for i in self.items if matches(i, "occupied"))
        return f"{len(self.items)} rooms · {occ} occupied · {ready} ready to sell"

    def on_show(self, **kwargs) -> None:
        if kwargs.get("filter"):
            self.chips.set_current(kwargs["filter"])
        if kwargs.get("room_id"):
            self.selected = kwargs["room_id"]
            self._stale = True
        super().on_show(**kwargs)

    def refresh(self) -> None:
        current_type = self.type_filter.currentData()
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("All types", None)
        for t in self.ctx.rooms.list_types():
            self.type_filter.addItem(t.name, t.id)
        idx = self.type_filter.findData(current_type)
        self.type_filter.setCurrentIndex(max(idx, 0))
        self.type_filter.blockSignals(False)
        self.items = self.ctx.rooms.board()
        counts = {key: sum(1 for i in self.items if matches(i, key)) for _, key in FILTERS}
        for text, key in FILTERS:
            self.chips.set_label(key, f"{text}  {counts[key]}")
        self._render()
        self.app.page_subtitle.setText(self.subtitle()) if self.app.current_page() is self else None

    def _render(self) -> None:
        clear_layout(self.board_layout)
        key = self.chips.current() or "all"
        type_id = self.type_filter.currentData()
        text = self.search.text().strip().lower()
        shown = []
        for item in self.items:
            if not matches(item, key) or (type_id and item.room.room_type_id != type_id):
                continue
            if text:
                names = " ".join(r.guest_name for r in (item.in_house, item.arrival) if r).lower()
                if text not in item.room.number.lower() and text not in names:
                    continue
            shown.append(item)
        if not self.items:
            empty = EmptyState("bed", "No rooms yet", "Add your rooms in Settings › Rooms & rates to start "
                               "taking reservations.", "Add rooms" if self.ctx.can("rooms.manage") else None)
            empty.action.connect(lambda: self.app.navigate("settings", section="rooms"))
            self.board_layout.addWidget(empty)
        elif not shown:
            self.board_layout.addWidget(EmptyState("filter", "No rooms match", "Try another filter."))
        floors: OrderedDict[str, list[RoomBoardItem]] = OrderedDict()
        for item in shown:
            floors.setdefault(item.room.floor or "", []).append(item)
        for floor, items in floors.items():
            title = f"Floor {floor}" if floor else "Rooms"
            self.board_layout.addWidget(label(f"{title}  ·  {len(items)}", "overline"))
            host = QWidget()
            host.setObjectName("Transparent")
            flow = FlowLayout(host, spacing=12)
            for item in items:
                tile = RoomTile(item, self.fmt)
                tile.setProperty("selected", item.room.id == self.selected)
                tile.clicked.connect(self._select)
                tile.menu_requested.connect(self._tile_menu)
                flow.addWidget(tile)
            host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            self.board_layout.addWidget(host)
        self.board_layout.addStretch(1)
        if self.selected and not any(i.room.id == self.selected for i in self.items):
            self.selected = None
        self._render_drawer()

    def _select(self, room_id: int) -> None:
        self.selected = room_id
        for tile in self.board.findChildren(RoomTile):
            tile.setProperty("selected", tile.room_id == room_id)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        self._render_drawer()

    # -- detail drawer -----------------------------------------------------------------------------------
    def _clear_drawer(self) -> None:
        clear_layout(self.drawer_layout)

    def _fit_drawer(self) -> None:
        """Word-wrapped labels need height-for-width; size the drawer so it scrolls instead of squeezing."""
        width = self.drawer.width() or 350
        needed = self.drawer_layout.totalHeightForWidth(width)
        self.drawer.setMinimumHeight(max(needed, 0))

    def _render_drawer(self) -> None:
        self._clear_drawer()
        self.drawer.setMinimumHeight(0)
        D = self.drawer_layout
        item = next((i for i in self.items if i.room.id == self.selected), None)
        if item is None:
            D.addWidget(EmptyState("grid", "Select a room", "Click a room to see who is in it and what you can do.",
                                   compact=True))
            D.addStretch(1)
            return
        room, fmt, can = item.room, self.fmt, self.ctx.can
        head = QHBoxLayout()
        head.addWidget(label(f"Room {room.number}", "h2"))
        head.addStretch(1)
        head.addWidget(icon_button("x", "Close", lambda: self._select(0), size=15))
        D.addLayout(head)
        D.addWidget(label(f"{room.type_name} · {room.effective_beds or 'beds n/a'} · sleeps {room.capacity}",
                          "muted", wrap=True))
        badges = QHBoxLayout()
        badges.setSpacing(6)
        badges.addWidget(Badge(RoomState.LABELS[item.state], RoomState.TONES[item.state]))
        badges.addWidget(Badge(HKStatus.LABELS[room.hk_status], HKStatus.TONES[room.hk_status]))
        badges.addStretch(1)
        D.addLayout(badges)
        if "conflict" in item.flags:
            D.addWidget(Banner("A reservation is assigned to this room while it is out of order.", "error"))
        if "arrival_blocked" in item.flags:
            D.addWidget(Banner("The arriving guest cannot check in until the current guest checks out.", "warning"))
        if room.service_status != ServiceStatus.IN_SERVICE:
            D.addWidget(Banner(f"{ServiceStatus.LABELS[room.service_status]}: {room.service_reason or 'no reason'}"
                               + (f" (until {fmt.date(room.service_until)})" if room.service_until else ""), "warning"))
        res = item.in_house
        if res:
            D.addWidget(Divider())
            D.addWidget(label("IN HOUSE", "overline"))
            D.addWidget(label(res.guest_name, "h3"))
            grid = KeyValueGrid()
            grid.add("dates", "Stay", f"{fmt.short_date(res.check_in_date)} → {fmt.short_date(res.check_out_date)}")
            grid.add("bal", "Balance", fmt.money(res.balance))
            grid.add("conf", "Reservation", res.confirmation_no)
            D.addWidget(grid)
            row = QHBoxLayout()
            row.addWidget(button("Open", "book", small=True, on_click=lambda: self.actions.open_reservation(res.id)))
            if can("reservations.checkout"):
                row.addWidget(button("Check out", "log-out", "primary", small=True,
                                     on_click=lambda: self.actions.check_out(res.id)))
            if can("billing.payment"):
                row.addWidget(button("Payment", "dollar", small=True,
                                     on_click=lambda: self.actions.take_payment(res.id)))
            row.addStretch(1)
            D.addLayout(row)
        if item.arrival:
            arr = item.arrival
            D.addWidget(Divider())
            D.addWidget(label("ARRIVING TODAY" if arr.check_in_date == self.ctx.clock.today() else "LATE ARRIVAL",
                              "overline"))
            D.addWidget(label(arr.guest_name, "h3"))
            D.addWidget(label(f"{arr.confirmation_no} · {arr.nights} night(s)"
                              + (f" · ETA {fmt.time(arr.expected_arrival)}" if arr.expected_arrival else ""),
                              "muted"))
            row = QHBoxLayout()
            row.addWidget(button("Open", "book", small=True, on_click=lambda: self.actions.open_reservation(arr.id)))
            if can("reservations.checkin"):
                row.addWidget(button("Check in", "log-in", "primary", small=True,
                                     on_click=lambda: self.actions.check_in(arr.id)))
            row.addStretch(1)
            D.addLayout(row)
        if item.next_reservation and not item.arrival:
            nxt = item.next_reservation
            D.addWidget(Divider())
            D.addWidget(label("NEXT RESERVATION", "overline"))
            link = button(f"{nxt.guest_name} · {fmt.relative_day(nxt.check_in_date)}", variant="link",
                          on_click=lambda: self.actions.open_reservation(nxt.id))
            D.addWidget(link)
        D.addWidget(Divider())
        D.addWidget(label("ACTIONS", "overline"))
        sellable = room.service_status == ServiceStatus.IN_SERVICE and not res
        if sellable and can("reservations.create"):
            D.addWidget(button("New reservation for this room", "calendar", "soft",
                               on_click=lambda: self.actions.new_reservation(room_id=room.id)))
            if can("reservations.checkin") and not item.arrival:
                D.addWidget(button("Walk-in to this room", "log-in",
                                   on_click=lambda: self.actions.walk_in(room_id=room.id)))
        hk = QHBoxLayout()
        hk.setSpacing(6)
        if can("housekeeping.work") or can("housekeeping.manage"):
            if room.hk_status != HKStatus.DIRTY:
                hk.addWidget(button("Mark dirty", small=True, on_click=lambda: self._set_hk(HKStatus.DIRTY)))
            if room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING):
                hk.addWidget(button("Mark clean", "check", small=True, on_click=lambda: self._set_hk(HKStatus.CLEAN)))
        if can("housekeeping.inspect") and room.hk_status != HKStatus.INSPECTED:
            hk.addWidget(button("Inspected", "check-circle", small=True,
                                on_click=lambda: self._set_hk(HKStatus.INSPECTED)))
        hk.addStretch(1)
        D.addLayout(hk)
        if can("maintenance.report"):
            D.addWidget(button("Report maintenance issue", "tool", on_click=lambda: self.actions.new_ticket(room.id)))
        if can("rooms.status"):
            if room.service_status == ServiceStatus.IN_SERVICE:
                b = button("Take out of order", "slash", "danger-outline",
                           on_click=lambda: self.actions.take_out_of_order(room.id))
                b.setEnabled(not res)
                if res:
                    b.setToolTip("Move the guest to another room first.")
                D.addWidget(b)
            else:
                D.addWidget(button("Return to service", "check-circle", "primary", on_click=self._return_to_service))
        if can("rooms.manage"):
            D.addWidget(button("Edit room details", "edit", "ghost", on_click=self._edit_room))
        history = self.ctx.rooms.status_history(room.id)[:6]
        if history:
            D.addWidget(Divider())
            D.addWidget(label("RECENT STATUS CHANGES", "overline"))
            for h in history:
                field = "Housekeeping" if h["field"] == "hk_status" else "Service"
                new = HKStatus.LABELS.get(h["new_value"]) or ServiceStatus.LABELS.get(h["new_value"], h["new_value"])
                D.addWidget(label(f"{h['ts'][5:16]} · {field}: {new} · {h['user_name']}", "faint", wrap=True))
        D.addStretch(1)
        self._fit_drawer()

    def _tile_menu(self, room_id: int, pos) -> None:
        self._select(room_id)
        item = next((i for i in self.items if i.room.id == room_id), None)
        if not item:
            return
        menu = QMenu(self)
        can = self.ctx.can
        if item.in_house:
            menu.addAction("Open reservation", lambda: self.actions.open_reservation(item.in_house.id))
            if can("reservations.checkout"):
                menu.addAction("Check out…", lambda: self.actions.check_out(item.in_house.id))
        if item.arrival and can("reservations.checkin"):
            menu.addAction(f"Check in {item.arrival.guest_name}…", lambda: self.actions.check_in(item.arrival.id))
        if item.room.service_status == ServiceStatus.IN_SERVICE and not item.in_house and can("reservations.create"):
            menu.addAction("New reservation…", lambda: self.actions.new_reservation(room_id=room_id))
        menu.addSeparator()
        if can("housekeeping.work") or can("housekeeping.manage"):
            menu.addAction("Mark dirty", lambda: self._set_hk(HKStatus.DIRTY))
            menu.addAction("Mark clean", lambda: self._set_hk(HKStatus.CLEAN))
        if can("housekeeping.inspect"):
            menu.addAction("Mark inspected", lambda: self._set_hk(HKStatus.INSPECTED))
        if can("maintenance.report"):
            menu.addAction("Report maintenance issue…", lambda: self.actions.new_ticket(room_id))
        menu.exec(pos)

    def _set_hk(self, status: str) -> None:
        room_id = self.selected
        if room_id and guarded(self, lambda: self.ctx.housekeeping.set_room_status(room_id, status),
                               f"Room marked {HKStatus.LABELS[status].lower()}", self.app.toast):
            self.mark_stale()

    def _return_to_service(self) -> None:
        room = self.ctx.rooms.get(self.selected)
        if confirm(self, "Return to service", f"Return room {room.number} to service? It will be marked dirty so "
                   "housekeeping can prepare it.", "Return to service"):
            guarded(self, lambda: self.ctx.rooms.set_service_status(room.id, ServiceStatus.IN_SERVICE, ""),
                    f"Room {room.number} is back in service", self.app.toast)

    def _edit_room(self) -> None:
        from motelmg.ui.dialogs.property import RoomDialog
        RoomDialog(self, self.app, self.selected).exec()


__all__ = ["RoomsPage", "TaskType"]
