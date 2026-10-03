"""Computed operational alerts (never stale: derived from current data).

Alerts are grouped by category; each category can be switched off in the
notification settings, and individual alerts can be dismissed for the day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from motelmg.core.enums import HKStatus, Priority, TicketStatus
from motelmg.core.dates import parse_datetime

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class Alert:
    key: str
    severity: str
    category: str
    title: str
    message: str
    target: str = ""  # reservation | room | maintenance | housekeeping | billing | backup | settings
    target_id: int | None = None


def _time_label(value: str) -> str:
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return value


class AlertService:
    def __init__(self, ctx):
        self.ctx = ctx

    def _enabled(self, category: str) -> bool:
        return self.ctx.settings.get_bool(f"notify.{category}")

    def current(self, include_dismissed: bool = False) -> list[Alert]:
        if self.ctx.session is None:
            return []
        alerts: list[Alert] = []
        builders = [
            ("overdue", self._overdue), ("conflicts", self._conflicts), ("arrivals", self._arrivals),
            ("departures", self._departures), ("no_shows", self._no_shows), ("balances", self._balances),
            ("housekeeping", self._housekeeping), ("maintenance", self._maintenance), ("system", self._system),
        ]
        for category, builder in builders:
            if self._enabled(category):
                alerts.extend(builder())
        if not include_dismissed:
            dismissed = self.ctx.repo_notify.dismissed_keys(self.ctx.session.user_id, self.ctx.clock.today())
            alerts = [a for a in alerts if a.key not in dismissed]
        alerts.sort(key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), a.category))
        return alerts

    def dismiss(self, key: str) -> None:
        if self.ctx.session:
            with self.ctx.db.transaction():
                self.ctx.repo_notify.dismiss(key, self.ctx.session.user_id, self.ctx.clock.today())
                self.ctx.repo_notify.purge_old_dismissals(self.ctx.clock.today() - timedelta(days=7))
            self.ctx.events.emit("alerts")

    def restore_dismissed(self) -> None:
        if self.ctx.session:
            with self.ctx.db.transaction():
                self.ctx.repo_notify.clear_dismissals(self.ctx.session.user_id, self.ctx.clock.today())
            self.ctx.events.emit("alerts")

    # -- system notifications (persisted events) ---------------------------------------
    def notify(self, title: str, message: str = "", level: str = "info", category: str = "system") -> None:
        with self.ctx.db.transaction():
            self.ctx.repo_notify.add(self.ctx.clock.now(), level, category, title, message)
        self.ctx.events.emit("alerts")

    def notifications(self, limit: int = 30):
        return self.ctx.repo_notify.recent(limit)

    def mark_notifications_read(self) -> None:
        with self.ctx.db.transaction():
            self.ctx.repo_notify.mark_read()
        self.ctx.events.emit("alerts")

    # -- builders --------------------------------------------------------------------------
    def _overdue(self) -> list[Alert]:
        result = []
        co_time = self.ctx.settings.check_out_time()
        for res in self.ctx.repo_res.in_house():
            if self.ctx.reservations.is_overdue(res):
                when = res.check_out_date.strftime("%b %d") if res.check_out_date < self.ctx.clock.today() else \
                    _time_label(res.late_checkout_until or co_time.strftime("%H:%M"))
                result.append(Alert(f"overdue:{res.id}", "critical", "overdue", f"Overdue check-out · Room "
                                    f"{res.room_number}", f"{res.guest_name} was due out {when}.",
                                    "reservation", res.id))
        return result

    def _conflicts(self) -> list[Alert]:
        result = []
        today = self.ctx.clock.today()
        for room, row in self.ctx.rooms.conflicting_reservations():
            status = "archived" if not room.is_active else "out of service"
            result.append(Alert(
                f"conflict:{row['id']}", "critical", "conflicts", f"Booking conflict · Room {room.number}",
                f"{row['guest_name']} ({row['confirmation_no']}) arrives {row['check_in_date']} but the room is "
                f"{status}. Move the reservation to another room.", "reservation", row["id"]))
        in_house = {r.room_id: r for r in self.ctx.repo_res.in_house()}
        for res in self.ctx.repo_res.arrivals_pending(today):
            occupant = in_house.get(res.room_id)
            if occupant and occupant.id != res.id:
                result.append(Alert(
                    f"blocked:{res.id}", "critical", "conflicts", f"Room {res.room_number} not free for arrival",
                    f"{res.guest_name} arrives today but {occupant.guest_name} is still in the room.",
                    "reservation", res.id))
        return result

    def _arrivals(self) -> list[Alert]:
        now = self.ctx.clock.now()
        today = now.date()
        window = self.ctx.settings.get_int("notify.arrival_window_hours")
        pending = [r for r in self.ctx.repo_res.arrivals_pending(today) if r.check_in_date == today]
        result = []
        if pending:
            result.append(Alert(f"arrivals:{today}", "info", "arrivals", f"{len(pending)} arrival(s) still expected",
                                ", ".join(f"{r.guest_name} (Rm {r.room_number})" for r in pending[:4])
                                + (" …" if len(pending) > 4 else ""), "arrivals"))
        for res in pending:
            if not res.expected_arrival or not window:
                continue
            try:
                eta = datetime.combine(today, datetime.strptime(res.expected_arrival, "%H:%M").time())
            except ValueError:
                continue
            if now <= eta <= now + timedelta(hours=window):
                result.append(Alert(f"eta:{res.id}", "info", "arrivals", f"Arriving soon · Room {res.room_number}",
                                    f"{res.guest_name} expected around {_time_label(res.expected_arrival)}.",
                                    "reservation", res.id))
            elif eta < now - timedelta(hours=1):
                result.append(Alert(f"late:{res.id}", "warning", "arrivals", f"Late arrival · Room {res.room_number}",
                                    f"{res.guest_name} was expected at {_time_label(res.expected_arrival)}.",
                                    "reservation", res.id))
        return result

    def _departures(self) -> list[Alert]:
        today = self.ctx.clock.today()
        due = [r for r in self.ctx.repo_res.in_house() if r.check_out_date == today
               and not self.ctx.reservations.is_overdue(r)]
        if not due:
            return []
        return [Alert(f"departures:{today}", "info", "departures", f"{len(due)} departure(s) today",
                      ", ".join(f"Rm {r.room_number} {r.guest_name}" for r in due[:4]) + (" …" if len(due) > 4 else ""),
                      "departures")]

    def _no_shows(self) -> list[Alert]:
        today = self.ctx.clock.today()
        return [Alert(f"noshow:{r.id}", "warning", "no_shows", f"Possible no-show · {r.confirmation_no}",
                      f"{r.guest_name} was due {r.check_in_date:%b %d} (room {r.room_number}). Check in or mark as "
                      "no-show to release the room.", "reservation", r.id)
                for r in self.ctx.repo_res.stale_confirmed(today)]

    def _balances(self) -> list[Alert]:
        money = self.ctx.settings.money
        threshold = max(self.ctx.settings.get_int("notify.balance_threshold") * 100, 1)
        today = self.ctx.clock.today()
        result = []
        open_folios = []
        for row in self.ctx.repo_folio.balances(threshold):
            balance = row["total"] - row["paid"]
            if row["status"] == "checked_in":
                if row["check_out_date"] <= today.isoformat():
                    result.append(Alert(f"due:{row['id']}", "warning", "balances",
                                        f"Balance due · Room {row['room_number']}",
                                        f"{row['guest_name']} departs today and owes {money(balance)}.",
                                        "reservation", row["id"]))
            else:
                open_folios.append((row, balance))
        if open_folios:
            total = sum(b for _, b in open_folios)
            result.append(Alert("receivables", "warning", "balances", f"{len(open_folios)} unpaid folio(s)",
                                f"Closed stays owe {money(total)} in total.", "billing"))
        for row in self.ctx.repo_folio.credits():
            result.append(Alert(f"credit:{row['id']}", "warning", "balances", f"Refund due · {row['confirmation_no']}",
                                f"{row['guest_name']} has a credit of {money(row['paid'] - row['total'])}.",
                                "reservation", row["id"]))
        return result

    def _housekeeping(self) -> list[Alert]:
        today = self.ctx.clock.today()
        rooms = {r.id: r for r in self.ctx.repo_rooms.list_rooms()}
        result = []
        arrival_rooms = set()
        for res in self.ctx.repo_res.arrivals_pending(today):
            room = rooms.get(res.room_id)
            arrival_rooms.add(res.room_id)
            if room and room.hk_status in (HKStatus.DIRTY, HKStatus.CLEANING):
                result.append(Alert(f"hkarrival:{room.id}", "warning", "housekeeping",
                                    f"Room {room.number} not ready", f"{res.guest_name} arrives today; the room is "
                                    f"{HKStatus.LABELS[room.hk_status].lower()}.", "room", room.id))
        dirty = [r for r in rooms.values() if r.hk_status == HKStatus.DIRTY and r.id not in arrival_rooms]
        if dirty:
            result.append(Alert(f"dirty:{today}", "info", "housekeeping", f"{len(dirty)} room(s) need cleaning",
                                ", ".join(r.number for r in dirty[:10]) + (" …" if len(dirty) > 10 else ""),
                                "housekeeping"))
        return result

    def _maintenance(self) -> list[Alert]:
        result = []
        for ticket in self.ctx.repo_maint.search(statuses=TicketStatus.ACTIVE):
            if ticket.priority == Priority.URGENT:
                result.append(Alert(f"ticket:{ticket.id}", "critical", "maintenance",
                                    f"Urgent maintenance · {ticket.where}", f"#{ticket.id} {ticket.title}",
                                    "maintenance", ticket.id))
        blocked = [r for r in self.ctx.repo_rooms.list_rooms() if r.service_status != "in_service"]
        if blocked:
            result.append(Alert("blocked_rooms", "info", "maintenance", f"{len(blocked)} room(s) out of order",
                                ", ".join(f"{r.number}" for r in blocked[:10]), "maintenance"))
        return result

    def _system(self) -> list[Alert]:
        result = []
        for row in self.ctx.repo_notify.recent(10, unread_only=True):
            result.append(Alert(f"notification:{row['id']}", row["level"], "system", row["title"], row["message"],
                                "notification", row["id"]))
        if self.ctx.can("backup.manage"):
            last = parse_datetime(self.ctx.settings.get_str("backup.last_at"))
            if last is None or (self.ctx.clock.now() - last) > timedelta(days=7):
                result.append(Alert("backup_old", "warning", "system", "No recent backup",
                                    "The database has not been backed up in over a week." if last else
                                    "No backup has been made yet.", "backup"))
        return result
