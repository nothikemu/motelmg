from __future__ import annotations

from motelmg.core import validation as v
from motelmg.core.errors import NotFoundError, PermissionDenied
from motelmg.models import Note


class NoteService:
    """Free-form notes attached to guests, reservations or rooms."""

    def __init__(self, ctx):
        self.ctx = ctx

    def list(self, *, guest_id: int | None = None, reservation_id: int | None = None,
             room_id: int | None = None) -> list[Note]:
        return self.ctx.repo_notes.list(guest_id=guest_id, reservation_id=reservation_id, room_id=room_id)

    def important_for_guest(self, guest_id: int) -> list[Note]:
        return self.ctx.repo_notes.important_for_guest(guest_id)

    def add(self, body: str, *, important: bool = False, guest_id: int | None = None,
            reservation_id: int | None = None, room_id: int | None = None) -> int:
        if self.ctx.session is None:
            raise PermissionDenied("You must be signed in.")
        body = v.required(body, "Note", "body", max_len=2000)
        entity, entity_id = (("guest", guest_id) if guest_id else
                             ("reservation", reservation_id) if reservation_id else ("room", room_id))
        with self.ctx.db.transaction():
            note_id = self.ctx.repo_notes.add(body=body, important=important, user_id=self.ctx.user_id,
                                              ts=self.ctx.now_str(), guest_id=guest_id,
                                              reservation_id=reservation_id, room_id=room_id)
            self.ctx.audit.log("notes.add", entity, entity_id, f"Added note to {entity}: {body[:60]}")
        self.ctx.events.emit("notes")
        return note_id

    def delete(self, note_id: int) -> None:
        row = self.ctx.repo_notes.get(note_id)
        if not row:
            raise NotFoundError("Note not found.")
        session = self.ctx.session
        if session is None or (row["created_by"] != session.user_id and not session.has("staff.manage")
                               and not session.has("reservations.edit")):
            raise PermissionDenied("You can only delete notes you wrote.")
        entity, entity_id = (("guest", row["guest_id"]) if row["guest_id"] else
                             ("reservation", row["reservation_id"]) if row["reservation_id"]
                             else ("room", row["room_id"]))
        with self.ctx.db.transaction():
            self.ctx.repo_notes.delete(note_id)
            self.ctx.audit.log("notes.delete", entity, entity_id, f"Deleted note: {row['body'][:60]}")
        self.ctx.events.emit("notes")
