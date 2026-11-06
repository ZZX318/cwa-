# 项目8 一键复现：正文 6 张图表（图1、图2、表1–表4）

默认模式**不重新规划**：只读 9 个冻结 CSV/JSON（外加 2 张参照 PNG），先校验 SHA256，再重算全部数字、重绘图1/图2，
并与稿件快照（当前 v3.9）逐格比对。所有输出写到 `results/repro_main/`（已加入 `.gitignore`），不改任何入库文件，`planning/` 零改动。

## 一条命令

```bash
cd /workspace/wt-P8
MPLCONFIGDIR=/tmp/mplcfg /workspace/.venv-fig/bin/python scripts/repro_main.py
```

退出码：`0` 全部通过；`1` 与稿件有不等格；`2` 冻结输入 SHA256 不符（不会继续计算）；`3` 子步骤校验失败
（表2 误差表重建与入库文件不一致、图2 json checks 与 CSV 不符、规划器被调用）；`4` 运行后有入库文件被改动。

## 环境（本次实测）

| 项 | 值 |
|---|---|
| 解释器 | `/workspace/.venv-fig/bin/python`（Python 3.13.5） |
| 包 | numpy 2.5.4，matplotlib 3.11.2；其余只用标准库（不需要 scipy：精确 Wilcoxon 自写全枚举） |
| 字体 | `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc`（作图脚本内 `configure_fonts`） |
| 代码 | 分支 `task/P8`：`a32944b`（task/F123）+ merge `979cf79`（task/T2T3 作图脚本，`42ff628`，只新增文件） |

## 实测耗时（冷跑一次）

2026-11-06 02:05 EST，删除 `results/repro_main/` 并换用新的空 `MPLCONFIGDIR` 后：

```
( time MPLCONFIGDIR=/tmp/mplcfg_cold /workspace/.venv-fig/bin/python scripts/repro_main.py ) → exit_code=0
real 0m5.767s   user 0m5.916s   sys 0m0.631s
```

## 流程与输出（`results/repro_main/`）

| 步骤 | 输入 → 脚本 | 输出 | 核对项 |
|---|---|---|---|
| 0 SHA256 | 9 个冻结输入 + 2 张参照 PNG（清单见 `scripts/p8_common.py`，同 `/workspace/paper/proj8_repro_spec.md` §2） | `sha256_check.json` | 任一不符 → exit 2 |
| 表1 | `F3_main_postcache_46360be_geom.csv` → `p8_main_tables.py`（d=11/13）+ `p8_table1_d15.py`（d=15 两行，非配对） | `table1_numbers.csv`、`table1_d15.csv`、`table1_table3_notes.json` | 均值±样本 SD；表注 p=0.0020（精确 Wilcoxon，6 格）、冷重跑 16/16、d=15 lane_found 0/10、可配对 n=0、L=[14,15] |
| 表2 | `c1_blind_predict_seed10.json` + `c1_blind_plans_ed94b82.csv` → `p8_table2_error.py`（补「误差表无生成脚本」缺口） | `table2_error_table.csv`、`table2_error_diff.md` | 与入库 `c1_blind_error_table.csv` **逐字节相同**（150/150 字段） |
| 表3 | geom.csv（d=11/13）+ `F3_main_postcache_46360be_main.csv`（整数档 d=10）→ `p8_main_tables.py` | `table3_numbers.csv` | 含 ≡ 判定（90° B ≡ oh_rot、整数档 0° S_h ≡ B，逐 seed \|Δ\|≤1e-9）、d=15 90° 表注、时间代价段 |
| 表4 | 表3 d=11 行 → `p8_table4.py`（原为手工派生，补脚本） | `table4_values.csv` | 每个数字带来源；差值/百分比由均值计算 |
| 图1 | `a_trial_heading.scene0(0)` + `scene/random_map.py` → `figA_scene_construction.py`（模块 `PREFIX` 改指输出目录后调用 `main()`，脚本未改） | `fig1_scene_construction.{png,pdf,json,caption.md}`、`fig1_numbers.json` | 图注数字；json 与入库 `figA_scene_construction.json` 除 commit/路径外相等；PNG 字节比对 |
| 图2 | `F2_noninteger_dw_71278c2.csv/.geom.json` → `fig1b_noninteger_buffer_lanes.py`（同上） | `fig2_noninteger_buffer_lanes.{png,pdf,json,caption.md}`、`fig2_numbers.json` | json checks（plan_hash、A_extra、total_time、offset）与 CSV 一致；与入库 json checks 相等；PNG 字节比对 |
| 比对 | `scripts/p8_manuscript_expected.json`（`p8_extract_manuscript.py` 抽自 `/workspace/paper/draft_v3_skeleton.md` v3.9，sha256 `6655de0a…`；原 v3.7 快照 `a5a4c194…`=`bak8.md`，两版 6 张图表只差表2 出处注误差定义一句） | `compare.md`、`compare.csv`、`run_meta.json` | 稿件写几位小数就按几位比；表2 出处注须写「误差 = 实测 − 预测」且与 CSV 符号一致（1 项 claim）；每次运行另查现行稿件的 6 张图表是否仍与快照一致 |

