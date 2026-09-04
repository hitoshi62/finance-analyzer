import io
import zipfile

from edinet_parser import normalize_percentage_fraction, parse_financial_values, read_edinet_csv_zip
from financial_metrics import calculate_metrics


def financial_zip() -> bytes:
    rows = (
        "要素ID,項目名,コンテキストID,相対年度,連結・個別,期間・時点,ユニットID,単位,値\n"
        "jppfs_cor:NetSales,売上高,CurrentYearDuration,当期,連結,期間,JPY,円,1000\n"
        "jppfs_cor:OperatingIncomeLoss,営業利益,CurrentYearDuration,当期,連結,期間,JPY,円,100\n"
        "jppfs_cor:ProfitLossAttributableToOwnersOfParent,純利益,CurrentYearDuration,当期,連結,期間,JPY,円,60\n"
        "jppfs_cor:Assets,資産,CurrentYearInstant,当期,連結,時点,JPY,円,800\n"
        "jppfs_cor:Assets,資産,Prior1YearInstant,前期,連結,時点,JPY,円,700\n"
        "jppfs_cor:Equity,自己資本,CurrentYearInstant,当期,連結,時点,JPY,円,400\n"
        "jppfs_cor:Equity,自己資本,Prior1YearInstant,前期,連結,時点,JPY,円,350\n"
    ).encode("utf-8-sig")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("XBRL_TO_CSV/test.csv", rows)
    return output.getvalue()


def test_parse_and_calculate_metrics():
    values = parse_financial_values(read_edinet_csv_zip(financial_zip()))
    metrics = calculate_metrics(values)
    assert metrics.avg_assets == 750
    assert metrics.avg_equity == 375
    assert metrics.roe == 60 / 375
    assert metrics.roa == 60 / 750
    assert metrics.operating_margin == 0.1
    assert metrics.asset_turnover == 1000 / 750
    assert metrics.financial_leverage == 2


def test_japanese_gaap_equity_excludes_noncontrolling_interests():
    rows = (
        "要素ID,項目名,コンテキストID,相対年度,連結・個別,期間・時点,ユニットID,単位,値\n"
        "jppfs_cor:NetAssets,純資産,CurrentYearInstant,当期,連結,時点,JPY,円,1000\n"
        "jppfs_cor:NetAssets,純資産,Prior1YearInstant,前期,連結,時点,JPY,円,900\n"
        "jppfs_cor:NonControllingInterests,非支配株主持分,CurrentYearInstant,当期,連結,時点,JPY,円,100\n"
        "jppfs_cor:NonControllingInterests,非支配株主持分,Prior1YearInstant,前期,連結,時点,JPY,円,80\n"
    ).encode("utf-8-sig")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("XBRL_TO_CSV/equity.csv", rows)
    values = parse_financial_values(read_edinet_csv_zip(output.getvalue()))
    assert values.current_equity == 900
    assert values.prior_equity == 820


def test_bank_kpis_are_read_without_estimating_missing_values():
    rows = (
        "要素ID,項目名,コンテキストID,相対年度,連結・個別,期間・時点,ユニットID,単位,値\n"
        "jppfs_cor:OrdinaryIncomeLoss,経常利益,CurrentYearDuration,当期,連結,期間,JPY,円,120\n"
        "jppfs_cor:LoansAndBillsDiscounted,貸出金,CurrentYearInstant,当期,連結,時点,JPY,円,8000\n"
        "jppfs_cor:Deposits,預金,CurrentYearInstant,当期,連結,時点,JPY,円,10000\n"
    ).encode("utf-8-sig")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("XBRL_TO_CSV/bank.csv", rows)
    values = parse_financial_values(read_edinet_csv_zip(output.getvalue()))
    assert values.ordinary_income == 120
    assert values.loans == 8000
    assert values.deposits == 10000
    assert values.bank_equity_ratio is None


def test_percentage_normalization_avoids_double_conversion():
    assert normalize_percentage_fraction(0.3) == 0.3
    assert normalize_percentage_fraction(30) == 0.3
    assert normalize_percentage_fraction(None) is None
