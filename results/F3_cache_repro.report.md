# F3 cache hash repro（步骤①，只读）

结论：同进程先跑 seed2 U=2 heuristic 0°，再跑 seed2 U=2 B-boundary 0°，可稳定复现池内错配 hash `dc9c98d6…`；新进程只跑 B 得冻结 hash `4a81e0ea…`。根因是 `_ROUTE_CACHE` 对 start/goal 做 `round(..., 9)` 后发生假命中，却返回第一次调用的全精度端点，污染 plan 航段坐标。

## 1. 池内前序任务

`results/F3_main_checkpoint.jsonl` 完成序（非 worker PID；池未记 PID）：

| 序 | seed | variant | U | heading | solve_s | plan_hash 前缀 |
|---|---|---|---|---|---|---|
| 14 | 2 | heuristic | 2.0 | 0 | 77.7 | `d742d538…` |
| **15** | **2** | **b_boundary** | **2.0** | **0** | **13.9** | **`dc9c98d6…`（错配）** |

推断前序 = 同 seed/U/heading 的 heuristic：完成序紧邻，且 B 的 13.9 s 远短于冻结 134.4 s / 新进程 ~78–84 s。受控复现用「同进程 pred→target」代替未记录的 worker 亲和。

## 2. 受控复现

命令：

```bash
/home/box/.venvs/mpl/bin/python scripts/f3_cache_hash_repro.py --mode lane_compare --out results/F3_cache_repro_lanes.json
/home/box/.venvs/mpl/bin/python scripts/f3_cache_hash_repro.py --mode chained --out results/F3_cache_repro_chained.json
/home/box/.venvs/mpl/bin/python scripts/f3_cache_hash_repro.py --mode fresh_target --out results/F3_cache_repro_fresh.json
```

| 条件 | plan_hash | vs 冻结 | vs 池 | solve_s | route hits/misses | false_endpoint |
|---|---|---|---|---|---|---|
| chained：先 heuristic 再 B | `dc9c98d65faa6dd350207837387a4b8aba106bd50086c9653ae42d0260432f12` | 否 | **是** | 13.4 | **403/0** | **25** |
| fresh：只跑 B | `4a81e0ea87be1bbc291cf334a1ad82a4c8162711ad60ddc445d3d91bca98443c` | **是** | 否 | 77.8 | 0/403 | 0 |
| pred（chained 内） | `d742d538e13bfd1a70b42f2b5e25e7d5b31dd80e3c9bd546bab9169a311c2f86` | — | — | 78.5 | 0/403 | 0 |

false_endpoint 例（B 请求 goal x=`2.0`，缓存返回 heuristic 的 `1.9999999999999996`，`round9` 仍相等）：见 `F3_cache_repro_chained.json` → `chained.route_cache_stats_during_target.examples`。

## 3. 指标是否等于冻结（池行）

是。池内错配行与冻结 / 新进程在下列字段逐字相等：

- `A_extra_tau0` = 0.0
- `A_extra_tau0.5` = 0.5875000000000001
- `A_extra_tau1` = 1.3725000000000003
- `total_time` = 1442.2321342517662
- `violations` = 0

另：`path_length` / `path_spray` / `n_lanes` 亦相等。汇总表数字不受 hash 错配影响；错的是 plan 坐标指纹。

## 4. Cache key 与根因

`planning/routing3d.py`：

- `_ROUTE_CACHE` key = `(fingerprint(scene), config_fingerprint(effective), objective, round(start,9), round(goal,9), step_xy, step_z, max_expansions, max_grid_nodes, smoothing)`
- 命中后 `return copy.deepcopy(cached)`，path 端点是**第一次**写入时的 start/goal
- `_GRID_CACHE` key 含 scene/config/step 与 z，**不含** start/goal XY（共享占用格，本例非主因）

**并非** key 漏了 no-spray / no-fly / buffer d / heading / seed / U：这些已进入 `fingerprint(scene)` 或 `config_fingerprint`（本例 pred/target 的 scene 与 U/heading 配置一致）。

**真正缺的是**：全精度 start/goal（或命中后把 path 端点改写成本次请求）。heuristic offset `0.15000000000000036` 与 B offset `0.1499999999999999` 差 `4.44e-16`；402 条航道中 **32** 个端点 bit 不等、**0** 个 `round9` 不等 → 403 次 route 全假命中 → plan 段坐标混入 heuristic 的 ULP → hash=`dc9c98d6…`。

航道对比：`results/F3_cache_repro_lanes.json`。

## 5. 步骤②建议（本步未改 planning/）

1. 命中后重写 `path[0]=start`、`path[-1]=goal`（或 key 改用全精度 / 更高位数）；或每个 job 开头 `clear_cache()`。
2. 加测试：同 scene 下 ULP 不同的 start/goal，打乱顺序后 `fingerprint(plan)` 不变。
3. 修完再用 `maxtasksperchild=1` 重跑 F3 main 80 固化 hash。

本步：`planning/` 未改。
