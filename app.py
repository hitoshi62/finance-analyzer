from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Optional

import pandas as pd
import streamlit as st

from edinet_client import (
    CODE_LIST_URL, Company, EdinetClient, EdinetError, find_companies,
    find_latest_annual_filing, load_company_list, read_api_key,
)
from edinet_parser import parse_financial_values, read_edinet_csv_zip
from financial_metrics import calculate_metrics

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


def analysis_text(d: dict[str, Any]) -> list[str]:
    notes = []
    roe, margin, turnover, lev, roa = d["roe"], d["net_margin"], d["asset_turnover"], d["financial_leverage"], d["roa"]
    if roe is not None:
        if roe >= 0.15:
            notes.append("ROEは高水準。株主資本を効率よく利益に変えている。")
        elif roe >= 0.08:
            notes.append("ROEはまずまずの水準。収益性と資本効率の内訳確認が重要。")
        elif roe >= 0:
            notes.append("ROEは低め。利益率・資産回転率・レバレッジのどこが弱いかを見る必要がある。")
        else:
            notes.append("ROEはマイナス。最終赤字または自己資本の特殊要因を確認したい。")
    if margin is not None:
        if margin >= 0.10:
            notes.append("純利益率が高く、本業・コスト構造・価格決定力のいずれかに強みがある可能性が高い。")
        elif margin < 0.03:
            notes.append("純利益率は薄め。売上規模が大きくても利益が残りにくい構造の可能性がある。")
    if turnover is not None:
        if turnover >= 1.2:
            notes.append("総資産回転率は高め。保有資産を売上に変える効率が良い。")
        elif turnover < 0.6:
            notes.append("総資産回転率は低め。設備・不動産・金融資産など重い資産構成の可能性がある。")
    if lev is not None:
        if lev >= 3.0:
            notes.append("財務レバレッジは高め。ROE押上げ要因になり得る一方、負債依存度も確認したい。")
        elif lev <= 1.8:
            notes.append("財務レバレッジは低めで、自己資本の厚い財務構造。")
    if roa is not None and roa < 0.03:
        notes.append("ROAは低め。会社全体の資産効率という観点では改善余地がある。")
    if None not in (margin, turnover, lev, roe):
        dupont = margin * turnover * lev
        if math.isfinite(dupont):
            notes.append(f"DuPont分解の概算では、利益率×資産回転率×財務レバレッジ ≒ {dupont*100:.1f}%（ROEとのズレは平均残高・会計項目差など）。")
    return notes[:5] or ["必要な財務項目を十分取得できませんでした。EDINET原本の財務諸表をご確認ください。"]


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
        with st.spinner("EDINETから最新の有価証券報告書を検索・取得中..."):
            filing = find_latest_annual_filing(selected, lambda target_date: cached_document_list(api_key, target_date))
            values = parse_financial_values(read_edinet_csv_zip(cached_document_csv(api_key, filing.doc_id)), selected.has_consolidated)
            metrics = calculate_metrics(values)
            d = asdict(metrics)
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
    st.markdown("### 簡潔な分析")
    for note in analysis_text(d):
        st.write("• " + note)
    st.info("計算式: ROE=純利益÷平均自己資本、ROA=純利益÷平均総資産、純利益率=純利益÷売上高、営業利益率=営業利益÷売上高、総資産回転率=売上高÷平均総資産、財務レバレッジ=平均総資産÷平均自己資本。")
    st.caption("平均残高は当期末と前期末のEDINET開示値から算出しています。数値は投資判断ではなく学習・企業分析用の概算です。")

st.divider()
st.caption(f"企業情報: [金融庁 EDINETコードリスト]({CODE_LIST_URL}) / 財務情報: 金融庁 EDINET API Version 2")
st.caption("EDINETの利用条件とAPI仕様を遵守し、取得結果を24時間キャッシュして不要な反復アクセスを抑制しています。")
