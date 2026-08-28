from __future__ import annotations

from dataclasses import dataclass

from edinet_parser import FinancialValues


def safe_div(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None or b == 0 else a / b


def average(current: float | None, prior: float | None) -> float | None:
    values = [value for value in (current, prior) if value is not None]
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class Metrics:
    revenue: float | None
    operating_income: float | None
    net_income: float | None
    avg_assets: float | None
    avg_equity: float | None
    roe: float | None
    roa: float | None
    net_margin: float | None
    operating_margin: float | None
    asset_turnover: float | None
    financial_leverage: float | None

    @property
    def has_financials(self) -> bool:
        return any(value is not None for value in (self.revenue, self.net_income, self.avg_assets, self.avg_equity))


def calculate_metrics(values: FinancialValues) -> Metrics:
    avg_assets = average(values.current_assets, values.prior_assets)
    avg_equity = average(values.current_equity, values.prior_equity)
    return Metrics(values.revenue, values.operating_income, values.net_income, avg_assets, avg_equity,
                   safe_div(values.net_income, avg_equity), safe_div(values.net_income, avg_assets),
                   safe_div(values.net_income, values.revenue), safe_div(values.operating_income, values.revenue),
                   safe_div(values.revenue, avg_assets), safe_div(avg_assets, avg_equity))
