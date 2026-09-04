from decimal import Decimal

import pandas as pd

from display_formatting import (
    format_money, format_percent, optional_attribute, optional_number,
)


class OldFinancialValues:
    current_assets = 1000


def test_missing_bank_field_displays_unavailable_instead_of_raising():
    old_values = OldFinancialValues()
    ratio = optional_attribute(old_values, "bank_equity_ratio")
    assert ratio is None
    assert format_percent(ratio) == "データ取得不可"


def test_formatters_accept_decimal_int_and_pandas_scalar():
    assert format_percent(Decimal("0.092")) == "9.2%"
    assert format_money(1000, "JPY") == "1,000 JPY"
    assert optional_number(pd.Series([0.3]).iloc[0]) == 0.3


def test_unexpected_values_do_not_raise():
    for value in (pd.NA, object(), float("nan"), float("inf")):
        assert format_percent(value) == "データ取得不可"
        assert format_money(value, "JPY") == "データ取得不可"
