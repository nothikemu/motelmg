"""Configurable billing catalog: taxes, fees/extras, discounts and payment methods."""

from __future__ import annotations

from typing import Any

from motelmg.core import validation as v
from motelmg.core.errors import ConflictError, NotFoundError, ValidationError
from motelmg.core.money import parse_amount, parse_percent
from motelmg.models import ChargeItem, DiscountType, PaymentMethod, Tax

TABLE_LABELS = {
    "taxes": "tax",
    "charge_items": "charge item",
    "discount_types": "discount",
    "payment_methods": "payment method",
}


class CatalogService:
    def __init__(self, ctx):
        self.ctx = ctx

    @property
    def repo(self):
        return self.ctx.repo_folio

    # -- queries -------------------------------------------------------------
    def taxes(self, include_inactive: bool = False) -> list[Tax]:
        return self.repo.taxes(include_inactive)

    def charge_items(self, include_inactive: bool = False) -> list[ChargeItem]:
        return self.repo.charge_items(include_inactive)

    def discount_types(self, include_inactive: bool = False) -> list[DiscountType]:
        return self.repo.discount_types(include_inactive)

    def payment_methods(self, include_inactive: bool = False) -> list[PaymentMethod]:
        return self.repo.payment_methods(include_inactive)

    def system_item(self, code: str) -> ChargeItem | None:
        return self.repo.charge_item_by_code(code)

    # -- mutations -----------------------------------------------------------
    def save_tax(self, tax_id: int | None, data: dict[str, Any]) -> int:
        kind = data.get("kind", "percent")
        if kind not in ("percent", "fixed_per_night"):
            raise ValidationError("Invalid tax type.", field="kind")
        applies_to = data.get("applies_to", "all")
        if applies_to not in ("room", "extras", "all"):
            raise ValidationError("Invalid tax scope.", field="applies_to")
        if kind == "percent":
            value = parse_percent(data.get("value"), field="value", label="Tax rate", maximum=50)
        else:
            value = parse_amount(data.get("value"), field="value", label="Tax amount")
            applies_to = "room"
        values = {
            "name": v.required(data.get("name"), "Tax name", "name", max_len=60),
            "kind": kind, "value": value, "applies_to": applies_to,
            "is_active": int(bool(data.get("is_active", True))),
            "sort_order": int(data.get("sort_order") or 0),
        }
        return self._save("taxes", tax_id, values)

    def save_charge_item(self, item_id: int | None, data: dict[str, Any]) -> int:
        category = data.get("category", "extra")
        if category not in ("fee", "extra"):
            raise ValidationError("Invalid category.", field="category")
        auto = data.get("auto_apply", "none")
        if auto not in ("none", "per_night", "per_stay"):
            raise ValidationError("Invalid auto-apply option.", field="auto_apply")
        values = {
            "name": v.required(data.get("name"), "Name", "name", max_len=60),
            "category": category,
            "default_amount": parse_amount(data.get("default_amount") or "0", field="default_amount",
                                           label="Default amount"),
            "taxable": int(bool(data.get("taxable", True))),
            "auto_apply": auto,
            "is_active": int(bool(data.get("is_active", True))),
            "sort_order": int(data.get("sort_order") or 0),
        }
        if item_id:
            existing = self.repo.charge_item(item_id)
            if existing and existing.system_code:
                values["auto_apply"] = "none"
                if not values["is_active"]:
                    raise ConflictError("Built-in fees cannot be deactivated; set the amount to 0 instead.")
        if auto != "none" and values["default_amount"] == 0:
            raise ValidationError("Automatic charges need an amount greater than zero.", field="default_amount")
        return self._save("charge_items", item_id, values)

    def save_discount(self, discount_id: int | None, data: dict[str, Any]) -> int:
        bp = parse_percent(data.get("percent"), field="percent", label="Discount")
        if bp <= 0:
            raise ValidationError("Discount must be greater than zero.", field="percent")
        values = {
            "name": v.required(data.get("name"), "Name", "name", max_len=60),
            "percent_bp": bp,
            "is_active": int(bool(data.get("is_active", True))),
            "sort_order": int(data.get("sort_order") or 0),
        }
        return self._save("discount_types", discount_id, values)

    def save_payment_method(self, method_id: int | None, data: dict[str, Any]) -> int:
        values = {
            "name": v.required(data.get("name"), "Name", "name", max_len=40),
            "requires_reference": int(bool(data.get("requires_reference"))),
            "is_cash": int(bool(data.get("is_cash"))),
            "is_active": int(bool(data.get("is_active", True))),
            "sort_order": int(data.get("sort_order") or 0),
        }
        if method_id and not values["is_active"]:
            others = [m for m in self.repo.payment_methods() if m.id != method_id]
            if not others:
                raise ConflictError("At least one payment method must stay active.")
        return self._save("payment_methods", method_id, values)

    def _save(self, table: str, row_id: int | None, values: dict[str, Any]) -> int:
        self.ctx.require("settings.manage")
        label = TABLE_LABELS[table]
        with self.ctx.db.transaction():
            new_id = self.repo.save_catalog_row(table, row_id, values)
            self.ctx.audit.log(f"settings.{table}", table, new_id,
                               f"{'Updated' if row_id else 'Created'} {label} '{values['name']}'", values)
        self.ctx.events.emit("settings", "catalog")
        return new_id

    def delete(self, table: str, row_id: int) -> None:
        self.ctx.require("settings.manage")
        if table not in TABLE_LABELS:
            raise ValidationError("Unknown catalog.")
        label = TABLE_LABELS[table]
        if table == "charge_items":
            item = self.repo.charge_item(row_id)
            if item and item.system_code:
                raise ConflictError("Built-in fees cannot be deleted.")
        if self.repo.catalog_row_in_use(table, row_id):
            raise ConflictError(f"This {label} has been used on guest folios and cannot be deleted. "
                                "Mark it inactive instead.")
        if table == "payment_methods" and len(self.repo.payment_methods()) <= 1:
            raise ConflictError("At least one payment method is required.")
        row = self.ctx.db.one(f"SELECT name FROM {table} WHERE id = ?", (row_id,))
        if not row:
            raise NotFoundError(f"The {label} no longer exists.")
        with self.ctx.db.transaction():
            self.repo.delete_catalog_row(table, row_id)
            self.ctx.audit.log(f"settings.{table}_delete", table, row_id, f"Deleted {label} '{row['name']}'")
        self.ctx.events.emit("settings", "catalog")
