"""Central place that opens task dialogs. Pages, alerts, search results and
shortcuts all call these so every workflow behaves the same everywhere."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import QDialog, QWidget

from motelmg.reporting import documents
from motelmg.ui.widgets.dialogs import guarded, show_error

Accepted = QDialog.DialogCode.Accepted


class Actions:
    def __init__(self, window):
        self.w = window

    @property
    def ctx(self):
        return self.w.ctx

    def _parent(self, parent: QWidget | None) -> QWidget:
        return parent or self.w

    def _run(self, dialog_factory) -> bool:
        try:
            dialog = dialog_factory()
        except Exception as exc:  # noqa: BLE001 - e.g. record deleted meanwhile
            show_error(self.w, exc)
            return False
        result = dialog.exec() == Accepted
        self.w.refresh_soon()
        return result

    # -- reservations ------------------------------------------------------------------------
    def new_reservation(self, *, guest_id: int | None = None, room_id: int | None = None,
                        arrival: date | None = None, nights: int = 1, parent: QWidget | None = None) -> int | None:
        if not self.ctx.can("reservations.create"):
            return None
        from motelmg.ui.dialogs.reservation_form import ReservationDialog
        holder: dict = {}

        def factory():
            dlg = ReservationDialog(self._parent(parent), self.w, mode="new", guest_id=guest_id, room_id=room_id,
                                    arrival=arrival, nights=nights)
            holder["d"] = dlg
            return dlg

        if self._run(factory):
            return getattr(holder["d"], "result_value", None)
        return None

    def walk_in(self, *, room_id: int | None = None, parent: QWidget | None = None) -> bool:
        if not (self.ctx.can("reservations.create") and self.ctx.can("reservations.checkin")):
            return False
        from motelmg.ui.dialogs.reservation_form import ReservationDialog
        return self._run(lambda: ReservationDialog(self._parent(parent), self.w, mode="walk_in", room_id=room_id))

    def edit_reservation(self, res_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.reservation_form import ReservationDialog
        return self._run(lambda: ReservationDialog(self._parent(parent), self.w, mode="edit", reservation_id=res_id))

    def open_reservation(self, res_id: int, parent: QWidget | None = None, tab: str = "overview") -> bool:
        from motelmg.ui.dialogs.reservation_view import ReservationView
        return self._run(lambda: ReservationView(self._parent(parent), self.w, res_id, tab))

    def check_in(self, res_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.frontdesk import CheckInDialog
        return self._run(lambda: CheckInDialog(self._parent(parent), self.w, res_id))

    def check_out(self, res_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.frontdesk import CheckOutDialog
        return self._run(lambda: CheckOutDialog(self._parent(parent), self.w, res_id))

    def transfer(self, res_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.frontdesk import TransferDialog
        return self._run(lambda: TransferDialog(self._parent(parent), self.w, res_id))

    def cancel(self, res_id: int, *, no_show: bool = False, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.frontdesk import CancelDialog
        return self._run(lambda: CancelDialog(self._parent(parent), self.w, res_id, no_show=no_show))

    # -- billing ---------------------------------------------------------------------------------
    def take_payment(self, res_id: int, *, refund: bool = False, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.billing import PaymentDialog
        return self._run(lambda: PaymentDialog(self._parent(parent), self.w, res_id, refund=refund))

    def add_charge(self, res_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.billing import ChargeDialog
        return self._run(lambda: ChargeDialog(self._parent(parent), self.w, res_id))

    def _preview(self, title: str, html_fn, filename: str, parent: QWidget | None) -> None:
        from motelmg.ui.dialogs.documents import DocumentPreview
        html = guarded(self._parent(parent), html_fn)
        if html:
            DocumentPreview(self._parent(parent), self.w, title, html, filename).exec()

    def print_folio(self, res_id: int, parent: QWidget | None = None) -> None:
        res = self.ctx.reservations.get(res_id)
        folio = self.ctx.billing.folio(res_id)
        name = folio.invoice_no or f"Folio-{res.confirmation_no}"
        self._preview(f"Invoice {folio.invoice_no}" if folio.invoice_no else f"Folio {res.confirmation_no}",
                      lambda: documents.folio_html(self.ctx, folio), name, parent)

    def print_payment(self, payment_id: int, parent: QWidget | None = None) -> None:
        payment = self.ctx.billing.get_payment(payment_id)
        self._preview(f"Receipt {payment.receipt_no}", lambda: documents.payment_receipt_html(self.ctx, payment),
                      payment.receipt_no, parent)

    def print_registration(self, res_id: int, parent: QWidget | None = None) -> None:
        res = self.ctx.reservations.get(res_id)
        self._preview("Registration card", lambda: documents.registration_card_html(self.ctx, res_id),
                      f"Registration-{res.confirmation_no}", parent)

    # -- guests ---------------------------------------------------------------------------------
    def new_guest(self, parent: QWidget | None = None) -> int | None:
        if not self.ctx.can("guests.edit"):
            return None
        from motelmg.ui.dialogs.guest import GuestDialog
        holder: dict = {}

        def factory():
            holder["d"] = GuestDialog(self._parent(parent), self.w)
            return holder["d"]

        if self._run(factory):
            guest_id = holder["d"].result_value
            if guest_id:
                self.w.toast("Guest profile saved")
            return guest_id
        return None

    def open_guest(self, guest_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.guest import GuestDialog
        return self._run(lambda: GuestDialog(self._parent(parent), self.w, guest_id))

    # -- rooms & maintenance -------------------------------------------------------------------------
    def open_room(self, room_id: int) -> None:
        self.w.navigate("rooms", room_id=room_id)

    def new_ticket(self, room_id: int | None = None, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.property import TicketDialog
        return self._run(lambda: TicketDialog(self._parent(parent), self.w, room_id=room_id))

    def open_ticket(self, ticket_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.property import TicketDialog
        return self._run(lambda: TicketDialog(self._parent(parent), self.w, ticket_id))

    def take_out_of_order(self, room_id: int, parent: QWidget | None = None) -> bool:
        from motelmg.ui.dialogs.property import ServiceStatusDialog
        return self._run(lambda: ServiceStatusDialog(self._parent(parent), self.w, room_id))

    def show_conflicts(self, room, rows) -> None:
        from motelmg.ui.dialogs.misc import ConflictsDialog
        self._run(lambda: ConflictsDialog(self.w, self.w, room, rows))

    # -- navigation from search / alerts ----------------------------------------------------------------
    def search(self, text: str = "") -> None:
        from motelmg.ui.dialogs.misc import GlobalSearchDialog
        GlobalSearchDialog(self.w, self.w, text).exec()

    def open_hit(self, hit) -> None:
        if hit.kind == "guest":
            self.open_guest(hit.id)
        elif hit.kind == "reservation":
            self.open_reservation(hit.id)
        elif hit.kind == "room":
            self.open_room(hit.id)
        elif hit.kind == "payment":
            payment = self.ctx.billing.get_payment(hit.id)
            self.open_reservation(payment.reservation_id, tab="folio")
        elif hit.kind == "ticket":
            self.open_ticket(hit.id)

    def open_alert(self, alert) -> None:
        target = alert.target
        if target == "reservation" and alert.target_id:
            self.open_reservation(alert.target_id)
        elif target == "room" and alert.target_id:
            self.open_room(alert.target_id)
        elif target == "maintenance":
            if alert.target_id and self.ctx.can("maintenance.view"):
                self.open_ticket(alert.target_id)
            else:
                self.w.navigate("maintenance")
        elif target == "housekeeping":
            self.w.navigate("housekeeping")
        elif target == "billing":
            self.w.navigate("billing", tab="outstanding")
        elif target in ("arrivals", "departures"):
            self.w.navigate("reservations", preset=target)
        elif target == "backup":
            self.w.navigate("settings", section="backup")
        elif target == "notification" and alert.target_id:
            with self.ctx.db.transaction():
                self.ctx.repo_notify.mark_read(alert.target_id)
            self.w.refresh_soon()
