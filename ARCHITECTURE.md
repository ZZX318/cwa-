# ARCHITECTURE.md — cwa 果园植保无人机航线规划实验平台

> 撰写时间：2026-11-04 02:33 PST（America/Los_Angeles）；02:50 PST 更新到 `e057a98`；03:00 PST 增补 `799da32`/`a444a93`（§9–§10）；03:05 PST 增补 `6343968` P0 切带验收（§11）；03:17 PST 增补 `eb36dc4`/`ff9e290` P1 验收（§12）；**2026-11-06 Asia/Shanghai 增补 §13，叙事基线 `HEAD = d51ed09`（分支 `paper/zones-drift-p1`）**。
> **基线叙事**：§1–§8 仍以 `e057a98`/`3076ba2` 为主；§9–§12 保留到 `ff9e290` 的验收笔记（**旧节不删，版本标签保留**）。§13 覆盖 `ff9e290..d51ed09`：Minkowski 缓冲修正、精确 overlap、A 小试评价口径、`S_h`、以及完整工程交付入口。
> 标注约定：**【已验证】** 表示在本机实际运行或逐行读码确认过；**【推断】** 表示根据读码推理得出、没有专门运行验证。
> 行号：§1–§4.3 以 `3076ba2` 为准；§4.4 和标注 e057a98 的地方以 `e057a98` 为准；缓冲/评价口径以 §13 所列提交为准。

---

## 1. 项目定位与运行方式

**一句话定位**：这是一个纯标准库的 Python 实验平台（附带本地 Web 前端），面向果园植保无人机。它在“树冠圆柱 + 障碍盒 + 禁飞/禁喷棱柱”的三维场景中，比较固定 Y 条带基线、逐目标 naive 基线和 CAW-A*（三维净空 + 风向代价 + 顺序优化）等航线规划方法。每条航线都要经过统一的安全校验、执行时间线和网格覆盖评价。平台还支持多机、架次补给、起降点优化和批量随机场景实验，服务于《农业工程学报》论文。

- **依赖**：`requirements.txt` 只要求 Python ≥ 3.9，没有任何第三方依赖。README 默认使用 Mac 上的 `.venv/bin/python`；本机直接用 `python3` 就能跑通全部检查。【已验证】
- **唯一入口**：`main.py`（argparse，约 600 行）。常用命令如下：
  - `python3 main.py`：启动本地 Web（`server.py`，绑定回环地址）并打开浏览器；加 `--no-browser` 不打开浏览器，`--port` 指定端口。
  - `python3 main.py --check`：依次运行全部 38 个检查模块，取各返回码的最大值（`main.py:205`）。
  - 场景来源（三选一，互斥）：`--config configs/xxx.json`、`--load scene.json`、`--random-scene <seed>`。随机场景可配合 `--style`、`--random-params`、`--require-reachable` 使用；`--save`、`--summary`、`--preview` 用于保存和查看场景。
  - 规划：`--plan --job configs/job.default.json [--algorithm fixed-y|naive|caw|caw-fixed-order|caw-nn] [--objective time|energy] [--order-strategy] [--step-xy] [--transition-mode fixed|search] [--save-plan] [--load-plan]`。
  - 其他实验模式：`--compare`、`--multi --uavs N`、`--joint`、`--coordinate`、`--optimize-depot`、架次相关参数、`--order`、`--route3d --start --end`、`--env-demo`、`--train/--evaluate-policy`（表格 RL）、`--execute --time/--step/--samples`。
  - 批量实验：`--experiment --seeds 0-29 --methods ... [--scene-style random_obstacles_zones] [--save-results]`（3076ba2 新增 `a-b` 区间写法和 `--scene-style`），以及 `--transition-experiment`。
- **配置**：`configs/` 下有两类文件。场景配置包括 `default`、`with_objects`、`caw.{nofly,small,tiny,wall}`、`joint.{small,blocked}`、`transition.small`；作业配置包括 `job.default`、`job.caw.{crosswind,headwind,nowind,tiny}`、`job.joint.small`。`examples/` 下放了示例场景、计划和执行结果。
- README 中提到的 `验证反馈_修复记录.md` 在仓库中**不存在**。【已验证】

---

## 2. 目录与模块地图

| 模块 | 职责 | 关键对象 | 调用关系 |
|---|---|---|---|
| `scene/schema.py` | 场景格式 1.0 的默认值和 `SceneError` | `DEFAULT` | 被 `scene/*` 引用 |
| `scene/config.py` | 校验场景生成配置 | `validate_config` | `generator` |
| `scene/generator.py` | 生成规则果园：树、目标（每棵树一个冠层圆柱）、`launch-1` 位于 `[-reserve/2, h/2, ground]` | `generate` | `main`/`server`/各实验 |
| `scene/random_map.py` | 随机场景样式：`regular`/`jitter_rows`/`clusters_gaps`(`clustered`)/`size_mix`/`random_obstacles_zones` | 各 style 函数 | `random_scene.py` |
| `scene/validation.py` | 场景的几何与引用校验，起降点规则，提醒信息 | `validate_scene`(91)、`report`、`summary` | 所有规划入口和存储 |
| `scene/geometry.py`、`shapes.py`、`presets.py` | 多边形运算和点在多边形内判断；障碍预设（shed/wall/container/post） | `polygon_bounds`、`in_polygon` | 校验、规划 |
| `scene/launch.py` | 解析起降点和多机分配 | `resolve`、`resolve_all` | 规划器、`safety` |
| `scene/storage.py` | 场景读写 | | `main`/`server` |
| `random_scene.py` | 带可达性报告的随机场景；用 `derive_seed` 生成重试种子 | `generate_with_report`(49) | `main`、`experiment`、`server` |
| `planning/model.py` | 作业配置默认值与校验（要求 `height_offset > clearance`）；`V12_PLANNERS`、`LEGACY_METHODS`；指纹计算 | `configuration`、`*_fingerprint` | 全部规划 |
| `planning/planner.py` | 固定 Y 条带布局、按禁喷/禁飞切割条带、计算排除目标、生成 fixed-y 计划 | `fixed_y_lanes`(14)、`lane_parts`(75)、`_split_lane`(90)、`zone_exclusions`(179)、`generate_plan`(210) | `planner_api`、`multi`、`joint`、`sortie`、`comparison`、`experiment` |
| `planning/routing3d.py` | 分层三维净空 A*（同层 8 邻域加垂直移动，关键高度层，视线平滑，网格与路径缓存） | `route3d`(338)、`_boxes`(64) | CAW、`generate_plan` 的禁飞绕行、`joint`、`multi_caw` |
| `planning/order.py` | 条带访问顺序：fixed / nn / nn+2opt；代价矩阵（n≤20 时为 exact3d，否则为 euclidean_lb）；下界 | `solve_order` | CAW |
| `planning/wind.py`、`planning/energy.py` | 风场时间/能耗模型；相对能耗代理量 eu | | routing3d、CAW、实验 |
| `planning/zones.py`（e057a98 新增） | 禁区目标分类与指标口径：`classify`(54) 把目标分成 `no_spray`（豁免）、`no_fly`（禁飞不可达）、`no_spray_cut`（禁喷切割后不可达）；`reachable_targets`(39) 基于固定 Y 条带模型；`summary`(83) 计算 N_total、N_eligible、豁免率；`overlap_area` 用于误喷面积 | `classify`、`summary`、`zone_box`、`inside` | `planner.zone_exclusions`、`safety.check`、`evaluation` |
| `planning/footprint.py` | 喷洒足迹矩形和接触判定 | `rectangle`(6)、`overlaps_target`(15)、`boxes_touch`(24) | safety、planner、evaluation |
| `planning/safety.py` | **统一安全与结构校验**（见 §4） | `check`(35)、`intersects`(18) | 所有计划在生成、读写、执行时都会调用 |
| `planning/storage.py` | 计划读写，写入和读取时都调用 `check` | `save_plan`、`load_plan` | |
| `planner_api.py` | 统一的规划器接口 | `FixedYPlanner`、`NaivePlanner`、`CawAStarPlanner`(193)、`CawFixedOrderPlanner`、`CawNNPlanner`、`_plan_subset`(537)、`make_planner`、`normalize_name` | `server`、`main`、`experiment`、`comparison`、`multi_caw` |
| `routing.py` | 旧的二维 4 邻域网格转场搜索（固定 z） | `route`(10)、`_blocked`(5) | `generate_plan` 在 `transition_mode=search` 时使用；`joint` 的 search 模式 |
| `execution/__init__.py` | 由计划生成执行时间线，支持采样和读写（会先调用 `check`） | `build`、`state_at`、`sample` | 评价、回放、实验 |
| `evaluation/__init__.py` | 网格覆盖评价；覆盖率分母剔除 `excluded_targets`；e057a98 起额外输出 `N_total/N_eligible/exempt_no_spray/unreachable_no_fly/unreachable_no_spray/exemption_rate/target_coverage/uncovered_targets/partial_targets/misspray` | `build`(11)、`at`(60)、`_zone_metrics`(124) | 比较、实验 |
| `playback.py` | 多机和联合回放 | | `server` |
| `comparison.py`、`transition_experiment.py` | 多方法统一执行与评价对比；转场模式对比 | `run` | `main`/`server` |
| `experiment.py` | 多 seed × 多方法 × 多机数的批量实验与描述统计 | `run`(177)、`one`(115) | `main --experiment`、`/api/experiment` |
| `multi.py` | 多机连续分块基线：把 fixed-y 的喷洒段切块，并以 allow_partial 模式校验 | `run`(24) | |
| `multi_caw.py` | 多机 CAW（按子集调用 `_plan_subset`/`plan_sequence`） | | |
| `coordination.py`、`coordination_plan.py` | 用解析 CPA 检测多机冲突；用地面等待延迟消解冲突 | | |
| `depot.py`、`sortie.py` | 起降点优化；按载药量分批的架次规划 | `plan_sorties`(89)、`_sortie_plan`(24) | |
| `joint.py` | 小规模联合顺序与转场的精确枚举基准 | `optimize`(338)、`_spray_lanes`(54) | |
| `env.py`、`rl.py`、`surrogate.py` | 多机环境接口、表格 RL 基线、代理模型接口 | | |
| `server.py` + `web/` | 回环 HTTP 服务。接口有 `/api/{default,initial,random,validate,plan,plan-check,generate,load,save,execution,compare,order,route3d,multi,experiment,route,coordinate,multi-playback,joint-playback,joint,depot,sorties,evaluation,state}`；前端包括 `app.js`（作业与算法面板，默认算法为 fixed-y）、`editor.js`（场景编辑器）、`execution.js`、`playback.js` | | |
| `*_checks.py`、`checks.py` | 回归检查脚本（见 §6） | | `main --check` |

