from financial_analysis import (
    PeerSnapshot, build_six_frame_analysis, comparison_outlier_warning,
    classify_business_model, comparison_statistics, dupont_driver,
    industry_comparison_caution, representative_peer_codes,
    roe_engine_explanation, select_peer_candidates,
    peer_similarity_score,
)
from news_analysis import MaterialEvent, NewsItem
from datetime import date
from financial_metrics import Metrics


def metrics(roe=0.10, roa=0.04, margin=0.08, operating=0.07, turnover=0.5, leverage=2.5,
            net_income=8, operating_income=7):
    return Metrics(100, operating_income, net_income, 200, 80, roe, roa, margin, operating, turnover, leverage)


def test_representative_peers_are_industry_specific():
    assert representative_peer_codes("輸送用機器", "72030") == ("7267", "7201")
    assert representative_peer_codes("電気・ガス業", "95020") == ("9501", "9503")
    assert representative_peer_codes("不明", "0000") == ()


def test_kanematsu_uses_business_content_peers_with_reasons():
    candidates = select_peer_candidates("卸売業", "80200")
    assert tuple(code for code, _ in candidates) == ("8001", "8058")
    assert all("総合商社" in reason for _, reason in candidates)


def test_kinki_sharyo_does_not_select_automakers_as_peers():
    candidates = select_peer_candidates("輸送用機器", "71220")
    codes = tuple(code for code, _ in candidates)
    assert "7102" in codes
    assert "7267" not in codes and "7201" not in codes
    assert "鉄道車両" in candidates[0][1]


def test_peer_similarity_weights_business_content_over_broad_industry():
    rail_peer = peer_similarity_score(True, 4, 1, True)
    automaker = peer_similarity_score(True, 0, 0, False)
    assert rail_peer > automaker


def test_business_model_separates_primary_from_auxiliary_traits():
    target = metrics(margin=0.04, turnover=1.5, leverage=3.5)
    classification = classify_business_model(target, [])
    assert classification.primary == "薄利高回転型"
    assert classification.characteristics == ("レバレッジ活用型",)
    assert "高回転型" not in classification.characteristics


def test_trading_company_comparison_caution_explains_accounting_differences():
    caution = industry_comparison_caution("卸売業")
    assert caution is not None
    assert "IFRS" in caution and "収益" in caution
    assert "持分法投資利益" in caution and "事業ポートフォリオ" in caution
    assert industry_comparison_caution("輸送用機器") is None


def test_beginner_explanations_cover_leverage_and_margin_gap_without_overclaiming_interest():
    target = metrics(roe=0.15, roa=0.04, margin=0.04, operating=0.09, leverage=3.75)
    text = " ".join(roe_engine_explanation(target, []))
    assert "財務レバレッジ" in text and "ROEが押し上げられ得る" in text
    assert "支払利息だけでなく" in text
    assert "税金" in text and "営業外損益" in text


def test_dupont_driver_explains_largest_peer_difference():
    peers = [PeerSnapshot("同業", "0001", "2026-03-31", metrics(margin=0.04, turnover=0.5, leverage=2.5))]
    text = dupont_driver(metrics(margin=0.08, turnover=0.5, leverage=2.5), peers)
    assert "純利益率" in text
    assert "10.0%" in text


def test_six_frame_output_has_required_sections():
    peers = [PeerSnapshot("同業", "0001", "2026-03-31", metrics(roe=0.08, roa=0.03))]
    result = build_six_frame_analysis("対象社", "輸送用機器", "2026-03-31", metrics(), peers)
    assert list(result) == [
        "財務上の強み", "財務上の弱み", "業界構造", "最新材料", "今後の注目指標", "投資家が確認すべき点"
    ]
    assert all(result[section] for section in result)


