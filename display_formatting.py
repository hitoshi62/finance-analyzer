from __future__ import annotations

import math
from typing import Any


UNAVAILABLE = "データ取得不可"


def optional_number(value: Any) -> float | None:
    """Convert ordinary, Decimal, and scalar-like values without raising."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def optional_attribute(value: Any, name: str) -> Any:
    """Read a field from current or older cached value objects safely."""
    try:
        return getattr(value, name, None)
    except (AttributeError, TypeError):
        return None


def format_percent(value: Any) -> str:
    number = optional_number(value)
    return UNAVAILABLE if number is None else f"{number * 100:.1f}%"


def format_multiple(value: Any, unit: str = "回") -> str:
    number = optional_number(value)
    return UNAVAILABLE if number is None else f"{number:.2f}{unit}"


def format_money(value: Any, currency: Any) -> str:
    number = optional_number(value)
    if number is None:
        return UNAVAILABLE
    unit = "" if currency is None else str(currency).strip()
    amount = abs(number)
    if amount >= 1e12:
        return f"{number/1e12:.2f}兆 {unit}".strip()
    if amount >= 1e8:
        return f"{number/1e8:.1f}億 {unit}".strip()
    if amount >= 1e6:
        return f"{number/1e6:.1f}百万 {unit}".strip()
    return f"{number:,.0f} {unit}".strip()
