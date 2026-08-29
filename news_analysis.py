from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

import requests


USER_AGENT = "finance-analyzer/1.0 (public financial-research app)"
RELIABLE_NEWS = ("ロイター", "Reuters", "NHK", "共同通信", "時事通信", "日本経済新聞")


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    kind: str
    format: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    published_date: date
    url: str
    source_name: str
    source_type: str


@dataclass(frozen=True)
class MaterialEvent:
    item: NewsItem
    category: str
    affected_metrics: tuple[str, ...]
    financial_impacts: tuple[str, ...]
    watch_metrics: tuple[str, ...]


@dataclass(frozen=True)
class MaterialResult:
    events: tuple[MaterialEvent, ...]
    errors: tuple[str, ...]


OFFICIAL_SOURCES = {
    "7203": (
        Source("トヨタ自動車 Global Newsroom", "https://global.toyota/export/jp/allnews_rss.xml", "会社公式ニュース", "rss"),
        Source("トヨタ自動車 IR", "https://global.toyota/jp/ir/", "会社公式IR・適時開示相当", "html"),
        Source("トヨタ自動車 株式情報", "https://global.toyota/jp/ir/stock/share/", "会社公式IR・適時開示相当", "html"),
        Source("トヨタ自動車 株式情報（2025年）", "https://global.toyota/jp/ir/stock/share/archives/", "会社公式IR・適時開示相当", "html"),
    ),
    "9502": (
        Source("中部電力 プレスリリース", "https://www.chuden.co.jp/rss/press.xml", "会社公式ニュース", "rss"),
        Source("中部電力 適時開示情報", "https://www.chuden.co.jp/ir/ir_kaiji/", "会社公式IR・適時開示相当", "html"),
    ),
}


EVENT_RULES = (
    ("不祥事・品質", ("不正", "不適切", "漏えい", "不祥事", "行政処分", "課徴金", "リコール", "認証"),
     ("売上高", "営業利益率", "純利益率", "ROA", "ROE"),
     ("対応費用や販売・信用への影響で売上高と利益率が低下する可能性。", "損失が純利益と自己資本を減らし、ROA・ROEへ波及する可能性。"),
     ("追加費用", "販売への影響", "再発防止策")),
    ("M&A・事業再編", ("買収", "M&A", "公開買付", "TOB", "合併", "子会社化", "事業譲渡", "株式譲渡", "売却"),
     ("売上高", "総資産回転率", "財務レバレッジ", "ROA", "ROE"),
     ("連結範囲や事業規模の変化が売上高に反映される可能性。", "取得・売却に伴う資産、負債、自己資本の変化が総資産回転率、財務レバレッジ、ROA・ROEへ波及する可能性。"),
     ("取得・売却対価", "連結売上・利益", "のれん・売却損益")),
    ("設備投資", ("設備投資", "新工場", "工場建設", "生産能力増強", "建設計画", "発電所建設", "電池投資"),
     ("売上高", "営業利益率", "総資産回転率", "ROA"),
     ("稼働後の供給能力増加が売上高を押し上げる可能性。", "先行して資産と減価償却費が増えると、営業利益率、総資産回転率、ROAを押し下げる可能性。"),
     ("設備投資額", "稼働時期", "減価償却費", "稼働率")),
    ("価格・料金", ("値上げ", "価格改定", "料金改定", "価格転嫁"),
     ("売上高", "営業利益率", "純利益率", "ROA", "ROE"),
     ("販売量が維持されれば単価上昇が売上高を押し上げる可能性。", "原価上昇を転嫁できれば利益率が改善し、ROA・ROEへ波及する可能性。"),
     ("販売単価", "販売数量", "原燃料価格", "営業利益率")),
    ("原子力", ("原発", "原子力", "再稼働", "浜岡"),
     ("営業利益率", "総資産回転率", "財務レバレッジ", "ROA", "ROE"),
     ("再稼働や停止期間は燃料費と稼働資産の収益性を通じて営業利益率と総資産回転率に影響する可能性。", "安全対策投資や資金調達は財務レバレッジを変え、ROA・ROEへ波及する可能性。"),
     ("再稼働審査", "火力燃料費", "安全対策投資", "設備利用率")),
    ("業績修正・決算", ("業績予想", "上方修正", "下方修正", "決算", "利益予想"),
     ("売上高", "営業利益率", "純利益率", "ROA", "ROE"),
     ("会社予想の変化は売上高や利益率の先行情報となる。", "純利益の変化がROA・ROEへ波及するため、修正理由と一過性要因の確認が必要。"),
     ("通期業績予想", "営業利益率", "純利益", "修正理由")),
    ("株主還元・資本政策", ("配当", "自己株", "株主還元", "増資", "社債", "資本政策", "株式消却", "消却"),
     ("純利益率", "財務レバレッジ", "ROE"),
     ("配当や自己株式取得は利益そのものを変えないが、現金と自己資本を減らす可能性。", "自己資本の変化で財務レバレッジとROEが動くため、還元額と資金調達の組み合わせの確認が必要。"),
     ("配当総額", "自己株式取得額", "自己資本", "有利子負債")),
)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.recent: list[str] = []
        self.current: dict | None = None
        self.links: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                # 日付は直前の表示要素だけを候補にし、別項目の日付の流用を防ぐ。
                self.current = {"href": href, "text": [], "context": self.recent[-1] if self.recent else ""}

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self.current is not None:
            self.current["text"].append(value)
        self.recent.append(value)
        self.recent = self.recent[-20:]

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current["href"], " ".join(self.current["text"]), self.current["context"]))
            self.current = None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        pass
    match = re.search(r"(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})日?", value)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    compact = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", value)
    if compact:
        try:
            return date(*map(int, compact.groups()))
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_rss(content: bytes, source: Source) -> list[NewsItem]:
    root = ElementTree.fromstring(content)
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        published = _parse_date(node.findtext("pubDate") or node.findtext("date") or "")
        source_node = node.find("source")
        source_name = (source_node.text or "").strip() if source_node is not None else source.name
        if title and url and published:
            items.append(NewsItem(title, published, url, source_name or source.name, source.kind))
    return items


