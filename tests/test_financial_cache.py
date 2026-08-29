import json
from datetime import datetime, timezone

import pytest

from edinet_client import Company, EdinetError, Filing
from edinet_parser import FinancialValues
from financial_cache import load_financial_with_fallback


CHUBU = Company("E04502", "中部電力株式会社", "95020", "03-31", "電気・ガス業", True)


def chubu_filing():
    return Filing(
        "S100TEST", "E04502", "中部電力株式会社", "2025-04-01", "2026-03-31",
        "2026-06-25 09:00", "有価証券報告書", True, True,
    )


def chubu_values():
    return FinancialValues(
        3_900_000_000_000, 210_000_000_000, 120_000_000_000,
        7_100_000_000_000, 7_000_000_000_000,
        2_100_000_000_000, 2_000_000_000_000, "JPY", "日本基準", True,
    )


def test_chubu_normal_fetch_saves_then_api_failure_uses_cache(tmp_path):
    retrieved = datetime(2026, 6, 25, 1, 2, 3, tzinfo=timezone.utc)
    current = load_financial_with_fallback(
        CHUBU, lambda: (chubu_filing(), chubu_values()), cache_dir=tmp_path, now=lambda: retrieved,
    )
    assert current.from_cache is False
    assert current.last_retrieved_at == "2026-06-25T01:02:03Z"
    cache_file = tmp_path / "E04502.json"
    assert cache_file.exists()
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["edinet_code"] == "E04502"
    assert "api" not in cache_file.read_text(encoding="utf-8").lower()
    assert "subscription-key" not in cache_file.read_text(encoding="utf-8").lower()

    def non_json_failure():
        raise EdinetError("EDINET書類一覧が一時的に非JSON応答を返しました。")

    fallback = load_financial_with_fallback(CHUBU, non_json_failure, cache_dir=tmp_path)
    assert fallback.from_cache is True
    assert fallback.last_retrieved_at == current.last_retrieved_at
    assert fallback.filing == current.filing
    assert fallback.metrics == current.metrics


def test_api_failure_without_company_cache_keeps_existing_error(tmp_path):
    def failure():
        raise EdinetError("既存のエラーメッセージ")

    with pytest.raises(EdinetError, match="既存のエラーメッセージ"):
        load_financial_with_fallback(CHUBU, failure, cache_dir=tmp_path)


def test_successful_recovery_updates_existing_cache(tmp_path):
    first = datetime(2026, 6, 25, tzinfo=timezone.utc)
    second = datetime(2026, 7, 1, tzinfo=timezone.utc)
    load_financial_with_fallback(CHUBU, lambda: (chubu_filing(), chubu_values()), cache_dir=tmp_path, now=lambda: first)
    updated_values = FinancialValues(
        4_000_000_000_000, 220_000_000_000, 130_000_000_000,
        7_200_000_000_000, 7_100_000_000_000,
        2_200_000_000_000, 2_100_000_000_000, "JPY", "日本基準", True,
    )
    updated = load_financial_with_fallback(
        CHUBU, lambda: (chubu_filing(), updated_values), cache_dir=tmp_path, now=lambda: second,
    )
    assert updated.from_cache is False
    assert updated.metrics.revenue == 4_000_000_000_000
    payload = json.loads((tmp_path / "E04502.json").read_text(encoding="utf-8"))
    assert payload["last_retrieved_at"] == "2026-07-01T00:00:00Z"
    assert payload["financial_values"]["revenue"] == 4_000_000_000_000
