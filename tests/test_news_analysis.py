from datetime import date

import requests

from news_analysis import NewsItem, Source, classify_event, collect_material_events, parse_listing_html, parse_rss


def test_parse_rss_and_classify_price_event():
    source = Source("会社公式", "https://example.jp/rss", "会社公式ニュース", "rss")
    xml = "<rss><channel><item><title>料金改定のお知らせ</title><link>https://example.jp/1</link><pubDate>Fri, 01 Aug 2025 10:00:00 +0900</pubDate></item></channel></rss>".encode()
    item = parse_rss(xml, source)[0]
    event = classify_event(item)
    assert item.published_date == date(2025, 8, 1)
    assert event is not None and event.category == "価格・料金"
    assert "営業利益率" in event.affected_metrics


def test_parse_official_listing_preserves_url_date_and_source():
    source = Source("公式IR", "https://example.jp/ir/", "会社公式IR・適時開示相当", "html")
    html = '<ul><li>2026年7月4日 <a href="docs/release.pdf">自己株式取得のお知らせ</a></li></ul>'.encode()
    item = parse_listing_html(html, source)[0]
    assert item.url == "https://example.jp/ir/docs/release.pdf"
    assert item.published_date == date(2026, 7, 4)
    assert item.source_name == "公式IR"


def test_document_url_date_wins_over_unrelated_nearby_date():
    source = Source("公式IR", "https://example.jp/ir/", "会社公式IR・適時開示相当", "html")
    html = '2026年8月7日 <a href="info_20260615_jp.pdf">関係会社株式売却益のお知らせ</a>'.encode()
    item = parse_listing_html(html, source)[0]
    assert item.published_date == date(2026, 6, 15)


class _Response:
    def __init__(self, content): self.content = content
    def raise_for_status(self): return None


def test_collection_filters_old_and_untrusted_news():
    def fake_get(url, **kwargs):
        return _Response("""<rss><channel>
          <item><title>業績予想を上方修正 - Reuters</title><link>https://news/1</link><pubDate>Sat, 01 Aug 2026 00:00:00 GMT</pubDate><source>Reuters</source></item>
          <item><title>自己株式取得 - Unknown Blog</title><link>https://news/2</link><pubDate>Sat, 01 Aug 2026 00:00:00 GMT</pubDate><source>Unknown Blog</source></item>
          <item><title>古い業績予想</title><link>https://news/3</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><source>Reuters</source></item>
        </channel></rss>""".encode())
    result = collect_material_events("テスト社", "9999", today=date(2026, 8, 29), get=fake_get)
    assert len(result.events) == 1
    assert result.events[0].item.source_name == "Reuters"


def test_every_requested_event_type_has_causal_analysis():
    titles = ("企業を買収", "新工場へ設備投資", "料金を値上げ", "原発再稼働", "認証不正", "業績予想を下方修正", "自己株式取得")
    for title in titles:
        item = NewsItem(title, date(2026, 1, 1), "https://example.jp", "公式", "会社公式ニュース")
        event = classify_event(item)
        assert event is not None
        assert event.financial_impacts and event.affected_metrics and event.watch_metrics


def test_market_comment_and_factory_feature_are_not_material_events():
    market = NewsItem("株価反落、株式売却益への反応薄", date(2026, 1, 1), "https://example.jp", "日本経済新聞", "信頼できる報道")
    feature = NewsItem("自動車工場を描いたクリエイター特集", date(2026, 1, 1), "https://example.jp", "公式", "会社公式ニュース")
    assert classify_event(market) is None
    assert classify_event(feature) is None