---

## 3. 核心数据流

```mermaid
flowchart LR
  A[configs/*.json 或 random_scene.generate_with_report] --> B[scene.generator / random_map]
  B --> C[scene.validation.validate_scene]
  C --> D{规划器}
  D -->|fixed-y| P1[planning.planner.generate_plan<br/>fixed_y_lanes → lane_parts/_split_lane<br/>→ 禁飞断口 route3d 绕行 → zone_exclusions]
  D -->|naive| P2[planner_api.NaivePlanner]
  D -->|caw-a*| P3[planner_api.CawAStarPlanner<br/>fixed_y_lanes → order.solve_order<br/>→ routing3d.route3d 转场]
  D -->|multi / multi_caw / sortie / joint / depot| P4[分块、多机、架次、联合]
  P1 -->|transition_mode=search| R2[routing.route 二维重建转场]
  P1 --> S[planning.safety.check]
  R2 --> S
  P2 --> S
  P3 --> S
  P4 --> S
  S -->|失败: status=failed, segments=[], stage/reason| F[失败结果]
  S -->|通过| E[execution.build 时间线]
  E --> V[evaluation.build 网格覆盖]
  E --> PB[playback / web 回放]
  V --> X[comparison / experiment / transition_experiment]
  X --> O[JSON 输出: plan / timeline / results/*.json]
```

各阶段说明：

1. **场景**：树（树干和树冠圆柱）、目标（树冠圆柱）、障碍（轴对齐盒）、`no_fly_zones` 和 `no_spray_zones`（`kind:"polygon_prism"`，多边形足迹加 `z_min/z_max`）、起降点（role 为 both/start/return）以及 `launch_assignments`。
2. **条带布局**：`fixed_y_lanes` 按喷幅沿 X 方向排列条带，每条沿 Y 方向飞；作业高度 = 最大树冠 `z_max` + `height_offset`（默认场景为 6.2 m）。所有条带式规划器共用这一布局。【已验证】
3. **规划**：输出计划版本 1.1/1.2，内容包括 `segments`（每段含 start/end/type/spray/speed/target_ids）、`scene_hash`、`config_hash` 和 `planner_options_hash`。
4. **安全校验**：每个规划器在返回前都会调用 `check`。校验失败时，计划的 `status` 为 `failed`，`segments` 清空，`stage` 取 plan/search/safety 之一，并写明 `reason`。
5. **执行与评价**：`execution.build` 和 `evaluation.build` 都会先校验指纹，确认与计划一致后才计算。
6. **实验**：`experiment.run` 和 `comparison.run` 汇总覆盖率、时长、能耗、成功率等指标。

---

## 4. 安全与约束校验

### 4.1 `planning/safety.py: check(scene, plan)` 的检查清单【已验证，读码】

| 行 | 检查 | 报错 |
|---|---|---|
| 37–40 | 运行 `validate_scene`，并检查计划版本和 `scene_hash` | 计划版本或场景指纹不匹配 |
| 42 | 计划状态必须为 success | 计划不是成功状态 |
| 45 | 1.1/1.2 版本要求 `config_hash` 一致 | 配置指纹不匹配 |
| 48–59 | 1.2 版本：`planner ∈ V12_PLANNERS`，`method==planner`，`objective ∈ {time, energy}`，`planner_options` 的指纹一致 | 未知规划器 / 不一致 / 指纹 |
| 62–69 | 旧版 method 与转场模式的对应关系 | 未知计划方法 / 与转场模式不一致 |
| 79–97 | `uav` 必须为正整数，起降点元数据要与 `launch.resolve` 一致，且必须有起降航段 | |
| 121 | 作业高度与配置一致 | |
| 132–157 | 坐标为有限值；航段首尾相接（容差 1e-8）且长度非零；type/spray 组合合法；速度大于 0；`target_ids` 为字符串列表、无重复、只出现在喷洒段且引用有效 | |
| 160–169 | 起飞在起点处垂直、降落在终点处垂直；1.2 版本的转场高度须在 `[extent.z_min+clearance, extent.z_max−clearance]` 内，其余航段必须在作业高度 | |
| 175 | 航段位于场景范围内 | 航段超出场景范围 |
| 100–115, 177–180 | 把树干、树冠、障碍和**禁飞区**都转成三维 AABB 并按 `clearance` 外扩，用 slab 法检测**整条航段**是否相交（**接触也算冲突**） | **航段 i 与实体净空或禁飞包围盒冲突** |
| 183–190 | 喷洒段必须沿 Y 方向且关联目标，`rectangle(seg, swath)` 足迹必须与每个关联目标有正面积重叠 | |
| 193–196 | 喷洒足迹（XY 矩形）与任一**禁喷区 XY AABB** 闭集接触（忽略 z） | **喷洒足迹触及禁喷区；不支持禁喷切割**（e057a98 起改为“误喷：航段 i 喷洒足迹触及禁喷区 <id>”） |
| 199–201 | 最后回到终点；至少有一段喷洒 | 未返回终点 / 没有喷洒航段 |
| 203–221 | （5c86bd2 新增，e057a98 改写）`excluded_targets` 的结构合法、不能与已关联的目标重叠、引用必须存在；e057a98 起每条排除都必须与 `zones.classify` 的结果完全一致（id 和理由都要对上，`safety.py:214–221`） | excluded_targets 结构非法 / 排除理由与区域几何不符 |
| 225–227 | 除排除目标外，所有目标都要有喷洒关联（`allow_partial` 时跳过） | **任务结构不完整：目标缺少有效喷洒关联** |

其他校验点：
- `scene/validation.py` 的 `validate_scene`：禁飞/禁喷区必须是 polygon_prism，多边形合法，`z_min<z_max`，且位于场景范围内（271 起）。起降点必须在地块外，且不能落入障碍或禁飞体积（299–305，只判断点是否在体内，**不考虑 clearance 外扩**）。严格模式下起降点还不能落在禁喷或禁飞区的 XY 足迹内（336–357）。若区域与目标重叠，只给提醒“禁喷会拒绝该处喷洒，禁飞可能阻断航段（仅提醒）”（405–421）。
- `planning/model.py`：校验作业配置，包括 `height_offset > clearance`、风速不小于 0 等。
- `execution.build`、`evaluation.build`、`planning/storage` 都会再次调用 `check` 或比对指纹。