def parse_listing_html(content: bytes, source: Source) -> list[NewsItem]:
    parser = _LinkParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    items = []
    for href, title, context in parser.links:
        # 個別資料のタイトル・ファイル名はリスト周辺の表示日付より確実。
        published = _parse_date(title) or _parse_date(href) or _parse_date(context)
        if published and len(title) >= 6 and not href.lower().startswith(("javascript:", "mailto:")):
            items.append(NewsItem(title, published, urljoin(source.url, href), source.name, source.kind))
    return items


def classify_event(item: NewsItem) -> MaterialEvent | None:
    # 市況コメントを会社イベントとして誤認しない。
    if item.source_type == "信頼できる報道" and any(word in item.title for word in ("株価", "相場", "ランキング")):
        return None
    for category, keywords, affected, impacts, watch in EVENT_RULES:
        if any(keyword.lower() in item.title.lower() for keyword in keywords):
            return MaterialEvent(item, category, affected, impacts, watch)
    return None


def _google_news_source(company_name: str) -> Source:
    query_name = company_name.replace("株式会社", "").strip()
    query = quote(f'"{query_name}" when:365d')
    return Source("Google News", f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja", "信頼できる報道", "rss")


def collect_material_events(
    company_name: str,
    security_code: str,
    *,
    today: date | None = None,
    timeout: float = 12,
    get=requests.get,
) -> MaterialResult:
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=370)
    sources = (*OFFICIAL_SOURCES.get(security_code[:4], ()), _google_news_source(company_name))
    items: list[NewsItem] = []
    errors: list[str] = []
    for source in sources:
        try:
            response = get(source.url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            parsed = parse_rss(response.content, source) if source.format == "rss" else parse_listing_html(response.content, source)
            if source.kind == "信頼できる報道":
                parsed = [item for item in parsed if any(name.lower() in item.source_name.lower() for name in RELIABLE_NEWS)]
            items.extend(item for item in parsed if cutoff <= item.published_date <= today)
        except (requests.RequestException, ElementTree.ParseError, UnicodeError, ValueError) as exc:
            errors.append(f"{source.name}: {exc}")

    seen: set[str] = set()
    events: list[MaterialEvent] = []
    category_counts: dict[str, int] = {}
    for item in sorted(items, key=lambda value: value.published_date, reverse=True):
        key = re.sub(r"[\s　]+|[（(]訂正[)）]", "", item.title).lower()
        if key in seen:
            continue
        seen.add(key)
        event = classify_event(item)
        if event and category_counts.get(event.category, 0) < 2:
            events.append(event)
            category_counts[event.category] = category_counts.get(event.category, 0) + 1
    return MaterialResult(tuple(events[:10]), tuple(errors))
