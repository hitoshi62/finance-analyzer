from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, median

from financial_metrics import Metrics
from news_analysis import MaterialEvent


PEER_CODES_BY_INDUSTRY = {
    "輸送用機器": ("7267", "7201"),
    "電気・ガス業": ("9501", "9503"),
}

INDUSTRY_STRUCTURES = {
    "輸送用機器": (
        "完成車・部品を含む製造業で、巨額の設備・研究開発投資とグローバルな供給網を必要とする。"
        "販売台数、製品構成、為替、原材料価格、品質費用の影響を受けやすく、金融子会社を持つ企業では総資産も大きくなる。"
    ),
    "電気・ガス業": (
        "発電・送配電設備を長期保有する資産集約型産業で、総資産回転率は構造的に低くなりやすい。"
        "燃料価格、為替、電源構成、規制料金、原子力設備の稼働状況が利益とキャッシュフローを左右し、負債活用も比較的大きい。"
    ),
}

FRAME_TITLES = (
    "財務上の強み",
    "財務上の弱み",
    "業界構造",
    "最新材料",
    "今後の注目指標",
    "投資家が確認すべき点",
)


@dataclass(frozen=True)
class PeerSnapshot:
    name: str
    security_code: str
    fiscal_period: str
    metrics: Metrics


def representative_peer_codes(industry: str, own_security_code: str) -> tuple[str, ...]:
    own = own_security_code[:4]
    return tuple(code for code in PEER_CODES_BY_INDUSTRY.get(industry, ()) if code != own)


COMPARISON_FIELDS = (
    "roe", "roa", "net_margin", "operating_margin",
    "asset_turnover", "financial_leverage",
)


def _available_statistic(metrics_rows: list[Metrics], field: str, statistic) -> float | None:
    values = [getattr(metrics, field) for metrics in metrics_rows]
    usable = [value for value in values if value is not None and math.isfinite(value)]
    return statistic(usable) if usable else None


def peer_averages(peers: list[PeerSnapshot]) -> dict[str, float | None]:
    return {
        field: _available_statistic([peer.metrics for peer in peers], field, mean)
        for field in COMPARISON_FIELDS
    }


def comparison_statistics(metrics: Metrics, peers: list[PeerSnapshot]) -> dict[str, dict[str, float | None]]:
    """Mean and median for the displayed group (target company plus peers)."""
    rows = [metrics, *(peer.metrics for peer in peers)]
    return {
        "average": {field: _available_statistic(rows, field, mean) for field in COMPARISON_FIELDS},
        "median": {field: _available_statistic(rows, field, median) for field in COMPARISON_FIELDS},
    }


def comparison_outlier_warning(metrics: Metrics, peers: list[PeerSnapshot]) -> str | None:
    rows = [metrics, *(peer.metrics for peer in peers)]
    loss_company = any(
        row.net_income is not None and row.net_income < 0
        or row.operating_income is not None and row.operating_income < 0
        for row in rows
    )
    stats = comparison_statistics(metrics, peers)
    divergent = False
    for field in COMPARISON_FIELDS:
        average, middle = stats["average"][field], stats["median"][field]
        if average is None or middle is None:
            continue
        divergent = divergent or (abs(average - middle) > max(abs(middle) * 0.25, 0.01))
    if loss_company or divergent:
        reason = "赤字企業または極端な値が含まれるため、" if loss_company else "極端な値が含まれるため、"
        return reason + "平均値は外れ値の影響を受けています。中央値も併せて確認してください。"
    return None


def dupont_driver(metrics: Metrics, peers: list[PeerSnapshot]) -> str:
    components = (
        ("純利益率", "net_margin"),
        ("総資産回転率", "asset_turnover"),
        ("財務レバレッジ", "financial_leverage"),
    )
    product = None
    if None not in (metrics.net_margin, metrics.asset_turnover, metrics.financial_leverage):
        product = metrics.net_margin * metrics.asset_turnover * metrics.financial_leverage
    product_text = "算出不可" if product is None else f"{product * 100:.1f}%"
    benchmarks = comparison_statistics(metrics, peers)["median"]
    differences: list[tuple[float, str, float, float]] = []
    for label, field in components:
        own = getattr(metrics, field)
        peer = benchmarks[field]
        if own is not None and peer is not None and peer != 0:
            differences.append((abs(own / peer - 1), label, own, peer))
    if not differences:
        return f"DuPont概算は{product_text}。比較可能な同業データが不足しているため、主因は単独数値で確認する必要がある。"
    _, label, own, peer = max(differences)
    direction = "上回る" if own >= peer else "下回る"
    if label == "純利益率":
        own_text, peer_text = f"{own * 100:.1f}%", f"{peer * 100:.1f}%"
    elif label == "総資産回転率":
        own_text, peer_text = f"{own:.2f}回", f"{peer:.2f}回"
    else:
        own_text, peer_text = f"{own:.2f}倍", f"{peer:.2f}倍"
    return (
        f"DuPont概算は{product_text}。同業中央値との差が最も大きい主因は{label}で、"
        f"自社{own_text}に対し同業中央値{peer_text}と、中央値を{direction}。"
    )


