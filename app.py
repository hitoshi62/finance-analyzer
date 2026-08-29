from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

import pandas as pd
import streamlit as st

from edinet_client import (
    CODE_LIST_URL, Company, EdinetClient, EdinetError, find_companies,
    find_latest_annual_filing, load_company_list, read_api_key,
)
from edinet_parser import parse_financial_values, read_edinet_csv_zip
from financial_analysis import (
    FRAME_TITLES, PeerSnapshot, build_six_frame_analysis,
    representative_peer_codes,
)
from financial_metrics import calculate_metrics
from news_analysis import MaterialResult, collect_material_events

st.set_page_config(page_title="企業財務分析", page_icon="📊", layout="wide")


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_company_list() -> list[Company]:
    return load_company_list()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_document_list(api_key: str, target_date) -> list[dict[str, Any]]:
    return EdinetClient(api_key).list_documents(target_date)


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_document_csv(api_key: str, doc_id: str) -> bytes:
    return EdinetClient(api_key).download_csv(doc_id)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def cached_material_events(company_name: str, security_code: str) -> MaterialResult:
    return collect_material_events(company_name, security_code)


def pct(x: Optional[float]) -> str:
    return "取得不可" if x is None else f"{x * 100:.1f}%"


def mult(x: Optional[float], unit: str = "回") -> str:
    return "取得不可" if x is None else f"{x:.2f}{unit}"


def money(x: Optional[float], currency: str) -> str:
    if x is None:
        return "取得不可"
    ax = abs(x)
    if ax >= 1e12:
        return f"{x/1e12:.2f}兆 {currency}".strip()
    if ax >= 1e8:
        return f"{x/1e8:.1f}億 {currency}".strip()
    if ax >= 1e6:
        return f"{x/1e6:.1f}百万 {currency}".strip()
    return f"{x:,.0f} {currency}".strip()


def load_financial_result(api_key: str, company: Company):
    filing = find_latest_annual_filing(
        company, lambda target_date: cached_document_list(api_key, target_date)
    )
    values = parse_financial_values(
        read_edinet_csv_zip(cached_document_csv(api_key, filing.doc_id)),
        company.has_consolidated,
    )
    return filing, values, calculate_metrics(values)


st.title("企業財務分析アプリ")
st.caption("日本の上場企業を検索し、金融庁EDINETの有価証券報告書から主要指標を概算します。")
st.caption("入力: 企業名、4桁証券コード、またはEDINETコード")
query = st.text_input("企業名 / 証券コード / EDINETコード", placeholder="例: トヨタ自動車 / 7203 / E02144")

try:
    companies = cached_company_list() if query.strip() else []
    matches = find_companies(companies, query) if query.strip() else []
except EdinetError as exc:
    st.error(str(exc))
    matches = []

selected: Company | None = None
if len(matches) == 1:
    selected = matches[0]
elif len(matches) > 1:
    labels = {f"{company.name}（証券コード {company.security_code[:4]} / {company.edinet_code}）": company for company in matches}
    selected = labels[st.selectbox("候補企業を選択", list(labels))]
elif query.strip():
    st.warning("該当する日本の上場企業が見つかりません。正式名称、4桁証券コード、EDINETコードを確認してください。")

