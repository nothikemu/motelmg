"""Money handling.

All monetary values are stored and computed as integer *cents* (1/100 of the
currency unit) to avoid floating point rounding errors. Percentages are stored
as integer *basis points* (1/100 of a percent, so 8.25% == 825).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from motelmg.core.errors import ValidationError

MAX_AMOUNT_CENTS = 100_000_000_00  # 100 million, sanity cap for any single amount


@dataclass(frozen=True)
class CurrencyFormat:
    code: str = "USD"
    symbol: str = "$"
    decimals: int = 2
    symbol_after: bool = False
    thousands_sep: str = ","
    decimal_sep: str = "."

    def format(self, cents: int | None, *, with_symbol: bool = True, signed: bool = False) -> str:
        if cents is None:
            return ""
        negative = cents < 0
        value = Decimal(abs(int(cents))) / Decimal(100)
        quant = Decimal(1) if self.decimals == 0 else Decimal(1).scaleb(-self.decimals)
        value = value.quantize(quant, rounding=ROUND_HALF_UP)
        text = f"{value:,.{self.decimals}f}"
        text = text.replace(",", "\x00").replace(".", self.decimal_sep).replace("\x00", self.thousands_sep)
        if with_symbol and self.symbol:
            text = f"{text} {self.symbol}" if self.symbol_after else f"{self.symbol}{text}"
        if negative:
            text = f"-{text}"
        elif signed and cents > 0:
            text = f"+{text}"
        return text

    def plain(self, cents: int | None) -> str:
        """Machine friendly decimal string (for CSV exports)."""
        if cents is None:
            return ""
        return f"{Decimal(int(cents)) / Decimal(100):.2f}"


COMMON_CURRENCIES: list[tuple[str, str, str, int]] = [
    # code, name, symbol, decimals
    ("USD", "US Dollar", "$", 2),
    ("CAD", "Canadian Dollar", "$", 2),
    ("EUR", "Euro", "€", 2),
    ("GBP", "British Pound", "£", 2),
    ("AUD", "Australian Dollar", "$", 2),
    ("NZD", "New Zealand Dollar", "$", 2),
    ("MXN", "Mexican Peso", "$", 2),
    ("INR", "Indian Rupee", "₹", 2),
    ("JPY", "Japanese Yen", "¥", 0),
    ("CHF", "Swiss Franc", "CHF ", 2),
    ("ZAR", "South African Rand", "R", 2),
    ("PHP", "Philippine Peso", "₱", 2),
    ("BRL", "Brazilian Real", "R$", 2),
]


def parse_amount(value: object, *, field: str | None = None, allow_negative: bool = False,
                 allow_zero: bool = True, label: str = "Amount") -> int:
    """Parse user input (``"1,234.50"``, ``12``, ``Decimal``) into cents."""
    if isinstance(value, bool):
        raise ValidationError(f"{label} is not a valid number.", field=field)
    if isinstance(value, int):
        cents = value * 100
    else:
        text = str(value if value is not None else "").strip()
        for ch in ("$", "€", "£", "¥", "₹", "₱", ",", " ", " "):
            text = text.replace(ch, "")
        if not text:
            raise ValidationError(f"{label} is required.", field=field)
        try:
            dec = Decimal(text)
        except InvalidOperation:
            raise ValidationError(f"{label} is not a valid number.", field=field) from None
        if not dec.is_finite():
            raise ValidationError(f"{label} is not a valid number.", field=field)
        if abs(dec) * 100 > MAX_AMOUNT_CENTS:
            raise ValidationError(f"{label} is unrealistically large.", field=field)
        cents = int((dec * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if cents < 0 and not allow_negative:
        raise ValidationError(f"{label} cannot be negative.", field=field)
    if cents == 0 and not allow_zero:
        raise ValidationError(f"{label} must be greater than zero.", field=field)
    if abs(cents) > MAX_AMOUNT_CENTS:
        raise ValidationError(f"{label} is unrealistically large.", field=field)
    return cents


def cents_to_decimal(cents: int) -> Decimal:
    return Decimal(int(cents)) / Decimal(100)


def percent_of(cents: int, basis_points: int) -> int:
    """``cents * basis_points / 10000`` rounded half away from zero."""
    value = Decimal(int(cents)) * Decimal(int(basis_points)) / Decimal(10000)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_percent(value: object, *, field: str | None = None, label: str = "Percentage",
                  maximum: float = 100.0) -> int:
    """Parse ``"8.25"`` or ``"8.25%"`` into basis points (825)."""
    text = str(value if value is not None else "").replace("%", "").strip()
    if not text:
        raise ValidationError(f"{label} is required.", field=field)
    try:
        dec = Decimal(text)
    except InvalidOperation:
        raise ValidationError(f"{label} is not a valid number.", field=field) from None
    if not dec.is_finite() or dec < 0:
        raise ValidationError(f"{label} must be zero or positive.", field=field)
    if dec > Decimal(str(maximum)):
        raise ValidationError(f"{label} cannot exceed {maximum:g}%.", field=field)
    return int((dec * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_percent(basis_points: int | None) -> str:
    if basis_points is None:
        return ""
    value = Decimal(int(basis_points)) / Decimal(100)
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"
