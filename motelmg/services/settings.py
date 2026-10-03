from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Any

from motelmg.core import paths
from motelmg.core.config import DEFAULT_SETTINGS
from motelmg.core.dates import parse_time
from motelmg.core.errors import ValidationError
from motelmg.core.money import CurrencyFormat


class SettingsService:
    """Typed, cached access to the ``settings`` table."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._cache: dict[str, Any] | None = None

    def invalidate(self) -> None:
        self._cache = None

    def _all(self) -> dict[str, Any]:
        if self._cache is None:
            values = dict(DEFAULT_SETTINGS)
            values.update(self.ctx.repo_settings.all())
            self._cache = values
        return self._cache

    def get(self, key: str, default: Any = None) -> Any:
        values = self._all()
        if key in values:
            return values[key]
        return DEFAULT_SETTINGS.get(key, default)

    def get_str(self, key: str) -> str:
        value = self.get(key, "")
        return "" if value is None else str(value)

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key, 0))
        except (TypeError, ValueError):
            return int(DEFAULT_SETTINGS.get(key, 0) or 0)

    def get_bool(self, key: str) -> bool:
        return bool(self.get(key, False))

    def section(self, prefix: str) -> dict[str, Any]:
        return {k: v for k, v in self._all().items() if k.startswith(prefix)}

    def update(self, values: dict[str, Any], *, audit: bool = True, require_permission: bool = True) -> None:
        if require_permission:
            self.ctx.require("settings.manage")
        unknown = [k for k in values if k not in DEFAULT_SETTINGS]
        if unknown:
            raise ValidationError(f"Unknown setting: {unknown[0]}")
        self._validate(values)
        changed = {k: v for k, v in values.items() if self.get(k) != v}
        if not changed:
            return
        with self.ctx.db.transaction():
            for key, value in changed.items():
                self.ctx.repo_settings.set(key, value)
            if audit:
                sections = sorted({k.split(".")[0] for k in changed})
                self.ctx.audit.log("settings.update", "settings", None,
                                   f"Updated settings: {', '.join(sections)}",
                                   {k: v for k, v in changed.items() if "password" not in k})
        self.invalidate()
        self.ctx.events.emit("settings")

    def _validate(self, values: dict[str, Any]) -> None:
        if "property.name" in values and not str(values["property.name"]).strip():
            raise ValidationError("Motel name is required.", field="property.name")
        for key in ("policy.check_in_time", "policy.check_out_time"):
            if key in values:
                parse_time(values[key], field=key, label="Time")
        numeric_ranges = {
            "policy.late_checkout_grace_minutes": (0, 600),
            "policy.early_checkin_grace_minutes": (0, 600),
            "policy.max_nights": (1, 365),
            "policy.booking_horizon_days": (30, 1825),
            "policy.deposit_percent": (0, 100),
            "backup.keep": (1, 365),
            "app.auto_lock_minutes": (0, 240),
            "notify.arrival_window_hours": (0, 24),
            "currency.decimals": (0, 2),
        }
        for key, (lo, hi) in numeric_ranges.items():
            if key in values:
                try:
                    number = int(values[key])
                except (TypeError, ValueError):
                    raise ValidationError("Enter a whole number.", field=key) from None
                if not lo <= number <= hi:
                    raise ValidationError(f"Value must be between {lo} and {hi}.", field=key)
        if "backup.frequency" in values and values["backup.frequency"] not in ("daily", "weekly", "on_exit"):
            raise ValidationError("Invalid backup frequency.", field="backup.frequency")
        if "app.theme" in values and values["app.theme"] not in ("light", "dark", "system"):
            raise ValidationError("Invalid theme.", field="app.theme")
        if values.get("backup.directory"):
            folder = Path(str(values["backup.directory"])).expanduser()
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise ValidationError("The backup folder cannot be created or is not writable.",
                                      field="backup.directory") from None
        for key in ("numbering.reservation_prefix", "numbering.invoice_prefix", "numbering.receipt_prefix"):
            if key in values and len(str(values[key])) > 8:
                raise ValidationError("Prefixes can be at most 8 characters.", field=key)

    # -- typed helpers -------------------------------------------------------
    @property
    def property_name(self) -> str:
        return self.get_str("property.name") or "My Motel"

    def currency(self) -> CurrencyFormat:
        return CurrencyFormat(
            code=self.get_str("currency.code") or "USD",
            symbol=self.get_str("currency.symbol"),
            decimals=self.get_int("currency.decimals"),
            symbol_after=self.get_bool("currency.symbol_after"),
            thousands_sep=self.get_str("currency.thousands_sep"),
            decimal_sep=self.get_str("currency.decimal_sep") or ".",
        )

    def money(self, cents: int | None, **kwargs) -> str:
        return self.currency().format(cents, **kwargs)

    def check_in_time(self) -> time:
        return parse_time(self.get_str("policy.check_in_time") or "15:00")

    def check_out_time(self) -> time:
        return parse_time(self.get_str("policy.check_out_time") or "11:00")

    def backup_dir(self) -> Path:
        custom = self.get_str("backup.directory")
        if custom:
            path = Path(custom).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            return path
        return paths.default_backup_dir()

    @property
    def setup_complete(self) -> bool:
        return self.get_bool("app.setup_complete")

    def property_address_lines(self) -> list[str]:
        city_line = " ".join(p for p in (
            self.get_str("property.city") + ("," if self.get_str("property.city") and self.get_str("property.state")
                                             else ""),
            self.get_str("property.state"), self.get_str("property.postal_code")) if p)
        lines = [self.get_str("property.address1"), self.get_str("property.address2"), city_line,
                 self.get_str("property.country")]
        return [line for line in lines if line.strip()]
