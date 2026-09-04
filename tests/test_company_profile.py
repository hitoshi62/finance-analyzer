from company_profile import (
    ListingKind, business_profile, financial_analysis_type,
    find_parent_suggestion, resolve_parent_company,
)
from edinet_client import Company, find_companies


def test_saitama_resona_requires_explicit_parent_resolution():
    suggestion = find_parent_suggestion("埼玉りそな銀行")
    assert suggestion is not None
    assert suggestion.listing_kind == ListingKind.UNLISTED_WITH_LISTED_PARENT
    assert suggestion.parent_security_code == "8308"
    parent = Company("E03610", "株式会社りそなホールディングス", "83080", "03-31", "銀行業", True)
    assert resolve_parent_company([parent], suggestion) == parent


def test_resona_uses_bank_mode_and_kinki_has_description():
    resona = Company("E03610", "株式会社りそなホールディングス", "83080", "03-31", "銀行業", True)
    kinki = Company("E02148", "近畿車輛株式会社", "71220", "03-31", "輸送用機器", True)
    assert financial_analysis_type(resona) == "bank"
    assert "鉄道車両" in business_profile(kinki).description


def test_financial_types_are_distinct():
    assert financial_analysis_type(Company("E1", "証券会社", "10000", "03-31", "証券業")) == "securities"
    assert financial_analysis_type(Company("E2", "保険会社", "10010", "03-31", "保険業")) == "insurance"
    assert financial_analysis_type(Company("E3", "信販会社", "10020", "03-31", "その他金融業")) == "financial"


def test_nomura_name_variants_suggest_listed_parent():
    for query in ("野村証券", "野村證券", "野村證券株式会社"):
        suggestion = find_parent_suggestion(query)
        assert suggestion is not None
        assert suggestion.subsidiary_name == "野村證券株式会社"
        assert suggestion.parent_name == "野村ホールディングス株式会社"
        assert suggestion.parent_security_code == "8604"


def test_daiwa_securities_suggests_group_parent():
    suggestion = find_parent_suggestion("大和証券")
    assert suggestion is not None
    assert suggestion.subsidiary_name == "大和証券株式会社"
    assert suggestion.parent_name == "株式会社大和証券グループ本社"
    assert suggestion.parent_security_code == "8601"


def test_listed_parent_names_resolve_by_partial_search():
    parents = [
        Company("E03752", "野村ホールディングス株式会社", "86040", "03-31"),
        Company("E03753", "株式会社大和証券グループ本社", "86010", "03-31"),
    ]
    assert find_companies(parents, "野村ホールディングス") == [parents[0]]
    assert find_companies(parents, "大和証券グループ本社") == [parents[1]]
