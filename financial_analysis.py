from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, median

from financial_metrics import Metrics
from news_analysis import MaterialEvent
from company_profile import BUSINESS_PROFILES


PEER_CODES_BY_INDUSTRY = {
    "輸送用機器": ("7267", "7201"),
    "電気・ガス業": ("9501", "9503"),
    "卸売業": ("8001", "8058"),
}

# EDINETの業種は広いため、事業内容が明確な代表企業は証券コード単位で補正する。
BUSINESS_PEERS_BY_CODE = {
    "8020": (("8001", "総合商社として事業領域・収益構造が近い"),
             ("8058", "総合商社として事業ポートフォリオが近い")),  # 兼松
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

INDUSTRY_COMPARISON_CAUTIONS = {
    "卸売業": (
        "商社はIFRSと日本基準などの会計基準、収益を総額・純額のどちらで認識するか、持分法投資利益の比重、"
        "事業ポートフォリオの違いが大きいため、営業利益率や総資産回転率の単純比較には注意が必要です。"
        "数値の高低だけでなく、各社の会計方針とセグメント構成を確認してください。"
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


@dataclass(frozen=True)
class BusinessModelClassification:
    primary: str
    characteristics: tuple[str, ...] = ()


def representative_peer_codes(industry: str, own_security_code: str) -> tuple[str, ...]:
    return tuple(code for code, _ in select_peer_candidates(industry, own_security_code))


def select_peer_candidates(industry: str, own_security_code: str) -> tuple[tuple[str, str], ...]:
    """Return peer codes with an auditable business-relevance reason."""
    own = own_security_code[:4]
    if own in BUSINESS_PEERS_BY_CODE:
        return BUSINESS_PEERS_BY_CODE[own]
    own_profile = BUSINESS_PROFILES.get(own)
    if own_profile:
        scored: list[tuple[int, str, str]] = []
        for code, candidate in BUSINESS_PROFILES.items():
            if code == own or candidate.broad_industry != industry:
                continue
            shared_keywords = set(own_profile.keywords) & set(candidate.keywords)
            shared_segments = set(own_profile.segments) & set(candidate.segments)
            score = peer_similarity_score(
                candidate.broad_industry == own_profile.broad_industry,
                len(shared_keywords), len(shared_segments),
                bool(own_profile.business_model and own_profile.business_model == candidate.business_model),
            )
            # 大分類一致だけでは同業としない。
            if not shared_keywords and not shared_segments and own_profile.business_model != candidate.business_model:
                continue
            common = sorted(shared_segments or shared_keywords)
            basis = "・".join(common[:2]) if common else own_profile.detailed_industry
            scored.append((score, code, f"{basis}が共通するため選定（同業類似度 {score}点）"))
        if scored:
            scored.sort(reverse=True)
            return tuple((code, reason) for score, code, reason in scored[:2])
    return tuple(
        (code, f"EDINET業種「{industry}」の代表企業として選定（事業構成の差は要確認）")
        for code in PEER_CODES_BY_INDUSTRY.get(industry, ()) if code != own
    )


def peer_similarity_score(
    industry_matches: bool,
    shared_keywords: int,
    shared_segments: int,
    business_model_matches: bool,
) -> int:
    """Score explainable peer similarity, keeping broad industry as a weak signal."""
    return min(100, (10 if industry_matches else 0) + min(shared_keywords, 4) * 10
               + min(shared_segments, 2) * 20 + (10 if business_model_matches else 0))


def classify_business_model(metrics: Metrics, peers: list[PeerSnapshot]) -> BusinessModelClassification:
    """Choose one primary ROE model and retain non-overlapping auxiliary traits."""
    medians = comparison_statistics(metrics, peers)["median"]
    margin, turnover, leverage = metrics.net_margin, metrics.asset_turnover, metrics.financial_leverage
    margin_base = medians["net_margin"]
    turnover_base = medians["asset_turnover"]
    leverage_base = medians["financial_leverage"]
    high_margin = margin is not None and (margin >= 0.10 or margin_base is not None and margin > margin_base * 1.2)
    high_turnover = turnover is not None and (turnover >= 1.0 or turnover_base is not None and turnover > turnover_base * 1.2)
    high_leverage = leverage is not None and (leverage >= 3.0 or leverage_base is not None and leverage > leverage_base * 1.2)
    low_margin = margin is not None and margin >= 0 and margin <= 0.05
    if low_margin and high_turnover:
        primary = "薄利高回転型"
    elif high_margin:
        primary = "高利益率型"
    elif high_turnover:
        primary = "高回転型"
    elif high_leverage:
        primary = "レバレッジ型"
    else:
        primary = "バランス型"

    characteristics: list[str] = []
    if high_leverage and primary != "レバレッジ型":
        characteristics.append("レバレッジ活用型")
    if high_margin and primary != "高利益率型":
        characteristics.append("利益率優位")
    return BusinessModelClassification(primary, tuple(characteristics))


def business_model_labels(metrics: Metrics, peers: list[PeerSnapshot]) -> list[str]:
    """Compatibility helper returning the primary model followed by auxiliary traits."""
    classification = classify_business_model(metrics, peers)
    return [classification.primary, *classification.characteristics]


def industry_comparison_caution(industry: str) -> str | None:
    return INDUSTRY_COMPARISON_CAUTIONS.get(industry)


def roe_engine_explanation(metrics: Metrics, peers: list[PeerSnapshot]) -> list[str]:
    classification = classify_business_model(metrics, peers)
    characteristic_text = (
        "、補助特性: " + "・".join(classification.characteristics)
        if classification.characteristics else "、補助特性: なし"
    )
    notes = [f"収益モデル分類 — 主分類: {classification.primary}{characteristic_text}。", dupont_driver(metrics, peers)]
    if metrics.roe is not None and metrics.roa is not None:
        gap = metrics.roe - metrics.roa
        if metrics.financial_leverage is not None and abs(gap) >= 0.03:
            notes.append(
                f"ROEとROAの差は{gap * 100:.1f}ポイント。会社全体の資産効率を示すROAに対し、ROEは自己資本を基準にするため、"
                f"財務レバレッジ{metrics.financial_leverage:.2f}倍の影響が大きい。借入等を含む資本構成でROEが押し上げられ得る一方、返済・金利負担のリスクも確認したい。"
            )
    if metrics.operating_margin is not None and metrics.net_margin is not None:
        gap = metrics.operating_margin - metrics.net_margin
        if gap > 0.005:
            notes.append(
                f"営業利益率から純利益率まで{gap * 100:.1f}ポイント低下している。支払利息だけでなく、税金、営業外損益、特別損益などが"
                "利益を減らした可能性があるため、損益計算書の内訳を確認したい。"
            )
        elif gap < -0.005:
            notes.append(
                f"純利益率が営業利益率を{-gap * 100:.1f}ポイント上回る。受取利息・配当、持分法利益、特別利益、税効果などの可能性があり、内訳確認が必要。"
            )
    return notes


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


def _display_number(value: float, percent: bool) -> float:
    """Round to the same precision used by the comparison display."""
    scale, decimals = (100, 1) if percent else (1, 2)
    return float(f"{value * scale:.{decimals}f}")


def _display_comparison(own: float, benchmark: float, percent: bool) -> int:
    displayed_own = _display_number(own, percent)
    displayed_benchmark = _display_number(benchmark, percent)
    return (displayed_own > displayed_benchmark) - (displayed_own < displayed_benchmark)


def _format_comparison_value(value: float, percent: bool) -> str:
    decimals = 1 if percent else 2
    return f"{_display_number(value, percent):.{decimals}f}{'%' if percent else ''}"


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
    if label == "純利益率":
        own_text, peer_text = _format_comparison_value(own, True), _format_comparison_value(peer, True)
        order = _display_comparison(own, peer, True)
    elif label == "総資産回転率":
        own_text, peer_text = _format_comparison_value(own, False) + "回", _format_comparison_value(peer, False) + "回"
        order = _display_comparison(own, peer, False)
    else:
        own_text, peer_text = _format_comparison_value(own, False) + "倍", _format_comparison_value(peer, False) + "倍"
        order = _display_comparison(own, peer, False)
    comparison_text = (
        f"同業中央値{peer_text}と同水準。" if order == 0
        else f"同業中央値{peer_text}を{'上回る' if order > 0 else '下回る'}。"
    )
    return (
        f"DuPont概算は{product_text}。同業中央値との差が最も大きい主因は{label}で、"
        f"自社{own_text}に対し{comparison_text}"
    )


def _comparison_note(label: str, own: float | None, average: float | None, middle: float | None, percent: bool = True) -> str | None:
    benchmark = middle if middle is not None else average
    if own is None or benchmark is None:
        return None
    own_text = _format_comparison_value(own, percent)
    average_text = "算出不可" if average is None else _format_comparison_value(average, percent)
    middle_text = "算出不可" if middle is None else _format_comparison_value(middle, percent)
    order = _display_comparison(own, benchmark, percent)
    comparison_text = (
        f"同業中央値{middle_text}と同水準" if order == 0
        else f"同業中央値{middle_text}を{'上回る' if order > 0 else '下回る'}"
    )
    return (
        f"{label}は{own_text}で、{comparison_text}"
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
            percent = field != "asset_turnover"
            (strengths if _display_comparison(own, benchmark, percent) >= 0 else weaknesses).append(note)
    if not strengths:
        strengths.append("比較可能な主要指標では明確な同業中央値超過がない。財務の安定性や事業別内訳を追加確認したい。")
    if not weaknesses:
        weaknesses.append("比較可能な主要指標では明確な同業中央値割れがないが、持続性は複数年度で確認する必要がある。")

    structure = INDUSTRY_STRUCTURES.get(
        industry,
        "同一業種でも事業構成や会計基準が異なるため、利益率・資産効率・資本構成を分けて比較する必要がある。",
    )
    comparison_caution = industry_comparison_caution(industry)
    leverage_note = comparisons["financial_leverage"] or "財務レバレッジは同業比較可能なデータが不足。"
    peer_names = "、".join(peer.name for peer in peers) if peers else "比較対象なし"
    latest_materials = [
        f"{event.item.published_date.isoformat()}「{event.item.title}」— {event.financial_impacts[0]}"
        for event in events[:3]
    ] or [f"最新材料を取得できなかったため、EDINET有価証券報告書（{fiscal_period}）の財務数値のみで分析している。"]
    engine_notes = roe_engine_explanation(metrics, peers)
    event_watches = list(dict.fromkeys(metric for event in events[:5] for metric in event.watch_metrics))
    event_checks = [
        f"「{event.item.title}」について、会社開示の続報と{event.watch_metrics[0]}を確認する。"
        for event in events[:2]
    ]
    return {
        "財務上の強み": [*strengths, *engine_notes],
        "財務上の弱み": weaknesses[:3],
        "業界構造": [structure, f"今回の同業比較対象は{peer_names}。", *([comparison_caution] if comparison_caution else [])],
        "最新材料": latest_materials,
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
