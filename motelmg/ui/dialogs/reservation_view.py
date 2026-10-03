"""Reservation detail window: stay overview, folio, notes and history, with
every front desk action available from one place."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QMenu, QTabWidget, QVBoxLayout, QWidget

from motelmg.core.enums import ChargeKind, PaymentKind, ReservationSource, ReservationStatus as RS
from motelmg.ui.widgets.common import Badge, Banner, Card, Divider, KeyValueGrid, button, clear_layout, label
from motelmg.ui.widgets.dialogs import BaseDialog, ask_text, confirm, guarded
from motelmg.ui.widgets.notes import NotesPanel
from motelmg.ui.widgets.table import Column, DataTable


class ReservationView(BaseDialog):
    def __init__(self, parent, app, res_id: int, tab: str = "overview"):
        self.app, self.ctx, self.res_id = app, app.ctx, res_id
        super().__init__(parent, "Reservation", icon_name="book", width=980)
        self.resize(1040, 780)
        self.banner.hide()
        self.header_card = QWidget()
        self.header_card.setObjectName("Transparent")
        self.header_layout = QVBoxLayout(self.header_card)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.header_card)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self.overview = QWidget()
        self.folio_tab = QWidget()
        self.history_tab = QWidget()
        for w in (self.overview, self.folio_tab, self.history_tab):
            QVBoxLayout(w).setContentsMargins(0, 14, 0, 0)
        self.tabs.addTab(self.overview, "Overview")
        self.tabs.addTab(self.folio_tab, "Folio")
        self.notes = NotesPanel(app, reservation_id=res_id)
        notes_host = QWidget()
        nl = QVBoxLayout(notes_host)
        nl.setContentsMargins(0, 14, 0, 0)
        nl.addWidget(self.notes)
        self.tabs.addTab(notes_host, "Notes")
        self.tabs.addTab(self.history_tab, "History")
        self.add_footer_button("Close", self.accept)
        self._show_void = False
        self.reload()
        self.tabs.setCurrentIndex({"overview": 0, "folio": 1, "notes": 2, "history": 3}.get(tab, 0))

    @staticmethod
    def _clear(layout) -> None:
        clear_layout(layout)

    def reload(self) -> None:
        self.res = res = self.ctx.reservations.get(self.res_id)
        self.folio = self.ctx.billing.folio(self.res_id)
        self.title_label.setText(f"{res.confirmation_no} · {res.guest_name}")
        self.setWindowTitle(f"Reservation {res.confirmation_no}")
        self._build_header()
        self._build_overview()
        self._build_folio()
        self._build_history()
        self.tabs.setTabText(1, f"Folio ({self.app.fmt.money(self.folio.balance)} due)" if self.folio.balance > 0
                             else "Folio")
        self.tabs.setTabText(2, f"Notes ({len(self.ctx.notes.list(reservation_id=self.res_id))})")

    # -- header with actions ----------------------------------------------------------------
    def _build_header(self) -> None:
        self._clear(self.header_layout)
        res, fmt, ctx = self.res, self.app.fmt, self.ctx
        card = Card(padding=14, spacing=10)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(Badge(RS.LABELS[res.status], RS.TONES[res.status]))
        if res.status == RS.CHECKED_IN and ctx.reservations.is_overdue(res):
            top.addWidget(Badge("Overdue", "red"))
        if res.is_walk_in:
            top.addWidget(Badge("Walk-in", "teal"))
        if res.guest_is_vip:
            top.addWidget(Badge("VIP", "amber"))
        top.addWidget(label(f"Room {res.room_number} · {res.room_type_name}", "h3"))
        top.addWidget(label(f"{fmt.date(res.check_in_date)} → {fmt.date(res.check_out_date)} · "
                            f"{res.nights} night{'s' if res.nights != 1 else ''}", "muted"))
        top.addStretch(1)
        bal = self.folio.balance
        if res.status == RS.CONFIRMED:
            top.addWidget(label(f"Est. {fmt.money(ctx.billing.estimate(res))}", "muted"))
        top.addWidget(label("Balance" if bal >= 0 else "Credit", "overline"))
        bal_lbl = label(fmt.money(abs(bal)), "kpi_small")
        top.addWidget(bal_lbl)
        card.body.addLayout(top)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        can = ctx.can
        status = res.status

        def add(text, icon, fn, variant=None, perm=None, enabled=True):
            if perm and not can(perm):
                return
            b = button(text, icon, variant, small=True, on_click=fn)
            b.setEnabled(enabled)
            actions.addWidget(b)

        if status == RS.CONFIRMED:
            add("Check in", "log-in", self._check_in, "primary", "reservations.checkin")
            add("Modify", "edit", self._edit, None, "reservations.edit")
            add("Change room", "transfer", self._transfer, None, "reservations.transfer")
            add("Deposit", "dollar", lambda: self._pay(False), None, "billing.payment")
            add("Cancel", "slash", lambda: self._cancel(False), "danger-outline", "reservations.cancel")
            if res.check_in_date <= ctx.clock.today():
                add("No-show", "x", lambda: self._cancel(True), "danger-outline", "reservations.cancel")
        elif status == RS.CHECKED_IN:
            add("Check out", "log-out", self._check_out, "primary", "reservations.checkout")
            add("Take payment", "dollar", lambda: self._pay(False), None, "billing.payment")
            add("Add charge", "plus", self._charge, None, "billing.charge")
            add("Modify stay", "edit", self._edit, None, "reservations.edit")
            add("Move room", "transfer", self._transfer, None, "reservations.transfer")
        else:
            if bal > 0:
                add("Take payment", "dollar", lambda: self._pay(False), "primary", "billing.payment")
            if status == RS.CHECKED_OUT:
                add("Add late charge", "plus", self._charge, None, "billing.charge")
            if status in (RS.CANCELLED, RS.NO_SHOW) and res.check_in_date >= ctx.clock.today():
                add("Reinstate", "undo", self._reinstate, None, "reservations.cancel")
        if self.folio.paid > 0 and can("billing.refund"):
            add("Refund", "undo", lambda: self._pay(True))
        actions.addStretch(1)
        more = button("More", "more", "ghost", small=True)
        menu = QMenu(more)
        menu.addAction("Print folio / invoice", lambda: self.app.actions.print_folio(self.res_id, parent=self))
        menu.addAction("Print registration card", lambda: self.app.actions.print_registration(self.res_id,
                                                                                              parent=self))
        menu.addAction("Open guest profile", lambda: (self.app.actions.open_guest(res.guest_id, parent=self),
                                                      self.reload()))
        if status in (RS.CHECKED_IN, RS.CHECKED_OUT):
            if can("billing.discount"):
                menu.addAction("Apply discount…", self._discount)
            if can("billing.void"):
                menu.addAction("Folio adjustment…", self._adjust)
        if status == RS.CHECKED_IN and can("reservations.edit") and can("billing.void"):
            menu.addSeparator()
            menu.addAction("Undo check-in…", self._undo_check_in)
        more.setMenu(menu)
        actions.addWidget(more)
        card.body.addLayout(actions)
        self.header_layout.addWidget(card)
        if status == RS.CHECKED_IN and ctx.reservations.is_overdue(res):
            self.header_layout.addWidget(Banner("This guest is past their check-out time.", "warning"))
        for note in ctx.notes.important_for_guest(res.guest_id):
            self.header_layout.addWidget(Banner(f"Guest note: {note.body}", "info"))

    # -- overview -------------------------------------------------------------------------------------
    def _build_overview(self) -> None:
        layout = self.overview.layout()
        self._clear(layout)
        res, fmt = self.res, self.app.fmt
        guest = self.ctx.guests.get(res.guest_id)
        row = QHBoxLayout()
        row.setSpacing(14)
        stay = Card("Stay", padding=16)
        grid = KeyValueGrid(columns=2)
        grid.add("arr", "Arrival", f"{fmt.date(res.check_in_date)}" +
                 (f" (expected {fmt.time(res.expected_arrival)})" if res.expected_arrival else ""))
        grid.add("dep", "Departure", fmt.date(res.check_out_date) +
                 (f" (late until {fmt.time(res.late_checkout_until)})" if res.late_checkout_until else ""))
        grid.add("nights", "Nights", str(res.nights))
        grid.add("guests", "Guests", f"{res.adults} adult(s)" + (f", {res.children} child(ren)" if res.children else ""))
        grid.add("room", "Room", f"{res.room_number} · {res.room_type_name}")
        grid.add("rate", "Nightly rate", fmt.money(res.nightly_rate) + (" (override)" if res.rate_overridden else ""))
        grid.add("discount", "Discount", f"{res.discount_name} ({res.discount_bp / 100:g}%)" if res.discount_bp
                 else "—")
        grid.add("source", "Booked via", ReservationSource.LABELS.get(res.source, res.source))
        grid.add("created", "Booked", f"{fmt.datetime(res.created_at)}" +
                 (f" by {res.created_by_name}" if res.created_by_name else ""))
        if res.actual_check_in:
            grid.add("ci", "Checked in", fmt.datetime(res.actual_check_in))
        if res.actual_check_out:
            grid.add("co", "Checked out", fmt.datetime(res.actual_check_out))
        if res.cancelled_at:
            grid.add("cx", "Cancelled", f"{fmt.datetime(res.cancelled_at)} — {res.cancel_reason}")
        stay.body.addWidget(grid)
        if res.special_requests:
            stay.body.addWidget(Divider())
            stay.body.addWidget(label("Special requests", "label"))
            stay.body.addWidget(label(res.special_requests, wrap=True))
        row.addWidget(stay, 3)
        gcard = Card("Guest", padding=16)
        g = KeyValueGrid()
        g.add("name", "Name", guest.full_name)
        g.add("phone", "Phone", guest.phone or "—")
        g.add("email", "Email", guest.email or "—")
        g.add("id", "ID", f"{guest.id_number}" if guest.id_number else "Not recorded")
        g.add("plate", "Vehicle", guest.vehicle_plate or "—")
        g.add("stays", "History", f"{guest.stays} stay(s), {fmt.money(guest.total_spent)} total")
        gcard.body.addWidget(g)
        gcard.body.addWidget(button("Open guest profile", "user", "link",
                                    on_click=lambda: (self.app.actions.open_guest(guest.id, parent=self),
                                                      self.reload())))
        row.addWidget(gcard, 2)
        layout.addLayout(row)
        layout.addStretch(1)

    # -- folio ---------------------------------------------------------------------------------------------
    def _build_folio(self) -> None:
        layout = self.folio_tab.layout()
        self._clear(layout)
        fmt = self.app.fmt
        folio = self.folio
        self._show_void = False
        if self.res.status == RS.CONFIRMED:
            quote = self.ctx.billing.quote(nights=self.res.nights, nightly_rate=self.res.nightly_rate,
                                           discount_bp=self.res.discount_bp, discount_name=self.res.discount_name)
            layout.addWidget(Banner(f"Room charges are posted at check-in. Estimated stay total: "
                                    f"<b>{fmt.money(quote.total)}</b> ({quote.nights} nights incl. taxes).", "info"))
        charges = DataTable([
            Column("service_date", "Date", "date", width=110),
            Column("description", "Description", stretch=True),
            Column("kind", "Type", width=90, fmt=lambda r: ChargeKind.LABELS.get(r["kind"], r["kind"])),
            Column("quantity", "Qty", "int", width=50),
            Column("amount", "Amount", "money", width=100, bold=True),
            Column("status", "", "badge", width=80, fmt=lambda r: "Void" if r["is_void"] else "",
                   tone=lambda r: "gray"),
        ], fmt, empty_icon="receipt", empty_title="No charges yet", row_height=34)
        rows = []
        for c in folio.charges:
            rows.append({"id": c.id, "service_date": c.service_date, "description": c.description +
                         (f" — void: {c.void_reason}" if c.is_void else ""), "kind": c.kind,
                         "quantity": c.quantity, "amount": c.amount, "is_void": c.is_void, "charge": c})
        charges.set_rows(rows)
        charges.set_predicate(lambda r: not r["is_void"] or self._show_void)
        charges.set_menu_builder(self._charge_menu)
        charges.setMinimumHeight(200)
        top = QHBoxLayout()
        top.addWidget(label("Charges", "h3"))
        top.addStretch(1)
        toggle = button("Show voided", variant="ghost", small=True)
        toggle.setCheckable(True)

        def flip(on):
            self._show_void = on
            charges.set_predicate(lambda r: not r["is_void"] or self._show_void)

        toggle.toggled.connect(flip)
        top.addWidget(toggle)
        if self.ctx.can("billing.charge") and self.res.status in (RS.CHECKED_IN, RS.CHECKED_OUT):
            top.addWidget(button("Add charge", "plus", "soft", small=True, on_click=self._charge))
        layout.addLayout(top)
        layout.addWidget(charges, 3)

        payments = DataTable([
            Column("created_at", "Date", "datetime", width=170),
            Column("receipt_no", "Receipt", width=100),
            Column("kind", "Type", "badge", width=100, fmt=lambda r: PaymentKind.LABELS[r["kind"]] +
                   (" (void)" if r["is_void"] else ""),
                   tone=lambda r: "gray" if r["is_void"] else PaymentKind.TONES[r["kind"]]),
            Column("method", "Method", width=130),
            Column("reference", "Reference / notes", stretch=True),
            Column("amount", "Amount", "money", width=100, bold=True),
        ], fmt, empty_icon="card", empty_title="No payments yet", row_height=34)
        payments.set_rows([{"id": p.id, "created_at": p.created_at, "receipt_no": p.receipt_no, "kind": p.kind,
                            "method": p.method_name, "reference": " · ".join(x for x in (p.reference, p.notes)
                                                                                    if x),
                            "amount": p.signed_amount, "is_void": p.is_void,
                            "payment": p} for p in folio.payments])
        payments.set_menu_builder(self._payment_menu)
        payments.activated.connect(lambda r: self.app.actions.print_payment(r["id"], parent=self))
        payments.setMinimumHeight(130)
        top2 = QHBoxLayout()
        top2.addWidget(label("Payments", "h3"))
        top2.addStretch(1)
        if self.ctx.can("billing.payment"):
            top2.addWidget(button("Take payment", "dollar", "soft", small=True, on_click=lambda: self._pay(False)))
        layout.addLayout(top2)
        layout.addWidget(payments, 2)

        totals = Card(padding=12, spacing=4)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        items = [("Subtotal", fmt.money(folio.subtotal))]
        items += [(t.name, fmt.money(t.amount)) for t in folio.taxes]
        items += [("Total", fmt.money(folio.total)), ("Paid", fmt.money(folio.paid)),
                  ("Balance" if folio.balance >= 0 else "Credit", fmt.money(abs(folio.balance)))]
        for i, (k, v) in enumerate(items):
            grid.addWidget(label(k, "overline"), 0, i)
            grid.addWidget(label(v, "kpi_small" if k in ("Total", "Balance", "Credit") else "h3"), 1, i)
        totals.body.addLayout(grid)
        if folio.invoice_no:
            totals.body.addWidget(label(f"Invoice {folio.invoice_no} issued {fmt.datetime(folio.invoice_issued_at)}",
                                        "faint"))
        layout.addWidget(totals)

    def _charge_menu(self, row) -> list:
        c = row["charge"]
        entries = []
        if not c.is_void and c.kind not in (ChargeKind.ROOM, ChargeKind.TAX):
            entries.append(("Void charge…", lambda: self._void_charge(c), self.ctx.can("billing.void")))
        if c.kind == ChargeKind.ROOM:
            entries.append(("Room nights follow the stay dates (use Modify stay)", lambda: None, False))
        return entries

    def _payment_menu(self, row) -> list:
        p = row["payment"]
        entries = [("Print receipt", lambda: self.app.actions.print_payment(p.id, parent=self))]
        if not p.is_void:
            entries.append(None)
            entries.append(("Void payment…", lambda: self._void_payment(p), self.ctx.can("billing.void")))
        return entries

    # -- history ------------------------------------------------------------------------------------------------
    def _build_history(self) -> None:
        layout = self.history_tab.layout()
        self._clear(layout)
        entries = self.ctx.audit.for_entity("reservation", self.res_id)
        table = DataTable([
            Column("ts", "When", "datetime", width=170),
            Column("username", "Staff", width=110),
            Column("summary", "What happened", stretch=True),
        ], self.app.fmt, empty_icon="clock", empty_title="No history", row_height=34)
        table.set_rows([{"id": e.id, "ts": e.ts, "username": e.username, "summary": e.summary} for e in entries])
        moves = self.ctx.reservations.room_moves(self.res_id)
        if moves:
            layout.addWidget(label("Room moves: " + ", ".join(f"{m.from_room} → {m.to_room} "
                                                               f"({self.app.fmt.datetime(m.moved_at)}, {m.reason})"
                                                               for m in moves), "muted", wrap=True))
        layout.addWidget(table)

    # -- actions --------------------------------------------------------------------------------------------------
    def _after(self, changed) -> None:
        if changed:
            self.reload()

    def _check_in(self) -> None:
        self._after(self.app.actions.check_in(self.res_id, parent=self))

    def _check_out(self) -> None:
        self._after(self.app.actions.check_out(self.res_id, parent=self))

    def _edit(self) -> None:
        self._after(self.app.actions.edit_reservation(self.res_id, parent=self))

    def _transfer(self) -> None:
        self._after(self.app.actions.transfer(self.res_id, parent=self))

    def _pay(self, refund: bool) -> None:
        self._after(self.app.actions.take_payment(self.res_id, refund=refund, parent=self))

    def _charge(self) -> None:
        self._after(self.app.actions.add_charge(self.res_id, parent=self))

    def _discount(self) -> None:
        from motelmg.ui.dialogs.billing import DiscountDialog
        self._after(DiscountDialog(self, self.app, self.res_id).exec())

    def _adjust(self) -> None:
        from motelmg.ui.dialogs.billing import AdjustmentDialog
        self._after(AdjustmentDialog(self, self.app, self.res_id).exec())

    def _cancel(self, no_show: bool) -> None:
        self._after(self.app.actions.cancel(self.res_id, no_show=no_show, parent=self))

    def _reinstate(self) -> None:
        if confirm(self, "Reinstate reservation", "Restore this reservation to confirmed? Any cancellation or no-show "
                   "fee will be voided.", "Reinstate"):
            self._after(guarded(self, lambda: self.ctx.reservations.reinstate(self.res_id), "Reservation reinstated",
                                self.app.toast))

    def _undo_check_in(self) -> None:
        reason = ask_text(self, "Undo check-in", "Room charges posted at check-in will be voided and the reservation "
                          "returns to confirmed. Why?", danger=True, confirm_text="Undo check-in")
        if reason:
            self._after(guarded(self, lambda: self.ctx.reservations.revert_check_in(self.res_id, reason),
                                "Check-in undone", self.app.toast))

    def _void_charge(self, charge) -> None:
        reason = ask_text(self, "Void charge", f"Void '{charge.description}' ({self.app.fmt.money(charge.amount)})? "
                          "Its taxes are voided too.", placeholder="Reason", danger=True, confirm_text="Void charge")
        if reason:
            self._after(guarded(self, lambda: self.ctx.billing.void_charge(charge.id, reason), "Charge voided",
                                self.app.toast))

    def _void_payment(self, payment) -> None:
        reason = ask_text(self, "Void payment", f"Void {payment.receipt_no} ({self.app.fmt.money(payment.amount)})? "
                          "Use this only for payments entered by mistake; use Refund to return money.",
                          placeholder="Reason", danger=True, confirm_text="Void payment")
        if reason:
            self._after(guarded(self, lambda: self.ctx.billing.void_payment(payment.id, reason), "Payment voided",
                                self.app.toast))


__all__ = ["ReservationView", "Qt"]
