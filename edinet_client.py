from __future__ import annotations

import io
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

import pandas as pd
import requests

API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
CODE_LIST_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
EDINET_VIEWER_URL = "https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx"
ANNUAL_REPORT_DOC_TYPE = "120"


class EdinetError(RuntimeError):
    """Base error safe to show in the application."""


class EdinetConfigurationError(EdinetError):
    pass


class EdinetNotFoundError(EdinetError):
    pass


@dataclass(frozen=True)
class Company:
    edinet_code: str
    name: str
    security_code: str
    fiscal_year_end: str
    industry: str = ""
    has_consolidated: bool = False


@dataclass(frozen=True)
class Filing:
    doc_id: str
    edinet_code: str
    filer_name: str
    period_start: str
    period_end: str
    submit_datetime: str
    doc_description: str
    csv_available: bool
    xbrl_available: bool

    @property
    def source_url(self) -> str:
        return f"{EDINET_VIEWER_URL}?{self.doc_id}"


def read_api_key(streamlit_secrets: Any | None = None) -> str:
    """Read the key without ever placing it in output or logs."""
    key = os.getenv("EDINET_API_KEY", "").strip()
    if not key and streamlit_secrets is not None:
        try:
            key = str(streamlit_secrets.get("EDINET_API_KEY", "")).strip()
        except Exception:
            key = ""
    if not key:
        raise EdinetConfigurationError(
            "EDINET APIキーが設定されていません。EDINET_API_KEYをSecretsまたは環境変数に設定してください。"
        )
    return key


class EdinetClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 20) -> None:
        if not api_key:
            raise EdinetConfigurationError("EDINET APIキーが空です。")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({"User-Agent": "finance-analyzer/2.0 (EDINET public information client)"})

    def _get(self, path: str, params: dict[str, str]) -> requests.Response:
        request_params = {**params, "Subscription-Key": self.api_key}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(f"{API_BASE}/{path}", params=request_params, timeout=self.timeout)
                if response.status_code in (401, 403):
                    raise EdinetConfigurationError("EDINET APIキーが無効か、APIへのアクセスが許可されていません。")
                response.raise_for_status()
                return response
            except EdinetConfigurationError:
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))
        raise EdinetError(f"EDINET APIへの接続に失敗しました: {last_error}")

    def list_documents(self, target_date: date) -> list[dict[str, Any]]:
        payload: dict[str, Any] | None = None
        last_error: ValueError | None = None
        for attempt in range(3):
            response = self._get("documents.json", {"date": target_date.isoformat(), "type": "2"})
            try:
                payload = response.json()
                break
            except ValueError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))
        if payload is None:
            raise EdinetError("EDINET書類一覧が一時的に非JSON応答を返しました。時間をおいて再試行してください。") from last_error
        status = str(payload.get("metadata", {}).get("status", "200"))
        if status != "200":
            message = payload.get("metadata", {}).get("message", "不明なエラー")
            raise EdinetError(f"EDINET書類一覧APIエラー: {message}")
        return payload.get("results") or []

    def download_csv(self, doc_id: str) -> bytes:
        response = self._get(f"documents/{doc_id}", {"type": "5"})
        if not response.content.startswith(b"PK"):
            raise EdinetError("EDINETから取得したCSV書類がZIP形式ではありません。")
        return response.content