默认模式不调用规划器：`repro_main.py` 在导入后把所有已加载模块里的 `generate_plan` / `make_planner` 换成计数并报错的守卫，
运行结束 `planner calls` 必须为 0（记录在 `run_meta.json`）。

## 两个作图脚本单独运行的确切命令

两脚本都把输出写到入库路径 `results/figA_scene_construction.*` / `results/fig1b_noninteger_buffer_lanes.*`（没有 `--out` 参数）。
caption 模板已与入库 `*.caption.md` 同步（见下），直接运行时两份 caption 与 PNG 不变；但 figA json 的 `commit`/`outputs` 字段和两份 PDF 的字节会变，运行后用 `git checkout -- <file>` 还原即可。`repro_main.py` 改 `PREFIX` 写到 `results/repro_main/`，不碰入库文件。

```bash
# 图1（figA，不规划，json 记 planning_ran: False）
MPLCONFIGDIR=/tmp/mplcfg /workspace/.venv-fig/bin/python scripts/figA_scene_construction.py
# 图2（fig1b，只读 F2 CSV/geom；import fig1_scene_buffer_lanes 作绘图工具）
MPLCONFIGDIR=/tmp/mplcfg /workspace/.venv-fig/bin/python scripts/fig1b_noninteger_buffer_lanes.py
```

实测（2026-11-06 02:18 EST，在 wt-P8 入库目录按上面两条命令直接运行；caption 模板已同步：fig1b 写 `[x_F, x_F+(w−r)]`（同 `70bd376`），
figA 中英文均含 d=16 时 x_F 由 9 m 变为 15 m 一句（同 `979cf79`），figA 图注末尾的 commit 固定为作图逻辑最后改动的 `2e35a75`（`FIG_LOGIC_COMMIT`），
不再取运行时 HEAD）：两条命令退出码均为 0；两份 `*.caption.md` 与两张 PNG 均与入库版**逐字节相同**（git status 无变化）。
仍会变化的入库文件只有三个，运行后已用 `git checkout --` 还原：`figA_scene_construction.json`（`commit` 取运行时 HEAD、`outputs` 为绝对路径）、
`figA_scene_construction.pdf`（仅 `/CreationDate`）、`fig1b_noninteger_buffer_lanes.pdf`（`/CreationDate` 和一段内嵌字体流字节，大小不变；
两份 PDF 用 pdftoppm 以 100 dpi 渲染，与入库版逐像素相同）。图上图例仍写 `x_F+r`，按约定不重绘。 给 figA 补 d=16 时 x_F=15），
脚本模板没有同步（fig1b 模板仍写 `[x_F, x_F+r]`，图上图例同样是 `x_F+r`，图未重绘）。所以不要在入库目录直接运行这两个脚本。

## `--replan`（全量重规划；本次未运行）

```bash
MPLCONFIGDIR=/tmp/mplcfg /workspace/.venv-fig/bin/python scripts/repro_main.py --replan
```

只打印命令清单并退出，**不执行**。表1/表3/表4 全量重规划耗时上界约 **12525.6 s ≈ 3.5 h**，按现有日志相加：
F2 60 次 1772.9 s（`F2.report.md` L11）+ F3 首跑 5574.2 s（`F3_run.log` 末行；主 80 与几何 60 无法拆开，主 80 后被 postcache 取代，故为上界）
+ F3 postcache 主对比 5178.5 s（`F3_main_postcache_run.log` 末行）。另：表2 实测 12 次 303.1 s，几何档冷重跑 16 格 622.6 s。
注意：`f3_seed_expand.py`（含 `--report-only`）会改写 `results/F3_tables.md` 与 `results/F3.report.md`；`c1_blind_plans.py` 要求
`results/c1_blind_plans_{HEAD}.csv` 不存在且每次都重规划。重规划只应在临时 worktree 中手动运行。

## 回归检查（debe9e5 工作树）

`python3 -u drift_checks.py` → 通过 23、失败 0；`python3 -u main.py --check` → 通过 171、失败 0（日志 `results/p8_drift.log`、
`results/p8_main_check.log`；冷跑输出与 `time` 记录 `results/p8_repro_main_cold.log`）。`git diff a32944b -- planning/` 为空。

2026-11-06 02:30 EST 同步 caption 模板后复跑：`repro_main.py` exit 0、PASS 316 / FAIL 0、规划调用 0；drift 23/0；`main.py --check` 171/0（日志未覆盖，仍为上面三份）。

2026-11-06 02:29 EST 快照由 v3.7 换为 v3.9（只改表2 出处注误差定义为「实测 − 预测」）：比对项 316→317（新增上述 1 项 claim），原 316 项结果逐项不变；PASS 317 / FAIL 0。
