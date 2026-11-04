# A 小试 seed 0：重叠判定修复（bb22ae6）前后逐行对比

- 旧：results/a_trial_seed0_c92be77.csv（16 主行 + no_zone/wind_away/rot180）+ results/a_trial_seed0_0f3a583_rot180aligned.csv
- 新：results/a_trial_seed0_70db42d.csv（同 24 行，τ 增加 1.0 s；旧表无 τ=1.0 列，不比较）
- 比较字段：status/stage、A_excluded、A_extra τ=0/0.5、total_time、n_lanes、strip_count、cut_segments、cut_boundaries、excluded_targets、violations、spray_samples、path_spray、plan_hash（容差 1e-6）
- 机器可读：results/a_trial_seed0_70db42d.diff_vs_c92be77.{json,txt}（scripts/a_trial_diff.py）
- 原因证据：results/a_trial_seed0_overlap_probe.json（scripts/a_trial_overlap_probe.py：在规划坐标系、外扩后场景上逐条带复现 planner 的 0.05 m Y 切片扫描，分别用旧网格实现和新精确面积实现判定）

## 变化的行（2 行）

| 行 | 旧 | 新 | 原因 |
|---|---|---|---|
| main U=2 90°/0 | failed@safety：漂移硬检查违规 | success；A_excl 123.6225，A_extra τ0/0.5/1.0 = 3.6225/13.6650/27.5575，time 1434.5265 s，407 lanes，cut 9，violations 0 | 规划系条带 382（x=95.903）喷幅 [94.903, 96.903] 与外扩禁喷区 x 向重叠仅 0.097 m（精确面积 0.2817 m²）。旧网格（nx=20，步长 0.1 m）0/59 个切片判重叠 → 该条带未切；新实现 59/59 → 切成 transit。旧失败信息"喷洒采样点…进入原始禁喷区"即这条漏切的条带（U=4 旧报的例点 x=94.903 正是该喷幅边缘）。 |
| main U=4 90°/0 | failed@safety：64 个喷洒采样点下风 16 m 内进入原始禁喷区，例 [94.903, 9.5184] | success；A_excl 242.8325，A_extra τ0/0.5/1.0 = 6.9775/12.0550/18.9400，time 1654.2669 s，407 lanes，cut 5，violations 0 | 同上：条带 382、383（x=95.903）重叠 0.097 m（精确面积 0.2817 / 0.3010 m²），旧 0/59、0/63 切片判重叠，新 59、63。 |

## 未变化的行（22 行）

main U=2 / U=4 的 0°×{0,0.5,1.0,1.5} 和 90°×{0.5,1.0,1.5}（14 行），以及 no_zone、wind_away、rot180、rot180_aligned 各两档（8 行）：所有比较字段（含 plan_hash）逐位相同。
原因：probe 显示这 22 行里没有任何条带的旧/新切片判定不同（changed=0）；同时用旧计划的全部喷洒段足迹 vs 评价器 F 复查，旧/新实现均为 0 次相交、漏判 0。也就是说窄于 0.1 m 的重叠只在 90°/偏移 0 这个相位出现。
