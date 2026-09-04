import io
import zipfile
from datetime import date

from edinet_client import Company, find_companies, find_latest_annual_filing, load_company_list


def code_list_zip() -> bytes:
    csv = (
        "ダウンロード実行日,2\r\n"
        "EDINETコード,提出者種別,上場区分,連結の有無,資本金,決算日,提出者名,提出者名（英字）,提出者名（ヨミ）,所在地,提出者業種,証券コード,提出者法人番号\r\n"
        "E00001,内国会社・組合,上場,有,,03-31,テスト株式会社,,,東京都,製造業,12340,1\r\n"
        "E00002,内国会社・組合,非上場,無,,12-31,非上場株式会社,,,東京都,製造業,,2\r\n"
    ).encode("cp932")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("EdinetcodeDlInfo.csv", csv)
    return output.getvalue()


def test_load_and_find_listed_company():
    companies = load_company_list(code_list_zip())
    assert len(companies) == 1
    assert find_companies(companies, "1234")[0].edinet_code == "E00001"
    assert find_companies(companies, "1234.T")[0].name == "テスト株式会社"
    assert find_companies(companies, "テスト")[0].security_code == "12340"


def test_company_search_orders_exact_then_prefix_then_partial():
    companies = [
        Company("E3", "新テスト株式会社", "33330", "03-31"),
        Company("E2", "テスト工業株式会社", "22220", "03-31"),
        Company("E1", "テスト", "11110", "03-31"),
    ]
    assert [company.edinet_code for company in find_companies(companies, "テスト")] == ["E1", "E2", "E3"]


def test_company_search_normalizes_sho_variant_but_preserves_official_name():
    company = Company("E00001", "野村證券株式会社", "", "03-31")
    result = find_companies([company], "野村証券")
    assert result == [company]
    assert result[0].name == "野村證券株式会社"


def test_find_latest_annual_filing_filters_document_type():
    company = Company("E00001", "テスト株式会社", "12340", "03-31")

    def documents(target_date):
        if target_date == date(2025, 7, 1):
            return [{
                "docID": "S100TEST", "edinetCode": "E00001", "docTypeCode": "120",
                "legalStatus": "1", "csvFlag": "1", "xbrlFlag": "1",
                "filerName": "テスト株式会社", "periodStart": "2024-04-01",
                "periodEnd": "2025-03-31", "submitDateTime": "2025-07-01 10:00",
                "docDescription": "有価証券報告書",
            }]
        return []

    filing = find_latest_annual_filing(company, documents, date(2025, 7, 10))
    assert filing.doc_id == "S100TEST"
    assert filing.period_end == "2025-03-31"
