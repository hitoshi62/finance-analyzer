from __future__ import annotations

import io
import math
import re
import zipfile
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from edinet_client import EdinetError

CONCEPTS = {
    "revenue": ("Revenue", "Revenues", "NetSales", "OperatingRevenue1", "OperatingRevenues"),
    "operating_income": ("OperatingIncomeLoss", "OperatingProfitLoss", "OperatingIncome", "OperatingProfit"),
    "net_income": ("ProfitLossAttributableToOwnersOfParent", "ProfitAttributableToOwnersOfParent", "NetIncomeLossAttributableToOwnersOfParent", "ProfitLoss", "NetIncomeLoss"),
    "assets": ("Assets", "TotalAssets"),
    "equity": ("EquityAttributableToOwnersOfParent", "Equity", "ShareholdersEquity", "NetAssets"),
    "net_assets": ("NetAssets",),
    "noncontrolling_interests": ("NonControllingInterests", "MinorityInterests"),
    "share_acquisition_rights": ("SubscriptionRightsToShares", "ShareAcquisitionRights"),
    "ordinary_income": ("OrdinaryIncomeLoss", "OrdinaryIncome"),
    "loans": ("LoansAndBillsDiscounted", "LoansAndBillsDiscountedBankingBusiness"),
    "deposits": ("Deposits", "DepositsBankingBusiness"),
    "capital_adequacy_ratio": ("CapitalAdequacyRatio", "ConsolidatedCapitalAdequacyRatio"),
}


@dataclass(frozen=True)
class FinancialValues:
    revenue: float | None
    operating_income: float | None
    net_income: float | None
    current_assets: float | None
    prior_assets: float | None
    current_equity: float | None
    prior_equity: float | None
    currency: str
    accounting_standard: str
    consolidated: bool
    ordinary_income: float | None = None
    loans: float | None = None
    deposits: float | None = None
    bank_equity_ratio: float | None = None


