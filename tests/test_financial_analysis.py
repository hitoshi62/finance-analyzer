from financial_analysis import PeerSnapshot, build_six_frame_analysis, dupont_driver, representative_peer_codes
from financial_metrics import Metrics


def metrics(roe=0.10, roa=0.04, margin=0.08, operating=0.07, turnover=0.5, leverage=2.5):
    return Metrics(100, 7, 8, 200, 80, roe, roa, margin, operating, turnover, leverage)


def test_representative_peers_are_industry_specific():
    assert representative_peer_codes("輸送用機器", "72030") == ("7267", "7201")
    assert representative_peer_codes("電気・ガス業", "95020") == ("9501", "9503")
    assert representative_peer_codes("不明", "0000") == ()


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
        assert "ニュースは使用せず" in result["最新材料"][0]
