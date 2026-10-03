"""Reports and analytics.

Every report returns a :class:`ReportResult` - a title, column definitions,
rows, optional totals, summary figures and chart data - which the UI renders
as KPI tiles, a chart and a sortable table, and the exporter turns into CSV,
PDF or a printout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from motelmg.core.dates import iter_days, month_bounds
from motelmg.core.enums import (PaymentKind, Priority, ReservationSource, ReservationStatus, TaskStatus, TaskType,
                                TicketCategory, TicketStatus)


@dataclass
class ReportColumn:
    key: str
    title: str
    kind: str = "text"  # text | money | int | percent | date | datetime | float


@dataclass
class ReportResult:
    title: str
    subtitle: str
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None = None
    summary: list[tuple[str, str]] = field(default_factory=list)  # (label, formatted value)
    chart: dict[str, Any] | None = None  # {"type": "bar"|"line", "labels": [...], "series": [(name, [...])], "kind"}


@dataclass
class ReportDef:
    key: str
    title: str
    group: str
    description: str
    params: str  # range | month | year | none
    permission: str
    builder: Callable[..., ReportResult]


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


class ReportService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.catalog: list[ReportDef] = [
            ReportDef("daily_revenue", "Daily revenue", "Financial",
                      "Room and other revenue, taxes and payments collected for each day.", "range",
                      "reports.financial", self.daily_revenue),
            ReportDef("monthly_revenue", "Monthly revenue", "Financial",
                      "Revenue, occupancy, ADR and RevPAR month by month.", "year", "reports.financial",
                      self.monthly_revenue),
            ReportDef("payments", "Payment history", "Financial",
                      "Every payment, deposit and refund with totals by method.", "range", "reports.financial",
                      self.payment_history),
            ReportDef("outstanding", "Outstanding balances", "Financial",
                      "Folios with money owed by guests.", "none", "reports.financial", self.outstanding_balances),
            ReportDef("occupancy", "Occupancy", "Operations",
                      "Rooms sold, occupancy rate, ADR and RevPAR per day.", "range", "reports.view", self.occupancy),
            ReportDef("room_utilization", "Room utilization", "Operations",
                      "Nights sold, occupancy and revenue for each room.", "range", "reports.view",
                      self.room_utilization),
            ReportDef("arrivals_departures", "Arrivals & departures", "Operations",
                      "Guests arriving and departing in the period.", "range", "reports.view",
                      self.arrivals_departures),
            ReportDef("cancellations", "Cancellations & no-shows", "Operations",
                      "Cancellation and no-show counts, rates and lost revenue.", "range", "reports.view",
                      self.cancellations),
            ReportDef("guest_history", "Guest history", "Guests",
                      "Guests who stayed in the period with nights and spend.", "range", "reports.view",
                      self.guest_history),
            ReportDef("sources", "Booking sources", "Guests",
                      "Where reservations came from.", "range", "reports.view", self.booking_sources),
            ReportDef("maintenance", "Maintenance", "Property",
                      "Tickets opened and resolved, by category, with costs.", "range", "reports.view",
                      self.maintenance_report),
            ReportDef("housekeeping", "Housekeeping", "Property",
                      "Cleaning tasks completed per staff member and average times.", "range", "reports.view",
                      self.housekeeping_report),
        ]

    def available(self) -> list[ReportDef]:
        return [r for r in self.catalog if self.ctx.can(r.permission)]

    def run(self, key: str, **params) -> ReportResult:
        report = next((r for r in self.catalog if r.key == key), None)
        if report is None:
            raise KeyError(key)
        self.ctx.require(report.permission)
        return report.builder(**params)

    # -- shared helpers ------------------------------------------------------------------
    def _money(self, cents: int) -> str:
        return self.ctx.settings.money(cents)

    def _room_count(self) -> int:
        return max(self.ctx.repo_rooms.count_active_rooms(), 0)

    def _revenue_by_day(self, start: date, end: date) -> dict[str, dict[str, int]]:
        rows = self.ctx.db.query(
            "SELECT c.service_date AS d, "
            "SUM(CASE WHEN c.kind IN ('room', 'discount') THEN c.amount ELSE 0 END) AS room, "
            "SUM(CASE WHEN c.kind IN ('fee', 'extra', 'adjustment') THEN c.amount ELSE 0 END) AS other, "
            "SUM(CASE WHEN c.kind = 'discount' THEN c.amount ELSE 0 END) AS discounts, "
            "SUM(CASE WHEN c.kind = 'tax' THEN c.amount ELSE 0 END) AS tax "
            "FROM charges c WHERE c.is_void = 0 AND c.service_date BETWEEN ? AND ? GROUP BY c.service_date",
            (start.isoformat(), end.isoformat()))
        return {r["d"]: dict(room=r["room"], other=r["other"], discounts=r["discounts"], tax=r["tax"]) for r in rows}

    def _payments_by_day(self, start: date, end: date) -> dict[str, int]:
        rows = self.ctx.db.query(
            "SELECT substr(created_at, 1, 10) AS d, SUM(CASE WHEN kind = 'refund' THEN -amount ELSE amount END) AS net "
            "FROM payments WHERE is_void = 0 AND created_at >= ? AND created_at < date(?, '+1 day') GROUP BY d",
            (start.isoformat(), end.isoformat()))
        return {r["d"]: r["net"] for r in rows}

    def _sold_by_day(self, start: date, end: date) -> dict[str, int]:
        """Room nights sold per day (in-house/checked-out stays, plus confirmed for future dates)."""
        today = self.ctx.clock.today().isoformat()
        result: dict[str, int] = {}
        rows = self.ctx.db.query(
            "SELECT check_in_date, check_out_date, status FROM reservations "
            "WHERE status IN ('confirmed', 'checked_in', 'checked_out') AND check_in_date <= ? AND check_out_date > ?",
            (end.isoformat(), start.isoformat()))
        for row in rows:
            d = max(date.fromisoformat(row["check_in_date"]), start)
            stop = min(date.fromisoformat(row["check_out_date"]), end + timedelta(days=1))
            while d < stop:
                key = d.isoformat()
                if row["status"] != "confirmed" or key >= today:
                    result[key] = result.get(key, 0) + 1
                d += timedelta(days=1)
        return result

    # -- financial --------------------------------------------------------------------------
    def daily_revenue(self, start: date, end: date) -> ReportResult:
        revenue = self._revenue_by_day(start, end)
        payments = self._payments_by_day(start, end)
        sold = self._sold_by_day(start, end)
        rows = []
        for d in iter_days(start, end):
            key = d.isoformat()
            r = revenue.get(key, {"room": 0, "other": 0, "discounts": 0, "tax": 0})
            rows.append({"date": d, "rooms_sold": sold.get(key, 0), "room": r["room"], "other": r["other"],
                         "discounts": r["discounts"], "tax": r["tax"], "total": r["room"] + r["other"] + r["tax"],
                         "collected": payments.get(key, 0)})
        totals = {k: sum(row[k] for row in rows) for k in ("rooms_sold", "room", "other", "discounts", "tax", "total",
                                                           "collected")}
        totals["date"] = "Total"
        days = max(len(rows), 1)
        return ReportResult(
            "Daily revenue", f"{start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("date", "Date", "date"), ReportColumn("rooms_sold", "Rooms sold", "int"),
             ReportColumn("room", "Room revenue", "money"), ReportColumn("other", "Other revenue", "money"),
             ReportColumn("discounts", "Discounts", "money"), ReportColumn("tax", "Taxes", "money"),
             ReportColumn("total", "Total", "money"), ReportColumn("collected", "Payments collected", "money")],
            rows, totals,
            summary=[("Total revenue", self._money(totals["total"])), ("Room revenue", self._money(totals["room"])),
                     ("Average per day", self._money(totals["total"] // days)),
                     ("Payments collected", self._money(totals["collected"]))],
            chart={"type": "bar", "kind": "money", "labels": [r["date"].strftime("%b %d") for r in rows],
                   "series": [("Room", [r["room"] for r in rows]), ("Other", [r["other"] for r in rows])]})

    def monthly_revenue(self, year: int) -> ReportResult:
        rooms = self._room_count()
        rows = []
        for month in range(1, 13):
            first, last = month_bounds(year, month)
            revenue = self._revenue_by_day(first, last)
            sold = sum(self._sold_by_day(first, last).values())
            room = sum(r["room"] for r in revenue.values())
            other = sum(r["other"] for r in revenue.values())
            tax = sum(r["tax"] for r in revenue.values())
            available = rooms * last.day
            rows.append({"month": first.strftime("%B"), "nights": sold, "occupancy": _pct(sold, available),
                         "room": room, "other": other, "tax": tax, "total": room + other + tax,
                         "adr": room // sold if sold else 0, "revpar": room // available if available else 0,
                         "collected": sum(self._payments_by_day(first, last).values())})
        tot_nights = sum(r["nights"] for r in rows)
        tot_room = sum(r["room"] for r in rows)
        available = rooms * (366 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 365)
        totals = {"month": "Year", "nights": tot_nights, "occupancy": _pct(tot_nights, available), "room": tot_room,
                  "other": sum(r["other"] for r in rows), "tax": sum(r["tax"] for r in rows),
                  "total": sum(r["total"] for r in rows), "adr": tot_room // tot_nights if tot_nights else 0,
                  "revpar": tot_room // available if available else 0,
                  "collected": sum(r["collected"] for r in rows)}
        return ReportResult(
            "Monthly revenue", str(year),
            [ReportColumn("month", "Month"), ReportColumn("nights", "Room nights", "int"),
             ReportColumn("occupancy", "Occupancy", "percent"), ReportColumn("room", "Room revenue", "money"),
             ReportColumn("other", "Other revenue", "money"), ReportColumn("tax", "Taxes", "money"),
             ReportColumn("total", "Total", "money"), ReportColumn("adr", "ADR", "money"),
             ReportColumn("revpar", "RevPAR", "money"), ReportColumn("collected", "Collected", "money")],
            rows, totals,
            summary=[("Total revenue", self._money(totals["total"])), ("Occupancy", f"{totals['occupancy']}%"),
                     ("ADR", self._money(totals["adr"])), ("RevPAR", self._money(totals["revpar"]))],
            chart={"type": "bar", "kind": "money", "labels": [r["month"][:3] for r in rows],
                   "series": [("Room", [r["room"] for r in rows]), ("Other", [r["other"] for r in rows])]})

    def payment_history(self, start: date, end: date) -> ReportResult:
        payments = self.ctx.repo_folio.search_payments(start=start, end=end, include_void=True)
        rows = []
        by_method: dict[str, int] = {}
        for p in sorted(payments, key=lambda p: (p.created_at, p.id)):
            signed = 0 if p.is_void else p.signed_amount
            rows.append({"date": p.created_at, "receipt": p.receipt_no, "type": PaymentKind.LABELS[p.kind]
                         + (" (void)" if p.is_void else ""), "guest": p.guest_name, "reservation": p.confirmation_no,
                         "method": p.method_name, "reference": p.reference, "amount": signed,
                         "user": p.created_by_name})
            if not p.is_void:
                by_method[p.method_name] = by_method.get(p.method_name, 0) + signed
        total = sum(r["amount"] for r in rows)
        refunds = sum(p.amount for p in payments if p.kind == "refund" and not p.is_void)
        summary = [("Net collected", self._money(total)), ("Transactions", str(len(rows))),
                   ("Refunds", self._money(refunds))]
        summary += [(m, self._money(a)) for m, a in sorted(by_method.items(), key=lambda kv: -kv[1])[:3]]
        return ReportResult(
            "Payment history", f"{start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("date", "Date / time", "datetime"), ReportColumn("receipt", "Receipt"),
             ReportColumn("type", "Type"), ReportColumn("guest", "Guest"), ReportColumn("reservation", "Reservation"),
             ReportColumn("method", "Method"), ReportColumn("reference", "Reference"),
             ReportColumn("amount", "Amount", "money"), ReportColumn("user", "Taken by")],
            rows, {"date": "Total", "amount": total}, summary=summary,
            chart={"type": "hbar", "kind": "money", "labels": list(by_method),
                   "series": [("Amount", list(by_method.values()))]} if by_method else None)

    def outstanding_balances(self) -> ReportResult:
        today = self.ctx.clock.today()
        rows = []
        for r in self.ctx.repo_folio.balances(1):
            rows.append({"reservation": r["confirmation_no"], "guest": r["guest_name"], "phone": r["phone"],
                         "room": r["room_number"], "status": ReservationStatus.LABELS[r["status"]],
                         "departure": date.fromisoformat(r["check_out_date"]), "total": r["total"], "paid": r["paid"],
                         "balance": r["total"] - r["paid"],
                         "age": (today - date.fromisoformat(r["check_out_date"])).days if r["status"] != "checked_in"
                         else 0, "_id": r["id"]})
        total = sum(r["balance"] for r in rows)
        return ReportResult(
            "Outstanding balances", f"As of {today:%b %d, %Y}",
            [ReportColumn("reservation", "Reservation"), ReportColumn("guest", "Guest"), ReportColumn("phone", "Phone"),
             ReportColumn("room", "Room"), ReportColumn("status", "Status"), ReportColumn("departure", "Departure", "date"),
             ReportColumn("total", "Charges", "money"), ReportColumn("paid", "Paid", "money"),
             ReportColumn("balance", "Balance", "money"), ReportColumn("age", "Days since departure", "int")],
            rows, {"reservation": "Total", "balance": total, "total": sum(r["total"] for r in rows),
                   "paid": sum(r["paid"] for r in rows)},
            summary=[("Total owed", self._money(total)), ("Folios", str(len(rows))),
                     ("In house", str(sum(1 for r in rows if r["status"] == "In house")))])

    # -- operations -----------------------------------------------------------------------------
    def occupancy(self, start: date, end: date) -> ReportResult:
        rooms = self._room_count()
        sold = self._sold_by_day(start, end)
        revenue = self._revenue_by_day(start, end)
        oos_rows = self.ctx.db.query("SELECT COUNT(*) FROM rooms WHERE is_active = 1 AND service_status <> 'in_service'")
        today = self.ctx.clock.today()
        rows = []
        for d in iter_days(start, end):
            key = d.isoformat()
            n = sold.get(key, 0)
            room_rev = revenue.get(key, {}).get("room", 0)
            rows.append({"date": d, "available": rooms, "sold": n, "vacant": max(rooms - n, 0),
                         "occupancy": _pct(n, rooms), "adr": room_rev // n if n else 0,
                         "revpar": room_rev // rooms if rooms else 0, "room": room_rev,
                         "forecast": "Forecast" if d > today else ""})
        total_sold = sum(r["sold"] for r in rows)
        total_avail = rooms * len(rows)
        total_rev = sum(r["room"] for r in rows)
        return ReportResult(
            "Occupancy", f"{start:%b %d, %Y} – {end:%b %d, %Y} · {rooms} rooms"
            + (f" ({oos_rows[0][0]} currently out of order)" if oos_rows and oos_rows[0][0] else ""),
            [ReportColumn("date", "Date", "date"), ReportColumn("available", "Rooms", "int"),
             ReportColumn("sold", "Occupied", "int"), ReportColumn("vacant", "Vacant", "int"),
             ReportColumn("occupancy", "Occupancy", "percent"), ReportColumn("adr", "ADR", "money"),
             ReportColumn("revpar", "RevPAR", "money"), ReportColumn("room", "Room revenue", "money"),
             ReportColumn("forecast", "")],
            rows, {"date": "Total", "available": total_avail, "sold": total_sold,
                   "vacant": total_avail - total_sold, "occupancy": _pct(total_sold, total_avail),
                   "adr": total_rev // total_sold if total_sold else 0,
                   "revpar": total_rev // total_avail if total_avail else 0, "room": total_rev},
            summary=[("Average occupancy", f"{_pct(total_sold, total_avail)}%"), ("Room nights sold", str(total_sold)),
                     ("ADR", self._money(total_rev // total_sold if total_sold else 0)),
                     ("RevPAR", self._money(total_rev // total_avail if total_avail else 0))],
            chart={"type": "line", "kind": "percent", "labels": [r["date"].strftime("%b %d") for r in rows],
                   "series": [("Occupancy %", [r["occupancy"] for r in rows])]})

    def room_utilization(self, start: date, end: date) -> ReportResult:
        days = (end - start).days + 1
        stats: dict[int, dict[str, int]] = {}
        for row in self.ctx.db.query(
                "SELECT c.room_id, COUNT(*) AS nights, SUM(c.amount) AS revenue FROM charges c "
                "WHERE c.kind = 'room' AND c.is_void = 0 AND c.service_date BETWEEN ? AND ? GROUP BY c.room_id",
                (start.isoformat(), end.isoformat())):
            stats[row["room_id"]] = {"nights": row["nights"], "revenue": row["revenue"]}
        tickets = {r[0]: r[1] for r in self.ctx.db.query(
            "SELECT room_id, COUNT(*) FROM maintenance_tickets WHERE room_id IS NOT NULL AND created_at >= ? "
            "AND created_at < date(?, '+1 day') GROUP BY room_id", (start.isoformat(), end.isoformat()))}
        rows = []
        for room in self.ctx.repo_rooms.list_rooms():
            s = stats.get(room.id, {"nights": 0, "revenue": 0})
            rows.append({"room": room.number, "type": room.type_name, "nights": s["nights"],
                         "occupancy": _pct(s["nights"], days), "revenue": s["revenue"],
                         "avg_rate": s["revenue"] // s["nights"] if s["nights"] else 0,
                         "tickets": tickets.get(room.id, 0)})
        total_nights = sum(r["nights"] for r in rows)
        total_rev = sum(r["revenue"] for r in rows)
        top = sorted(rows, key=lambda r: -r["nights"])
        return ReportResult(
            "Room utilization", f"{start:%b %d, %Y} – {end:%b %d, %Y} ({days} days)",
            [ReportColumn("room", "Room"), ReportColumn("type", "Type"), ReportColumn("nights", "Nights sold", "int"),
             ReportColumn("occupancy", "Occupancy", "percent"), ReportColumn("revenue", "Room revenue", "money"),
             ReportColumn("avg_rate", "Average rate", "money"), ReportColumn("tickets", "Maintenance tickets", "int")],
            rows, {"room": "Total", "nights": total_nights,
                   "occupancy": _pct(total_nights, days * max(len(rows), 1)), "revenue": total_rev,
                   "avg_rate": total_rev // total_nights if total_nights else 0,
                   "tickets": sum(r["tickets"] for r in rows)},
            summary=[("Room nights", str(total_nights)), ("Room revenue", self._money(total_rev)),
                     ("Busiest room", top[0]["room"] if top and top[0]["nights"] else "—"),
                     ("Least used", top[-1]["room"] if top else "—")],
            chart={"type": "bar", "kind": "int", "labels": [r["room"] for r in rows],
                   "series": [("Nights", [r["nights"] for r in rows])]})

    def arrivals_departures(self, start: date, end: date) -> ReportResult:
        rows = []
        for res in self.ctx.repo_res.search(arrival_from=start, arrival_to=end,
                                            statuses=["confirmed", "checked_in", "checked_out", "no_show"],
                                            order="r.check_in_date"):
            rows.append({"date": res.check_in_date, "movement": "Arrival", "reservation": res.confirmation_no,
                         "guest": res.guest_name, "room": res.room_number, "nights": res.nights,
                         "status": ReservationStatus.LABELS[res.status],
                         "actual": res.actual_check_in, "_id": res.id})
        for res in self.ctx.repo_res.search(departure_from=start, departure_to=end,
                                            statuses=["confirmed", "checked_in", "checked_out"],
                                            order="r.check_out_date"):
            rows.append({"date": res.check_out_date, "movement": "Departure", "reservation": res.confirmation_no,
                         "guest": res.guest_name, "room": res.room_number, "nights": res.nights,
                         "status": ReservationStatus.LABELS[res.status],
                         "actual": res.actual_check_out, "_id": res.id})
        rows.sort(key=lambda r: (r["date"], r["movement"], r["room"]))
        arrivals = sum(1 for r in rows if r["movement"] == "Arrival")
        departures = len(rows) - arrivals
        by_day: dict[date, list[int]] = {}
        for d in iter_days(start, end):
            by_day[d] = [0, 0]
        for r in rows:
            by_day.setdefault(r["date"], [0, 0])[0 if r["movement"] == "Arrival" else 1] += 1
        return ReportResult(
            "Arrivals & departures", f"{start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("date", "Date", "date"), ReportColumn("movement", "Movement"),
             ReportColumn("reservation", "Reservation"), ReportColumn("guest", "Guest"), ReportColumn("room", "Room"),
             ReportColumn("nights", "Nights", "int"), ReportColumn("status", "Status"),
             ReportColumn("actual", "Actual time", "datetime")],
            rows, None,
            summary=[("Arrivals", str(arrivals)), ("Departures", str(departures)),
                     ("Walk-ins", str(sum(1 for r in self.ctx.repo_res.search(arrival_from=start, arrival_to=end)
                                          if r.is_walk_in)))],
            chart={"type": "bar", "kind": "int", "labels": [d.strftime("%b %d") for d in by_day],
                   "series": [("Arrivals", [v[0] for v in by_day.values()]),
                              ("Departures", [v[1] for v in by_day.values()])]})

    def cancellations(self, start: date, end: date) -> ReportResult:
        booked = self.ctx.repo_res.search(arrival_from=start, arrival_to=end)
        total = len(booked)
        cancelled = [r for r in booked if r.status == ReservationStatus.CANCELLED]
        no_shows = [r for r in booked if r.status == ReservationStatus.NO_SHOW]
        rows = []
        for res in sorted(cancelled + no_shows, key=lambda r: r.check_in_date):
            lost = res.nights * res.nightly_rate
            rows.append({"reservation": res.confirmation_no, "guest": res.guest_name,
                         "type": ReservationStatus.LABELS[res.status], "arrival": res.check_in_date,
                         "nights": res.nights, "lost": lost, "fees": res.total, "reason": res.cancel_reason,
                         "when": res.cancelled_at,
                         "lead": (res.check_in_date - res.cancelled_at.date()).days if res.cancelled_at else 0,
                         "_id": res.id})
        lost_total = sum(r["lost"] for r in rows)
        fees_total = sum(r["fees"] for r in rows)
        months: dict[str, list[int]] = {}
        for res in booked:
            label = res.check_in_date.strftime("%b %Y")
            entry = months.setdefault(label, [0, 0])
            if res.status == ReservationStatus.CANCELLED:
                entry[0] += 1
            elif res.status == ReservationStatus.NO_SHOW:
                entry[1] += 1
        return ReportResult(
            "Cancellations & no-shows", f"Arrivals {start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("reservation", "Reservation"), ReportColumn("guest", "Guest"), ReportColumn("type", "Type"),
             ReportColumn("arrival", "Arrival", "date"), ReportColumn("nights", "Nights", "int"),
             ReportColumn("lost", "Lost room revenue", "money"), ReportColumn("fees", "Fees charged", "money"),
             ReportColumn("lead", "Days before arrival", "int"), ReportColumn("reason", "Reason"),
             ReportColumn("when", "Cancelled at", "datetime")],
            rows, {"reservation": "Total", "lost": lost_total, "fees": fees_total},
            summary=[("Reservations", str(total)),
                     ("Cancellation rate", f"{_pct(len(cancelled), total)}%"),
                     ("No-show rate", f"{_pct(len(no_shows), total)}%"),
                     ("Lost revenue", self._money(lost_total))],
            chart={"type": "bar", "kind": "int", "labels": list(months),
                   "series": [("Cancelled", [v[0] for v in months.values()]),
                              ("No-show", [v[1] for v in months.values()])]} if months else None)

    # -- guests ----------------------------------------------------------------------------------
    def guest_history(self, start: date, end: date) -> ReportResult:
        rows_db = self.ctx.db.query(
            "SELECT g.id, g.first_name || ' ' || g.last_name AS guest, g.email, g.phone, g.city, g.is_vip, "
            "COUNT(r.id) AS stays, SUM(CAST(julianday(r.check_out_date) - julianday(r.check_in_date) AS INTEGER)) AS nights, "
            "MAX(r.check_out_date) AS last_departure, "
            "(SELECT COALESCE(SUM(c.amount), 0) FROM charges c JOIN reservations r2 ON r2.id = c.reservation_id "
            " WHERE r2.guest_id = g.id AND c.is_void = 0 AND r2.status IN ('checked_in', 'checked_out') "
            " AND r2.check_in_date <= ? AND r2.check_out_date >= ?) AS spent "
            "FROM guests g JOIN reservations r ON r.guest_id = g.id "
            "WHERE r.status IN ('checked_in', 'checked_out') AND r.check_in_date <= ? AND r.check_out_date >= ? "
            "GROUP BY g.id ORDER BY spent DESC",
            (end.isoformat(), start.isoformat(), end.isoformat(), start.isoformat()))
        repeat = {r[0] for r in self.ctx.db.query(
            "SELECT guest_id FROM reservations WHERE status IN ('checked_in','checked_out') AND check_in_date < ? "
            "GROUP BY guest_id", (start.isoformat(),))}
        rows = [{"guest": r["guest"], "vip": "VIP" if r["is_vip"] else "", "email": r["email"], "phone": r["phone"],
                 "city": r["city"], "stays": r["stays"], "nights": r["nights"] or 0, "spent": r["spent"] or 0,
                 "returning": "Returning" if r["id"] in repeat else "New",
                 "last": date.fromisoformat(r["last_departure"]), "_guest_id": r["id"]} for r in rows_db]
        returning = sum(1 for r in rows if r["returning"] == "Returning")
        return ReportResult(
            "Guest history", f"Stays {start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("guest", "Guest"), ReportColumn("vip", "VIP"), ReportColumn("returning", "Guest type"),
             ReportColumn("stays", "Stays", "int"), ReportColumn("nights", "Nights", "int"),
             ReportColumn("spent", "Total spent", "money"), ReportColumn("last", "Last departure", "date"),
             ReportColumn("city", "City"), ReportColumn("phone", "Phone"), ReportColumn("email", "Email")],
            rows, {"guest": "Total", "stays": sum(r["stays"] for r in rows), "nights": sum(r["nights"] for r in rows),
                   "spent": sum(r["spent"] for r in rows)},
            summary=[("Guests", str(len(rows))), ("Returning guests", f"{_pct(returning, len(rows))}%"),
                     ("Average spend", self._money(sum(r["spent"] for r in rows) // len(rows) if rows else 0)),
                     ("Average nights", f"{(sum(r['nights'] for r in rows) / len(rows)):.1f}" if rows else "0")])

    def booking_sources(self, start: date, end: date) -> ReportResult:
        res_list = self.ctx.repo_res.search(arrival_from=start, arrival_to=end)
        data: dict[str, dict[str, int]] = {}
        for res in res_list:
            entry = data.setdefault(res.source, {"count": 0, "nights": 0, "cancelled": 0, "revenue": 0})
            entry["count"] += 1
            if res.status in (ReservationStatus.CANCELLED, ReservationStatus.NO_SHOW):
                entry["cancelled"] += 1
            else:
                entry["nights"] += res.nights
                entry["revenue"] += self.ctx.billing.estimate(res)
        total = max(len(res_list), 1)
        rows = [{"source": ReservationSource.LABELS.get(k, k), "count": d["count"], "share": _pct(d["count"], total),
                 "nights": d["nights"], "revenue": d["revenue"], "cancelled": d["cancelled"],
                 "cancel_rate": _pct(d["cancelled"], d["count"])}
                for k, d in sorted(data.items(), key=lambda kv: -kv[1]["count"])]
        return ReportResult(
            "Booking sources", f"Arrivals {start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("source", "Source"), ReportColumn("count", "Reservations", "int"),
             ReportColumn("share", "Share", "percent"), ReportColumn("nights", "Nights", "int"),
             ReportColumn("revenue", "Revenue (est.)", "money"), ReportColumn("cancelled", "Cancelled / no-show", "int"),
             ReportColumn("cancel_rate", "Cancel rate", "percent")],
            rows, {"source": "Total", "count": len(res_list), "nights": sum(r["nights"] for r in rows),
                   "revenue": sum(r["revenue"] for r in rows), "cancelled": sum(r["cancelled"] for r in rows)},
            summary=[("Reservations", str(len(res_list))), ("Top source", rows[0]["source"] if rows else "—")],
            chart={"type": "hbar", "kind": "int", "labels": [r["source"] for r in rows],
                   "series": [("Reservations", [r["count"] for r in rows])]} if rows else None)

    # -- property ---------------------------------------------------------------------------------
    def maintenance_report(self, start: date, end: date) -> ReportResult:
        tickets = self.ctx.repo_maint.search(start=start, end=end)
        rows = []
        hours = []
        by_cat: dict[str, int] = {}
        for t in tickets:
            duration = None
            if t.resolved_at and t.created_at and t.status == TicketStatus.RESOLVED:
                duration = round((t.resolved_at - t.created_at).total_seconds() / 3600, 1)
                hours.append(duration)
            cat = TicketCategory.LABELS.get(t.category, t.category)
            by_cat[cat] = by_cat.get(cat, 0) + 1
            rows.append({"id": f"#{t.id}", "opened": t.created_at, "where": t.where, "title": t.title,
                         "category": cat, "priority": Priority.LABELS[t.priority],
                         "status": TicketStatus.LABELS[t.status], "hours": duration if duration is not None else "",
                         "cost": t.cost, "blocked": "Yes" if t.blocks_room else "", "_id": t.id})
        resolved = sum(1 for t in tickets if t.status == TicketStatus.RESOLVED)
        open_count = sum(1 for t in tickets if t.status in TicketStatus.ACTIVE)
        return ReportResult(
            "Maintenance", f"Tickets opened {start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("id", "Ticket"), ReportColumn("opened", "Opened", "datetime"), ReportColumn("where", "Location"),
             ReportColumn("title", "Issue"), ReportColumn("category", "Category"), ReportColumn("priority", "Priority"),
             ReportColumn("status", "Status"), ReportColumn("hours", "Hours to resolve", "float"),
             ReportColumn("cost", "Cost", "money"), ReportColumn("blocked", "Room blocked")],
            rows, {"id": "Total", "cost": sum(r["cost"] for r in rows)},
            summary=[("Tickets", str(len(rows))), ("Resolved", str(resolved)), ("Still open", str(open_count)),
                     ("Avg. resolution", f"{sum(hours) / len(hours):.1f} h" if hours else "—"),
                     ("Total cost", self._money(sum(r["cost"] for r in rows)))],
            chart={"type": "hbar", "kind": "int", "labels": list(by_cat),
                   "series": [("Tickets", list(by_cat.values()))]} if by_cat else None)

    def housekeeping_report(self, start: date, end: date) -> ReportResult:
        tasks = self.ctx.repo_hk.search(self.ctx.clock.today(), start=start, end=end,
                                        statuses=[TaskStatus.COMPLETED, TaskStatus.INSPECTED])
        failed = self.ctx.db.scalar(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'housekeeping.inspect' AND summary LIKE '%failed%' "
            "AND ts >= ? AND ts < date(?, '+1 day')", (start.isoformat(), end.isoformat()), 0)
        per_staff: dict[str, dict[str, Any]] = {}
        for t in tasks:
            name = t.completed_by_name or t.assigned_name or "Unassigned"
            entry = per_staff.setdefault(name, {"tasks": 0, "minutes": [], "departure": 0, "stayover": 0,
                                                "other": 0, "inspected": 0})
            entry["tasks"] += 1
            if t.task_type == TaskType.CHECKOUT:
                entry["departure"] += 1
            elif t.task_type == TaskType.STAYOVER:
                entry["stayover"] += 1
            else:
                entry["other"] += 1
            if t.status == TaskStatus.INSPECTED:
                entry["inspected"] += 1
            if t.started_at and t.completed_at:
                minutes = (t.completed_at - t.started_at).total_seconds() / 60
                if 0 < minutes < 600:
                    entry["minutes"].append(minutes)
        rows = []
        for name, e in sorted(per_staff.items(), key=lambda kv: -kv[1]["tasks"]):
            avg = round(sum(e["minutes"]) / len(e["minutes"]), 1) if e["minutes"] else ""
            rows.append({"staff": name, "tasks": e["tasks"], "departure": e["departure"], "stayover": e["stayover"],
                         "other": e["other"], "inspected": e["inspected"], "avg_minutes": avg})
        all_minutes = [m for e in per_staff.values() for m in e["minutes"]]
        return ReportResult(
            "Housekeeping", f"{start:%b %d, %Y} – {end:%b %d, %Y}",
            [ReportColumn("staff", "Staff member"), ReportColumn("tasks", "Tasks completed", "int"),
             ReportColumn("departure", "Departure cleans", "int"), ReportColumn("stayover", "Stayovers", "int"),
             ReportColumn("other", "Other", "int"), ReportColumn("inspected", "Passed inspection", "int"),
             ReportColumn("avg_minutes", "Avg. minutes", "float")],
            rows, {"staff": "Total", "tasks": len(tasks), "departure": sum(r["departure"] for r in rows),
                   "stayover": sum(r["stayover"] for r in rows), "other": sum(r["other"] for r in rows),
                   "inspected": sum(r["inspected"] for r in rows)},
            summary=[("Tasks completed", str(len(tasks))),
                     ("Avg. clean time", f"{sum(all_minutes) / len(all_minutes):.0f} min" if all_minutes else "—"),
                     ("Failed inspections", str(failed))],
            chart={"type": "hbar", "kind": "int", "labels": [r["staff"] for r in rows],
                   "series": [("Tasks", [r["tasks"] for r in rows])]} if rows else None)
