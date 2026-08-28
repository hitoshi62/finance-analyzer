# 企業財務分析アプリ

日本の上場企業を企業名、証券コード、EDINETコードで検索し、金融庁EDINETに提出された最新の有価証券報告書から財務指標を概算するStreamlitアプリです。

- ROE / ROA
- 純利益率 / 営業利益率
- 総資産回転率 / 財務レバレッジ
- 売上高、営業利益、純利益、平均総資産、平均自己資本
- DuPont分解を含む短い分析

## データ取得元と利用上の注意

- 企業情報は金融庁の公式EDINETコードリストを使用します。
- 財務数値はEDINET API Version 2から取得した有価証券報告書のXBRL変換CSVを使用します。
- 画面には書類管理番号、提出日時、対象決算期、EDINET原本へのリンクを表示します。
- 不要な反復アクセスを避けるため、企業一覧・書類一覧・取得書類を24時間キャッシュします。
- 金融庁の[EDINET API仕様書・関連資料](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WZEK0110.html)と[利用規約](https://disclosure2.edinet-fsa.go.jp/usageTerms/)を確認し、遵守してください。
- 本アプリは金融庁の公式アプリではなく、表示値は学習・企業分析用の概算です。

## EDINET APIキー

EDINET API Version 2の利用にはAPIキーが必須です。APIキーは公開リポジトリへ保存しないでください。

```bash
export EDINET_API_KEY="発行されたAPIキー"
./run.sh
```

または `.streamlit/secrets.toml.example` を `.streamlit/secrets.toml` にコピーして設定できます。Streamlit Community Cloudではアプリ設定のSecretsに登録します。

```toml
EDINET_API_KEY = "発行されたAPIキー"
```

## ローカル起動

```bash
./run.sh
```

手動起動の場合:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## テスト

```bash
python -m pytest
```

## 対応範囲

- 日本の上場企業のみを対象にします。
- 最新の有価証券報告書（書類種別コード120）を利用します。
- EDINET変換CSVが提供されている書類を対象にします。
- 連結財務諸表がある会社では連結値を優先します。
- 日本基準・IFRS・米国基準の主要な標準要素を対象にしますが、企業独自の拡張要素や金融業固有の表示では一部項目を取得できない場合があります。