### 4.2 禁飞与禁喷的表示和执行

| | 表示 | 规划侧处理（3076ba2） | 校验侧处理 |
|---|---|---|---|
| 禁飞 | 多边形棱柱，按**AABB**（而非真实多边形）加 clearance 外扩成三维盒 | `_split_lane` 在条带与禁飞区 XY 相交处断开，断口为 `[zy_lo − clearance − 1e-6, zy_hi + clearance + 1e-6]`。断口以及“上条带、换条带、回家”这些转场都交给 `route3d` 绕行（`planner.py:261–294`）；`route3d._boxes` 把禁飞区加 clearance 后当作障碍 | `safety:177`：三维盒相交检测 |
| 禁喷 | 多边形棱柱，**只用 XY AABB，忽略 z** | `_split_lane` 在禁喷区处把条带切开，区内这段改为关闭喷头的 transit 并照常飞越（禁喷≠禁飞） | `safety:193`：喷洒足迹与禁喷 AABB 闭集接触即拒绝 |
| 区内目标 | — | e057a98：`zone_exclusions`（`planner.py:182`）改为调用 `zones.classify`。分类规则：树冠外接框**整个**落在某个禁喷 AABB 内，记为 `no_spray`；不在固定 Y 条带切割后的可达集合中、且接近禁飞区（外扩 clearance + swath/2），记为 `no_fly`；其余不可达且接触禁喷区的，记为 `no_spray_cut` | `safety:214–221` 逐条比对 classify；`evaluation` 剔除分母并输出口径指标 |

### 4.3 “加了禁飞、禁喷后生成不了航线”的根因

我在默认场景（4×6 棵树，作业高度 6.2 m，起降点 `[-3,12.5,0]`）上构造了 8 组禁飞/禁喷用例，并在三个版本上分别运行。【已验证】脚本和输出见 `/tmp/cwa-probe/probe.py` 和 `probe_*.txt`。

| 用例 | f798f2c（= `/workspace/cwa`，阶段22） | 55beaf2（Mac 上的 WIP，只切禁喷） | **3076ba2（当前 HEAD）** |
|---|---|---|---|
| C 禁喷位于航带中段 | 全部失败：`喷洒足迹触及禁喷区；不支持禁喷切割` | fixed-y 成功；CAW 和 naive 仍失败（报错同左） | fixed-y、CAW、search 成功；**naive 失败** |
| D 禁喷罩住整棵树 | 失败（同上） | fixed-y 失败：`任务结构不完整：目标缺少有效喷洒关联 [target-tree-01-01]` | fixed-y、CAW 成功，`excluded=[target-tree-01-01]`；naive 失败 |
| A 禁飞在地块内，z 0–10 | fixed-y、naive、search 失败：`航段 N 与实体净空或禁飞包围盒冲突`；CAW 失败：`搜索失败：起点/终点位于实体净空或禁飞包围盒内` | 同左 | fixed-y、CAW 成功；**naive、fixed+search 失败**（航段冲突） |
| A2 禁飞在两行之间的空隙（x 4.5–5.5） | fixed-y、CAW 失败（外扩 0.5 后恰好接触 x=4 的条带线，接触即冲突）；naive 成功 | 同左 | fixed-y、CAW、naive 成功；**search 失败** |
| A3 禁飞低于作业面（z 0–3） | 全部成功 | 全部成功 | 全部成功 |
| B 禁飞在起降点与航带之间的外圈 | fixed-y、naive、search 失败；CAW 成功 | 同左 | fixed-y、CAW、search 成功；**naive 失败** |
| E/F/G/H 禁飞与禁喷组合 | 全部失败 | 全部失败（G：切割后的 transit 穿过同位置的禁飞盒） | fixed-y、CAW 全部成功；naive 全部失败；search 在禁飞位于地块内时失败 |

**根因（按代码位置）：**

1. **禁喷**：在 f798f2c 中，没有任何规划器会切割条带。只要喷洒足迹接触禁喷 AABB，`safety.py:193–196` 就会直接拒绝。这条报错文案本身就写着“不支持禁喷切割”。【已验证】55beaf2 只给 fixed-y 加了 `_split_lane`；5c86bd2 把切割补到了 CAW（`planner_api.py` 中的 `lane_parts`/`zone_exclusions`），并引入了 `excluded_targets`，用来处理被禁喷区完全罩住、无法喷洒的目标。【已验证】
2. **禁飞**：在 f798f2c 中，fixed-y 和 naive 的转场都是直线，作业段也直接穿越禁飞区，因此会被 `safety.py:177–180` 拒绝。CAW 虽然用 `route3d` 绕行，但条带端点本身就落在外扩后的禁飞盒内，于是 `routing3d.py:439/441` 报“起点/终点位于…内”。另外，接触即冲突的规则让紧贴条带的禁飞区也会失败。【已验证】5c86bd2 在禁飞区处断开条带，并用 `route3d` 绕行，这个问题在 fixed-y 和 CAW 上已修复。【已验证】
3. **3076ba2 仍未覆盖的路径**【已验证】：
   - `NaivePlanner`（`planner_api.py:96`）既不切割条带也不绕行，任何接触航线的禁飞/禁喷区都会导致失败。
   - `transition_mode=search`：`generate_plan` 会用 `routing.route` 重建全部 transit（`planner.py:312–323`），而 `routing._blocked`（`routing.py:5–9`）**只检查 `obstacles`，不检查树和禁飞区**。重建后的二维路径会把原本的 route3d 绕行路径替换成穿越禁飞区的路径，于是被 `safety:177` 拒绝。
   - `sortie.py:_sortie_plan`（第 70–72 行）仍然是 `add(lane["end"], "spray", ...)`，整条条带一段喷完，既不切割也不绕行。实测结果：禁喷时报“第 1 批失败：喷洒足迹触及禁喷区；不支持禁喷切割”，地块内有禁飞时报“第 1 批失败：航段 30 与实体净空或禁飞包围盒冲突”。【已验证，`/tmp/cwa-probe/aux_head2.txt`】
   - `joint._spray_lanes` 和 `multi.run` 直接复用基线计划的喷洒段，但**没有**把 `excluded_targets` 传给子计划。`multi` 用 allow_partial 校验，所以能通过；`joint` 是否会因此误报“缺少喷洒关联”目前未验证。【推断】
4. **随机场景的批量结果**：样式 `random_obstacles_zones`，seed 0–19，比较 fixed-y 与 caw-a*-fixed-order。【已验证】说明：3076ba2 把这个样式的 `base_style` 从 `regular` 改成了 `jitter_rows`，所以前后两个版本生成的场景**并不相同**，下表只能说明趋势，不是严格的配对比较。

   | 版本 | `allow_inside_plot` | fixed-y 失败 | CAW 失败 | 原因 |
   |---|---|---|---|---|
   | 55beaf2 | True | 11/20 | 9/20 | 9 次净空/禁飞冲突、2 次禁喷；CAW 有 6 次搜索起终点落在禁飞盒内 |
   | 55beaf2 | False（默认） | 3/20 | 2/20 | 净空/禁飞冲突 |
   | 55beaf2 仅禁飞（无障碍、无禁喷） | True / False | 5 / 4 | 3 / 0 | 禁飞 |
   | 3076ba2 | True / False | 1 / 1 | 1 / 1 | seed 1：**航段 0（起飞）**冲突 |
   | 3076ba2 仅禁飞 | True / False | 0 / 0 | 0 / 0 | — |

   3076ba2 下剩下的 seed 1 失败与禁飞/禁喷无关：`obstacle-03` 的范围是 `[-3.057,12.803]–[-0.18,15.68]`，起降点 `[-3,12.5,0]` 离它只有 0.303 m，小于 clearance 0.5。`validate_scene` 只判断起降点是否在障碍体内，因此认为场景合法；但 `safety` 判定垂直起飞段与外扩后的障碍盒冲突。随机场景生成器没有让障碍避开起降点的净空范围。【已验证】

**结论**：用户反馈的“加了禁飞、禁喷后生成不了航线”，在 `/workspace/cwa`（f798f2c）上可以 100% 复现，根源是“禁喷不切割 + 禁飞不断带/直线转场 + 接触即冲突”。在 3076ba2 上，fixed-y 和 CAW 主链已经修复；naive、`transition_mode=search` 和 sortie 架次三条路径仍会失败。【已验证】

### 4.4 e057a98 的禁区口径验收（2026-11-04 02:40–02:50 PST）【已验证，脚本见 `/tmp/cwa-accept/`】

