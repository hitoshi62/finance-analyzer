from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from edinet_client import Company, EdinetError, Filing
from edinet_parser import FinancialValues
from financial_metrics import Metrics, calculate_metrics


CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path(".cache/edinet")


@dataclass(frozen=True)
class FinancialResult:
    filing: Filing
    values: FinancialValues
    metrics: Metrics
    last_retrieved_at: str
    from_cache: bool = False
    cache_warning: str = ""


def _cache_path(company: Company, cache_dir: Path) -> Path:
    # EDINETコードは公式コードリスト由来だが、念のためファイル名を英数字に限定する。
    safe_code = "".join(character for character in company.edinet_code.upper() if character.isalnum())
    if not safe_code:
        raise ValueError("キャッシュ用のEDINETコードが不正です。")
    return cache_dir / f"{safe_code}.json"


def _save_cache(
    company: Company,
    filing: Filing,
    values: FinancialValues,
    retrieved_at: str,
    cache_dir: Path,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(company, cache_dir)
    payload = {
        "version": CACHE_VERSION,
        "edinet_code": company.edinet_code,
        "security_code": company.security_code[:4],
        "last_retrieved_at": retrieved_at,
        "filing": asdict(filing),
        "financial_values": asdict(values),
    }
    # APIキー、Secrets、HTTPヘッダー、APIレスポンス原文はpayloadへ含めない。
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(cache_dir), prefix=f".{path.stem}-", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, str(path))
    finally:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _load_cache(company: Company, cache_dir: Path) -> FinancialResult | None:
    path = _cache_path(company, cache_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CACHE_VERSION or payload.get("edinet_code") != company.edinet_code:
            return None
        filing = Filing(**payload["filing"])
        values = FinancialValues(**payload["financial_values"])
        retrieved_at = str(payload["last_retrieved_at"])
        # 壊れた日時や別会社の書類をキャッシュとして採用しない。
        datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        if filing.edinet_code != company.edinet_code:
            return None
        metrics = calculate_metrics(values)
        if not metrics.has_financials:
            return None
        return FinancialResult(filing, values, metrics, retrieved_at, True)
    except (FileNotFoundError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def load_financial_with_fallback(
    company: Company,
    fetch_live: Callable[[], tuple[Filing, FinancialValues]],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    now: Callable[[], datetime] | None = None,
) -> FinancialResult:
    """Fetch current EDINET data, falling back only when a prior valid snapshot exists."""
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        filing, values = fetch_live()
        metrics = calculate_metrics(values)
    except EdinetError:
        cached = _load_cache(company, cache_dir)
        if cached is not None:
            return cached
        raise

    retrieved_at = clock().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    cache_warning = ""
    if metrics.has_financials:
        try:
            _save_cache(company, filing, values, retrieved_at, cache_dir)
        except OSError as exc:
            # 正常取得した分析結果は、ローカル保存障害だけでは止めない。
            cache_warning = f"EDINET財務キャッシュを保存できませんでした: {exc}"
    return FinancialResult(filing, values, metrics, retrieved_at, False, cache_warning)
