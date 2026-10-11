#!/usr/bin/env bash
# 一键启动（Linux / macOS）：bash run.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ -d ".libs/fastapi" ]; then
  echo "使用项目内置依赖 (.libs)"
  export PYTHONPATH=".libs"
  PY=python3
else
  if [ ! -d ".venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv .venv
  fi
  echo "安装依赖..."
  ./.venv/bin/python -m pip install --upgrade pip -q
  ./.venv/bin/python -m pip install -r requirements.txt -q
  PY=./.venv/bin/python
fi

echo "构建索引..."
"$PY" scripts/build_index.py

echo "启动服务： http://127.0.0.1:8000"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
