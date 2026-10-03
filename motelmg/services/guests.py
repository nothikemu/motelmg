"""Guest profiles."""

from __future__ import annotations

from typing import Any

from motelmg.core import validation as v
from motelmg.core.dates import parse_optional_date
from motelmg.core.enums import IdType
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.models import Guest, Reservation

TEXT_FIELDS = [
    # key, label, max length
    ("address_line1", "Address", 120), ("address_line2", "Address line 2", 120), ("city", "City", 80),
    ("state", "State / province", 60), ("postal_code", "Postal code", 20), ("country", "Country", 60),
    ("company", "Company", 100), ("vehicle_plate", "Vehicle plate", 20), ("preferences", "Preferences", 1000),
    ("banned_reason", "Reason", 300),
]


class GuestService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_guests

    def search(self, text: str = "", **filters) -> list[Guest]:
        self.ctx.require("guests.view")
        return self.repo.search(text, **filters)

    def get(self, guest_id: int) -> Guest:
        guest = self.repo.get(guest_id)
        if not guest:
            raise NotFoundError("Guest not found. It may have been deleted.")
        return guest

    def history(self, guest_id: int) -> list[Reservation]:
        return self.ctx.repo_res.search(guest_id=guest_id, order="r.check_in_date DESC")

    def _clean(self, data: dict[str, Any]) -> dict[str, Any]:
        errors: dict[str, str] = {}
        values: dict[str, Any] = {}

        def run(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValidationError as exc:
                errors.update(exc.field_errors)
                return ""

        values["first_name"] = run(v.required, data.get("first_name"), "First name", "first_name", max_len=60)
        values["last_name"] = run(v.required, data.get("last_name"), "Last name", "last_name", max_len=60)
        values["email"] = run(v.email, data.get("email"))
        values["phone"] = run(v.phone, data.get("phone"))
        for key, label, max_len in TEXT_FIELDS:
            values[key] = run(v.optional, data.get(key), label, key, max_len=max_len)
        id_type = v.clean(data.get("id_type"))
        if id_type and id_type not in IdType.LABELS:
            errors["id_type"] = "Select a valid ID type."
        id_number = v.clean(data.get("id_number")).upper()
        if id_number and not id_type:
            errors["id_type"] = "Select the type of ID document."
        if len(id_number) > 40:
            errors["id_number"] = "ID number is too long."
        values["id_type"] = id_type if id_number else ""
        values["id_number"] = id_number
        values["id_expiry"] = run(parse_optional_date, data.get("id_expiry"), field="id_expiry", label="ID expiry")
        dob = run(parse_optional_date, data.get("date_of_birth"), field="date_of_birth", label="Date of birth")
        today = self.ctx.clock.today()
        if dob and dob > today:
            errors["date_of_birth"] = "Date of birth cannot be in the future."
        elif dob and (today.year - dob.year) > 120:
            errors["date_of_birth"] = "Please check the date of birth."
        values["date_of_birth"] = dob
        values["vehicle_plate"] = (values.get("vehicle_plate") or "").upper()
        values["is_vip"] = int(bool(data.get("is_vip")))
        values["is_banned"] = int(bool(data.get("is_banned")))
        if values["is_banned"] and not values.get("banned_reason"):
            errors["banned_reason"] = "Please record why this guest may not book."
        if not values["is_banned"]:
            values["banned_reason"] = ""
        if errors:
            raise ValidationError(field_errors=errors)
        for key in ("id_expiry", "date_of_birth"):
            values[key] = values[key].isoformat() if values[key] else None
        values["phone_digits"] = v.digits_only(values["phone"])
        values["first_name"] = values["first_name"][:1].upper() + values["first_name"][1:]
        values["last_name"] = values["last_name"][:1].upper() + values["last_name"][1:]
        return values

    def find_duplicates(self, data: dict[str, Any], exclude_id: int | None = None) -> list[Guest]:
        first = v.clean(data.get("first_name"))
        last = v.clean(data.get("last_name"))
        email = v.clean(data.get("email")).lower()
        digits = v.digits_only(v.clean(data.get("phone")))
        id_number = v.clean(data.get("id_number")).upper()
        return self.repo.possible_duplicates(first, last, email, digits, id_number, exclude_id)

    def create(self, data: dict[str, Any]) -> int:
        self.ctx.require("guests.edit")
        values = self._clean(data)
        now = self.ctx.now_str()
        values.update({"created_at": now, "updated_at": now, "created_by": self.ctx.user_id})
        with self.ctx.db.transaction():
            guest_id = self.repo.insert(values)
            self.ctx.audit.log("guests.create", "guest", guest_id,
                               f"Created guest {values['first_name']} {values['last_name']}")
        self.ctx.events.emit("guests")
        return guest_id

    def update(self, guest_id: int, data: dict[str, Any]) -> None:
        self.ctx.require("guests.edit")
        old = self.get(guest_id)
        values = self._clean(data)
        values["updated_at"] = self.ctx.now_str()
        changed = [k for k, val in values.items()
                   if k not in ("updated_at", "phone_digits") and str(getattr(old, k, "") or "") != str(val or "")
                   and not (k in ("is_vip", "is_banned") and bool(getattr(old, k)) == bool(val))]
        with self.ctx.db.transaction():
            self.repo.update(guest_id, values)
            if changed:
                summary = f"Updated guest {values['first_name']} {values['last_name']}"
                if "is_banned" in changed:
                    summary += " — flagged DO NOT RENT" if values["is_banned"] else " — DNR flag removed"
                self.ctx.audit.log("guests.update", "guest", guest_id, summary, {"fields": changed})
        self.ctx.events.emit("guests", "reservations")

    def delete(self, guest_id: int) -> None:
        self.ctx.require("guests.delete")
        guest = self.get(guest_id)
        count = self.repo.reservation_count(guest_id)
        if count:
            raise ConflictError(
                f"{guest.full_name} has {count} reservation(s) on file. Guests with stay or billing history "
                "cannot be deleted because the financial records must be preserved.")
        with self.ctx.db.transaction():
            self.repo.delete(guest_id)
            self.ctx.audit.log("guests.delete", "guest", guest_id, f"Deleted guest {guest.full_name}")
        self.ctx.events.emit("guests")

    def ensure_bookable(self, guest_id: int) -> Guest:
        guest = self.get(guest_id)
        if guest.is_banned:
            raise ConflictError(f"{guest.full_name} is flagged DO NOT RENT"
                                + (f": {guest.banned_reason}" if guest.banned_reason else ".")
                                + " A manager must remove the flag on the guest profile first.")
        return guest

    def update_identity(self, guest_id: int, id_type: str, id_number: str, vehicle_plate: str | None = None) -> None:
        """Quick update of ID details captured at the front desk during check-in."""
        self.ctx.require("reservations.checkin")
        guest = self.get(guest_id)
        data = {f: getattr(guest, f) for f in (
            "first_name", "last_name", "email", "phone", "address_line1", "address_line2", "city", "state",
            "postal_code", "country", "company", "preferences", "is_vip", "is_banned", "banned_reason",
            "id_expiry", "date_of_birth", "vehicle_plate")}
        data.update({"id_type": id_type, "id_number": id_number})
        if vehicle_plate is not None:
            data["vehicle_plate"] = vehicle_plate
        values = self._clean(data)
        values["updated_at"] = self.ctx.now_str()
        with self.ctx.db.transaction():
            self.repo.update(guest_id, values)
            self.ctx.audit.log("guests.identity", "guest", guest_id, f"Recorded ID for {guest.full_name}")
        self.ctx.events.emit("guests")
