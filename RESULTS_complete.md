# 完整工程交付（dbm 代定，恒已授权领导）

> 工作副本：`/workspace/cwa-bench`，分支 `paper/zones-drift-p1`。  
> 基线 HEAD（开工时）：`d51ed09`。本文档与随后的 ARCHITECTURE 入库 / 复现入口 / 检查提交会叠在其后。  
> **禁止事项（本交付遵守）**：不改 `planning/` 算法语义；不做 nn_astar / 2-opt / 风力基准 / 修复带 / 岛状缓冲扩或 buffer_expand=ON 附录 / τ 感知偏移；不 push；不编造数字；不重跑 30 场景主集。

---

## 1. 主线定稿声明

**主线（定稿）**：缓冲区约束 + 缓冲边界航道对齐（`S_h` / `B-boundary`）。

- **标注**：dbm 代定，恒已授权领导（群聊「农业工程学报论文」当晚交付口径）。
- **含义**：
  - 缓冲区约束：园外/贴边敏感禁喷沿下风做 Minkowski 内扩（`expand_sensitive_inward`）。方法表述为**约束**（引孔令标 2026），**不是创新点**。
  - 缓冲边界航道对齐：启发式 `S_h`（0°，`o_h = (xmin − x_F) mod w`，喷幅边贴齐缓冲前沿）相对地块边界对齐代理 `B-boundary`（简化自张昆 2022 摘要，**不是原方法复现**）。
- **`buffer_expand` / 岛状禁喷**：主实验显式开启上风缓冲外扩（buffer_expand=1，d 按风速分档取 10/16 m，见 `scripts/a_trial_heading.py` L209 与 meta 顶层 buffer_expand=1.0）；园内岛状禁喷区不外扩（见 drift 检查「园内岛状禁喷不扩」）；软件默认值为 0。（口径更正：此前写作「主结果跟默认（OFF）」有误，数字不变。）
- **固定条带修复带**：今晚不做；拒出保持 fail-closed（见 §4）。
- **新功能**：先交完本闭环工程包（A–E），再开新功能；本交付不开 nn_astar / 2-opt / 风力基准等。

---

## 2. 关键数字指针（只引用已有报告 / CSV / commit）

下列数字均来自已归档产物；完整表在 `RESULTS_overnight.md` 对应节。此处只给指针与一句已写结论，**不重抄估数**。

### 2.1 五种子 A 试验（§1）

| 项 | 指针 |
|---|---|
| 运行 | `scripts/a_trial_heading.py --seeds 0-4 --workers 7` @ commit **`2ff2df1`** |
| CSV | `results/a_trial_seeds0-4_2ff2df1.csv`（逐 seed：`results/a_trial_seed{0..4}_2ff2df1.csv`）+ `.summary.json` / `.meta.json` / `.log` |
| 汇总 | `scripts/a_trial_5seed_report.py 2ff2df1` → `results/a_trial_seeds0-4_2ff2df1.report.md` |
| 隔夜正文 | `RESULTS_overnight.md` §1「A 小试 seed 0–4」 |
| 检查日志 | `results/drift_checks_after_seeds0-4.log`；`results/check_after_seeds0-4.log` |

已写结论（出处同上，非本文件新算）：U=2、τ≥0.5 时按均值 `S_h` 在 `A_extra` 上优于网格搜索 `S3`；U=2、τ>0 时 `S3` 多数退回与 `S_h` 同计划（见 item2 / 1b「不淡化」段）。

### 2.2 对照基线 1b（§1b）

| 项 | 指针 |
|---|---|
| 主批 | `2ff2df1` → `results/a_trial_seeds0-4_2ff2df1.csv` |
| 90°/`o_h` | `scripts/a_trial_extra_runs.py --variants oh_rot` @ **`58024ac`** → `results/a_trial_extra_oh_rot_h90_58024ac.csv` |
| 基线 | `scripts/a_trial_extra_runs.py --variants b_online,b_boundary --headings 0,90 --seeds 0-4` @ **`0e0715a`** → `results/a_trial_extra_b_online_b_boundary_h0_90_0e0715a.csv` |
| 汇总 | `scripts/a_trial_1b_report.py 2ff2df1 58024ac 0e0715a` → `results/a_trial_1b_0e0715a.report.md` + `.overnight_section.md` |
| 隔夜正文 | `RESULTS_overnight.md` §1b |

已写结论（出处同上）：合并 `o_h` 后，U=2 且 τ>0 时 `S3` 在 4/5 seed 上等于 `S_h`；搜索增益几乎全部来自几何边界对齐。

### 2.3 喷幅敏感性 1c（w=3，假设值）（§1c）

| 项 | 指针 |
|---|---|
| 主批 / oh_rot / 基线 | 均 @ commit **`25d2e4f`**，`--swath 3`；CSV 见 `results/a_trial_*_25d2e4f_w3.*` |
| 汇总 | `scripts/a_trial_1c_report.py 25d2e4f 3` → `results/a_trial_1c_25d2e4f_w3.report.md` |
| 隔夜正文 | `RESULTS_overnight.md` §1c |

说明：w=3 m 为假设值，不替代 w=2 主结果。

### 2.4 余数扫描 1c-sweep（§1c-sweep）