- **截图场景**：禁喷区 `[0.5,10.5]×[16.5,24.5]` 罩住 01-05、01-06、02-05、02-06。fixed-y、`caw-a*-3d-wind`、`caw-a*-nn` 的结果均为 N=20/24、豁免 4、豁免率 0.167、目标覆盖率 1.000、单元覆盖率 1.000、误喷 0/0 段，用时依次为 127.4 s、126.2 s、126.2 s，与 Codex 的报告一致。naive 在该场景下失败，报“误喷：航段 10 …”。
- **反向条带修复**：禁喷区 `y 17.6–19.4` 落在反向条带（x=4）中段时，3076ba2 上 fixed-y、CAW 全部失败，e057a98 上全部成功。在无禁区的 51 个场景 × 5 种规划器上，两个版本的航段 sha256 完全相同，时长和覆盖率也一致（详见 §6）。
- **与口径不符的地方**：
  - `zones.inside` 用的是禁区**AABB** 而不是真实多边形。三角形或 L 形禁喷区只要外接框罩住树，就会把这棵树判为整株豁免（`zones.py:29,60`）。
  - `unreachable_no_fly` 的判定只基于固定 Y 条带（`zones.py:39–51`），并且 `_split_lane` 切禁飞时忽略 z。结果是：低于作业面的禁飞区（z 0–3），以及细长禁飞区（x 2.9–3.1），都会把在几何上可以喷到的树判为不可达。在低空禁飞用例中，naive 实际喷到了这棵树，于是 naive 的 N=24，而 fixed-y 和 CAW 的 N=23。
  - 由于 N 取自计划自带的 `excluded_targets`（`evaluation/__init__.py:52`），不同规划器之间 N 可能不一致。
  - 闭集接触规则下，禁喷区边界与条带足迹相切（x=3.0）时，01-05 被判为 `no_spray_cut`；实际上树冠 x∈[3,4] 这一段在禁喷区外，仍然可以喷。
  - `drift_buffer` 没有接入，`buffer` 恒为 0。
  - 误喷面积按 AABB 计算，且 safety 已经拒绝所有接触，因此对成功的计划来说，误喷恒为 0，这个指标本身不提供额外信息。

---

## 5. 实验与可复现性

- **种子**：确定性规划器（fixed-y/naive/CAW）不使用 seed。在固定场景模式下，不同 seed 的结果完全相同，因此 `runs=1, std=None`（`experiment.py` 的 seed_note）。3076ba2 新增了 `scene_style` 模式：每个 seed 生成一个独立的随机场景，seed 只决定场景几何。随机场景按 `(style, seed, params)` 确定生成；`require_reachable` 模式下的重试种子用 `derive_seed` 由 sha256 推导，落在 `[2^31, 2^32)` 区间，并记录为 `seed_used`。【已验证，读码】
- **指纹**：场景、配置和规划参数分别有 `scene_hash`、`config_hash`、`planner_options_hash`，都是规范化 JSON 的 sha256。执行和评价阶段会拒绝被篡改的计划（有专门的 check 覆盖）。【已验证】
- **消融机制**：CAW 的消融变体有 `caw-a*-fixed-order`、`caw-a*-nn` 和默认的 `nn+2opt`；目标口径可选 `--objective time|energy`；风场配置有 `job.caw.{nowind,crosswind,headwind}`；`--transition-experiment` 比较 fixed 与 search 两种转场；还有 `--step-xy`、`matrix_mode` 等参数。【已验证，读码】
- **指标**：覆盖率（网格近似，3076ba2 起剔除排除目标）、漏喷单元、时长、相对能耗 eu（代理量，不是实测 Wh）、成功率和失败原因。多机覆盖率口径是 `per_uav_mean_not_union`（各机平均，而不是并集）。【已验证，读码】
- **统计检验**：只有描述统计（`statistics.mean`/`pstdev`，`experiment.py:232–238`），失败样本计入分母。**没有**显著性检验（例如配对 Wilcoxon 或 t 检验）、置信区间或效应量，也没有对多方法比较做校正。【已验证，读码】论文如果要声称“显著优于”，需要另外补充。
- `results/`（未跟踪，属于其他代理）：`bench_{clusters_gaps,jitter_rows,random_obstacles_zones,size_mix}_30.json`，每个文件 30 个 seed × 4 种方法，全部成功。文件生成于 02:19–02:20 PST，早于 5c86bd2 提交（02:26），具体用的是哪个工作区版本、哪些参数，我无法确认。【推断】这些结果与我在 55beaf2 上测到的 random_obstacles_zones 失败率（3/20）不一致，可能用了 `--require-reachable`（会把失败场景重试替换掉），也可能用了不同的参数。【推断】

---

## 6. 测试与检查脚本

共 38 个模块：`checks.py` 和 37 个 `*_checks.py`。它们都是断言式的冒烟或回归检查，没有使用 pytest 框架，每个模块打印“通过 · …”并返回 0。

| 脚本 | 覆盖内容（取自各脚本的“通过”行） |
|---|---|
| `checks.py` | 场景生成与校验、起降点、编辑器约束等（共 8 项） |
| `planning_checks.py` | 第二阶段：往返、喷幅、高度、重排、阻挡、禁喷、文件匹配与篡改；任务结构回归 |
| `no_spray_cut_checks.py` | 禁喷切割：无区回归、中段切割、多区合并、罩住目标时排除、禁飞绕行、伪造排除被拒、search 模式、反向连续 |
| `planner_checks.py`、`caw_checks.py`、`order_checks.py`、`routing3d_checks.py`、`wind_checks.py`、`wind_planning_checks.py`、`routing_checks.py` | 规划器接口、CAW 主链、顺序优化、三维 A*、风场 |
| `execution_checks.py`、`evaluation_checks.py`、`evaluation_swath_checks.py`、`plant_evaluation_checks.py`、`playback_checks.py` | 执行时间线、覆盖评价、喷幅、目标级统计、回放 |
| `comparison_checks.py`、`comparison_real_checks.py`、`experiment_checks.py`、`experiment_semantics_checks.py`、`transition_checks.py`、`transition_experiment_checks.py` | 对比与实验语义 |
| `multi_checks.py`、`multi_caw_checks.py`、`coordination_checks.py`、`coordination_plan_checks.py`、`joint_checks.py`、`joint_transit_checks.py`、`depot_checks.py`、`sortie_checks.py`、`launch_checks.py` | 多机、协同、联合、起降点、架次 |
| `env_checks.py`、`rl_checks.py`、`surrogate_checks.py` | 环境、RL、代理模型 |
| `random_map_checks.py`、`scene_editor_checks.py`、`web_checks.py`、`regression_cli_checks.py` | 随机地图、编辑器、前端静态检查、CLI 回归 |

**运行结果**【已验证】：逐个模块执行 `python3 -c "import m; m.run()"`，设置 `PYTHONDONTWRITEBYTECODE=1`，`TMPDIR` 指向 `/tmp`。日志见 `/tmp/cwa-run*/logs/`。

| 脚本 | 55beaf2 | 5c86bd2 前的工作区快照（02:24 PST） | **3076ba2（HEAD）** |
|---|---|---|---|
| `regression_cli_checks.py` | **FAIL**：`FileNotFoundError: '.venv/bin/python'`（硬编码的 Mac 虚拟环境路径） | PASS | PASS（改为 `sys.executable`） |
| `no_spray_cut_checks.py` | PASS | **FAIL**：第 101 行 `AssertionError: 罩住目标不应成功`（代码已改成排除语义，检查还没同步） | PASS |
| `planning_checks.py` | PASS | **FAIL**：第 78 行断言“缺少有效喷洒关联”（原因同上） | PASS（3076ba2 正是修这一处） |
| 其余 35 个 | 全部 PASS | 全部 PASS | 全部 PASS |
| “通过”行合计 | 144（与 README 的 144 一致） | 142 | **145** |
| `python3 main.py --check` | — | — | **退出码 0**，145 行“通过”，耗时约 11 s |

**e057a98**：新增 `zone_metric_checks.py`，共 39 个检查模块全部 PASS。“通过”行合计 146（145+1），除新增脚本外，每个脚本的“通过”行数与 3076ba2 完全相同；`main.py --check` 退出码 0。【已验证，`/tmp/cwa-run-e057/`】

**检查强度问题**【已验证，读码】：部分检查的断言本身恒为真，起不到验证作用：
- `routing_checks.py` 的 `assert b['status'] in ('success','failed')`；
- `joint_checks.py` 的 `status in ('success','unsupported')`；
- `comparison_checks.py` 的 `assert ... if False else True`。

