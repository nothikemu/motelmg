"""HTML documents for printing / PDF export: folio invoice, payment receipt,
registration card and report printouts.

The HTML deliberately sticks to the subset supported by Qt's rich text engine
(tables, inline styles, no flexbox) so it renders identically in the preview,
on paper and in exported PDFs.
"""

from __future__ import annotations

import html
from datetime import datetime

from motelmg.core.enums import ChargeKind, IdType, PaymentKind, ReservationStatus
from motelmg.models import Folio, Payment
from motelmg.services.reports import ReportResult

ACCENT = "#1f4fd1"
MUTED = "#6b7280"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_date(d) -> str:
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else ""


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ") if dt else ""


def _header(ctx, title: str, number: str = "", extra: str = "") -> str:
    s = ctx.settings
    lines = [esc(line) for line in s.property_address_lines()]
    contact = " &middot; ".join(esc(x) for x in (s.get_str("property.phone"), s.get_str("property.email"),
                                                 s.get_str("property.website")) if x)
    tax_id = s.get_str("property.tax_id")
    header_text = s.get_str("invoice.header_text")
    return f"""
<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:14px">
<tr>
  <td valign="top">
    <div style="font-size:20pt; font-weight:700; color:{ACCENT}">{esc(s.property_name)}</div>
    <div style="color:{MUTED}; font-size:9pt">{'<br>'.join(lines)}{'<br>' if lines and contact else ''}{contact}
    {f'<br>Tax ID: {esc(tax_id)}' if tax_id else ''}</div>
    {f'<div style="font-size:9pt; margin-top:4px">{esc(header_text)}</div>' if header_text else ''}
  </td>
  <td valign="top" align="right">
    <div style="font-size:16pt; font-weight:700">{esc(title)}</div>
    {f'<div style="font-size:10pt">No. <b>{esc(number)}</b></div>' if number else ''}
    {extra}
  </td>
</tr>
</table>
<hr style="border:0; border-top:1px solid #d1d5db">
"""


def _footer(ctx) -> str:
    text = ctx.settings.get_str("invoice.footer_text")
    printed = datetime.now().strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    return f"""
<p style="margin-top:22px; text-align:center; color:{MUTED}; font-size:9pt">{esc(text)}</p>
<p style="text-align:center; color:#9ca3af; font-size:7.5pt">Printed {printed}</p>"""


def _wrap(body: str) -> str:
    return f"""<html><head><meta charset="utf-8"><style>
body {{ font-family: 'Inter', 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #111827; }}
table.lines {{ border-collapse: collapse; width: 100%; }}
table.lines th {{ background: #f3f4f6; text-align: left; font-size: 8.5pt; color: #374151; padding: 6px 8px;
                 border-bottom: 1px solid #d1d5db; }}
table.lines td {{ padding: 5px 8px; border-bottom: 1px solid #eef0f3; font-size: 9.5pt; }}
.num {{ text-align: right; }}
.muted {{ color: {MUTED}; }}
</style></head><body>{body}</body></html>"""


