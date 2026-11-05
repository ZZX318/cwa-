#!/usr/bin/env bash
set -euo pipefail
# 「新增，不改已冻结主表」
# T10 repair lane variant
python3 scripts/t10_repair_lane_validate.py
python3 drift_checks.py
python3 main.py --check