另外，`no_spray_cut_checks.run` 在失败时直接抛出 AssertionError，而不是返回非 0。`main --check` 用 `max(...)` 汇总结果，一旦某项失败，整个命令以 traceback 结束，后面的检查都不会再运行。【推断】

---

## 7. 版本差异与未提交改动

### 7.1 提交历史【已验证】

| 提交 | 时间（PST） | 内容 |
|---|---|---|
| `7edf8a2` | 11-02 07:39 | Initial commit |
| `f798f2c` | 11-02 22:26 | 阶段22：CAW-A* 主链、场景编辑器、多机协同与起降点优化。**与 `/workspace/cwa` 完全一致**（`git archive` 后逐文件比对确认） |
| `55beaf2` | 11-04 02:22 | “WIP: 用户本机未提交的禁喷切割改动（来自 Mac）”（作者为 `x`）。改动：README、`main.py`（把 `no_spray_cut_checks` 加入 `--check`）、新增 `no_spray_cut_checks.py`、`planning/planner.py` 新增 `_split_lane`、`planning_checks.py`、`random_map_checks.py` |
| `5c86bd2` | 11-04 02:26 | （Codex Runner，作者 ZZX318）禁飞/禁喷：区内目标标记为排除并经几何复核；禁喷切割后关喷头飞越；禁飞处断开条带并用 A* 绕行；覆盖率分母剔除排除目标。11 个文件，+249/−43 |
| `3076ba2` | 11-04 02:26 | `planning_checks`：罩住目标的用例改为排除语义（1 行） |
| `e057a98` | 11-04 02:39 | 禁区口径：整株才豁免、禁飞不可达几何复核、N_eligible、豁免率、误喷、partial_targets 指标，修复反向条带切割顺序。8 个文件，+273/−45：新增 `planning/zones.py` 和 `zone_metric_checks.py`；修改 `evaluation`、`safety`、`planner`、`planner_api`、`experiment`、`main` |

### 7.2 `/workspace/cwa`（f798f2c）与 3076ba2 的差异

`git diff --stat f798f2c 3076ba2`：13 个文件，+487/−26。【已验证】

- `planning/planner.py` (+192)：新增 `_split_lane`、`lane_parts`、`zone_exclusions`；`generate_plan` 增加禁飞绕行（输出 `no_fly_detours`）、排除目标，以及出现绕行时升级到 1.2 版本。
- `planner_api.py` (+36)：CAW 和 `_plan_subset` 改用 `lane_parts` 并输出 `excluded_targets`。
- `planning/safety.py` (+23)：新增 `excluded_targets` 的校验与几何复核。
- `evaluation/__init__.py` (+7)：覆盖率分母剔除排除目标。
- `experiment.py` (+15)：新增 `scene_style`、`scene_params`、`require_reachable`，每个 seed 生成独立随机场景。
- `main.py` (+8)：新增 `--scene-style`，`--seeds` 支持 `a-b` 写法，`--check` 纳入 `no_spray_cut_checks`。
- `random_scene.py` (+13)：新增 `derive_seed`，报告中记录 `seed_used`。
- `scene/random_map.py`：`random_obstacles_zones` 的 `base_style` 从 `regular` 改为 `jitter_rows`。**这会改变同一 seed 生成的场景，破坏与旧结果的可比性。**
- `regression_cli_checks.py`：`.venv/bin/python` 改为 `sys.executable`。
- `no_spray_cut_checks.py`：新增（174 行）。`planning_checks.py`、`random_map_checks.py`、`README.md`：同步修改。

### 7.3 历史快照：02:32:55 PST 时的未提交改动（之后已作为 e057a98 提交；e057a98 提交后工作区只剩未跟踪的 `results/` 和本文件）

```
 evaluation/__init__.py | 36 +++++
 experiment.py          |  4 +
 main.py                |  3 +-
 planner_api.py         |  4 +-
 planning/planner.py    | 37 ++----
 planning/safety.py     | 25 ++---
 6 files changed, 64 insertions(+), 45 deletions(-)
?? planning/zones.py         （新增：禁喷/禁飞目标分类与误喷度量口径，exempt_no_spray / unreachable_no_fly 等）
?? zone_metric_checks.py     （新增）
?? results/                  （其他代理的基准结果与补丁，未跟踪）
```

这些属于 Codex Runner 正在进行的工作，我没有改动、提交或回滚。`planning/zones.py` 的文件头写着“口径（技术负责人 2026-11-04…）”，这个口径需要由人确认后再写入论文。【已验证存在，内容未评审】

---

## 8. 已知问题、技术债与风险

| # | 问题 | 状态 |
|---|---|---|
| 1 | `NaivePlanner` 既不切割禁喷，也不绕行禁飞；只要区域接触航线就失败，基线对比会因此偏向 CAW | **a444a93 起**：用 `_spray_candidates`（与 classify 同口径）选喷带；A1 部分重叠不再结构失败。仍只飞单段候选，覆盖常低于 fixed-y |
| 2 | `routing.py:_blocked` 只检查 `obstacles`，忽略树和禁飞区。`transition_mode=search` 会把 route3d 的绕行路径替换成穿越禁飞区的二维路径，最后被 safety 拒绝 | **799da32 起已修**：`_blocked` 含树/禁飞；有禁飞时 search 改走 `route3d` |
| 3 | `sortie.py:_sortie_plan` 不切割、不绕行，禁喷或地块内禁飞都会让架次规划失败 | **799da32 起已修**：复用 `lane_parts` + `zone_exclusions` + 禁飞 `route3d` |
| 4 | `joint`、`multi` 复用基线喷洒段，但不传递 `excluded_targets`；`joint` 可能误报“缺少喷洒关联”，多机覆盖率分母口径也可能不一致 | 推断 |
| 5 | 禁飞/禁喷都按**多边形 AABB** 处理，非矩形或斜向多边形会被过度保守地放大；禁喷完全忽略 z | 已验证（读码） |
| 6 | 安全校验采用“接触即冲突”的闭集规则，紧贴条带的禁飞区或障碍也会被拒；切割依靠 `_ZONE_GAP=1e-6` 留出间隙，数值上比较脆弱 | 已验证（f798f2c 的 A2 用例）/ 推断（数值） |
| 7 | `_split_lane` 判断禁飞区是否影响条带时，X 方向用的是 `swath/2`，而 safety 用的是 `clearance` 外扩。当 `swath/2 < clearance` 时，横向贴近的禁飞区不会被切割，但会被 safety 拒绝 | 推断 |
| 8 | `validate_scene` 只检查起降点是否在障碍体内，不检查 clearance，随机场景可能生成合法但无法起飞的场景（random_obstacles_zones 的 seed 1） | **799da32 起已修**：障碍水平净空 0.5 m；随机放置膨胀避让；失败换派生种子。禁飞仍只禁止落入体积 |
| 9 | `base_style` 从 regular 改为 jitter_rows，同一 seed 生成的场景前后不同；`results/` 中旧结果的版本和参数来源不明 | 已验证（改动）/ 推断（影响） |
| 10 | 只有描述统计，没有显著性检验或置信区间；确定性规划器的 std=None | 已验证 |
| 11 | 能耗 eu 是相对代理量，不是实测功耗；多机覆盖率是各机平均而非并集 | 已验证（读码） |
| 12 | 若干检查的断言恒为真（routing、joint、comparison）；`main --check` 遇到断言异常会以 traceback 结束，后续检查不再运行 | 已验证（读码）/ 推断 |
| 13 | README 引用的 `验证反馈_修复记录.md` 不存在；README 默认使用 `.venv/bin/python` | 已验证 |
| 14 | `route3d` 使用模块级缓存（`_GRID_CACHE` 8 项、`_ROUTE_CACHE`），长时间运行的 server 可能共用缓存状态 | 推断 |
| 16 | `zones.inside`/`classify` 用禁区 AABB 判断“整株落在区内”，非矩形禁区会把只被部分覆盖的树误判为豁免 | **a444a93 起豁免侧已修**：`disk_in_polygon(冠层圆+drift_buffer)`。**切割侧未修**：`_split_lane` 禁喷仍按多边形 AABB 切带 → 三角/L 易误标 `no_spray_cut` |
| 17 | `unreachable_no_fly` 只针对固定 Y 条带，且禁飞切割忽略 z，不构成真正的几何证明；低空或细长禁飞区会把可达的树判为不可达 | **a444a93 起高度侧已修**：`active_no_fly` 要求 z 挡住作业高；候选=树心短带∪fixed-y 切割喷段+中心线净空。**仍偏保守**：禁飞切断仍按喷幅 AABB，adv A8 式贴边细禁飞可误标 `no_fly` |
| 18 | N_eligible 取自各计划自带的 `excluded_targets`，naive、multi、joint 等方法的 N 可能与 fixed-y、CAW 不同 | **a444a93 起**：评价分母/`summary` 只跟 `classify(scene,c)`；截图/三角/L/低空等用例三规划器 N 一致。joint/multi 分母是否完全对齐未专项测 |
| 19 | `multi.run` 在场景有禁飞区时，两架机的子计划都失败（报“规划器与方法不一致”，起因是 1.2 版本升级），但总体 `status` 仍为 success。3076ba2 上已存在 | **a444a93 起顶层会 `failed`**（任一子机失败）。子机仍常报「规划器与方法不一致」（1.2 升级副作用），根因未清 |
| 20 | 误喷指标在成功计划上恒为 0（safety 已拒绝所有接触），`partial_targets` 靠 ±1 m 启发式筛选，会把 naive 本身就有的部分覆盖也算进去 | **a444a93 起**：safety/指标改正面积相交（相切面积 0 不拒）；`partial_targets` 要求与禁喷正面积相交（或 classify 的 no_fly/no_spray_cut）。无区 naive 不再进 partial |
| 15 | 工作区由多个代理并发修改，存在审计和复现风险。论文中的实验应固定提交哈希，并在结果 JSON 中记录 `git rev` | 已验证（现象） |

