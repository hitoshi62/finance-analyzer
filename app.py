import math
import re
from typing import Dict, Any, Optional
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="企業財務分析", page_icon="📊", layout="wide")


def _first_existing(df: pd.DataFrame, names: list[str]) -> Optional[float]:
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            row = df.loc[name]
            if isinstance(row, pd.Series):
                for value in row.values:
                    if pd.notna(value):
                        try:
                            return float(value)
                        except Exception:
                            pass
            elif pd.notna(row):
                try:
                    return float(row)
                except Exception:
                    pass
    return None


def _two_period_values(df: pd.DataFrame, names: list[str]) -> list[float]:
    if df is None or df.empty:
        return []
    for name in names:
        if name in df.index:
            row = df.loc[name]
            vals = []
            if isinstance(row, pd.Series):
                for v in row.values[:2]:
                    if pd.notna(v):
                        try:
                            vals.append(float(v))
                        except Exception:
                            pass
            return vals
    return []


def avg_balance(df: pd.DataFrame, names: list[str]) -> Optional[float]:
    vals = _two_period_values(df, names)
    if not vals:
        return None
    return sum(vals) / len(vals)


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


@st.cache_data(ttl=60 * 60, show_spinner=False)
def resolve_symbol(query: str) -> tuple[str, str]:
    """Resolve company name/ticker with yfinance Search. Fallback to raw input."""
    q = query.strip()
    if re.fullmatch(r"\d{4}", q):
        q = f"{q}.T"
    try:
        search = yf.Search(q, max_results=8, news_count=0)
        quotes = getattr(search, "quotes", []) or []
        equities = [x for x in quotes if x.get("quoteType") in ("EQUITY", None)]
        jp = [x for x in equities if str(x.get("exchange", "")).upper() in {"JPX", "TYO", "OSA"} or str(x.get("symbol", "")).endswith(".T")]
        is_japanese_query = bool(re.search(r"[ぁ-んァ-ヶ一-龠]", q)) or q.endswith(".T")
        candidates = (jp if is_japanese_query else equities) or equities or quotes
        if candidates:
            c = candidates[0]
            return c.get("symbol", q), c.get("longname") or c.get("shortname") or c.get("symbol", q)
    except Exception:
        pass
    if re.search(r"[ぁ-んァ-ヶ一-龠]", q):
        try:
            response = requests.get(
                "https://finance.yahoo.co.jp/search/",
                params={"query": q},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            response.raise_for_status()
            match = re.search(
                r'"detailLink":"https://finance\.yahoo\.co\.jp/quote/([^"/]+)".*?"name":"([^"]+)"',
                response.text,
                re.DOTALL,
            )
            if match:
                return match.group(1), match.group(2)
        except Exception:
            pass
    return q, q


@st.cache_data(ttl=60 * 60, show_spinner=False)
def get_data(symbol: str) -> Dict[str, Any]:
    t = yf.Ticker(symbol)
    income = t.income_stmt
    balance = t.balance_sheet
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    revenue = _first_existing(income, ["Total Revenue", "Operating Revenue"])
    net_income = _first_existing(income, ["Net Income", "Net Income Common Stockholders"])
    operating_income = _first_existing(income, ["Operating Income"])

    avg_assets = avg_balance(balance, ["Total Assets"])
    avg_equity = avg_balance(balance, ["Stockholders Equity", "Total Equity Gross Minority Interest"])

    roe = safe_div(net_income, avg_equity)
    roa = safe_div(net_income, avg_assets)
    net_margin = safe_div(net_income, revenue)
    operating_margin = safe_div(operating_income, revenue)
    asset_turnover = safe_div(revenue, avg_assets)
    financial_leverage = safe_div(avg_assets, avg_equity)

    fiscal_date = income.columns[0] if income is not None and not income.empty else None
    if fiscal_date is not None:
        try:
            fiscal_timestamp = pd.Timestamp(fiscal_date)
            fiscal_period = f"{fiscal_timestamp.year}年{fiscal_timestamp.month:02d}月期"
        except Exception:
            fiscal_period = str(fiscal_date)
    else:
        fiscal_period = "決算期不明"
    source_url = f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/financials/"

    return {
        "revenue": revenue,
        "net_income": net_income,
        "operating_income": operating_income,
        "avg_assets": avg_assets,
        "avg_equity": avg_equity,
        "roe": roe,
        "roa": roa,
        "net_margin": net_margin,
        "operating_margin": operating_margin,
        "asset_turnover": asset_turnover,
        "financial_leverage": financial_leverage,
        "currency": info.get("financialCurrency") or info.get("currency") or "",
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "website": info.get("website", ""),
        "fiscal_period": fiscal_period,
        "source_url": source_url,
        "has_financials": any(
            value is not None
            for value in (revenue, net_income, avg_assets, avg_equity)
        ),
    }


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


def analysis_text(d: Dict[str, Any]) -> list[str]:
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

    # DuPont consistency note
    if None not in (margin, turnover, lev, roe):
        dupont = margin * turnover * lev
        if math.isfinite(dupont):
            notes.append(f"DuPont分解の概算では、利益率×資産回転率×財務レバレッジ ≒ {dupont*100:.1f}%（ROEとのズレは平均残高・会計項目差など）。")

    return notes[:5] or ["必要な財務項目を十分取得できなかった。ティッカーを直接入力すると改善する場合がある。"]


st.title("企業財務分析アプリ")
st.caption("会社名またはティッカーを入力すると、公開財務データから主要指標を概算します。")

query = st.text_input("企業名 / ティッカー", placeholder="例: トヨタ自動車 / 7203.T / AAPL")

if st.button("分析する", type="primary", use_container_width=True) and query.strip():
    with st.spinner("企業を特定して財務データを取得中..."):
        symbol, company = resolve_symbol(query)
        try:
            d = get_data(symbol)
        except Exception as e:
            st.error(f"財務データの取得に失敗しました: {e}")
            st.stop()

    st.subheader(f"{company}  ({symbol})")
    if not d["has_financials"]:
        st.error(
            "この銘柄の財務データを取得できませんでした。"
            "上場企業のティッカー（例: 7203.T / AAPL）で再度お試しください。"
        )
        st.stop()
    if d["sector"] or d["industry"]:
        st.caption(" / ".join(x for x in [d["sector"], d["industry"]] if x))
    st.info(f"対象決算期: **{d['fiscal_period']}**（この決算期の年次財務数値を使用）")
    st.markdown(f"データ取得元: [Yahoo Finance 財務ページ]({d['source_url']})")

    c1, c2, c3 = st.columns(3)
    c1.metric("ROE", pct(d["roe"]))
    c2.metric("ROA", pct(d["roa"]))
    c3.metric("純利益率", pct(d["net_margin"]))

    c4, c5, c6 = st.columns(3)
    c4.metric("営業利益率", pct(d["operating_margin"]))
    c5.metric("総資産回転率", mult(d["asset_turnover"]))
    c6.metric("財務レバレッジ", mult(d["financial_leverage"], "倍"))

    st.markdown(f"### 財務データ（{d['fiscal_period']}）")
    table = pd.DataFrame({
        "項目": ["売上高", "営業利益", "純利益", "平均総資産", "平均自己資本"],
        "値": [money(d["revenue"], d["currency"]), money(d["operating_income"], d["currency"]), money(d["net_income"], d["currency"]), money(d["avg_assets"], d["currency"]), money(d["avg_equity"], d["currency"])],
        "対象年度": [d["fiscal_period"]] * 5,
    })
    st.dataframe(table, hide_index=True, use_container_width=True)

    st.markdown("### 簡潔な分析")
    for note in analysis_text(d):
        st.write("• " + note)

    st.info("計算式: ROE=純利益÷平均自己資本、ROA=純利益÷平均総資産、純利益率=純利益÷売上高、総資産回転率=売上高÷平均総資産、財務レバレッジ=平均総資産÷平均自己資本。")
    st.caption(f"対象年度: {d['fiscal_period']} / データ取得元: Yahoo Finance（yfinance経由）。投資判断ではなく学習・企業分析用の概算です。")
