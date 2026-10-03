"""Global search across guests, reservations, rooms, payments and tickets."""

from __future__ import annotations

from dataclasses import dataclass

from motelmg.core.enums import ReservationStatus, ServiceStatus, TicketStatus


@dataclass
class SearchHit:
    kind: str  # guest | reservation | room | payment | ticket
    id: int
    title: str
    subtitle: str
    badge: str = ""
    tone: str = "gray"


class SearchService:
    def __init__(self, ctx):
        self.ctx = ctx

    def search(self, text: str, limit_per_kind: int = 8) -> list[SearchHit]:
        text = (text or "").strip()
        if len(text) < 2:
            return []
        hits: list[SearchHit] = []
        ctx = self.ctx
        money = ctx.settings.money
        if ctx.can("rooms.view"):
            for room in ctx.repo_rooms.list_rooms():
                if room.number.lower().startswith(text.lower()) or text.lower() in room.type_name.lower():
                    hits.append(SearchHit("room", room.id, f"Room {room.number}",
                                          f"{room.type_name} · Floor {room.floor or '-'}",
                                          ServiceStatus.LABELS[room.service_status] if room.service_status != "in_service"
                                          else room.hk_status.title(), "gray"))
                    if len([h for h in hits if h.kind == "room"]) >= limit_per_kind:
                        break
        if ctx.can("reservations.view"):
            for res in ctx.repo_res.search(text=text, limit=limit_per_kind,
                                           order="r.status = 'checked_in' DESC, r.check_in_date DESC"):
                hits.append(SearchHit(
                    "reservation", res.id, f"{res.confirmation_no} · {res.guest_name}",
                    f"Room {res.room_number} · {res.check_in_date:%b %d} → {res.check_out_date:%b %d, %Y}",
                    ReservationStatus.LABELS[res.status], ReservationStatus.TONES[res.status]))
        if ctx.can("guests.view"):
            for guest in ctx.repo_guests.search(text, limit=limit_per_kind):
                details = " · ".join(p for p in (guest.phone, guest.email, guest.city) if p)
                hits.append(SearchHit("guest", guest.id, guest.full_name, details or "No contact details",
                                      "In house" if guest.in_house else ("VIP" if guest.is_vip else
                                                                          ("Do not rent" if guest.is_banned else "")),
                                      "blue" if guest.in_house else ("amber" if guest.is_vip else "red")))
        if ctx.can("billing.view") and len(text) >= 3:
            for p in ctx.repo_folio.search_payments(text=text, limit=limit_per_kind):
                hits.append(SearchHit("payment", p.id, f"{p.receipt_no} · {money(p.signed_amount)}",
                                      f"{p.guest_name} · {p.method_name} · {p.created_at:%b %d, %Y}",
                                      "Void" if p.is_void else p.kind.title(), "gray"))
        if ctx.can("maintenance.view"):
            for t in ctx.repo_maint.search(text=text, limit=limit_per_kind):
                hits.append(SearchHit("ticket", t.id, f"#{t.id} {t.title}", t.where,
                                      TicketStatus.LABELS[t.status], TicketStatus.TONES[t.status]))
        return hits