if st.button("分析する", type="primary", use_container_width=True, disabled=selected is None):
    try:
        api_key = read_api_key(st.secrets)
        with st.spinner("EDINETから対象企業と同業他社の有価証券報告書を検索・取得中..."):
            filing, values, metrics = load_financial_result(api_key, selected)
            d = asdict(metrics)
            peers: list[PeerSnapshot] = []
            peer_errors: list[str] = []
            peer_codes = representative_peer_codes(selected.industry, selected.security_code)
            if not peer_codes:
                peer_codes = tuple(
                    company.security_code[:4]
                    for company in companies
                    if company.industry == selected.industry
                    and company.edinet_code != selected.edinet_code
                )[:2]
            for peer_code in peer_codes:
                candidates = find_companies(companies, peer_code)
                if not candidates:
                    peer_errors.append(f"証券コード{peer_code}: 企業を特定できません")
                    continue
                peer_company = candidates[0]
                try:
                    peer_filing, _, peer_metrics = load_financial_result(api_key, peer_company)
                    peers.append(PeerSnapshot(
                        peer_company.name, peer_company.security_code[:4],
                        peer_filing.period_end, peer_metrics,
                    ))
                except EdinetError as exc:
                    peer_errors.append(f"{peer_company.name}: {exc}")
    except EdinetError as exc:
        st.error(str(exc))
        st.stop()

    st.subheader(f"{selected.name}（証券コード {selected.security_code[:4]} / {selected.edinet_code}）")
    if selected.industry:
        st.caption(selected.industry)
    if not metrics.has_financials:
        st.error("この報告書から必要な財務データを取得できませんでした。EDINET原本をご確認ください。")
        st.stop()
    fiscal_period = filing.period_end or "決算期不明"
    basis = "連結" if values.consolidated else "個別"
    accounting = values.accounting_standard or "会計基準不明"
    st.info(f"対象決算期: **{fiscal_period}** / {accounting} / {basis}")
    st.markdown(f"データ取得元: 金融庁 EDINET「{filing.doc_description}」（書類管理番号 [{filing.doc_id}]({filing.source_url})、提出日時 {filing.submit_datetime}）")

    c1, c2, c3 = st.columns(3)
    c1.metric("ROE", pct(d["roe"]))
    c2.metric("ROA", pct(d["roa"]))
    c3.metric("純利益率", pct(d["net_margin"]))
    c4, c5, c6 = st.columns(3)
    c4.metric("営業利益率", pct(d["operating_margin"]))
    c5.metric("総資産回転率", mult(d["asset_turnover"]))
    c6.metric("財務レバレッジ", mult(d["financial_leverage"], "倍"))

    st.markdown(f"### 財務データ（{fiscal_period}）")
    table = pd.DataFrame({
        "項目": ["売上高", "営業利益", "純利益", "平均総資産", "平均自己資本"],
        "値": [money(d[key], values.currency) for key in ("revenue", "operating_income", "net_income", "avg_assets", "avg_equity")],
        "対象年度": [fiscal_period] * 5,
    })
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.markdown("### 同業他社比較")
    comparison_rows = [PeerSnapshot(selected.name, selected.security_code[:4], fiscal_period, metrics), *peers]
    comparison = pd.DataFrame({
        "企業": [row.name for row in comparison_rows],
        "証券コード": [row.security_code for row in comparison_rows],
        "対象決算期": [row.fiscal_period for row in comparison_rows],
        "ROE": [pct(row.metrics.roe) for row in comparison_rows],
        "ROA": [pct(row.metrics.roa) for row in comparison_rows],
        "営業利益率": [pct(row.metrics.operating_margin) for row in comparison_rows],
        "純利益率": [pct(row.metrics.net_margin) for row in comparison_rows],
        "総資産回転率": [mult(row.metrics.asset_turnover) for row in comparison_rows],
        "財務レバレッジ": [mult(row.metrics.financial_leverage, "倍") for row in comparison_rows],
    })
    st.dataframe(comparison, hide_index=True, use_container_width=True)
    if peer_errors:
        st.warning("一部の同業データを取得できませんでした: " + " / ".join(peer_errors))

    with st.spinner("直近約1年の公式発表・重要ニュースを確認中..."):
        try:
            material_result = cached_material_events(selected.name, selected.security_code)
        except Exception as exc:  # ニュース障害でEDINET分析を止めない
            material_result = MaterialResult((), (f"最新材料の取得処理: {exc}",))

    st.markdown("### 財務・業界分析")
    analysis = build_six_frame_analysis(
        selected.name, selected.industry, fiscal_period, metrics, peers, material_result.events
    )
    for index in range(0, len(FRAME_TITLES), 2):
        columns = st.columns(2)
        for column, title in zip(columns, FRAME_TITLES[index:index + 2]):
            with column:
                st.markdown(f"#### {title}")
                for note in analysis[title]:
                    st.write("• " + note)
    st.markdown("### 最新材料の根拠（直近約1年）")
    if material_result.events:
        st.caption("取得した事実（発表タイトル）と、ルールベースで推定した財務への影響を分けて表示します。影響は確定事項ではありません。")
        for event in material_result.events:
            with st.expander(f"{event.item.published_date.isoformat()}｜{event.category}｜{event.item.title}"):
                st.markdown(f"**取得した事実:** [{event.item.title}]({event.item.url})")
                st.write(f"発表日: {event.item.published_date.isoformat()} / 情報源: {event.item.source_name} / 種別: {event.item.source_type}")
                st.markdown("**財務への影響（可能性）:**")
                for impact in event.financial_impacts:
                    st.write("• " + impact)
                st.write("影響候補の指標: " + "、".join(event.affected_metrics))
                st.write("今後の確認項目: " + "、".join(event.watch_metrics))
    else:
        st.info("重要材料を確認できなかったため、財務分析のみ表示しています。")
    if material_result.errors:
        st.warning("一部の情報源を取得できませんでした（財務分析は継続）: " + " / ".join(material_result.errors))
    st.info("計算式: ROE=純利益÷平均自己資本、ROA=純利益÷平均総資産、純利益率=純利益÷売上高、営業利益率=営業利益÷売上高、総資産回転率=売上高÷平均総資産、財務レバレッジ=平均総資産÷平均自己資本。")
    st.caption("平均残高は当期末と前期末のEDINET開示値から算出。同業比較は代表2社の最新有価証券報告書を使用。最新材料は公式発表・許可リスト化した報道の見出しを根拠に、財務への影響可能性をルールベースで整理しています。数値・分析は投資判断ではなく学習用の概算です。")

st.divider()
st.caption(f"企業情報: [金融庁 EDINETコードリスト]({CODE_LIST_URL}) / 財務情報: 金融庁 EDINET API Version 2")
st.caption("EDINETの利用条件とAPI仕様を遵守し、取得結果を24時間キャッシュして不要な反復アクセスを抑制しています。")
