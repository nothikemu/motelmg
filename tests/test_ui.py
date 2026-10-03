"""GUI tests: drive the real widgets and dialogs (offscreen) through the main
front desk workflow, the setup wizard and role-based navigation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from motelmg.core.dates import Clock  # noqa: E402
from motelmg.core.enums import HKStatus, ReservationStatus  # noqa: E402
from motelmg.services.context import AppContext  # noqa: E402
from tests.conftest import ADMIN, START, make_context, new_guest, room  # noqa: E402


@pytest.fixture(autouse=True)
def no_modal_popups(monkeypatch):
    """Modal sub-dialogs (confirmations, previews) would block the test; accept them instead."""
    from motelmg.ui.dialogs import documents
    from motelmg.ui.widgets import dialogs
    monkeypatch.setattr(dialogs.MessageDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(documents.DocumentPreview, "exec", lambda self: QDialog.DialogCode.Accepted)
    yield


@pytest.fixture
def window(qtbot, tmp_path):
    from motelmg.ui.main_window import MainWindow
    ctx = make_context(tmp_path / "ui.db", clock=Clock(START))
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    yield win
    win._closing_for_signout = True
    win.close()
    ctx.close()


def test_every_page_renders(window, qtbot):
    for key in window.pages:
        window.navigate(key)
        qtbot.wait(5)
        assert window.current_page().key == key
        assert window.page_title.text()


def test_front_desk_workflow_through_dialogs(window, qtbot):
    from motelmg.ui.dialogs.billing import ChargeDialog, PaymentDialog
    from motelmg.ui.dialogs.frontdesk import CheckInDialog, CheckOutDialog
    from motelmg.ui.dialogs.guest import GuestDialog
    from motelmg.ui.dialogs.reservation_form import ReservationDialog
    ctx = window.ctx

    # Create the guest through the guest form
    gd = GuestDialog(window, window)
    qtbot.addWidget(gd)
    gd.form.set_values({"first_name": "Grace", "last_name": "Hopper", "phone": "555 010 2000",
                        "email": "grace@example.com"})
    gd._save()
    guest_id = gd.result_value
    assert ctx.guests.get(guest_id).full_name == "Grace Hopper"

    # Invalid input stays in the dialog with an inline error
    bad = GuestDialog(window, window)
    qtbot.addWidget(bad)
    bad.form.set_values({"first_name": "", "last_name": "X", "email": "nope"})
    bad._save()
    assert bad.result() != QDialog.DialogCode.Accepted
    assert bad.form.errors["email"].isVisibleTo(bad) and bad.form.errors["first_name"].text()

    # New reservation: pick the guest and a room, check the live quote, save
    rd = ReservationDialog(window, window, mode="new")
    qtbot.addWidget(rd)
    rd.guest.set_guest(guest_id)
    rd.nights.setValue(2)
    rd._refresh_rooms()
    assert rd.rooms.select_id(room(ctx, "101").id)
    rd._update_summary()
    rd._save()
    res_id = rd.result_value
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CONFIRMED and res.nights == 2 and res.room_number == "101"

    # Check in at 3 PM, recording the ID and taking the stay total
    ctx.clock.set(datetime(2026, 3, 10, 15, 30))
    ci = CheckInDialog(window, window, res_id)
    qtbot.addWidget(ci)
    ci.id_number.setText("D1234567")
    assert ci.pay_amount.cents() == 224_00
    ci.pay_amount.setText("")
    ci._save()
    assert ctx.reservations.get(res_id).status == ReservationStatus.CHECKED_IN
    assert ctx.guests.get(guest_id).id_number == "D1234567"

    # Add a charge from the catalog
    ch = ChargeDialog(window, window, res_id)
    qtbot.addWidget(ch)
    vending = next(i for i in ctx.catalog.charge_items() if i.name == "Vending / snacks")
    ch.item.setCurrentIndex(ch.item.findData(vending.id))
    ch.quantity.setValue(2)
    ch._save()
    assert ctx.billing.folio(res_id).subtotal == 200_00 + 6_00

    # Take payment for the balance (prefilled)
    pd = PaymentDialog(window, window, res_id)
    qtbot.addWidget(pd)
    assert pd.amount.cents() == ctx.billing.balance(res_id)
    pd._save()
    assert ctx.billing.balance(res_id) == 0

    # Check out two days later
    ctx.clock.set(datetime(2026, 3, 12, 10, 0))
    co = CheckOutDialog(window, window, res_id)
    qtbot.addWidget(co)
    assert not co.pay_card.isVisibleTo(co)
    co._save()
    res = ctx.reservations.get(res_id)
    assert res.status == ReservationStatus.CHECKED_OUT and ctx.billing.folio(res_id).invoice_no

    # Housekeeping page: start, complete and inspect the departure clean
    window.navigate("housekeeping")
    page = window.pages["housekeeping"]
    page.safe_refresh()
    rows = page.table.visible_rows()
    assert any(r["room"] == "101" for r in rows)
    page.table.select_id(next(r["id"] for r in rows if r["room"] == "101"))
    page._start()
    page._complete()
    assert room(ctx, "101").hk_status == HKStatus.CLEAN
    page.chips.set_current("inspect")
    page.safe_refresh()
    page.table.select_id(page.table.visible_rows()[0]["id"])
    page._inspect(True)
    assert room(ctx, "101").hk_status == HKStatus.INSPECTED

    # The dashboard and room board reflect the final state
    window.navigate("rooms")
    board = window.pages["rooms"]
    board._select(room(ctx, "101").id)
    assert board.selected == room(ctx, "101").id
    window.navigate("dashboard")


def test_walk_in_cancel_and_transfer_dialogs(window, qtbot):
    from motelmg.ui.dialogs.frontdesk import CancelDialog, TransferDialog
    from motelmg.ui.dialogs.reservation_form import ReservationDialog
    from motelmg.ui.dialogs.reservation_view import ReservationView
    ctx = window.ctx
    ctx.clock.set(datetime(2026, 3, 10, 20, 0))
    gid = new_guest(ctx, "Walk", "Inn")
    wi = ReservationDialog(window, window, mode="walk_in")
    qtbot.addWidget(wi)
    wi.guest.set_guest(gid)
    wi._refresh_rooms()
    wi.rooms.select_id(room(ctx, "102").id)
    wi._update_summary()
    wi._save()
    res = ctx.repo_res.in_house_for_room(room(ctx, "102").id)
    assert res is not None and res.is_walk_in and ctx.billing.balance(res.id) == 0

    td = TransferDialog(window, window, res.id)
    qtbot.addWidget(td)
    td.table.select_id(room(ctx, "201").id)
    td.reason.setText("Guest asked for two beds")
    td._save()
    assert ctx.reservations.get(res.id).room_number == "201"

    other = ctx.reservations.create({"guest_id": new_guest(ctx, "Future", "Guest"), "room_id": room(ctx, "101").id,
                                     "check_in_date": START.date() + timedelta(days=3),
                                     "check_out_date": START.date() + timedelta(days=4)})
    cd = CancelDialog(window, window, other)
    qtbot.addWidget(cd)
    cd.reason.setPlainText("Plans changed")
    cd._save()
    assert ctx.reservations.get(other).status == ReservationStatus.CANCELLED

    view = ReservationView(window, window, res.id, tab="folio")
    qtbot.addWidget(view)
    assert "R1000" in view.title_label.text()
    view.reload()


def test_settings_and_backup_from_ui(window, qtbot, tmp_path):
    ctx = window.ctx
    window.navigate("settings")
    page = window.pages["settings"]
    panel = page.panels["property"]
    panel.bindings["property.name"][0].setText("Desert Rose Inn")
    panel.save()
    assert ctx.settings.property_name == "Desert Rose Inn"
    panel.bindings["property.name"][0].setText("")
    panel.save()
    assert ctx.settings.property_name == "Desert Rose Inn"  # invalid value rejected
    assert panel.banner.isVisibleTo(panel)
    ctx.settings.update({"backup.directory": str(tmp_path / "bk")})
    page._backup_now()
    assert len(ctx.backups.list()) == 1


def test_role_based_navigation(qtbot, tmp_path):
    from motelmg.ui.main_window import MainWindow
    ctx = make_context(tmp_path / "roles.db")
    role_id = next(r.id for r in ctx.users.list_roles() if r.name == "Housekeeping")
    ctx.users.create_user({"full_name": "Maria Lopez", "username": "maria", "role_id": role_id}, "Password123",
                          must_change=False)
    ctx.auth.login("maria", "Password123")
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    assert set(win.pages) == {"rooms", "housekeeping", "maintenance"}
    assert win.current_page().key == "rooms"
    win._closing_for_signout = True
    win.close()
    ctx.close()


def test_setup_wizard_end_to_end(qtbot, tmp_path):
    from motelmg.ui.wizard import SetupWizard
    ctx = AppContext(tmp_path / "wizard.db")
    wiz = SetupWizard(ctx)
    qtbot.addWidget(wiz)
    wiz._next()  # welcome
    wiz._next()  # property: name missing
    assert wiz.stack.currentIndex() == 1 and wiz.banner.isVisibleTo(wiz)
    wiz.prop.set_values({"property.name": "Lakeside Lodge", "property.city": "Tahoe"})
    wiz._next()
    wiz.admin.set_values({"full_name": "Pat Owner", "username": "owner", "password": "short", "confirm": "short"})
    wiz._next()
    assert wiz.stack.currentIndex() == 2
    wiz.admin.set_values({"password": "Secret123", "confirm": "Secret123"})
    wiz._next()
    wiz.rates.set_values({"tax_rate": "7.5"})
    wiz._next()
    wiz._next()  # default room types
    wiz.rooms_table.setRowCount(0)
    wiz._next()
    assert wiz.stack.currentIndex() == 5  # at least one room required
    wiz.gen_first.setValue(1)
    wiz.gen_count.setValue(8)
    wiz._generate()
    wiz._next()
    wiz._next()  # finish
    assert wiz.result() == QDialog.DialogCode.Accepted
    assert ctx.settings.setup_complete and ctx.session.username == "owner"
    assert len(ctx.rooms.list_rooms()) == 8 and ctx.catalog.taxes()[0].value == 750
    ctx.close()


def test_login_window(qtbot, tmp_path):
    from motelmg.ui.login import LoginWindow
    ctx = make_context(tmp_path / "login.db")
    ctx.auth.logout()
    lw = LoginWindow(ctx)
    qtbot.addWidget(lw)
    lw.username.setText("admin")
    lw.password.setText("wrong-password1")
    lw._login()
    assert ctx.session is None and lw.banner.isVisibleTo(lw)
    with qtbot.waitSignal(lw.logged_in, timeout=2000):
        lw.username.setText(ADMIN["username"])
        lw.password.setText(ADMIN["password"])
        qtbot.keyClick(lw.password, Qt.Key.Key_Return)
    assert ctx.session.username == "admin"
    lw._success = True
    ctx.close()


def test_every_dialog_opens_on_demo_data(qtbot, tmp_path):
    """Open every dialog for records in every state of a realistic database."""
    from motelmg.services.setup import DEFAULT_ROOM_TYPES, DEFAULT_ROOMS, SetupService
    from motelmg.ui.dialogs.billing import AdjustmentDialog, ChargeDialog, DiscountDialog, PaymentDialog
    from motelmg.ui.dialogs.frontdesk import CancelDialog, CheckInDialog, CheckOutDialog, TransferDialog
    from motelmg.ui.dialogs.guest import GuestDialog
    from motelmg.ui.dialogs.misc import GlobalSearchDialog, ShortcutsDialog
    from motelmg.ui.dialogs.property import (AssignDialog, BulkRoomsDialog, ResolveTicketDialog, RoomDialog,
                                             RoomTypeDialog, ServiceStatusDialog, TaskDialog, TicketDialog)
    from motelmg.ui.dialogs.reservation_form import ReservationDialog
    from motelmg.ui.dialogs.reservation_view import ReservationView
    from motelmg.ui.dialogs.staff import ChangePasswordDialog, ResetPasswordDialog, RoleDialog, UserDialog
    from motelmg.ui.main_window import MainWindow
    ctx = AppContext(tmp_path / "demo.db")
    SetupService(ctx).complete({"admin": ADMIN, "property": {"property.name": "Demo"}, "tax_rate": "8",
                                "room_types": DEFAULT_ROOM_TYPES, "rooms": DEFAULT_ROOMS, "demo": True})
    win = MainWindow(ctx)
    qtbot.addWidget(win)
    opened = []

    def check(dialog):
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.close()
        opened.append(type(dialog).__name__)

    for status in ReservationStatus.ALL:
        for res in ctx.repo_res.search(statuses=[status], limit=2):
            check(ReservationView(win, win, res.id, tab="folio"))
            check(PaymentDialog(win, win, res.id))
            if res.paid > 0:
                check(PaymentDialog(win, win, res.id, refund=True))
            if status == ReservationStatus.CONFIRMED:
                check(ReservationDialog(win, win, mode="edit", reservation_id=res.id))
                check(CheckInDialog(win, win, res.id))
                check(CancelDialog(win, win, res.id))
                check(CancelDialog(win, win, res.id, no_show=True))
                check(TransferDialog(win, win, res.id))
            if status == ReservationStatus.CHECKED_IN:
                check(ReservationDialog(win, win, mode="edit", reservation_id=res.id))
                check(CheckOutDialog(win, win, res.id))
                check(TransferDialog(win, win, res.id))
                check(ChargeDialog(win, win, res.id))
                check(DiscountDialog(win, win, res.id))
                check(AdjustmentDialog(win, win, res.id))
    for guest in ctx.guests.search("")[:3]:
        check(GuestDialog(win, win, guest.id))
    rooms = ctx.rooms.list_rooms()
    check(RoomDialog(win, win, rooms[0].id))
    check(RoomDialog(win, win))
    check(RoomTypeDialog(win, win, ctx.rooms.list_types()[0].id))
    check(BulkRoomsDialog(win, win))
    vacant = next(r for r in rooms if not ctx.repo_res.in_house_for_room(r.id))
    check(ServiceStatusDialog(win, win, vacant.id))
    for ticket in ctx.maintenance.search()[:3]:
        check(TicketDialog(win, win, ticket.id))
        if ticket.status in ("open", "in_progress", "on_hold"):
            check(ResolveTicketDialog(win, win, ticket.id))
    check(TicketDialog(win, win, room_id=rooms[0].id))
    task = ctx.housekeeping.tasks()[0]
    check(TaskDialog(win, win, task_id=task.id))
    check(TaskDialog(win, win, room_id=rooms[0].id))
    check(AssignDialog(win, win, [task.id]))
    user = ctx.users.list_users()[-1]
    check(UserDialog(win, win, user.id))
    check(UserDialog(win, win))
    check(ResetPasswordDialog(win, win, user.id))
    check(ChangePasswordDialog(win, win))
    for role in ctx.users.list_roles():
        check(RoleDialog(win, win, role.id))
    check(GlobalSearchDialog(win, win, "a"))
    check(ShortcutsDialog(win))
    win.navigate("reports")
    reports = win.pages["reports"]
    for i in range(reports.list.count()):
        item = reports.list.item(i)
        if item.data(Qt.ItemDataRole.UserRole):
            reports.list.setCurrentItem(item)
            assert reports.result is not None
    assert len(opened) > 40
    win._closing_for_signout = True
    win.close()
    ctx.close()


def test_toast_outliving_its_window_is_harmless(qtbot):
    """Signing out right after an action closes the window while its toast is still showing.
    The toast's timer must not fire into the deleted window."""
    from PySide6.QtWidgets import QWidget

    from motelmg.ui.widgets.toast import ToastManager
    host = QWidget()
    host.resize(400, 300)
    host.show()
    toasts = ToastManager(host)
    toasts.show("Room 205 is clean", duration=50)
    host.deleteLater()
    qtbot.wait(20)
    qtbot.wait(150)  # the dismiss timer would have fired by now