---

## 9. 验收笔记：`799da32`（2026-11-04 ~02:55 PST，技术负责人 /tmp 复核）

> 工作副本：`/tmp/cwa-799`（`git archive 799da32`）、对照 `/tmp/cwa-e057-cmp`；**未改**任何已跟踪源码；本文件仍为未跟踪。

### 9.1 裁决：**有条件通过**

四项声明中 2/3/4 已用复现证据核实；1（Naive）主体修好但 **A1 部分重叠禁喷** 仍会因短 Y 中心线被切成纯 transit、树又未进 `classify` 排除而报「缺少有效喷洒关联」。`e057a98` 遗留的 **AABB 整株豁免** 与 **unreachable_no_fly 无视 z / 只看 fixed-Y** 仍在（`planning/zones.py` 与 e057 字节级相同）。`multi.run` 禁飞场景仍 `status=success` 而两机 `failed`（未宣称修复）。`--check` 全绿；无区航段相对 e057 抽样 22/22 一致。

### 9.2 相对 e057a98 的 diff 面

11 files, +322/−54：`planner_api.py`、`planning/planner.py`、`routing.py`、`sortie.py`、`scene/validation.py`、`scene/random_map.py`、`random_scene.py`、`comparison_checks.py`、`joint_checks.py`、`routing_checks.py`、`zone_metric_checks.py`。**未改** `zones.py`。

### 9.3 四项声明核对

| # | 声明 | 结论 | 证据 |
|---|---|---|---|
| 1 | Naive：跳过 classify 豁免/不可达；短 Y + `lane_parts`；有禁飞用 `route3d`；写 `excluded_targets` | **部分** | 截图场景 S：naive N=20/24 mis=0 exempt 对齐；A6/A9/A10 成功。**A1**（禁喷 x0.5–2.9）：`lane_parts` 在 x=2.5 短 Y 全变 transit，classify 不含该树 → `FAILED 缺少有效喷洒关联` |
| 2 | `routing._blocked` 含树/禁飞盒；search+禁飞改 `route3d` | **已核实** | A6/A8/A9/A10 的 `fixed-y+search` 由 e057 的「航段…冲突」改为 success；`routing_checks` 墙+禁飞断言非恒真 |
| 3 | sortie 复用 `lane_parts`+`zone_exclusions`+禁飞 `route3d` | **已核实** | `plan_sorties` 禁喷截图区与 A9 禁飞均 `status=success`；`zone_metric_checks` 覆盖 |
| 4 | 起降净空 0.5 m；随机图膨胀避让；`random_obstacles_zones` 失败换派生种子 | **已核实** | `validate_scene` 拒 0.2/0.4 m、过 0.5 m；邻接禁飞仍过。seed1：e057 min_obs_dist=0.303 且 plan fail；799 同 seed 放置后 min=7.751、fy/nn success。seed 0–19 fy+nn **0 失败** |

### 9.4 几何口径（e057 遗留，799 未动）

- **A3 三角禁喷**：crown AABB `([1,17],[4,20])` ⊂ zone AABB，`inside`→豁免；冠层圆采样仅 4/8 在三角形内 → 仍误豁免。【已验证】
- **A7 低空禁飞 z0–3**：作业高 6.2 > z_max+clearance，仍 `unreachable_no_fly`；`reachable_targets` 只用 `fixed_y_lanes`。【已验证】

### 9.5 检查与回归

- `python3 main.py --check` @799：exit 0；约 146 条「通过」；含扩写后的 `zone_metric_checks`（naive/search/sortie/seed0–19）。
- 恒真断言收紧：`comparison_checks` 要求两方法 success+满覆盖一方；`joint_checks` 小场景要求 success；`routing_checks` 要求挡墙/禁飞后失败或更长。
- 无区抽样（default + regular/clusters/jitter/size_mix seed0 + size_mix 1–2 × fy/naive/nn/wind）：相对 e057 **22/22 航段签名相同**。

### 9.6 仍建议 Codex Runner 下一轮

1. `zones.classify`：整株豁免改**真实多边形**（+可选冠层圆盘 ⊆ 多边形），禁止只用 AABB。
2. `unreachable_no_fly`：纳入高度（可飞越的低禁飞不算不可达）；勿把「仅 fixed-Y 不可达」写成与规划器无关的几何真理，或显式标注为 fixed-Y 作业带口径并让 naive 的 N 分母与之脱钩说明。
3. Naive A1：短 Y 被切光但树仍 eligible 时，应并入 `excluded_targets`（`no_spray_cut`）或改用能碰到冠层的残余足迹，避免结构校验失败。
4. `multi.run`：任一子机失败时顶层不得 `success`（禁飞回归仍复现）。
5. 通过后再谈 GitHub push；`ARCHITECTURE.md` §8 表项 1–3、8、12 状态需随下轮改码更新。

---

## 10. 验收笔记：`a444a93`（2026-11-04 ~03:00 PST，技术负责人 /tmp 复核）

> 工作副本：`/tmp/cwa-a444`（`git archive a444a93`）；对照 `/tmp/cwa-799`；对抗脚本 `/tmp/cwa-accept/adv.py` → `adv_a444.txt`；`--check` 日志 `/tmp/cwa-accept/check_a444.txt`。**未改**任何已跟踪源码；本文件仍为未跟踪。

### 10.1 裁决：**有条件通过**

几何口径主线（多边形整株豁免、作业高度有效禁飞、N 仅由 `classify`、误喷正面积、`drift_buffer`、`multi` 失败传播）与 799 四项抽查均成立；Naive A1 部分重叠禁喷不再结构失败；`main.py --check` 退出码 0（146 条「通过」）。仍卡住全量签字的是 **条带切割仍按禁区多边形 AABB / 喷幅盒**，导致三角/L 禁喷易误标 `unreachable_no_spray`（N 偏小），以及贴边细禁飞（adv A8）在中心线可飞时仍可能误标 `unreachable_no_fly`。

### 10.2 Diff 面（`799da32..a444a93`）

8 files, +441/−160：`planning/zones.py`、`planning/safety.py`、`planning/planner.py`、`planning/model.py`、`planner_api.py`、`evaluation/__init__.py`、`multi.py`、`zone_metric_checks.py`。

### 10.3 主张 1–9