def folio_html(ctx, folio: Folio) -> str:
    res = folio.reservation
    money = ctx.settings.money
    guest = ctx.guests.get(res.guest_id)
    is_invoice = bool(folio.invoice_no)
    title = "INVOICE" if is_invoice else ("GUEST FOLIO" if res.status == ReservationStatus.CHECKED_IN else "STATEMENT")
    extra = f'<div style="font-size:9pt">Issued {_fmt_dt(folio.invoice_issued_at)}</div>' if is_invoice else \
        f'<div style="font-size:9pt">Date {_fmt_date(ctx.clock.today())}</div>'
    show_tax_lines = ctx.settings.get_bool("invoice.show_tax_lines")
    show_breakdown = ctx.settings.get_bool("invoice.show_tax_breakdown")
    address = esc(guest.address_text).replace("\n", "<br>")
    stay = f"""
<table width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0 14px 0">
<tr>
 <td valign="top" width="50%">
   <div class="muted" style="font-size:8pt; letter-spacing:1px">BILL TO</div>
   <div style="font-weight:600; font-size:11pt">{esc(guest.full_name)}</div>
   {f'<div>{esc(guest.company)}</div>' if guest.company else ''}
   <div class="muted">{address}</div>
   <div class="muted">{esc(guest.phone)} {('&middot; ' + esc(guest.email)) if guest.email else ''}</div>
 </td>
 <td valign="top" width="50%">
   <table cellspacing="0" cellpadding="2" align="right">
   <tr><td class="muted">Confirmation</td><td><b>{esc(res.confirmation_no)}</b></td></tr>
   <tr><td class="muted">Room</td><td>{esc(res.room_number)} &middot; {esc(res.room_type_name)}</td></tr>
   <tr><td class="muted">Arrival</td><td>{_fmt_date(res.check_in_date)}</td></tr>
   <tr><td class="muted">Departure</td><td>{_fmt_date(res.check_out_date)}</td></tr>
   <tr><td class="muted">Nights / guests</td><td>{res.nights} / {res.adults + res.children}</td></tr>
   </table>
 </td>
</tr></table>"""
    rows = []
    for c in folio.charges:
        if c.is_void:
            continue
        rows.append(f"<tr><td>{_fmt_date(c.service_date)}</td><td>{esc(c.description)}</td>"
                    f"<td class='num'>{c.quantity}</td><td class='num'>{money(c.unit_amount)}</td>"
                    f"<td class='num'>{money(c.amount)}</td></tr>")
    if show_tax_lines:
        for t in folio.tax_lines:
            if not t.is_void:
                rows.append(f"<tr><td class='muted'>{_fmt_date(t.service_date)}</td><td class='muted'>"
                            f"{esc(t.description)}</td><td></td><td></td><td class='num muted'>{money(t.amount)}</td></tr>")
    if not rows:
        rows.append("<tr><td colspan='5' class='muted'>No charges have been posted yet.</td></tr>")
    charges = f"""
<table class="lines" cellspacing="0">
<tr><th width="16%">Date</th><th>Description</th><th class="num" width="7%">Qty</th>
<th class="num" width="15%">Rate</th><th class="num" width="15%">Amount</th></tr>
{''.join(rows)}
</table>"""
    pay_rows = []
    for p in folio.payments:
        if p.is_void:
            continue
        sign = -1 if p.kind != PaymentKind.REFUND else 1
        pay_rows.append(f"<tr><td>{_fmt_dt(p.created_at)}</td><td>{esc(PaymentKind.LABELS[p.kind])} &middot; "
                        f"{esc(p.method_name)}{(' ' + esc(p.reference)) if p.reference else ''}</td>"
                        f"<td>{esc(p.receipt_no)}</td><td class='num'>{money(sign * p.amount)}</td></tr>")
    payments = ""
    if pay_rows:
        payments = f"""
<div style="font-weight:600; margin:16px 0 6px 0">Payments</div>
<table class="lines" cellspacing="0">
<tr><th width="26%">Date</th><th>Details</th><th width="16%">Receipt</th><th class="num" width="15%">Amount</th></tr>
{''.join(pay_rows)}
</table>"""
    tax_rows = ""
    if show_breakdown:
        tax_rows = "".join(f"<tr><td class='muted'>{esc(t.name)}</td><td class='num muted'>{money(t.amount)}</td></tr>"
                           for t in folio.taxes)
    else:
        tax_rows = f"<tr><td class='muted'>Taxes</td><td class='num muted'>{money(folio.tax_total)}</td></tr>"
    balance_label = "Balance due" if folio.balance > 0 else ("Credit" if folio.balance < 0 else "Balance")
    balance_color = "#b91c1c" if folio.balance > 0 else "#047857"
    totals = f"""
<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:14px"><tr><td></td><td width="42%">
<table width="100%" cellspacing="0" cellpadding="4">
<tr><td>Subtotal</td><td class="num">{money(folio.subtotal)}</td></tr>
{tax_rows}
<tr><td style="border-top:1px solid #d1d5db"><b>Total</b></td>
    <td class="num" style="border-top:1px solid #d1d5db"><b>{money(folio.total)}</b></td></tr>
<tr><td>Payments</td><td class="num">{money(-folio.paid)}</td></tr>
<tr><td style="font-size:12pt; color:{balance_color}"><b>{balance_label}</b></td>
    <td class="num" style="font-size:12pt; color:{balance_color}"><b>{money(abs(folio.balance))}</b></td></tr>
</table></td></tr></table>"""
    return _wrap(_header(ctx, title, folio.invoice_no or res.confirmation_no, extra) + stay + charges + payments
                 + totals + _footer(ctx))


def payment_receipt_html(ctx, payment: Payment) -> str:
    money = ctx.settings.money
    kind = PaymentKind.LABELS[payment.kind]
    res = ctx.reservations.get(payment.reservation_id)
    balance = ctx.billing.balance(res.id)
    void = (f"<p style='color:#b91c1c; font-weight:700'>VOID — {esc(payment.void_reason)}</p>"
            if payment.is_void else "")
    body = f"""
{_header(ctx, 'REFUND RECEIPT' if payment.kind == PaymentKind.REFUND else 'PAYMENT RECEIPT', payment.receipt_no,
         f'<div style="font-size:9pt">{_fmt_dt(payment.created_at)}</div>')}
{void}
<table cellspacing="0" cellpadding="5" width="100%" style="margin-top:8px">
<tr><td class="muted" width="35%">{'Refunded to' if payment.kind == PaymentKind.REFUND else 'Received from'}</td>
    <td><b>{esc(payment.guest_name)}</b></td></tr>
<tr><td class="muted">Reservation</td><td>{esc(res.confirmation_no)} &middot; Room {esc(res.room_number)} &middot;
    {_fmt_date(res.check_in_date)} – {_fmt_date(res.check_out_date)}</td></tr>
<tr><td class="muted">Type</td><td>{esc(kind)}</td></tr>
<tr><td class="muted">Method</td><td>{esc(payment.method_name)}{(' &middot; ref ' + esc(payment.reference))
                                                               if payment.reference else ''}</td></tr>
{f'<tr><td class="muted">Notes</td><td>{esc(payment.notes)}</td></tr>' if payment.notes else ''}
<tr><td class="muted">Received by</td><td>{esc(payment.created_by_name)}</td></tr>
<tr><td style="font-size:13pt"><b>Amount</b></td><td style="font-size:13pt"><b>{money(payment.amount)}</b></td></tr>
<tr><td class="muted">Folio balance now</td><td>{money(balance)}</td></tr>
</table>
{_footer(ctx)}"""
    return _wrap(body)


