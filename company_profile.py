from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from company_identity import normalize_company_search_text

if TYPE_CHECKING:
    from edinet_client import Company


class ListingKind(str, Enum):
    LISTED = "listed"
    UNLISTED = "unlisted"
    LISTED_SUBSIDIARY = "listed_subsidiary"
    UNLISTED_WITH_LISTED_PARENT = "unlisted_with_listed_parent"


@dataclass(frozen=True)
class BusinessProfile:
    security_code: str
    description: str
    detailed_industry: str
    keywords: tuple[str, ...]
    segments: tuple[str, ...] = ()
    business_model: str = ""
    financial_type: str = "general"
    broad_industry: str = ""


@dataclass(frozen=True)
class ParentSuggestion:
    subsidiary_name: str
    parent_name: str
    parent_security_code: str
    relationship: str
    listing_kind: ListingKind = ListingKind.UNLISTED_WITH_LISTED_PARENT


# EDINETの大分類を補う、監査可能な最小限の事業プロフィール。
# 未登録企業は大分類フォールバックを使う。
BUSINESS_PROFILES: dict[str, BusinessProfile] = {
    "7122": BusinessProfile(
        "7122", "鉄道車両の設計・製造を主力とし、国内外の鉄道事業者向けに電車などを供給する鉄道車両メーカー。",
        "鉄道車両製造", ("鉄道車両", "車両製造", "電車", "鉄道"), ("鉄道車両",), "受注生産型製造", broad_industry="輸送用機器",
    ),
    "7102": BusinessProfile(
        "7102", "鉄道車両、輸送用機器、建設機械などを製造し、鉄道事業者や公共分野へ供給するメーカー。",
        "鉄道車両製造", ("鉄道車両", "車両製造", "電車", "鉄道"), ("鉄道車両",), "受注生産型製造", broad_industry="輸送用機器",
    ),
    "7012": BusinessProfile(
        "7012", "鉄道車両に加え、航空宇宙・エネルギー・二輪車などを手掛ける総合重工業メーカー。",
        "総合重工業", ("鉄道車両", "車両製造", "鉄道", "航空宇宙", "二輪車"), ("車両", "航空宇宙"), "大型受注型製造", broad_industry="輸送用機器",
    ),
    "7267": BusinessProfile(
        "7267", "自動車と二輪車を世界市場で開発・製造・販売し、金融サービスも展開するモビリティメーカー。",
        "自動車・二輪車製造", ("自動車", "二輪車", "モビリティ"), ("四輪", "二輪"), "量産型製造", broad_industry="輸送用機器",
    ),
    "7201": BusinessProfile(
        "7201", "乗用車や商用車を世界市場で開発・製造・販売する自動車メーカー。",
        "自動車製造", ("自動車", "乗用車", "商用車"), ("自動車",), "量産型製造", broad_industry="輸送用機器",
    ),
    "8308": BusinessProfile(
        "8308", "りそな銀行や埼玉りそな銀行などを傘下に持ち、個人・法人向け銀行サービスを提供する金融持株会社。",
        "銀行持株会社", ("銀行", "預金", "貸出金", "信託"), ("銀行",), "預貸・金融サービス", "bank", "銀行業",
    ),
    "8604": BusinessProfile(
        "8604", "野村證券などを傘下に持ち、国内外で証券・資産運用・投資銀行サービスを提供する金融持株会社。",
        "証券持株会社", ("証券", "資産運用", "投資銀行"), ("証券",), "金融サービス", "securities", "証券、商品先物取引業",
    ),
    "8601": BusinessProfile(
        "8601", "大和証券などを傘下に持ち、国内外で証券・投資・資産運用サービスを提供する金融持株会社。",
        "証券持株会社", ("証券", "資産運用", "投資"), ("証券",), "金融サービス", "securities", "証券、商品先物取引業",
    ),
}


PARENT_SUGGESTIONS = {
    "埼玉りそな銀行": ParentSuggestion(
        "埼玉りそな銀行", "株式会社りそなホールディングス", "8308", "非上場の100％子会社"
    ),
    "株式会社埼玉りそな銀行": ParentSuggestion(
        "埼玉りそな銀行", "株式会社りそなホールディングス", "8308", "非上場の100％子会社"
    ),
    "野村証券": ParentSuggestion(
        "野村證券株式会社", "野村ホールディングス株式会社", "8604", "非上場企業"
    ),
    "大和証券": ParentSuggestion(
        "大和証券株式会社", "株式会社大和証券グループ本社", "8601", "非上場企業"
    ),
}


def _parent_lookup_key(value: str) -> str:
    normalized = normalize_company_search_text(value)
    if normalized.startswith("株式会社"):
        normalized = normalized[len("株式会社"):]
    if normalized.endswith("株式会社"):
        normalized = normalized[:-len("株式会社")]
    return normalized


PARENT_SUGGESTIONS = {
    _parent_lookup_key(name): suggestion for name, suggestion in PARENT_SUGGESTIONS.items()
}


def business_profile(company: Company) -> BusinessProfile:
    code = company.security_code[:4]
    return BUSINESS_PROFILES.get(code, BusinessProfile(
        code,
        f"EDINETでは「{company.industry or '業種未分類'}」に分類される上場企業です。主力事業や顧客市場の詳細は有価証券報告書の事業内容をご確認ください。",
        company.industry,
        tuple(filter(None, (company.industry,))),
        broad_industry=company.industry,
    ))


def find_parent_suggestion(query: str) -> ParentSuggestion | None:
    return PARENT_SUGGESTIONS.get(_parent_lookup_key(query))


def is_financial_company(company: Company, profile: BusinessProfile | None = None) -> bool:
    profile = profile or business_profile(company)
    return profile.financial_type != "general" or any(
        word in company.industry for word in ("銀行", "証券", "保険", "その他金融")
    )


def financial_analysis_type(company: Company, profile: BusinessProfile | None = None) -> str:
    profile = profile or business_profile(company)
    if profile.financial_type != "general":
        return profile.financial_type
    for kind, words in (("bank", ("銀行",)), ("securities", ("証券",)), ("insurance", ("保険",))):
        if any(word in company.industry or word in company.name for word in words):
            return kind
    return "financial" if is_financial_company(company, profile) else "general"


def resolve_parent_company(companies: list[Company], suggestion: ParentSuggestion) -> Company | None:
    return next((c for c in companies if c.security_code[:4] == suggestion.parent_security_code), None)
