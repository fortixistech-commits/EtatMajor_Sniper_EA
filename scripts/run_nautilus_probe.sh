#!/usr/bin/env bash
# Reproduce the NautilusTrader evaluation probe (Phase 2).
#
# The probe runs in an isolated virtual environment with the pinned version:
# it never touches the project virtualenv and never sends a real order.
#
# Usage: ./scripts/run_nautilus_probe.sh
set -euo pipefail

cd "$(dirname "$0")/.."

VENV="${VENV_NT:-.venv-nautilus}"
VERSION="1.231.0"

if [ ! -d "$VENV" ]; then
  echo "==> creating $VENV with nautilus_trader==$VERSION"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install "nautilus_trader==$VERSION"
fi

echo "==> probe on the sample dataset"
"$VENV/bin/python" scripts/probe_nautilus.py \
  --data data/sample_eurusd_1m.csv \
  --output artifacts/nautilus_probe.json

echo "==> probe on the gapped dataset (look-ahead evidence)"
"$VENV/bin/python" scripts/probe_nautilus.py \
  --data tests/fixtures/gap_gap.csv \
  --output artifacts/nautilus_probe_gap.json

echo "==> done: see artifacts/nautilus_probe*.json"
