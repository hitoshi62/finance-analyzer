from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd
import streamlit as st

from edinet_client import (
    CODE_LIST_URL, Company, EdinetClient, EdinetError, find_companies,
    find_latest_annual_filing, load_company_list, read_api_key,
)
from edinet_parser import parse_financial_values, read_edinet_csv_zip
from display_formatting import (
    format_money as money, format_multiple as mult, format_percent as pct,
    optional_attribute,
)
from company_profile import (
    business_profile, financial_analysis_type, find_parent_suggestion,
    resolve_parent_company,
)
from financial_analysis import (
    PeerSnapshot, build_six_frame_analysis,
    classify_business_model, comparison_outlier_warning, comparison_statistics,
    industry_comparison_caution, roe_engine_explanation, select_peer_candidates,
)
from financial_cache import FinancialResult, load_financial_with_fallback
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


def load_financial_result(api_key: str, company: Company) -> FinancialResult:
    def fetch_live():
        filing = find_latest_annual_filing(
            company, lambda target_date: cached_document_list(api_key, target_date)
        )
        values = parse_financial_values(
            read_edinet_csv_zip(cached_document_csv(api_key, filing.doc_id)),
            company.has_consolidated,
        )
        return filing, values

    return load_financial_with_fallback(company, fetch_live)


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
    parent_suggestion = find_parent_suggestion(query)
    if parent_suggestion:
        st.info(
            f"{parent_suggestion.subsidiary_name}は非上場企業です。\n\n"
            f"上場親会社『{parent_suggestion.parent_name}』を分析しますか？"
        )
        if st.checkbox("上場親会社を分析対象にする", key="use_listed_parent"):
            selected = resolve_parent_company(companies, parent_suggestion)
            if selected is None:
                st.warning("EDINET企業一覧から上場親会社を特定できませんでした。")
    else:
        st.warning("該当する日本の上場企業が見つかりません。正式名称、4桁証券コード、EDINETコードを確認してください。")

