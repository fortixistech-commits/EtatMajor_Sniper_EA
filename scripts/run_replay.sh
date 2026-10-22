#!/usr/bin/env bash
# Reproducible laboratory run (Phase 2 deliverable).
#
# Usage: ./scripts/run_replay.sh [data_file]
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${VENV_EM:-.venv}"
DATA="${1:-data/sample_eurusd_1m.csv}"
CONFIG="${CONFIG:-configs/simulation.toml}"

if [ ! -d "$VENV" ]; then
  echo "==> creating $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install -e ".[dev]"
fi

echo "==> validating the dataset"
"$VENV/bin/python" -m etatmajor.cli validate --data "$DATA" --config "$CONFIG"

echo "==> running the replay"
"$VENV/bin/python" -m etatmajor.cli replay \
  --data "$DATA" \
  --config "$CONFIG" \
  --report artifacts/report.json \
  --journal artifacts/journal.jsonl \
  --pending-limit

echo "==> done: artifacts/report.json and artifacts/journal.jsonl"