def load_company_list(content: bytes | None = None) -> list[Company]:
    """Load the official Japanese EDINET code list and retain listed issuers."""
    if content is None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.get(CODE_LIST_URL, timeout=30, headers={"User-Agent": "finance-analyzer/2.0"})
                response.raise_for_status()
                content = response.content
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))
        if content is None:
            raise EdinetError(f"EDINETコードリストを取得できませんでした: {last_error}") from last_error
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise EdinetError("EDINETコードリストZIPにCSVがありません。")
            raw = archive.read(csv_names[0])
    except (zipfile.BadZipFile, OSError) as exc:
        raise EdinetError("EDINETコードリストZIPを解析できませんでした。") from exc

    frame = pd.read_csv(io.BytesIO(raw), encoding="cp932", skiprows=1, dtype=str).fillna("")
    if "ＥＤＩＮＥＴコード" in frame.columns:
        frame = frame.rename(columns={"ＥＤＩＮＥＴコード": "EDINETコード"})
    required = {"EDINETコード", "上場区分", "提出者名", "証券コード", "決算日"}
    if not required.issubset(frame.columns):
        raise EdinetError("EDINETコードリストの列構成が想定と異なります。")
    companies: list[Company] = []
    for _, row in frame.iterrows():
        security_code = str(row["証券コード"]).strip()
        listed = str(row["上場区分"]).strip()
        if not security_code or listed in {"非上場", "0"}:
            continue
        companies.append(Company(
            edinet_code=str(row["EDINETコード"]).strip().upper(),
            name=str(row["提出者名"]).strip(),
            security_code=security_code,
            fiscal_year_end=str(row["決算日"]).strip(),
            industry=str(row.get("提出者業種", "")).strip(),
            has_consolidated=str(row.get("連結の有無", "")).strip() in {"有", "1"},
        ))
    return companies


def normalize_security_code(value: str) -> str:
    value = value.strip().upper()
    if value.endswith(".T"):
        value = value[:-2]
    if len(value) == 5 and value.isdigit() and value.endswith("0"):
        value = value[:4]
    return value


def find_companies(companies: Iterable[Company], query: str, limit: int = 20) -> list[Company]:
    q = query.strip()
    if not q:
        return []
    q_upper = q.upper()
    security_query = normalize_security_code(q)
    exact: list[Company] = []
    partial: list[Company] = []
    for company in companies:
        security = normalize_security_code(company.security_code)
        if q_upper == company.edinet_code or security_query == security or q == company.name:
            exact.append(company)
        elif q.casefold() in company.name.casefold():
            partial.append(company)
    return (exact + partial)[:limit]


def _parse_fiscal_month_day(value: str) -> tuple[int, int]:
    text = value.strip().replace("/", "-")
    for fmt in ("%m-%d", "%Y-%m-%d", "%m月%d日", "%m月%d日現在"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.month, parsed.day
        except ValueError:
            pass
    raise EdinetError(f"決算日を解釈できません: {value}")


def filing_search_dates(fiscal_year_end: str, today: date | None = None) -> list[date]:
    """Likely annual-report dates, newest first, avoiding a full API crawl."""
    today = today or date.today()
    month, day = _parse_fiscal_month_day(fiscal_year_end)
    dates: list[date] = []
    for year in range(today.year, today.year - 3, -1):
        try:
            period_end = date(year, month, day)
        except ValueError:
            period_end = date(year, month, 28)
        if period_end > today:
            continue
        start = period_end + timedelta(days=45)
        end = min(period_end + timedelta(days=110), today)
        cursor = end
        while cursor >= start:
            dates.append(cursor)
            cursor -= timedelta(days=1)
    return dates


def find_latest_annual_filing(company: Company, list_documents: Callable[[date], list[dict[str, Any]]], today: date | None = None) -> Filing:
    candidates: list[Filing] = []
    for target_date in filing_search_dates(company.fiscal_year_end, today):
        for item in list_documents(target_date):
            if str(item.get("edinetCode", "")).upper() != company.edinet_code:
                continue
            if str(item.get("docTypeCode", "")) != ANNUAL_REPORT_DOC_TYPE:
                continue
            if str(item.get("legalStatus", "1")) not in {"1", "2"}:
                continue
            csv_available = str(item.get("csvFlag", "0")) == "1"
            if not csv_available:
                continue
            candidates.append(Filing(
                doc_id=str(item.get("docID", "")), edinet_code=company.edinet_code,
                filer_name=str(item.get("filerName") or company.name),
                period_start=str(item.get("periodStart", "")), period_end=str(item.get("periodEnd", "")),
                submit_datetime=str(item.get("submitDateTime", "")),
                doc_description=str(item.get("docDescription", "有価証券報告書")),
                csv_available=True, xbrl_available=str(item.get("xbrlFlag", "0")) == "1",
            ))
        if candidates:
            break
    if not candidates:
        raise EdinetNotFoundError("直近の有価証券報告書（EDINET変換CSV付き）を見つけられませんでした。")
    return max(candidates, key=lambda filing: filing.submit_datetime)
