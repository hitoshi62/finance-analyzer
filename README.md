# 企業財務分析アプリ MVP

企業名またはティッカーを入力すると、Yahoo Finance の公開データを `yfinance` 経由で取得し、以下を表示します。

- ROE
- ROA
- 純利益率
- 営業利益率
- 総資産回転率
- 財務レバレッジ
- DuPont分解を含む短い分析

## Macでの起動

最短では、次のコマンドだけで仮想環境の作成、依存関係の導入、起動まで行えます。

```bash
./run.sh
```

手動で起動する場合:

```bash
cd finance-analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで通常 `http://localhost:8501` が開きます。

## 無料クラウド公開（iPhone対応）

このアプリは Streamlit Community Cloud にそのままデプロイできます。公開後は発行された `https://...streamlit.app` のURLをiPhoneのSafariから開けます。

1. このフォルダをGitHubリポジトリへpushします（公開・非公開のどちらでも利用可能）。
2. [Streamlit Community Cloud](https://share.streamlit.io/)へGitHubアカウントでログインします。
3. `Create app` → `Yup, I have an app` を選択します。
4. GitHubリポジトリとブランチを指定し、エントリポイントに `app.py` を指定します。
5. `Advanced settings` でPythonを **3.11** に指定します。
6. `Deploy` を押します。このアプリにAPIキーやSecretsの設定は不要です。

依存関係は、動作確認済みのNumPy 1.26 / PyArrow 14の組み合わせに固定しています。PythonのバージョンはファイルではなくCommunity Cloudのデプロイ画面で選択します。

## 入力例

- `トヨタ自動車`
- `7203.T`
- `Apple`
- `AAPL`

## 注意

- 企業名検索は Yahoo Finance の検索結果に依存するため、同名企業などでは誤認識する場合があります。その場合はティッカーを直接入力してください。
- Yahoo Finance / yfinance は公式IRやEDINETそのものではありません。実務・投資判断向けに精度を上げるなら、次段階で EDINET API / 各社IR / XBRL を一次情報源として追加するのが適切です。
- 初回起動時はPythonパッケージをダウンロードするため、インターネット接続が必要です。
- macOSで `xcode-select` エラーが出る場合は、Command Line ToolsまたはHomebrew版Pythonを導入してから再実行してください。
