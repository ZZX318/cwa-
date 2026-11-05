#!/usr/bin/env bash
set -euo pipefail
# 「新增，不改已冻结主表」
# T10 repair lane variant
python3 scripts/t10_repair_lane_validate.py
python3 drift_checks.py
python3 main.py --check

# T8 wind baseline (+ no_wind_awareness tier)
python3 scripts/wind_baseline_T8.py --workers 4
python3 drift_checks.py
python3 main.py --check