| # | 主张 | 结论 | 证据 |
|---|---|---|---|
| 1 | 整株豁免 = `disk_in_polygon(冠层圆+drift_buffer)`，非 AABB | **已核实** | 大半三角 `disk_in=False` 且 reason≠`no_spray`；全包三角/`[0.5,10.5]×[16.5,24.5]` 矩形 → `no_spray`。代码：`zones.classify` |
| 2 | 误喷/safety 正面积；纯相切不拒 | **已核实** | A1b 相切 plan+`check` success，`misspray.area=0`；`rect_poly_positive_overlap` |
| 3 | 有效禁飞看作业高；可达=短带∪fixed-y 喷段+中心线净空；低空不误标 | **部分** | A7 z0–3：N=24、`unreachable_no_fly=[]`、四规划器可覆盖。【缺口】`_split_lane` 禁飞仍按喷幅 AABB 切；adv A8（x2.9–3.1）中心线 x=2 可飞但仍 `no_fly` |
| 4 | N_eligible 只由 `classify`；三规划器同 N | **已核实** | 截图/三角/L/细长/低空等 `adv_a444.txt` 各方法 N 一致；`evaluation.build` 分母用 `classify` |
| 5 | `partial_targets` 仅禁区导致的 0<cov<1 | **已核实** | A1 partial 含 01-05；无区 naive `partial=[]`（虽 cellcov=0.75） |
| 6 | `multi.run` 任一子机失败 → 顶层 failed | **已核实** | 整幅禁飞 → `status=failed`；`zone_metric_checks` mock 用例 |
| 7 | `drift_buffer` 默认 0.0，`classify` 读取 | **已核实** | `model.DEFAULT`；`classify(..., buffer=c['drift_buffer'])` |
| 8 | `zone_metric_checks` 覆盖三角/L/相切/低空/细长/同N/search·sortie/multi/seed0–19 | **已核实** | 检查通过行文案与脚本分支 1–12 |
| 9 | 无区指纹因 `drift_buffer` 变；fixed-y 每带仍单段 spray | **已核实** | config_hash 799≠a444；默认场景 99 段/48 spray **航段签名逐段相同** |

### 10.4 Naive A1 与 799 四项抽查

| 项 | 结论 |
|---|---|
| Naive A1 部分重叠禁喷 | **通过**：success，N=24，partial≈0.312，不再「缺少有效喷洒关联」 |
| search + 禁飞 | **通过**（行间禁飞 success） |
| sortie + 禁飞 | **通过** |
| 起降障碍净空 0.5 m | **通过**（0.3 m 障碍 `validate_scene` 拒绝） |
| seed 0–5 / 检查内 0–19 | **通过**（0 失败） |

### 10.5 检查与回归

- `python3 main.py --check` @`/tmp/cwa-a444`：退出码 **0**；**146** 条「通过」；0 条「失败」。
- 无区相对 799：几何签名一致；仅 `config_hash` 因 `drift_buffer=0.0` 变化。

### 10.6 仍建议 Codex Runner 下一轮（签字前）

1. **`_split_lane` 禁喷**：按多边形正面积/真实相交切带，禁止用禁喷多边形 AABB 把三角/L 外露冠层整段切成 transit（adv A3/A3b 现误 `no_spray_cut`，N=23 偏小）。
2. **`_split_lane` 禁飞**：切断判据与 `classify` 中心线净空对齐（或按中心线±clearance），避免喷幅盒刚擦到细禁飞就把整段短带打成 detour（adv A8）。
3. （可选）`multi` 子机「规划器与方法不一致」根因：禁飞触发 1.2 升级后的 method/planner 字段。
4. 通过后再谈 GitHub push；勿在未点头前推送。

---

## 11. 验收笔记：`6343968`（2026-11-04 ~03:05 PST，技术负责人 /tmp 复核）

> 工作副本：`/tmp/cwa-634`（`git archive 6343968`）；对照 `/tmp/cwa-a444`；探针 `/tmp/cwa-accept/probe_634.py` → `probe_634.txt`；`--check` → `check_634.txt`。**未改**任何已跟踪源码；本文件仍为未跟踪。**未 push。**

### 11.1 裁决：**通过**（P0 `_split_lane`）

a444 卡住签字的 AABB 切带假阳性已消除：半三角/L（AABB 罩树、多边形未整盖）N=24 且留残余 spray；adv A8 细禁飞不再误标 `unreachable_no_fly`；`main.py --check` 146/0、exit 0。全盖三角 `[[0,16],[6,16],[3,22]]` 仍 N=23/`no_spray_cut`，因 x=2/4 覆盖带均为纯 transit——属**真切净**，不是 AABB 假切，不挡 P0。

### 11.2 Diff 面（`a444a93..6343968`）

2 files, +58/−17：`planning/planner.py`（`_split_lane`）、`multi.py`（v1.2 planner 同步）。

### 11.3 主张表

| # | 主张 | 结论 | 证据 |
|---|---|---|---|
| 1 | 禁喷：足迹∩多边形**正面积**才切；半三角/L 留残余 spray | **已核实** | 代码 `overlap_y_intervals` + `rect_poly_positive_overlap`；HALF-tri / L / advA3：`classify={}`，lane 有 spray，N=24；a444 同场景为 `no_spray_cut`/N=23 |
| 2 | 禁飞：中心线 ± clearance 走廊切；A8 不误标 no_fly | **已核实** | A8 classify=`{}`，N=24；x=2/4 整段 spray；fy/caw-nn/naive 均 success（naive 实际喷 x=2.0）。a444 同场景 classify=`no_fly`，连 x=2 也被 AABB 喷幅盒切成 detour |
| 3 | multi：base 升 v1.2 时同步 `planner=method` | **已核实（代码+检查）** | `multi.py` 在 `check` 前写回 `planner=multi-contiguous-uav`；禁区检查仍绿；走廊/横墙禁飞顶层 `failed` 正常 |
| 4 | 检查 146 / zone / no_spray_cut | **已核实** | `/tmp/cwa-634`：`python3 main.py --check` exit 0，146「通过」；`no_spray_cut_checks` 通过 |
| 5 | 截图 / A7 低空不变坏 | **已核实** | S：N=20/24 四豁免；A7：N=24、无 unreachable |
| 6 | 无区几何 vs a444 | **已核实** | `_split_lane` parts 与 plan segs **逐段相等**（99 段） |

### 11.4 口径澄清（Codex 补充，已交叉验证）

- **全盖三角** `[[0,16],[6,16],[3,22]]`：N=23/`no_spray_cut` 因覆盖带被多边形真正切光 → 允许。
- **半三角 / L**：N=24 + residual → 正是本提交要修的 AABB 假切。
- **A8**：不可达假阳性已消；若某规划器强行走 x≈2.5 刷边，属路径选择问题，与 classify 假 `no_fly` 分离。

### 11.5 非阻塞备注（不挡 P0 / 可开 P1）

1. `rect_poly_positive_overlap` 在 ~0.1 m 级薄 X 重叠 + 0.05 m Y 扫描下可能漏检（x=2.5×A8 走廊本应擦边却未切）。当前 fixed-y/naive 不走该 X，未触发安全回归；P1 可加密采样或改精确裁剪。
2. 方向①（孔令标缓冲、航向代价、1–3 ha、sort-only vs sort+drift）→ 见 §12（`eb36dc4`/`ff9e290`）。
3. **仍不 push**，等恒点头；`ARCHITECTURE.md`/`results/` 保持未跟踪。

---

## 12. 验收笔记：`eb36dc4` + `ff9e290`（2026-11-04 ~03:17 PST，技术负责人 /tmp 复核）

> 工作副本：`/tmp/p1-review`（`git archive ff9e290`）；`--check` → `/tmp/p1-review-check.log`。**未改**任何已跟踪源码；本文件仍为未跟踪。**未 push。**
> 用户已锁：缓冲=①约束、不进贡献；`buffer_expand` **默认关**；主消融 sort-only vs sort+drift；缓冲开=可选对照。

### 12.1 裁决：**有条件通过**（P1）

主路径（默认关缓冲 + sort/sort_drift 消融 + 孔令标查表 + 1 ha）全部对齐主张且 `--check` 158/0。条件：论文/工程要跑 **`buffer_expand=1` 且外扩盖到树冠** 前，必须修「切割用外扩副本、豁免/safety 仍用原场景」导致的关联失败（见 §12.5）。默认关时不挡主消融。

### 12.2 Diff 面（`6343968..ff9e290`）

- `eb36dc4`：+645/−26，9 files — 新 `planning/drift.py`、`drift_checks.py`；改 `model`/`order`/`planner`/`zones`/`planner_api`/`main`；`scene/random_map.py` 加 `ha_orchard`。
- `ff9e290`：+5/−5 — `DEFAULT.buffer_expand` 1→**0**；`resolve_effective_buffer` / 注释同步默认关。

### 12.3 主张表

