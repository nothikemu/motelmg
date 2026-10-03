"""Figures for the main dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from motelmg.core.enums import RoomState
from motelmg.models import Reservation


@dataclass
class DashboardData:
    today: date
    total_rooms: int = 0
    occupied: int = 0
    available: int = 0
    vacant_dirty: int = 0
    out_of_order: int = 0
    occupancy_pct: float = 0.0
    arrivals_total: int = 0
    arrivals_pending: int = 0
    departures_total: int = 0
    departures_pending: int = 0
    in_house_guests: int = 0
    revenue_today: int = 0
    revenue_mtd: int = 0
    collected_today: int = 0
    outstanding_total: int = 0
    outstanding_count: int = 0
    state_counts: dict[str, int] = field(default_factory=dict)
    arrivals: list[Reservation] = field(default_factory=list)
    departures: list[Reservation] = field(default_factory=list)
    upcoming: list[Reservation] = field(default_factory=list)
    revenue_7d: list[tuple[str, int]] = field(default_factory=list)
    occupancy_7d: list[tuple[str, float]] = field(default_factory=list)


class DashboardService:
    def __init__(self, ctx):
        self.ctx = ctx

    def data(self) -> DashboardData:
        ctx = self.ctx
        today = ctx.clock.today()
        d = DashboardData(today=today)
        board = ctx.rooms.board()
        d.total_rooms = len(board)
        counts: dict[str, int] = {}
        for item in board:
            counts[item.state] = counts.get(item.state, 0) + 1
        d.state_counts = counts
        d.occupied = sum(counts.get(s, 0) for s in (RoomState.OCCUPIED, RoomState.DUE_OUT, RoomState.OVERDUE))
        d.available = counts.get(RoomState.AVAILABLE, 0)
        d.vacant_dirty = counts.get(RoomState.VACANT_DIRTY, 0)
        d.out_of_order = counts.get(RoomState.MAINTENANCE, 0) + counts.get(RoomState.OUT_OF_SERVICE, 0)
        sellable = max(d.total_rooms - d.out_of_order, 0)
        d.occupancy_pct = round(100 * d.occupied / sellable, 1) if sellable else 0.0
        d.arrivals = ctx.reservations.arrivals(today)
        d.arrivals_total = len(d.arrivals)
        d.arrivals_pending = sum(1 for r in d.arrivals if r.status == "confirmed")
        d.departures = ctx.reservations.departures(today)
        d.departures_total = len(d.departures)
        d.departures_pending = sum(1 for r in d.departures if r.status == "checked_in")
        in_house = ctx.repo_res.in_house()
        d.in_house_guests = sum(r.guests_count for r in in_house)
        d.upcoming = ctx.repo_res.search(statuses=["confirmed"], arrival_from=today + timedelta(days=1),
                                         arrival_to=today + timedelta(days=7), order="r.check_in_date, rm.number")
        if ctx.can("reports.financial") or ctx.can("billing.view"):
            rev = ctx.db.query(
                "SELECT service_date, SUM(amount) AS total FROM charges WHERE is_void = 0 AND service_date BETWEEN ? AND ? "
                "GROUP BY service_date", ((today - timedelta(days=6)).isoformat(), today.isoformat()))
            by_day = {r["service_date"]: r["total"] for r in rev}
            d.revenue_7d = [((today - timedelta(days=i)).strftime("%a"),
                             by_day.get((today - timedelta(days=i)).isoformat(), 0)) for i in range(6, -1, -1)]
            d.revenue_today = by_day.get(today.isoformat(), 0)
            d.revenue_mtd = int(ctx.db.scalar(
                "SELECT COALESCE(SUM(amount), 0) FROM charges WHERE is_void = 0 AND service_date BETWEEN ? AND ?",
                (today.replace(day=1).isoformat(), today.isoformat()), 0))
            d.collected_today = int(ctx.db.scalar(
                "SELECT COALESCE(SUM(CASE WHEN kind = 'refund' THEN -amount ELSE amount END), 0) FROM payments "
                "WHERE is_void = 0 AND created_at >= ? AND created_at < date(?, '+1 day')",
                (today.isoformat(), today.isoformat()), 0))
            balances = ctx.repo_folio.balances(1)
            d.outstanding_count = len(balances)
            d.outstanding_total = sum(r["total"] - r["paid"] for r in balances)
        rooms = max(d.total_rooms, 1)
        sold = ctx.reports._sold_by_day(today - timedelta(days=6), today)
        d.occupancy_7d = [((today - timedelta(days=i)).strftime("%a"),
                           round(100 * sold.get((today - timedelta(days=i)).isoformat(), 0) / rooms, 1))
                          for i in range(6, -1, -1)]
        return d