| 项 | 指针 |
|---|---|
| 产物 | `results/a_trial_1c_sweep_7e7318e.{report.md,overnight_section.md,rows.csv,table.csv,fit.json}` + PNG |
| 隔夜正文 | `RESULTS_overnight.md` §1c-sweep |
| 代码提交 | 含 1c-sweep 的提交链止于 **`d51ed09`**（附拒出探针说明） |

已写主结论（出处 §1c-sweep 解读）：对齐缓冲线相对对齐地块边界的收益，大致等于「被切掉那条带里的冠层面积」——只有缓冲距不是喷幅整数倍、且切带压在树行上时才明显，否则打平。

---

## 3. τ=1.0 s 敏感性（正式定为敏感性档）

- **已有结果**：A 小试评价器与汇总已含 τ∈{0, 0.5, **1.0**}（自 commit **`70db42d`** 起写入；主批数字见 `results/a_trial_seeds0-4_2ff2df1.report.md` / `RESULTS_overnight.md` §1 各 τ 分表）。1b / 1c / 1c-sweep 配对表同样按三档 τ 独立选取。
- **文献依据（一句）**：Wang Z K 等 2023（Journal of Agricultural Engineering）在 4～6 m/s 航速下测得未补偿滞后平均约 3.87 m（摘要已核），换算等效延迟约 **0.6～1.0 s**；滞后还含雾滴下落与系统响应，不能全算阀门。故 τ 敏感性上限正式取 **1.0 s**；**今晚不加 1.5 / 1.9 s**。
- **本交付未新开大批实验**：未重跑 30 场景；未另造 τ 表。若需「突出 τ=1.0 主对比」的数字，直接读上述已有 CSV/报告中的 τ=1.0 列。

---

## 4. 拒出附录指针

- 正文：`RESULTS_overnight.md` 节 **「1c-sweep 附：S1 在 w=4、d=10 被拒绝出计划的原因」**（commit **`d51ed09`**）。
- 只读探针：`scripts/s1_w4_reject_probe.py`（同提交）。
- 口径：fail-closed；`geom_missing==safety_missing`；同场景下 `S_h` / `B-boundary` 仍能出计划 → **规划器在合法输入上有缺口，不是「喷不到」安全 bug**。修复带本阶段不做。

---

## 5. 未做项清单（本交付明确不做）

| 项 | 状态 |
|---|---|
| nn_astar（近邻排序 / 第 3 项） | 暂停 |
| 2-opt（第 4 项） | 暂停 |
| 风力基准（第 5 项） | 暂停 |
| 固定条带「修复带」 | 不做（fail-closed 保留） |
| 岛状禁喷外扩 / `buffer_expand` 附录 | 不做（主实验已显式开启 buffer_expand=1，d=10/16 m；园内岛状禁喷区不外扩；软件默认值为 0） |
| τ 感知偏移 | 不做 |
| `git push` | 不做（仅本地 commit） |

---

## 6. 可复现入口（主对比，冻结）

主对比 = **`S_h` vs `B-boundary`**（1b 配对，从已冻结 CSV 重算表，**不重规划**）。

```bash
# 在 /workspace/cwa-bench，工作树可有未跟踪文件；下列 CSV 必须存在且 SHA256 如下。
# 钉死数据 commit：main=2ff2df1, oh_rot=58024ac, baseline=0e0715a
bash scripts/repro_main_contrast.sh
```

等价单行：

```bash
python3 scripts/a_trial_1b_report.py 2ff2df1 58024ac 0e0715a
```

- 写出：`results/a_trial_1b_0e0715a.report.md`、`results/a_trial_1b_0e0715a.overnight_section.md`
- **完整重规划**（多小时、非本交付要求）仍是历史命令：  
  `python3 scripts/a_trial_heading.py --seeds 0-4 --workers 7` @ `2ff2df1`，以及  
  `python3 scripts/a_trial_extra_runs.py --variants b_online,b_boundary --headings 0,90 --seeds 0-4` @ `0e0715a`。本交付**禁止**为交包而重跑。

### 6.1 本机跑通记录

- 复现命令：`bash scripts/repro_main_contrast.sh`
- 退出码：**0**（日志 `results/repro_main_contrast_d51ed09.log`）
- 关键摘要：三份钉死 CSV SHA256 全部 OK；`a_trial_1b_report.py 2ff2df1 58024ac 0e0715a` 重写出 `results/a_trial_1b_0e0715a.report.md` / `.overnight_section.md`；附段核对 U=2 τ∈{0.5,1.0} 时 S3 与 S_h 同计划 4/5（与既有 1b 结论一致）。**未重规划**。
- `python3 drift_checks.py`：**23 通过 / 0 失败**，exit 0（`results/drift_checks_after_complete_delivery.log`）
- `python3 main.py --check`：**170 通过 / 0 失败**，exit 0（`results/check_after_complete_delivery.log`）
- 跑通时刻：2026-11-06 Asia/Shanghai（约 02:06–02:09）

---

## 7. 相关路径速查

| 文件 | 作用 |
|---|---|
| `RESULTS_overnight.md` | 隔夜实验全文（§1 / 1b / 1c / 1c-sweep / 拒出附 / 覆盖率口径） |
| `ARCHITECTURE.md` | 架构说明（更新到本分支 HEAD；旧节保留） |
| `scripts/repro_main_contrast.sh` | 冻结主对比复现入口 |
| `README.md` | 工程总说明（主对比入口见下节补链，若已写入） |
