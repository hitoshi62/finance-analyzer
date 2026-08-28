#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
if ! python -c "import streamlit, pandas, pyarrow, requests" >/dev/null 2>&1; then
  python -m ensurepip --upgrade
  python -m pip install -r requirements.txt
fi
python -m streamlit run app.py
