"""First-launch setup: property details, administrator, rates and rooms."""

from __future__ import annotations

from typing import Any

from motelmg.core import validation as v
from motelmg.core.errors import ConflictError, ValidationError
from motelmg.core.money import COMMON_CURRENCIES, parse_amount, parse_percent
from motelmg.core.permissions import ADMIN_ROLE
from motelmg.services.auth import validate_password_strength

DEFAULT_ROOM_TYPES = [
    {"code": "SQ", "name": "Standard Queen", "beds": "1 Queen", "max_occupancy": 2, "base_rate": "79.00",
     "description": "Comfortable room with one queen bed, TV, Wi-Fi, mini fridge and microwave."},
    {"code": "DQ", "name": "Double Queen", "beds": "2 Queens", "max_occupancy": 4, "base_rate": "95.00",
     "description": "Two queen beds - ideal for families and groups."},
    {"code": "KS", "name": "King Suite", "beds": "1 King + sofa bed", "max_occupancy": 4, "base_rate": "129.00",
     "description": "Spacious suite with king bed, sitting area and kitchenette."},
]

DEFAULT_ROOMS = (
    [{"number": str(n), "type_code": "SQ", "floor": "1"} for n in range(101, 107)]
    + [{"number": str(n), "type_code": "DQ", "floor": "1"} for n in range(107, 111)]
    + [{"number": str(n), "type_code": "DQ", "floor": "2"} for n in range(201, 205)]
    + [{"number": str(n), "type_code": "KS", "floor": "2"} for n in range(205, 207)]
)


class SetupService:
    def __init__(self, ctx):
        self.ctx = ctx

    def needed(self) -> bool:
        return not self.ctx.settings.setup_complete or not self.ctx.auth.has_users()

    def validate_admin(self, admin: dict[str, Any]) -> None:
        errors: dict[str, str] = {}
        if not v.clean(admin.get("full_name")):
            errors["full_name"] = "Your name is required."
        username = v.clean(admin.get("username")).lower()
        if not v.USERNAME_RE.match(username):
            errors["username"] = "3-32 characters: letters, numbers, dot, dash or underscore."
        password = admin.get("password") or ""
        try:
            validate_password_strength(password, username=username)
        except ValidationError as exc:
            errors.update(exc.field_errors)
        if password != (admin.get("confirm") or ""):
            errors["confirm"] = "Passwords do not match."
        if errors:
            raise ValidationError(field_errors=errors)

    def complete(self, data: dict[str, Any]) -> None:
        ctx = self.ctx
        if ctx.settings.setup_complete and ctx.auth.has_users():
            raise ConflictError("Setup has already been completed.")
        admin = data["admin"]
        self.validate_admin(admin)
        prop = {k: v.clean(val) for k, val in data.get("property", {}).items()}
        if not prop.get("property.name"):
            raise ValidationError("Motel name is required.", field="property.name")
        room_types = data.get("room_types") or []
        rooms = data.get("rooms") or []
        if not room_types:
            raise ValidationError("Add at least one room type.")
        if not rooms:
            raise ValidationError("Add at least one room.")
        currency = next((c for c in COMMON_CURRENCIES if c[0] == data.get("currency", "USD")), COMMON_CURRENCIES[0])
        tax_rate = parse_percent(data.get("tax_rate") or "0", field="tax_rate", label="Tax rate", maximum=50)
        nightly_tax = parse_amount(data.get("nightly_tax") or "0", field="nightly_tax", label="Per-night tax")
        try:
            with ctx.db.transaction():
                ctx.users.create_user({
                    "full_name": admin["full_name"], "username": admin["username"], "email": admin.get("email", ""),
                    "role_id": ctx.repo_staff.get_role_by_name(ADMIN_ROLE).id}, admin["password"], must_change=False)
                ctx.auth.login(admin["username"], admin["password"])
                settings = dict(prop)
                settings.update({
                    "currency.code": currency[0], "currency.symbol": currency[2], "currency.decimals": currency[3],
                    "policy.check_in_time": data.get("check_in_time") or "15:00",
                    "policy.check_out_time": data.get("check_out_time") or "11:00",
                    "app.theme": data.get("theme") or "light",
                })
                ctx.settings.update(settings)
                if tax_rate:
                    ctx.catalog.save_tax(None, {"name": data.get("tax_name") or "Sales tax", "kind": "percent",
                                                "value": data.get("tax_rate"), "applies_to": "all"})
                if nightly_tax:
                    ctx.catalog.save_tax(None, {"name": data.get("nightly_tax_name") or "Occupancy tax",
                                                "kind": "fixed_per_night", "value": data.get("nightly_tax"),
                                                "applies_to": "room"})
                type_ids: dict[str, int] = {}
                for order, rt in enumerate(room_types):
                    type_ids[str(rt["code"]).upper()] = ctx.rooms.save_type(None, {**rt, "sort_order": order})
                for room in rooms:
                    type_id = type_ids.get(str(room.get("type_code", "")).upper())
                    if type_id is None:
                        raise ValidationError(f"Room {room.get('number')} uses an unknown room type.")
                    ctx.rooms.save_room(None, {"number": room["number"], "room_type_id": type_id,
                                               "floor": room.get("floor", "")})
                ctx.settings.update({"app.setup_complete": True})
                ctx.audit.log("setup.complete", "settings", None,
                              f"Initial setup completed for {prop['property.name']}: {len(room_types)} room types, "
                              f"{len(rooms)} rooms")
        except Exception:
            ctx.session = None
            ctx.settings.invalidate()
            raise
        if data.get("demo"):
            from motelmg.services.demo import generate_demo_data
            generate_demo_data(ctx)
        ctx.events.emit("*")
