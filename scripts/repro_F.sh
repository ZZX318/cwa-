#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/f1_heading90_table.py
/home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py

# F2 tables only (no replan):
# /home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py --report-only results/F2_noninteger_dw_71278c2.meta.json