def _decode_csv(raw: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-16", "utf-8-sig", "cp932"):
        try:
            text = raw.decode(encoding)
            first_line = text.splitlines()[0] if text else ""
            if "要素" not in first_line or "値" not in first_line:
                raise UnicodeError("EDINET CSVヘッダーを認識できません。")
            separator = "\t" if first_line.count("\t") > first_line.count(",") else ","
            return pd.read_csv(io.StringIO(text), sep=separator, dtype=str).fillna("")
        except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            last_error = exc
    raise EdinetError(f"EDINET CSVの文字コードを判定できませんでした: {last_error}")


def read_edinet_csv_zip(content: bytes) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv") and not name.startswith("__MACOSX/")]
            if not names:
                raise EdinetError("EDINET書類ZIPにCSVファイルがありません。")
            frames = [_decode_csv(archive.read(name)) for name in names]
    except zipfile.BadZipFile as exc:
        raise EdinetError("EDINET書類ZIPを展開できませんでした。") from exc
    return pd.concat(frames, ignore_index=True, sort=False)


def _column(frame: pd.DataFrame, *names: str) -> str:
    normalized = {str(column).strip(): str(column) for column in frame.columns}
    for name in names:
        if name in normalized:
            return normalized[name]
    raise EdinetError(f"EDINET CSVに必要な列がありません: {' / '.join(names)}")


def _number(value: object) -> float | None:
    text = str(value).strip().replace(",", "").replace("△", "-").replace("▲", "-")
    if text in {"", "-", "—", "nan", "None"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        result = float(text)
        return -result if negative else result
    except ValueError:
        return None


def normalize_percentage_fraction(value: float | None) -> float | None:
    """Normalize either XBRL fraction form (0.3) or display-percent form (30)."""
    if value is None:
        return None
    return value / 100 if abs(value) > 1 else value


def _concept_suffix(value: str) -> str:
    return re.split(r"[:}]", value)[-1].strip()


def _is_consolidated(context: str, consolidated_text: str) -> bool:
    combined = f"{context} {consolidated_text}"
    if "NonConsolidated" in combined or "個別" in combined:
        return False
    if "連結" in consolidated_text:
        return True
    return "Member" not in context


def _matches_concept(suffix: str, concept: str) -> bool:
    if suffix == concept:
        return True
    remainder = suffix[len(concept):] if suffix.startswith(concept) else ""
    return remainder.startswith(("IFRS", "SummaryOfBusinessResults", "KeyFinancialData"))


def _context_score(context: str, period_kind: str, want_current: bool) -> int:
    context_lower = context.lower()
    score = 0
    if "currentyear" in context_lower or "当期" in context:
        score += 50 if want_current else -30
    if "prior1year" in context_lower or "前期" in context:
        score += 50 if not want_current else -30
    if period_kind in context_lower:
        score += 20
    if "member" not in context_lower:
        score += 5
    return score


def _pick(rows: Iterable[dict[str, str]], concept_names: tuple[str, ...], period_kind: str, want_current: bool, prefer_consolidated: bool) -> tuple[float | None, str]:
    choices: list[tuple[int, float, str]] = []
    for row in rows:
        suffix = _concept_suffix(row["concept"])
        matched_index = next((index for index, concept in enumerate(concept_names) if _matches_concept(suffix, concept)), None)
        if matched_index is None:
            continue
        context_lower = row["context"].lower()
        if want_current and "currentyear" not in context_lower:
            continue
        if not want_current and "prior1year" not in context_lower:
            continue
        value = _number(row["value"])
        if value is None or not math.isfinite(value):
            continue
        score = (len(concept_names) - matched_index) * 100
        score += _context_score(row["context"], period_kind, want_current)
        if _is_consolidated(row["context"], row["consolidated"]) == prefer_consolidated:
            score += 10_000
        else:
            score -= 10_000
        if "Member" in row["context"] and "NonConsolidatedMember" not in row["context"]:
            score -= 1_000
        choices.append((score, value, row["unit"]))
    if not choices:
        return None, ""
    _, value, unit = max(choices, key=lambda choice: choice[0])
    return value, unit


def parse_financial_values(frame: pd.DataFrame, prefer_consolidated: bool = True) -> FinancialValues:
    concept_col = _column(frame, "要素ID", "要素ＩＤ")
    context_col = _column(frame, "コンテキストID", "コンテキストＩＤ")
    value_col = _column(frame, "値")
    unit_col = next((c for c in ("単位", "ユニットID", "ユニットＩＤ") if c in frame.columns), "")
    consolidated_col = next((c for c in ("連結・個別", "連結／個別") if c in frame.columns), "")
    rows = [{
        "concept": str(row.get(concept_col, "")), "context": str(row.get(context_col, "")),
        "value": str(row.get(value_col, "")), "unit": str(row.get(unit_col, "")) if unit_col else "",
        "consolidated": str(row.get(consolidated_col, "")) if consolidated_col else "",
    } for _, row in frame.iterrows()]
    concept_text = " ".join(str(value) for value in frame[concept_col].head(500))
    standard = "IFRS" if ("ifrs-full" in concept_text or "IFRS" in concept_text) else "米国基準" if "us-gaap" in concept_text else "日本基準" if ("jppfs" in concept_text or "jpcrp" in concept_text) else ""
    picked: dict[str, float | None] = {}
    for key in ("revenue", "operating_income", "net_income"):
        picked[key], _ = _pick(rows, CONCEPTS[key], "duration", True, prefer_consolidated)
    ordinary_income, _ = _pick(rows, CONCEPTS["ordinary_income"], "duration", True, prefer_consolidated)
    loans, _ = _pick(rows, CONCEPTS["loans"], "instant", True, prefer_consolidated)
    deposits, _ = _pick(rows, CONCEPTS["deposits"], "instant", True, prefer_consolidated)
    capital_adequacy_ratio, _ = _pick(rows, CONCEPTS["capital_adequacy_ratio"], "instant", True, prefer_consolidated)
    capital_adequacy_ratio = normalize_percentage_fraction(capital_adequacy_ratio)
    current_assets, _ = _pick(rows, CONCEPTS["assets"], "instant", True, prefer_consolidated)
    prior_assets, _ = _pick(rows, CONCEPTS["assets"], "instant", False, prefer_consolidated)
    current_equity, _ = _pick(rows, CONCEPTS["equity"], "instant", True, prefer_consolidated)
    prior_equity, _ = _pick(rows, CONCEPTS["equity"], "instant", False, prefer_consolidated)
    if standard == "日本基準":
        current_net_assets, _ = _pick(rows, CONCEPTS["net_assets"], "instant", True, prefer_consolidated)
        prior_net_assets, _ = _pick(rows, CONCEPTS["net_assets"], "instant", False, prefer_consolidated)
        current_nci, _ = _pick(rows, CONCEPTS["noncontrolling_interests"], "instant", True, prefer_consolidated)
        prior_nci, _ = _pick(rows, CONCEPTS["noncontrolling_interests"], "instant", False, prefer_consolidated)
        current_rights, _ = _pick(rows, CONCEPTS["share_acquisition_rights"], "instant", True, prefer_consolidated)
        prior_rights, _ = _pick(rows, CONCEPTS["share_acquisition_rights"], "instant", False, prefer_consolidated)
        if current_net_assets is not None:
            current_equity = current_net_assets - (current_nci or 0) - (current_rights or 0)
        if prior_net_assets is not None:
            prior_equity = prior_net_assets - (prior_nci or 0) - (prior_rights or 0)
    return FinancialValues(
        picked["revenue"], picked["operating_income"], picked["net_income"],
        current_assets, prior_assets, current_equity, prior_equity, "JPY", standard,
        prefer_consolidated, ordinary_income, loans, deposits, capital_adequacy_ratio,
    )