def test_window_and_dialogs_fit_a_small_laptop_screen(window, qtbot):
    """1366x768 laptops and 1920x1080 at 150% scaling (1280x720) are common at front desks."""
    from motelmg.ui.dialogs.reservation_form import ReservationDialog
    hint = window.minimumSizeHint().expandedTo(window.minimumSize())
    assert hint.width() <= 1240 and hint.height() <= 640, hint
    window.resize(1280, 680)
    for key in window.pages:
        window.navigate(key)
        qtbot.wait(5)
        assert window.width() <= 1280 and window.height() <= 680, key
    dialog = ReservationDialog(window, window, mode="new")
    qtbot.addWidget(dialog)
    dialog.show()
    screen = dialog.screen().availableGeometry()
    assert dialog.height() <= screen.height() and dialog.width() <= screen.width()


def test_toolbar_wraps_and_lets_search_grow(qtbot):
    from PySide6.QtWidgets import QComboBox, QPushButton
    from motelmg.ui.widgets.common import SearchField, toolbar
    host, bar = toolbar()
    qtbot.addWidget(host)
    search, combo, btn = SearchField(), QComboBox(), QPushButton("Export")
    for w in (search, combo, btn):
        bar.addWidget(w)
    host.resize(1000, 40)
    host.show()
    qtbot.wait(5)
    assert search.width() > search.sizeHint().width()  # spare room goes to the search box
    assert combo.y() == search.y() == btn.y()
    narrow = search.minimumWidth() + 20
    host.resize(narrow, bar.heightForWidth(narrow))
    qtbot.wait(5)
    assert btn.y() > search.y()  # wrapped onto another line instead of overlapping
