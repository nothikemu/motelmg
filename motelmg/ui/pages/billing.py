from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from motelmg.core.dates import parse_datetime
from motelmg.core.enums import PaymentKind, ReservationStatus
from motelmg.ui.pages.base import Page
from motelmg.ui.widgets.common import SearchField, StatCard, button, label
from motelmg.ui.widgets.date_range import DateRangePicker
from motelmg.ui.widgets.forms import combo
from motelmg.ui.widgets.table import Column, DataTable


class BillingPage(Page):
    key = "billing"
    title = "Billing"
    icon = "card"
    permission = "billing.view"
    topics = ("billing", "reservations")

    def __init__(self, app):
        super().__init__(app)
        L = self.layout_
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.s_net = StatCard("NET COLLECTED", "dollar", "green")
        self.s_count = StatCard("TRANSACTIONS", "receipt", "blue")
        self.s_refunds = StatCard("REFUNDS", "undo", "red")
        self.s_outstanding = StatCard("OUTSTANDING", "alert-circle", "amber")
        for card in (self.s_net, self.s_count, self.s_refunds, self.s_outstanding):
            stats.addWidget(card)
        self.s_outstanding.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        L.addLayout(stats)
        self.tabs = QTabWidget()
        L.addWidget(self.tabs, 1)

        # transactions
        tx = QWidget()
        tl = QVBoxLayout(tx)
        tl.setContentsMargins(0, 14, 0, 0)
        tl.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.range = DateRangePicker(self.ctx.clock.today(), "7d")
        self.range.changed.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.range)
        self.method = combo([("All methods", None)])
        self.method.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.method)
        self.kind = combo([("All types", "")] + [(v, k) for k, v in PaymentKind.LABELS.items()])
        self.kind.currentIndexChanged.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.kind)
        self.search = SearchField("Receipt, guest, confirmation #…")
        self.search.search.connect(lambda *_: self.mark_stale())
        bar.addWidget(self.search, 1)
        bar.addWidget(button("Export", "download", on_click=lambda: self.export_table(self.tx_table, "transactions")))
        tl.addLayout(bar)
        self.tx_table = DataTable([
            Column("created_at", "Date / time", "datetime", width=160),
            Column("receipt_no", "Receipt", width=100, bold=True),
            Column("kind", "Type", "badge", width=104, fmt=lambda r: r["kind_label"], tone=lambda r: r["tone"]),
            Column("guest_name", "Guest", stretch=True),
            Column("confirmation_no", "Reservation", width=100),
            Column("room_number", "Room", width=60),
            Column("method", "Method", width=120),
            Column("reference", "Reference", width=110),
            Column("amount", "Amount", "money", width=104, bold=True),
            Column("user", "Taken by", width=120),
        ], self.fmt, empty_icon="card", empty_title="No transactions in this period")
        self.tx_table.activated.connect(lambda r: self.actions.open_reservation(r["reservation_id"], tab="folio"))
        self.tx_table.set_menu_builder(lambda r: [
            ("Open folio", lambda: self.actions.open_reservation(r["reservation_id"], tab="folio")),
            ("Print receipt", lambda: self.actions.print_payment(r["id"]))])
        tl.addWidget(self.tx_table, 1)
        self.by_method = label("", "muted", wrap=True)
        tl.addWidget(self.by_method)
        self.tabs.addTab(tx, "Transactions")

        # outstanding
        out = QWidget()
        ol = QVBoxLayout(out)
        ol.setContentsMargins(0, 14, 0, 0)
        ol.setSpacing(12)
        self.out_table = DataTable([
            Column("confirmation_no", "Reservation", width=100, bold=True),
            Column("guest_name", "Guest", stretch=True),
            Column("phone", "Phone", width=130),
            Column("room_number", "Room", width=60),
            Column("status", "Status", "badge", width=110, fmt=lambda r: ReservationStatus.LABELS[r["status"]],
                   tone=lambda r: ReservationStatus.TONES[r["status"]]),
            Column("check_out_date", "Departure", "date", width=120),
            Column("total", "Charges", "money", width=100),
            Column("paid", "Paid", "money", width=100),
            Column("balance", "Balance", "money", width=110, bold=True),
        ], self.fmt, empty_icon="check-circle", empty_title="No outstanding balances",
            empty_text="Every folio is fully paid.")
        self.out_table.activated.connect(lambda r: self.actions.open_reservation(r["id"], tab="folio"))
        self.out_table.set_menu_builder(lambda r: [
            ("Take payment…", lambda: self.actions.take_payment(r["id"]), self.ctx.can("billing.payment")),
            ("Open folio", lambda: self.actions.open_reservation(r["id"], tab="folio")),
            ("Print statement", lambda: self.actions.print_folio(r["id"]))])
        ol.addWidget(self.out_table, 1)
        obar = QHBoxLayout()
        self.out_summary = label("", "faint")
        obar.addWidget(self.out_summary)
        obar.addStretch(1)
        obar.addWidget(button("Export", "download", small=True,
                              on_click=lambda: self.export_table(self.out_table, "outstanding-balances")))
        if self.ctx.can("billing.payment"):
            obar.addWidget(button("Take payment", "dollar", "primary", small=True, on_click=self._pay_selected))
        ol.addLayout(obar)
        self.tabs.addTab(out, "Outstanding balances")

        # invoices
        inv = QWidget()
        il = QVBoxLayout(inv)
        il.setContentsMargins(0, 14, 0, 0)
        il.setSpacing(12)
        ibar = QHBoxLayout()
        self.inv_range = DateRangePicker(self.ctx.clock.today(), "30d")
        self.inv_range.changed.connect(lambda *_: self.mark_stale())
        ibar.addWidget(self.inv_range)
        self.inv_search = SearchField("Invoice #, guest…")
        self.inv_search.search.connect(lambda *_: self.mark_stale())
        ibar.addWidget(self.inv_search, 1)
        il.addLayout(ibar)
        self.inv_table = DataTable([
            Column("invoice_no", "Invoice", width=110, bold=True),
            Column("issued_at", "Issued", "datetime", width=160),
            Column("guest_name", "Guest", stretch=True),
            Column("confirmation_no", "Reservation", width=100),
            Column("room_number", "Room", width=60),
            Column("stay", "Stay", width=190),
            Column("total", "Total", "money", width=100),
            Column("balance", "Balance now", "money", width=110),
        ], self.fmt, empty_icon="file", empty_title="No invoices in this period",
            empty_text="Invoices are issued automatically at check-out.")
        self.inv_table.activated.connect(lambda r: self.actions.print_folio(r["reservation_id"]))
        il.addWidget(self.inv_table, 1)
        il.addWidget(label("Double-click an invoice to view, print or save it as PDF.", "faint"))
        self.tabs.addTab(inv, "Invoices")
        self.tabs.currentChanged.connect(lambda *_: self.mark_stale())

    def subtitle(self) -> str:
        return "Payments, refunds, invoices and balances"

    def on_show(self, **kwargs) -> None:
        tab = kwargs.get("tab")
        if tab:
            self.tabs.setCurrentIndex({"transactions": 0, "outstanding": 1, "invoices": 2}.get(tab, 0))
        super().on_show(**kwargs)

    def refresh(self) -> None:
        ctx, fmt = self.ctx, self.fmt
        current = self.method.currentData()
        self.method.blockSignals(True)
        self.method.clear()
        self.method.addItem("All methods", None)
        for m in ctx.catalog.payment_methods(include_inactive=True):
            self.method.addItem(m.name, m.id)
        self.method.setCurrentIndex(max(self.method.findData(current), 0))
        self.method.blockSignals(False)
        start, end = self.range.value()
        payments = ctx.billing.transactions(start=start, end=end, method_id=self.method.currentData(),
                                            kind=self.kind.currentData() or "", text=self.search.text().strip())
        rows = []
        by_method: dict[str, int] = {}
        for p in payments:
            signed = p.signed_amount
            rows.append({"id": p.id, "reservation_id": p.reservation_id, "created_at": p.created_at,
                         "receipt_no": p.receipt_no, "kind": p.kind,
                         "kind_label": PaymentKind.LABELS[p.kind] + (" · void" if p.is_void else ""),
                         "tone": "gray" if p.is_void else PaymentKind.TONES[p.kind], "guest_name": p.guest_name,
                         "confirmation_no": p.confirmation_no, "room_number": p.room_number,
                         "method": p.method_name, "reference": p.reference,
                         "amount": 0 if p.is_void else signed, "user": p.created_by_name})
            if not p.is_void:
                by_method[p.method_name] = by_method.get(p.method_name, 0) + signed
        self.tx_table.set_rows(rows)
        valid = [p for p in payments if not p.is_void]
        net = sum(p.signed_amount for p in valid)
        refunds = sum(p.amount for p in valid if p.kind == "refund")
        self.s_net.set(fmt.money(net), f"{fmt.date(start)} – {fmt.date(end)}")
        self.s_count.set(str(len(valid)), f"{len(payments) - len(valid)} voided" if len(payments) != len(valid)
                         else "in selected period")
        self.s_refunds.set(fmt.money(refunds), f"{sum(1 for p in valid if p.kind == 'refund')} refund(s)")
        self.by_method.setText("By method:  " + "   ·   ".join(f"{m}: {fmt.money(v)}" for m, v in
                                                                      sorted(by_method.items(), key=lambda kv: -kv[1]))
                               if by_method else "")
        balances = ctx.billing.outstanding()
        out_rows = [{"id": r["id"], "confirmation_no": r["confirmation_no"], "guest_name": r["guest_name"],
                     "phone": r["phone"], "room_number": r["room_number"], "status": r["status"],
                     "check_out_date": date.fromisoformat(r["check_out_date"]), "total": r["total"], "paid": r["paid"],
                     "balance": r["total"] - r["paid"]} for r in balances]
        self.out_table.set_rows(out_rows)
        total_out = sum(r["balance"] for r in out_rows)
        self.out_summary.setText(f"{len(out_rows)} folio(s) · {fmt.money(total_out)} owed")
        self.s_outstanding.set(fmt.money(total_out), f"{len(out_rows)} folio(s)", "red" if total_out else "green")
        istart, iend = self.inv_range.value()
        invoices = ctx.billing.invoices(start=istart, end=iend, text=self.inv_search.text().strip())
        self.inv_table.set_rows([{
            "id": r["id"], "reservation_id": r["reservation_id"], "invoice_no": r["invoice_no"],
            "issued_at": parse_datetime(r["issued_at"]),
            "guest_name": r["guest_name"], "confirmation_no": r["confirmation_no"], "room_number": r["room_number"],
            "stay": f"{fmt.date(date.fromisoformat(r['check_in_date']))} – "
                    f"{fmt.date(date.fromisoformat(r['check_out_date']))}",
            "total": r["current_total"], "balance": r["current_total"] - r["current_paid"]} for r in invoices])

    def _pay_selected(self) -> None:
        row = self.out_table.selected_row()
        if row:
            self.actions.take_payment(row["id"])
        else:
            self.app.toast("Select a folio first", "info")
