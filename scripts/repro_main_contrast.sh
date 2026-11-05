#!/usr/bin/env bash
# Frozen main-contrast repro: S_h vs B-boundary tables from pinned CSVs (no replan).
# Data commits: main=2ff2df1, oh_rot=58024ac, baseline=0e0715a
# Run from repo root: bash scripts/repro_main_contrast.sh
set -euo pipefail
cd "$(dirname "$0")/.."

MAIN=2ff2df1
OH=58024ac
BASE=0e0715a

need=(
  "results/a_trial_seeds0-4_${MAIN}.csv:02e8655782c9f1ef4c124c3022f50edba6e13e9055f74e08d7cc903b3861ecbc"
  "results/a_trial_extra_oh_rot_h90_${OH}.csv:a5d677c53ac7add91864b507c2234f87ada274a2245ea8d1ec07500bcb8e0bfc"
  "results/a_trial_extra_b_online_b_boundary_h0_90_${BASE}.csv:bd26882d939352469da6f6340086c38ec5878c1df9ba52b504f912ff77cca99c"
)

echo "repro_main_contrast: verify pinned CSV SHA256"
for entry in "${need[@]}"; do
  path="${entry%%:*}"
  want="${entry##*:}"
  if [[ ! -f "$path" ]]; then
    echo "MISSING $path" >&2
    exit 2
  fi
  got=$(sha256sum "$path" | awk '{print $1}')
  if [[ "$got" != "$want" ]]; then
    echo "SHA256 mismatch $path" >&2
    echo "  want $want" >&2
    echo "  got  $got" >&2
    exit 3
  fi
  echo "  OK $path"
done

echo "repro_main_contrast: regenerate 1b report (S_h vs B-boundary)"
python3 scripts/a_trial_1b_report.py "$MAIN" "$OH" "$BASE"
echo "repro_main_contrast: wrote results/a_trial_1b_${BASE}.report.md and .overnight_section.md"
echo "repro_main_contrast: DONE exit 0"
