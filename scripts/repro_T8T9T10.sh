#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# 「新增，不改已冻结主表」
# Order: T10 → T8 → T9 (tech-lead updated)

echo "=== T10 repair_lanes variant (default off; control stays fail-closed) ==="
python3 scripts/t10_repair_lane_validate.py
python3 drift_checks.py
python3 main.py --check

echo "=== T8 wind baseline (+ no_wind_awareness / downwind baseline tier) ==="
python3 scripts/wind_baseline_T8.py --workers 4
python3 drift_checks.py
python3 main.py --check

echo "=== T9 buffer_expand ON vs OFF sensitivity appendix (no planning/ change) ==="
python3 scripts/buffer_expand_sensitivity_T9.py --workers 4
python3 drift_checks.py
python3 main.py --check

echo "repro_T8T9T10 DONE"