if st.button("分析する", type="primary", use_container_width=True, disabled=selected is None):
    profile = business_profile(selected)
    analysis_type = financial_analysis_type(selected, profile)
    try:
        api_key = read_api_key(st.secrets)
        with st.spinner("EDINETから対象企業と同業他社の有価証券報告書を検索・取得中..."):
            financial_result = load_financial_result(api_key, selected)
            filing, values, metrics = financial_result.filing, financial_result.values, financial_result.metrics
            d = asdict(metrics)
            peers: list[PeerSnapshot] = []
            peer_errors: list[str] = []
            peer_candidates = () if analysis_type != "general" else select_peer_candidates(selected.industry, selected.security_code)
            if not peer_candidates and analysis_type == "general":
                peer_candidates = tuple(
                    (company.security_code[:4],
                     f"事業内容ルール未登録のためEDINET業種「{selected.industry}」一致から暫定選定")
                    for company in companies
                    if company.industry == selected.industry
                    and company.edinet_code != selected.edinet_code
                )[:2]
            peer_reasons = dict(peer_candidates)
            for peer_code, _reason in peer_candidates:
                candidates = find_companies(companies, peer_code)
                if not candidates:
                    peer_errors.append(f"証券コード{peer_code}: 企業を特定できません")
                    continue
                peer_company = candidates[0]
                try:
                    peer_result = load_financial_result(api_key, peer_company)
                    peer_filing, peer_metrics = peer_result.filing, peer_result.metrics
                    peers.append(PeerSnapshot(
                        peer_company.name, peer_company.security_code[:4],
                        peer_filing.period_end, peer_metrics,
                    ))
                    if peer_result.from_cache:
                        peer_errors.append(
                            f"{peer_company.name}: EDINET最新取得失敗のため前回取得データを使用"
                            f"（最終取得 {peer_result.last_retrieved_at}）"
                        )
                except EdinetError as exc:
                    peer_errors.append(f"{peer_company.name}: {exc}")
    except EdinetError as exc:
        st.error(str(exc))
        st.stop()

    st.subheader(f"{selected.name}（証券コード {selected.security_code[:4]} / {selected.edinet_code}）")
    st.write(profile.description)
    if financial_result.from_cache:
        st.warning(
            "EDINET最新取得に失敗したため、前回取得データを使用しています。"
            f" 最終取得日時: {financial_result.last_retrieved_at}（UTC）"
        )
    elif financial_result.cache_warning:
        st.warning(financial_result.cache_warning)
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

    if analysis_type == "general":
        c1, c2, c3 = st.columns(3)
        c1.metric("ROE", pct(d["roe"]))
        c2.metric("ROA", pct(d["roa"]))
        c3.metric("純利益率", pct(d["net_margin"]))
        c4, c5, c6 = st.columns(3)
        c4.metric("営業利益率", pct(d["operating_margin"]))
        c5.metric("総資産回転率", mult(d["asset_turnover"]))
        c6.metric("財務レバレッジ", mult(d["financial_leverage"], "倍"))

        st.markdown("### ROEの作られ方（DuPont分解）")
        st.write(f"**{pct(d['net_margin'])} × {mult(d['asset_turnover'])} × {mult(d['financial_leverage'], '倍')} = {pct(d['roe'])}（概算）**")
        classification = classify_business_model(metrics, peers)
        st.write(f"**主分類:** {classification.primary}")
        st.write("**補助特性:** " + (" / ".join(classification.characteristics) or "なし"))
        roe_notes = roe_engine_explanation(metrics, peers)
        if len(roe_notes) > 1:
            st.write("• " + roe_notes[1])
        with st.expander("DuPont分析を詳しく見る"):
            for note in (roe_notes[:1] + roe_notes[2:]):
                st.write("• " + note)
    elif analysis_type == "bank":
        st.markdown("### 金融業専用分析")
        st.caption("金融業は預貸・運用構造が一般企業と異なるため、一般企業用DuPont分析の対象外です。")
        c1, c2, c3 = st.columns(3)
        c1.metric("ROE", pct(d["roe"]))
        c2.metric("ROA", pct(d["roa"]))
        c3.metric("自己資本比率", pct(optional_attribute(values, "bank_equity_ratio")))
        currency = optional_attribute(values, "currency") or ""
        bank_table = pd.DataFrame({
            "主要KPI": ["総資産", "純利益", "経常利益", "貸出金", "預金", "利ざや関連指標"],
            "値": [money(optional_attribute(values, "current_assets"), currency),
                   money(optional_attribute(values, "net_income"), currency),
                   money(optional_attribute(values, "ordinary_income"), currency),
                   money(optional_attribute(values, "loans"), currency),
                   money(optional_attribute(values, "deposits"), currency), "データ取得不可"],
        })
        st.dataframe(bank_table, hide_index=True, use_container_width=True)
    else:
        financial_labels = {
            "securities": ("証券業", "証券業専用KPIは今後対応予定です。"),
            "insurance": ("保険業", "保険業専用KPIは今後対応予定です。"),
            "financial": ("その他金融業", "その他金融業専用KPIは今後対応予定です。"),
        }
        label, message = financial_labels[analysis_type]
        st.markdown(f"### {label}専用分析")
        st.info(message + " 銀行用KPIは流用せず、取得できない値の推定も行いません。")

    if analysis_type == "general":
        st.markdown(f"### 財務データ（{fiscal_period}）")
        table = pd.DataFrame({
            "項目": ["売上高", "営業利益", "純利益", "平均総資産", "平均自己資本"],
            "値": [money(d[key], values.currency) for key in ("revenue", "operating_income", "net_income", "avg_assets", "avg_equity")],
            "対象年度": [fiscal_period] * 5,
        })
        st.dataframe(table, hide_index=True, use_container_width=True)

    if analysis_type == "general":
        st.markdown("### 同業他社比較")
    comparison_caution = industry_comparison_caution(selected.industry) if analysis_type == "general" else None
    if comparison_caution:
        st.warning(comparison_caution)
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
    if analysis_type == "general":
        st.dataframe(comparison, hide_index=True, use_container_width=True)
        with st.expander("同業候補の選定理由"):
            if peer_candidates:
                peer_names_by_code = {peer.security_code: peer.name for peer in peers}
                for peer_code, reason in peer_candidates:
                    name = peer_names_by_code.get(peer_code, "取得できなかった候補")
                    st.write(f"• {name}（{peer_code}）: {reason}")
            else:
                st.write("比較可能な同業候補を取得できませんでした。")
    statistics = comparison_statistics(metrics, peers)
    summary = pd.DataFrame({
        "集計": ["単純平均", "中央値"],
        "対象社数": [len(comparison_rows)] * 2,
        "ROE": [pct(statistics[key]["roe"]) for key in ("average", "median")],
        "ROA": [pct(statistics[key]["roa"]) for key in ("average", "median")],
        "営業利益率": [pct(statistics[key]["operating_margin"]) for key in ("average", "median")],
        "純利益率": [pct(statistics[key]["net_margin"]) for key in ("average", "median")],
        "総資産回転率": [mult(statistics[key]["asset_turnover"]) for key in ("average", "median")],
        "財務レバレッジ": [mult(statistics[key]["financial_leverage"], "倍") for key in ("average", "median")],
    })
    if analysis_type == "general":
        st.dataframe(summary, hide_index=True, use_container_width=True)
    outlier_warning = comparison_outlier_warning(metrics, peers)
    if analysis_type == "general" and outlier_warning:
        st.warning(outlier_warning)
    if analysis_type == "general" and peer_errors:
        st.warning("一部の同業データを取得できませんでした: " + " / ".join(peer_errors))

    with st.spinner("直近約1年の公式発表・重要ニュースを確認中..."):
        try:
            material_result = cached_material_events(selected.name, selected.security_code)
        except Exception as exc:  # ニュース障害でEDINET分析を止めない
            material_result = MaterialResult((), (f"最新材料の取得処理: {exc}",))

    st.markdown("### 財務・業界分析")
    if analysis_type == "general":
        analysis = build_six_frame_analysis(
            selected.name, selected.industry, fiscal_period, metrics, peers, material_result.events
        )
    elif analysis_type == "bank":
        latest = [
            f"{event.item.published_date.isoformat()}「{event.item.title}」— {event.financial_impacts[0]}"
            for event in material_result.events[:3]
        ] or ["最新材料を取得できなかったため、EDINET開示値のみを表示しています。"]
        analysis = {
            "財務上の強み": ["銀行業ではROE・ROA、自己資本の厚み、預貸構造を組み合わせて確認します。"],
            "財務上の弱み": ["取得できない銀行KPIは推定していません。EDINET原本の業務別・セグメント別情報も確認が必要です。"],
            "業界構造": ["銀行は預金等で調達した資金を貸出・運用するため、一般企業の売上高ベースのDuPont比較には適しません。"],
            "最新材料": latest,
            "今後の注目指標": ["貸出金、預金、利ざや、与信費用、自己資本比率の推移。"],
            "投資家が確認すべき点": ["金利環境、貸出先の信用リスク、資本規制、傘下銀行の収益構成を確認する。"],
        }
    else:
        industry_label = {"securities": "証券業", "insurance": "保険業", "financial": "その他金融業"}[analysis_type]
        analysis = {
            "財務上の強み": [f"{industry_label}専用KPIは未実装のため、強みを推定評価していません。"],
            "財務上の弱み": [f"{industry_label}専用KPIは未実装のため、弱みを推定評価していません。"],
            "業界構造": [f"{industry_label}は一般企業や銀行と収益・資産構造が異なるため、専用指標での分析が必要です。"],
            "最新材料": ["最新材料は下記の根拠欄で確認してください。"],
            "今後の注目指標": [f"{industry_label}固有の指標は今後対応予定です。"],
            "投資家が確認すべき点": ["EDINET原本の事業別収益、リスク情報、自己資本に関する開示を確認してください。"],
        }
    key_points = [
        analysis["財務上の強み"][0],
        analysis["財務上の弱み"][0],
        analysis["業界構造"][0],
    ]
    st.caption("まず押さえたい要点")
    for note in key_points:
        st.write("• " + note)

    with st.expander("詳しい財務・業界分析"):
        for title in ("財務上の強み", "財務上の弱み", "業界構造", "最新材料"):
            st.markdown(f"#### {title}")
            for note in analysis[title]:
                st.write("• " + note)

    with st.expander("今後の注目指標"):
        for note in analysis["今後の注目指標"]:
            st.write("• " + note)

    with st.expander("投資家が確認すべき点"):
        for note in analysis["投資家が確認すべき点"]:
            st.write("• " + note)

    st.markdown("### 最新材料の根拠（直近約1年）")
    if material_result.events:
        st.caption("主な材料: " + " / ".join(event.item.title for event in material_result.events[:2]))
    with st.expander("最新材料の根拠"):
        if material_result.events:
            st.caption("取得した事実と、ルールベースで推定した財務への影響を分けて表示します。影響は確定事項ではありません。")
            for index, event in enumerate(material_result.events):
                if index:
                    st.divider()
                st.markdown(f"#### {event.item.published_date.isoformat()}｜{event.category}")
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
    if analysis_type == "general":
        st.info("計算式: ROE=純利益÷平均自己資本、ROA=純利益÷平均総資産、純利益率=純利益÷売上高、営業利益率=営業利益÷売上高、総資産回転率=売上高÷平均総資産、財務レバレッジ=平均総資産÷平均自己資本。")
    st.caption("平均残高は当期末と前期末のEDINET開示値から算出。同業比較は事業内容ルールを優先し、未登録時はEDINET業種から暫定選定した代表2社の最新有価証券報告書を使用。最新材料は公式発表・許可リスト化した報道の見出しを根拠に、財務への影響可能性をルールベースで整理しています。数値・分析は投資判断ではなく学習用の概算です。")

st.divider()
st.caption(f"企業情報: [金融庁 EDINETコードリスト]({CODE_LIST_URL}) / 財務情報: 金融庁 EDINET API Version 2")
st.caption("EDINETの利用条件とAPI仕様を遵守し、取得結果を24時間キャッシュして不要な反復アクセスを抑制しています。")