def _comparison_note(label: str, own: float | None, average: float | None, middle: float | None, percent: bool = True) -> str | None:
    benchmark = middle if middle is not None else average
    if own is None or benchmark is None:
        return None
    unit = "%" if percent else ""
    scale = 100 if percent else 1
    direction = "上回る" if own >= benchmark else "下回る"
    average_text = "算出不可" if average is None else f"{average * scale:.1f}{unit}"
    middle_text = "算出不可" if middle is None else f"{middle * scale:.1f}{unit}"
    return (
        f"{label}は{own * scale:.1f}{unit}で、同業中央値{middle_text}を{direction}"
        f"（単純平均{average_text}）。"
    )


def build_six_frame_analysis(
    company_name: str,
    industry: str,
    fiscal_period: str,
    metrics: Metrics,
    peers: list[PeerSnapshot],
    events: list[MaterialEvent] | tuple[MaterialEvent, ...] = (),
) -> dict[str, list[str]]:
    statistics = comparison_statistics(metrics, peers)
    averages, medians = statistics["average"], statistics["median"]
    comparisons = {
        "roe": _comparison_note("ROE", metrics.roe, averages["roe"], medians["roe"]),
        "roa": _comparison_note("ROA", metrics.roa, averages["roa"], medians["roa"]),
        "operating_margin": _comparison_note("営業利益率", metrics.operating_margin, averages["operating_margin"], medians["operating_margin"]),
        "asset_turnover": _comparison_note("総資産回転率", metrics.asset_turnover, averages["asset_turnover"], medians["asset_turnover"], False),
        "financial_leverage": _comparison_note("財務レバレッジ", metrics.financial_leverage, averages["financial_leverage"], medians["financial_leverage"], False),
    }
    strengths: list[str] = []
    weaknesses: list[str] = []
    for field in ("roe", "roa", "operating_margin", "asset_turnover"):
        note = comparisons[field]
        own = getattr(metrics, field)
        benchmark = medians[field] if medians[field] is not None else averages[field]
        if note and own is not None and benchmark is not None:
            (strengths if own >= benchmark else weaknesses).append(note)
    if not strengths:
        strengths.append("比較可能な主要指標では明確な同業中央値超過がない。財務の安定性や事業別内訳を追加確認したい。")
    if not weaknesses:
        weaknesses.append("比較可能な主要指標では明確な同業中央値割れがないが、持続性は複数年度で確認する必要がある。")

    structure = INDUSTRY_STRUCTURES.get(
        industry,
        "同一業種でも事業構成や会計基準が異なるため、利益率・資産効率・資本構成を分けて比較する必要がある。",
    )
    leverage_note = comparisons["financial_leverage"] or "財務レバレッジは同業比較可能なデータが不足。"
    peer_names = "、".join(peer.name for peer in peers) if peers else "比較対象なし"
    latest_materials = [
        f"{event.item.published_date.isoformat()}「{event.item.title}」— {event.financial_impacts[0]}"
        for event in events[:3]
    ] or [f"最新材料を取得できなかったため、EDINET有価証券報告書（{fiscal_period}）の財務数値のみで分析している。"]
    event_watches = list(dict.fromkeys(metric for event in events[:5] for metric in event.watch_metrics))
    event_checks = [
        f"「{event.item.title}」について、会社開示の続報と{event.watch_metrics[0]}を確認する。"
        for event in events[:2]
    ]
    return {
        "財務上の強み": strengths[:3],
        "財務上の弱み": weaknesses[:3],
        "業界構造": [structure, f"今回の同業比較対象は{peer_names}。"],
        "最新材料": [*latest_materials, dupont_driver(metrics, peers)],
        "今後の注目指標": [
            *(["取得した材料に対応して、" + "、".join(event_watches[:5]) + "を追跡する。"] if event_watches else []),
            "営業利益率の持続性と、売上規模の変化が利益へ結び付いているか。",
            "総資産回転率とROAが改善しているか。",
            leverage_note,
        ],
        "投資家が確認すべき点": [
            *event_checks,
            "単年度の指標だけでなく、過去数年の推移と会社計画との差を確認する。",
            "会計基準・決算期・事業構成の違いを踏まえ、同業比較を絶対評価にしない。",
            f"{company_name}のセグメント別利益、設備投資、資金調達方針をEDINET原本で確認する。",
        ],
    }