def registration_card_html(ctx, res_id: int) -> str:
    res = ctx.reservations.get(res_id)
    guest = ctx.guests.get(res.guest_id)
    s = ctx.settings
    money = s.money
    id_label = IdType.LABELS.get(guest.id_type, guest.id_type)

    def row(label: str, value: str) -> str:
        return f"<tr><td class='muted' width='30%'>{esc(label)}</td><td>{esc(value) or '&nbsp;'}</td></tr>"

    body = f"""
{_header(ctx, 'REGISTRATION CARD', res.confirmation_no)}
<table class="lines" cellspacing="0">
{row('Guest name', guest.full_name)}
{row('Address', guest.address_text.replace(chr(10), ', '))}
{row('Phone', guest.phone)}{row('Email', guest.email)}
{row('ID document', f'{id_label} {guest.id_number}'.strip())}
{row('Vehicle plate', guest.vehicle_plate)}
{row('Room', f'{res.room_number} - {res.room_type_name}')}
{row('Arrival', _fmt_date(res.check_in_date) + '  (check-in from ' + s.get_str('policy.check_in_time') + ')')}
{row('Departure', _fmt_date(res.check_out_date) + '  (check-out by ' + s.get_str('policy.check_out_time') + ')')}
{row('Guests', f'{res.adults} adult(s), {res.children} child(ren)')}
{row('Nightly rate', money(res.nightly_rate) + (f' less {res.discount_name}' if res.discount_name else ''))}
</table>
<p style="font-size:8.5pt; color:{MUTED}; margin-top:14px">I agree to pay all charges incurred during my stay and to
abide by the property's policies. The property is not responsible for valuables left in the room.
Smoking in non-smoking rooms will incur a cleaning fee.</p>
<table width="100%" style="margin-top:36px"><tr>
<td width="55%" style="border-top:1px solid #111827; padding-top:4px">Guest signature</td><td width="10%"></td>
<td style="border-top:1px solid #111827; padding-top:4px">Date</td></tr></table>
{_footer(ctx)}"""
    return _wrap(body)


def report_html(ctx, report: ReportResult, formatter) -> str:
    """Printable version of a report. ``formatter(value, kind)`` returns display text."""
    head = "".join(f"<th class='{'num' if c.kind in ('money', 'int', 'percent', 'float') else ''}'>{esc(c.title)}</th>"
                   for c in report.columns)
    body_rows = []
    for row in report.rows:
        cells = "".join(
            f"<td class='{'num' if c.kind in ('money', 'int', 'percent', 'float') else ''}'>"
            f"{esc(formatter(row.get(c.key), c.kind))}</td>" for c in report.columns)
        body_rows.append(f"<tr>{cells}</tr>")
    if report.totals:
        cells = "".join(
            f"<td class='{'num' if c.kind in ('money', 'int', 'percent', 'float') else ''}'><b>"
            f"{esc(formatter(report.totals.get(c.key), c.kind) if c.key in report.totals else '')}</b></td>"
            for c in report.columns)
        body_rows.append(f"<tr style='background:#f9fafb'>{cells}</tr>")
    summary = ""
    if report.summary:
        cells = "".join(f"<td style='padding:6px 14px 6px 0'><div class='muted' style='font-size:8pt'>{esc(k)}</div>"
                        f"<div style='font-size:13pt; font-weight:700'>{esc(v)}</div></td>" for k, v in report.summary)
        summary = f"<table cellspacing='0' style='margin:6px 0 12px 0'><tr>{cells}</tr></table>"
    body = f"""
{_header(ctx, report.title.upper(), '', f'<div style="font-size:9pt">{esc(report.subtitle)}</div>')}
{summary}
<table class="lines" cellspacing="0"><tr>{head}</tr>{''.join(body_rows) or
    f"<tr><td colspan='{len(report.columns)}' class='muted'>No data for this period.</td></tr>"}</table>
<p style="text-align:center; color:#9ca3af; font-size:7.5pt; margin-top:16px">Generated
{datetime.now().strftime('%b %d, %Y %I:%M %p')} by {esc(ctx.session.full_name if ctx.session else '')}</p>"""
    return _wrap(body)


__all__ = ["folio_html", "payment_receipt_html", "registration_card_html", "report_html", "ChargeKind"]
