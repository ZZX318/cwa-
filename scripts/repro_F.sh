#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/f1_heading90_table.py
/home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py

# F2 tables only (no replan):
# /home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py --report-only results/F2_noninteger_dw_71278c2.meta.json

# F3: replan frozen main seeds 0-4 and new 5-9; geometric seeds 0-4 reuse F2
/home/box/.venvs/mpl/bin/python scripts/f3_seed_expand.py --workers 5 --f2-csv results/F2_noninteger_dw_71278c2.csv