| # | 主张 | 结论 | 证据 |
|---|---|---|---|
| 1 | `buffer_expand` DEFAULT=0；无风有效缓冲=0 | **已核实** | `planning/model.py` DEFAULT；`resolve_effective_buffer` 门控；calm `generate_plan` success |
| 2 | 孔令标查表 U≤3→10、3<U≤5→16、U>5 空/报错、禁静默外推；小麦~7cm 外推写进注释 | **已核实** | `buffer_distance_m`；U=6 → ValueError「禁止静默外推」；`drift.py` 模块头 |
| 3 | 仅园外/贴边敏感区沿下风内扩；园内岛跳过 | **已核实** | `expand_sensitive_inward` + `_zone_is_exterior_sensitive`；drift_checks 园外/岛用例 |
| 4 | 航向/排序漂移代价：`drift_mode=sort_drift` 叠加 `lane_drift_proxy`（与 buffer 开关解耦） | **已核实** | `order.py` + `drift_cost_buffer`；消融 order_cost **13.5291 vs 73.5291** |
| 5 | `ha_orchard` 1 ha：192 树、~1.5 s、22 带、success | **已核实** | check 指标 `trees=192 elapsed=1.459s strips=22`；复现 ~1.39 s |
| 6 | `main.py --check` ~158、exit 0；禁区口径模块仍绿 | **已核实** | 158「通过 ·」/0 失败；含 `no_spray_cut` / `禁区口径` / 漂移P1×12 |
| 7 | `buffer_expand=1` 全链路规划可用、指标随外扩变化 | **部分核实 / 有缺口** | 几何外扩 OK；外扩盖树后 `generate_plan`/`planner_api` 失败（§12.5） |

### 12.4 检查 / 消融 / 1 ha 数字（`/tmp/p1-review`）

| 项 | 数值 |
|---|---|
| `--check` | exit 0；**158** 通过 / 0 失败（约 47.8 s） |
| 漂移P1 子套件 | 12 / 0 |
| sort-only `order_cost` | **13.5291**（order `[0,1,2]`） |
| sort_drift `order_cost` | **73.5291**（同 order） |
| 1 ha | area=1.00，trees=**192**，status=success，strips=**22**，elapsed≈**1.46 s** |

### 12.5 剩余修复（开缓冲对照前必做）

`planner.generate_plan` / `planner_api`：切割用 `expand_sensitive_inward` 副本，但 `classify` / `zone_exclusions` / `safety.check` 仍喂 **`original_scene`**。外扩盖住树冠时，喷带被切掉，豁免却认不出来 → `任务结构不完整：目标缺少有效喷洒关联 …（不在任何禁喷/禁飞区排除范围内）`。

建议：豁免与关联检查对**外扩后**场景做；`scene_hash` 可继续用原场景；误喷口径若要坚持「原敏感区」，需另写规则，不能假装树没被缓冲禁喷。并补一条 `generate_plan(..., buffer_expand=1)` 盖树回归。

另：当前「航向代价」= 条带排序侧风代理，**不是**条带航向角联合搜索——与已锁主消融一致，写作勿写成航向角优化器。

### 12.6 路径

- 导出：`/tmp/p1-review`
- 日志：`/tmp/p1-review-check.log`
- 仓库：`/workspace/cwa-bench` @ `ff9e290`（未 push；`ARCHITECTURE.md` / `results/` 未跟踪）


---

## 13. 更新到 `d51ed09`（2026-11-06 Asia/Shanghai，完整工程交付）

> 工作副本：`/workspace/cwa-bench`，分支 `paper/zones-drift-p1`。  
> 相对 §12 基线 `ff9e290` → 当前 **`HEAD = d51ed09`**（本地超前 `origin/paper/zones-drift-p1`；**未 push**）。  
> 主线定稿（dbm 代定，恒已授权领导）：**缓冲区约束 + 缓冲边界航道对齐（`S_h` / `B-boundary`）**。数字与复现入口见 `RESULTS_complete.md` / `RESULTS_overnight.md`；本节只记架构与口径变更。  
> **本交付不改 `planning/` 算法语义**；下列条目描述 `ff9e290..d51ed09` 已入库的事实。

### 13.1 Minkowski 缓冲（下风内扩）

| 提交 | 内容 |
|---|---|
| `ee286a0` | `expand_sensitive_inward`：对园外/贴边敏感禁喷做 **Minkowski 和** \(Z \oplus [0, d\cdot u]\)（凸包），**保留原多边形**；非凸抛错；裁到场景 XY。修正旧实现「沿下风平移并丢掉原区」把下风侧禁喷挪出地块的 bug。 |
| `00a596b` | 独立缓冲 oracle：(a) 包含 + Minkowski 面积；(b) 逐喷洒采样下风射线 vs 原区；(c) 拒绝旧 translate 实现。 |
| `e6cb3bb` | safety 独立漂移硬检查（oracle b）对照原外禁喷区。 |
| `54aa1ad` | 开缓冲盖冠时 `classify` / 豁免 / 误喷与外扩几何对齐（修 §12.5 缺口）；`scene_hash` 仍指纹原场景。 |

默认：`buffer_expand=0`（§12 已锁；**主结果跟默认 OFF**）。方法表述为约束（引孔令标 2026），**不是创新点**。园内岛状禁喷跳过外扩；`buffer_expand=ON` 若将来跑只作敏感性附录——**今晚不跑、不改默认、不扩岛缓冲语义**。

### 13.2 精确 overlap

| 提交 | 内容 |
|---|---|
| `bb22ae6` | `rect_poly_positive_overlap`：Sutherland–Hodgman 裁到矩形 + 鞋带公式，面积 \(>10^{-9}\,\mathrm{m}^2\) 才算正重叠；去掉会漏检窄于步长重叠的 0.1 m 栅格。`drift_checks` 增至 **23 通过 / 0 失败**；当时 `main.py --check` **170 / 0**。 |

用途：切带、`classify`、误喷、safety 的正面积判据（与 §11 P0 切带验收衔接）。

### 13.3 A 小试评价口径

| 提交 / 脚本 | 内容 |
|---|---|
| `c92be77` 起 | 独立栅格评价器 `scripts/a_trial_eval.py`：自建 \(F=Z\oplus[0,d\cdot u]\) 凸包；`A_excluded` / `A_extra`；阀门滞后 τ；切段与违规。 |
| `70db42d` | τ 档正式纳入 **{0, 0.5, 1.0} s**（τ=1.0 为假设敏感性档；文献依据见 `RESULTS_complete.md` §3 / Wang 2023 JAE）。 |
| `2ff2df1` 及后续 | 主批 seeds 0–4；每 τ **独立**按 `A_extra` 最小（平局 `total_time`）选 S1 / S2 / S2′ / S3 / `S_h`；栅格 0.2 / 0.1 / 0.05 m 与选择稳健性。 |
| `c075e6c` | 覆盖率异常：分母口径问题（非漏喷 bug）；见 `RESULTS_overnight.md` §2。 |
| 主对比基线 | `B-online` / `B-boundary`：`scripts/a_trial_extra_runs.py`（**简化代理，不是原方法复现**）；1b 报告 `scripts/a_trial_1b_report.py`。 |

面积单位 m²（评价器 0.05 m 栅格为主报告）；描述统计 n=5，**无显著性检验**。

### 13.4 启发式 `S_h`

| 提交 | 内容 |
|---|---|
| `2ff2df1` | `S_h`：航向 0°；`o_h = (xmin − x_F) \bmod w`；`xmin = \min(\mathrm{target\,cx}-r)`；`x_F = \max x` of swept buffer \(F\)；航道左喷幅边贴齐 \(x_F\)，中心线 \(x_F + w/2\)；**无搜索**。 |
| `58024ac` | `oh_rot`：把几何偏移推广到任意航向（断言 h=0 与 heuristic_offset 一致）。 |

与 `B-boundary`（地块边界对齐代理）的配对数字见 `RESULTS_overnight.md` §1b 与 `results/a_trial_1b_0e0715a.report.md`。

### 13.5 检查水位（`d51ed09` 叙事）

自 `bb22ae6` 起隔夜提交反复记录：

- `python3 drift_checks.py` → **23 通过 / 0 失败**
- `python3 main.py --check` → **170 通过 / 0 失败**，exit 0

完整工程交付时再次跑通并写入 `RESULTS_complete.md` §6.1 与提交说明。

### 13.6 交付入口与未做项

- 文档：`RESULTS_complete.md`（主线、指针、τ=1.0、拒出附录、未做项、复现命令）。
- 复现：`bash scripts/repro_main_contrast.sh`（钉死 CSV SHA256 + 重算 1b 表；**不重规划**）。
- **未做**：nn_astar、2-opt、风力基准、修复带、岛状缓冲扩 / `buffer_expand=ON` 附录、τ 感知偏移、push。先交闭环工程包，再开新功能。