def test_verified_toyota_and_chubu_metrics_render_all_sections():
    cases = (
        ("トヨタ自動車株式会社", "輸送用機器", metrics(0.10147, 0.03865, 0.07592, 0.07431, 0.50908, 2.62545)),
        ("中部電力株式会社", "電気・ガス業", metrics(0.07690, 0.03083, 0.06424, 0.06487, 0.47992, 2.49419)),
    )
    for company, industry, company_metrics in cases:
        result = build_six_frame_analysis(company, industry, "2026-03-31", company_metrics, [])
        assert list(result) == list((
            "財務上の強み", "財務上の弱み", "業界構造", "最新材料", "今後の注目指標", "投資家が確認すべき点"
        ))
        assert "最新材料を取得できなかった" in result["最新材料"][0]


def test_events_update_three_material_dependent_frames():
    event = MaterialEvent(
        NewsItem("自己株式取得のお知らせ", date(2026, 8, 1), "https://example.jp", "公式IR", "会社公式IR・適時開示相当"),
        "株主還元・資本政策", ("財務レバレッジ", "ROE"),
        ("自己資本が減る可能性。",), ("自己資本", "有利子負債"),
    )
    result = build_six_frame_analysis("対象社", "輸送用機器", "2026-03-31", metrics(), [], [event])
    assert "自己株式取得" in result["最新材料"][0]
    assert "自己資本" in result["今後の注目指標"][0]
    assert "会社開示の続報" in result["投資家が確認すべき点"][0]


def test_chubu_comparison_uses_median_when_tepco_is_loss_making_outlier():
    chubu = metrics(roe=0.077, roa=0.031, margin=0.064, operating=0.065, turnover=0.48, leverage=2.49)
    tepco = PeerSnapshot(
        "東京電力ホールディングス株式会社", "9501", "2026-03-31",
        metrics(roe=-0.20, roa=-0.05, margin=-0.15, operating=-0.08, turnover=0.42,
                leverage=5.0, net_income=-20, operating_income=-8),
    )
    kansai = PeerSnapshot(
        "関西電力株式会社", "9503", "2026-03-31",
        metrics(roe=0.070, roa=0.028, margin=0.058, operating=0.060, turnover=0.46, leverage=2.55),
    )
    peers = [tepco, kansai]

    stats = comparison_statistics(chubu, peers)
    assert stats["average"]["roe"] < 0
    assert stats["median"]["roe"] == 0.070
    warning = comparison_outlier_warning(chubu, peers)
    assert warning is not None
    assert "平均値は外れ値の影響を受けています" in warning

    result = build_six_frame_analysis("中部電力株式会社", "電気・ガス業", "2026-03-31", chubu, peers)
    roe_note = next(note for note in result["財務上の強み"] if note.startswith("ROE"))
    assert "同業中央値7.0%を上回る" in roe_note
    assert "単純平均-1.8%" in roe_note


def test_rounded_equal_values_are_described_as_same_level():
    target = metrics(roe=0.07654, roa=0.01, margin=0.07654, operating=0.01, turnover=0.4849)
    peers = [
        PeerSnapshot("同業A", "0001", "2026-03-31", metrics(roe=0.07651, margin=0.07651, turnover=0.4841)),
        PeerSnapshot("同業B", "0002", "2026-03-31", metrics(roe=0.07652, margin=0.07652, turnover=0.4842)),
    ]
    result = build_six_frame_analysis("対象社", "輸送用機器", "2026-03-31", target, peers)
    notes = result["財務上の強み"] + result["財務上の弱み"]
    roe_note = next(note for note in notes if note.startswith("ROE"))
    turnover_note = next(note for note in notes if note.startswith("総資産回転率"))
    assert "ROEは7.7%で、同業中央値7.7%と同水準" in roe_note
    assert "上回る" not in roe_note and "下回る" not in roe_note
    assert "総資産回転率は0.48で、同業中央値0.48と同水準" in turnover_note

    dupont = dupont_driver(target, peers)
    assert "同業中央値0.48回と同水準" in dupont
    assert "上回る" not in dupont and "下回る" not in dupont
