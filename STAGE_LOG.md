# 第一阶段接手记录

日期：2026-11-01。状态：场景工具、界面及本轮验证完成，停在场景验收。原参考工程未修改。

## 已落实的决定

- 新工程为外层工作目录下已存在的空目录 `从0开始写代码/`，没有再混入参考工程。
- 单一 Python 根入口，默认单服务＋自动打开系统浏览器；终端 `--check` 调用同一场景实现。
- 规则排列只在生成器中成立。消费者逐个读取独立 ID、位置、半径和高度，不从列表位置或来源参数重建。
- 连续米制场景：多边形地块、独立树干/树冠圆柱、关联喷洒目标、盒障碍、多边形柱体区域、起降点和范围。
- 统一 `terrain_height` 平地查询，未提前实现坡地框架。
- Python 按数据约定、配置、生成、校验、几何、保存加载分文件；前端结构/样式/逻辑分开。压缩语句已整理，主要公共函数已有类型和输入输出/单位说明。
- 加载只校验和读取实际几何；来源参数和实际几何明确区分，重新生成是主动替换操作。

## 自动与终端验证（实际运行）

解释器：工程 `.venv/bin/python`，Python 3.9.6。

运行 `main.py --check`：**8 组通过，0 失败，退出码 0**。

1. 默认 4×6、首尾树坐标、地块尺寸及起降点位置。
2. 修改行数、每行棵数、行株距、树冠尺寸；同配置实际几何完全一致。
3. 障碍＋禁飞＋禁喷区域实际文件保存/加载逐字段一致。
4. 非法数值、非有限值、非法数量、起降点落入实体的拒绝。
5. 错误版本、缺字段、重复 ID、无效引用、越界等损坏场景拒绝。
6. 树冠重叠允许并返回提醒。
7. 1 棵/200 棵及非零地面高度的几何校验。
8. 改单树位置与尺寸、树木重排、不规则多边形、地形查询及起降点禁飞约束。

另行实际验证：

- 非法配置通过 CLI 得到带 `row_spacing=-1` 的原因，退出码 **1**。
- 从 `/private/tmp` 启动根入口，使用项目相对路径加载默认场景，摘要正常。
- 从其他工作目录用 `--load examples/independent_edit.scene.json --preview --no-browser` 启动，服务返回的初始场景与文件所有字段一致，没有重建。
- 所有 `examples/*.scene.json` 可重新加载。

## 真实浏览器验证（实际操作）

在内置浏览器和系统 Safari 实际启动检查，不以退出码代替画面检查。

| 检查 | 实际结果 |
|---|---|
| 默认显示 | 数据 24 棵；俯视可数出 4 个种植行，每行 6 棵；地块、网格、树干/树冠、外侧起降点可辨 |
| 参数修改 | 改为 3×7、行距 8 m、株距 5 m、半径 2 m、高 3 m，生成后 21 棵、21×35 m；布局尺寸同步更新 |
| 未生成状态 | 输入变化后明确黄色提示，画面仍是上次成功结果 |
| 非法配置 | 行距 -2 m 报字段/值/原因；旧画面保留并说明 |
| 文件加载失败 | 版本 999 报错并说明旧画面保留 |
| 区域显示与保存 | 加载 `with_objects.scene.json`，障碍/禁飞/禁喷各 1；俯视可识别，浏览器下载保存后与源文件逐字段相同 |
| 手工修改保留 | 加载 `independent_edit.scene.json`：首棵树 X 移动 0.75 m、冠半径 2.1 m、顶部 5.5 m、树列表反序；画面显示独立大树冠；浏览器重新下载后全部字段与原文件相同 |
| 交互 | 已实际左键拖动旋转、滚轮放大、平移工具拖动、三维/俯视切换、重置；方向/米制比例保持一致 |
| 图层 | 隐藏树冠、显示独立目标轮廓、恢复树冠；透明度滑块降到 0.15，画面同步变化 |
| 尺度取景 | 从 24 扩为 8×12=96 棵、47×49 m，自动取景仍完整显示范围和地块 |
| 默认自动打开 | 直接运行统一入口后系统 Safari 自动打开 localhost 场景，已通过原生窗口确认并截图 |

浏览器下载的文件仅用于逐字段比对；没有清理用户下载目录中的文件。

## 真实截图

- `screenshots/default-3d-system.jpg`：系统浏览器，默认三维。
- `screenshots/default-top-system.jpg`：系统浏览器，默认俯视。
- `screenshots/default-3d.jpg` / `default-top.jpg`：内置浏览器窄窗口。

已人工查看截图：地块/范围区分、起降点位置、图例文字、树木数量与米制比例可辨。较低窗口的左侧控件需要独立滚动；没有右下第二地图、航线、播放条或指标占位。
`references/概念参考-非运行结果.png` 是原概念图，不能用于证明运行效果。

## 当前限制与后续接手点

- 平地；树干/树冠仅直立圆柱；障碍仅轴对齐盒。目标目前每树恰好一个圆柱体积；起降点目前要求在地块外。多边形不支持洞和自交，区域为竖直柱体。
- 不做全场碰撞/任务可行性判定。禁喷区域与目标可重叠，尚未生成扣除禁喷后的任务。
- Canvas 以 32 段圆周及面深度排序显示，透明面可能出现细小接缝；不是精确的体渲染。大规模/高度重叠场景的显示性能和透明交叉未全面测试。规则生成上限 2500 棵是输入保护，不是性能保证。
- 前端读取平地数据绘制平面；后续地形扩展需同时修改高度查询与显示适配。
- 目前 JSON 框/文件用于附加对象配置，无鼠标拖树/多边形编辑器。加载来源参数不等于实际几何；只有显式生成会替换场景。
- 不持久化颜色、相机和图层选项到物理场景；刷新页面从启动场景恢复，未保存的画面变化不会自动保留。
- 下一阶段应从 `scene.load` 和 `terrain_height` 读取实际对象。先讨论作业模型，再接单机规划；不要把原模板的覆盖统计/航高/时间语义直接移植。

# 第二阶段接手记录 · 2026-11-01

已完成单机固定 Y 方向逐带往返几何计划、独立作业配置、完整线段安全检查、计划 JSON 保存加载、场景指纹匹配和三维/俯视显示。第一阶段原始数据接口继续使用，原参考工程未修改。

实际终端：第一阶段 8 组全部通过；第二阶段行为检查通过，包括默认完整起降返航、喷幅变化、最高实际冠顶变化、树和目标列表重排、独立目标移动、起降与转场关闭喷洒、爬升线段中间障碍（端点在障碍外）、飞机中心线未进入但喷幅触及的窄禁喷区、保存加载、不匹配拒绝、不连续计划拒绝。浏览器 JSON 的 2/2.0 等价数值指纹已归一并有回归检查，不改变真实几何或列表顺序。

实际浏览器：默认生成成功为 8 个有效作业带，高度 6.20 m；喷幅 1 m 生成 12 带。作业参数变化和场景参数变化均清除旧计划并提示失效。已在三维、俯视查看同一计划及方向箭头，截图为 `screenshots/plan-3d.jpg`、`plan-top.jpg`。命令行默认计划已实际通过文件选择加载到浏览器，页面显示匹配成功；浏览器重新下载的计划通过后端校验并与命令行示例逐字段相同。

限制：这是分段直线几何计划，不是执行结果或覆盖率认证。目标投影按带内 Y 包络保守覆盖，会包含非目标区域；只有区间之间的空隙关闭喷洒。实体与区域使用保守包围盒，不做复杂绕障、禁喷区切割、转弯动力学。失败无可执行航段，不修改场景。已停在计划生成与展示验收。


## 第二阶段独立复核修正

已修复“全部喷洒段改成关闭喷洒转场仍能通过”的缺陷。新增独立任务结构检查：至少一个喷洒段、全目标合法关联、关联目标与矩形足迹正面积相交，非喷洒段不得声明目标。不是重新调用生成器，也不声称验证覆盖率。

实际重新执行 `main.py --check`：原第一阶段和第二阶段检查全部通过，新增全关喷、遗漏目标、远处伪关联、足迹侧边交叠、纯切触及无端部延伸回归全部通过。统一矩形足迹与禁喷判断，定义详见 README 和 planning/footprint.py。

## 第三阶段记录 · 2026-11-01

已实现 `execution/` 分段恒速时间模型、任意时刻状态查询、边界和中点采样、执行文件保存加载，以及 UI 播放/暂停/重置/拖动/倍速与二维四旋翼辨识图标。计划或场景失效会清除时间模型。默认模型总时长实际为 127.3963848374023 s。

`main.py --check` 实际结果：第一阶段 8 项、第二阶段任务结构检查、第三阶段手算和回归检查全部通过。第三阶段检查覆盖不同速度手算到达时间和中点、所有段边界、最终落地喷洒关闭、重复查询、短段采样、倍速不改模型状态、非法时间、计划指纹不匹配及执行文件重建。

浏览器回放尚待独立验收；如果浏览器不可用，不把终端通过当成画面验证。当前仍不实现覆盖累计、沉积、能耗、风场、多机或真实动力学。

## 第四阶段 UI 收尾

已接入 `/api/evaluation`，回放时间查询同步 evaluator 结果和覆盖网格图层；页面显示覆盖率、漏喷、重复和喷洒时间，并标记网格近似。`main.py --check` 第一至第四阶段全部通过。

## 第七阶段：规划器接口与环境抽象

新增统一 Planner 适配器、MultiUAVEnv、deterministic random policy 与 `--env-demo`；`--check` 已验证 seed、边界、非法动作和终止条件。本阶段尚未训练强化学习模型。

## 第八阶段：最小策略训练基线

新增 `rl.py` 与 `rl_checks.py`。训练使用现有 MultiUAVEnv 的奖励和动作校验，评价重新进入统一 execution/evaluation，并校验场景与计划指纹。当前仅为 deterministic/tabular random baseline，不宣称训练效果。

## 第九阶段：喷洒语义与目标级评价

新增目标类型与流量配置（兼容旧 JSON），评价输出目标级覆盖统计、漏喷/重复目标、喷洒时长和估算总量，并保留网格近似字段。UI 回放评价显示目标覆盖汇总。本阶段不引入新规划算法。

## 第十阶段：植保仿真实验与统计验证

新增统一实验运行器、逐次结果与均值/标准差汇总、失败保留、CLI `--experiment` 和 UI 最小实验入口。当前仅做描述性统计，不升级 MADDPG。

## 第十一阶段：风场与方向代价模型

加入无风兼容的风速、风向、方向代价配置，作用于时间估计并保留有效速度记录；新增风场回归检查。未升级 MADDPG。

## 第十二至十五阶段

完成转场搜索、联合顺序基准、多机连续时间冲突诊断和监督代理接口；全部接入回归检查，代理误差与安全复核边界已记录。

## 接手复核 · 2026-11-02

后续对话接手后重新执行 `.venv/bin/python main.py --check`：基础 8 项及第二至第十五阶段回归全部通过（0 失败）。

真实浏览器复核 `http://127.0.0.1:8765`：生成默认航线成功，显示 8 个有效作业带、高度 6.20 m；准备回放、播放/暂停后时间和位置状态更新；通过“定位时间”输入 127.3963848374023 s 后显示落地完成、喷洒 69.94 s、估算量 69.94。三维页面和评价文字可见。**历史数字 54.7% 来自旧评价器（把 resolution 当喷幅），已在第十八阶段失效；正确默认覆盖率为 100%。**

发现一个待修复的小交互问题：时间滑块按键移动到终点时，滑块数值会更新，但状态/评价不会同步；通过“定位时间”输入框定位可正常刷新。尚未修改代码，避免把验收观察误当成阶段完成。

## 回放滑块同步修复

新增统一 `handleSeekInput`，同步滑块、定位时间、执行状态和评价；新增 `web_checks.py` 回归检查。

## 可选转场搜索接入

新增 `transition_mode` 配置、计划链路搜索转场、失败原因保留和 `transition_checks.py`。默认 fixed 行为兼容旧计划，search 模式需经过独立安全检查。

## 转场模式接口一致性与计划指纹

- 新增 CLI `--transition-mode {fixed,search}`：未给出时沿用作业 JSON，JSON 未给出时为 `fixed`；显式给出时覆盖 JSON 同名设置。
- 新计划版本升至 `1.1`，新增 `config_hash`（有效配置指纹，含实际转场模式）；`scene_hash` 继续保存场景指纹。`1.0` 旧计划仍可加载。
- `check()` 在 `1.1` 计划上校验配置指纹，并拒绝方法名与实际模式不一致（fixed 计划不得声称搜索方法，反之亦然）。多机基线方法 `multi-contiguous-uav` 不受该一致性规则限制，其完整性由配置指纹覆盖。
- `transition_checks.py` 扩展为：默认 fixed 兼容、search 成功、有效场景下搜索失败保留原因、保存加载往返、模式篡改、配置指纹篡改、删指纹、方法/模式不一致、CLI 覆盖、旧计划兼容。
- 修复 `main.py` 中 `from rl import ... save, load` 与 `from experiment import run, save` 造成的局部名遮蔽，使 `--load` / `--save` 不再触发 `UnboundLocalError`。
- Web 计划状态显示实际转场模式、作业带数和航段数；计划失效时清空旧的覆盖评价文本，避免失败后仍显示上一次成功评价。
- 终端验证：`main.py --check` 全绿；fixed 计划 99 段，search 计划 162 段；阻塞场景 search 失败返回非零退出码且不保存计划。

## 固定/搜索转场对照实验

- 新增 `configs/transition.small.json`：2×3 棵、6 个目标的小场景，便于复现。
- 新增 `transition_experiment.py` 与 CLI `--transition-experiment --save-transition-results`，可与 `--config`、`--load`、`--job` 组合。
- planner 在 search 模式记录 `plan["search"] = {model, step, clearance, routes, nodes}`；`nodes` 是各转场 A* 扩展节点总数。
- 对照结果按 fixed/search 两行保存路径长度、航段数、总时间、搜索节点数、安全结果、失败原因、场景指纹和配置指纹；顶层含说明字段，明确单场景结果不构成 search 优越性结论。
- 新增 `transition_experiment_checks.py` 并接入 `--check`：成功字段、指纹一致性、保存/加载、阻塞场景两类失败原因保留。
- 本小场景观测（仅此场景）：fixed 27 段 / 84.617 m / 42.309 s / 0 节点；search 58 段 / 92.079 m / 46.039 s / 158 节点。
- 修复 Web 加载计划时对不存在的作业输入框写值导致的崩溃；加载后保留实际模式、航段数和配置指纹。
- 真实浏览器（端口 8792）：search 生成 162 段，保存文件落盘后独立校验通过，重新加载显示同一 `config_hash`；fixed/search 切换均使旧计划失效。

## 第十六阶段：作业顺序与转场路径联合精确穷举

日期：2026-11-02。状态：终端与浏览器均完成；本阶段只扩展小规模精确核验，不重写场景、规划、安全、执行和评价模块。

### 实现

- `joint.py` 从“仅排列喷洒航段端点距离”升级为完整计划构造：起飞 → 转场/喷洒交替 → 返航 → 降落。换序时喷洒航段起终点、目标关联和方向与原航段完全一致。
- `fixed` 模式构造同高度直线转场；`search` 模式调用现有 `routing.route` 净空网格 A*，并通过路由缓存避免重复搜索。
- 每个候选先调用独立 `planning.check`，通过后再调用统一 `execution.build`；按执行总时间选优，同分按总路径长度、再按顺序字典序。
- 返回 `status/method/order/transition_length/total_path_length/total_time/expanded/orders_total/feasible_orders/rejected/scene_hash/config_hash/baseline/improvement/optimality_gap/search_nodes/search_routes` 等字段。
- `len(sprays) > limit` 或排列数超过 `40320`（8!）返回 `unsupported`，原因写明航段数、上限和完整排列数；不返回 `order`/`total_time`。基准计划失败返回 `failed` 并保留原始原因。
- `rejected` 最多保留 20 条，`rejected_total`、`rejected_truncated`、`rejected_note` 说明总量与截断。
- `joint.verify` 拒绝场景/配置指纹不匹配、成功结果不是完整排列、未穷举全部排列或失败结果携带最优方案。
- 新增 `joint_transit_checks.py` 并接入 `main.py --check`；新增 `configs/joint.small.json`（2×2 棵）、`configs/job.joint.small.json`（喷幅 5 m）、`configs/joint.blocked.json`（贯穿障碍）。
- `main.py` 新增 `--joint`、`--save-joint`、`--limit`；退出码：success 0、failed 1、unsupported 2。旧命令行为不变。
- Web “09 · 联合作业顺序”面板新增穷举上限输入，显示顺序、转场/路径/时间、扩展数、搜索节点、安全状态、基准/改进量、不可行数、指纹；失败时显示原因与截断说明；场景、作业参数或上限变化立即使旧结果失效。

### 终端验证（实际运行）

```bash
.venv/bin/python main.py --check
.venv/bin/python main.py --joint --config configs/joint.small.json --job configs/job.joint.small.json --limit 8 --save-joint "$TMPDIR/joint.fixed.json"
.venv/bin/python main.py --joint --config configs/joint.small.json --job configs/job.joint.small.json --transition-mode search --limit 8 --save-joint "$TMPDIR/joint.search.json"
.venv/bin/python main.py --joint --job configs/job.default.json --limit 6
.venv/bin/python main.py --joint --config configs/joint.blocked.json --job configs/job.joint.small.json --limit 8
```

结果：

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `--check` | 0 | 33 条通过记录、0 失败（含第十六阶段 7 条子检查） |
| fixed 小场景 | 0 | success；4 航段；枚举 24/24；可行 24；顺序 [1,2,3,0]；转场 23.038 m；路径 47.438 m；时间 23.719 s；较基准省 1.194 s（4.79%） |
| search 小场景 | 0 | success；枚举 24/24；顺序 [1,2,3,0]；转场 24.236 m；路径 48.636 m；时间 24.318 s；搜索节点 36；较基准省 3.190 s（11.60%） |
| 默认场景 + limit 6 | 2 | unsupported；48 航段超过上限 6；`order`/`total_time` 为 null |
| 阻塞场景 | 1 | failed；基准原因“航段 1 与实体净空或禁飞包围盒冲突”；无伪最优 |

`joint_transit_checks.py` 的 7 条子检查均通过：3 航段独立暴力最优与执行器一致；超航段数/超排列数 unsupported；阻塞基准失败、部分候选拒绝与 20 条截断说明；指纹与篡改拒绝；fixed/search 确定性；非对象 `config`/`job` 输入防御；search 使用 `routing.route` 独立枚举并校验喷洒方向不变。

### 真实浏览器验证（实际运行）

- 端口：**8793**（`8791/8792` 未复用）；App Browser 面板启动 `main.py --no-browser --port 8793`，外层 `.claude/launch.json` 配置名 `joint-ui`。
- 页面：`http://127.0.0.1:8793`，“果园场景实验台”。
- 小场景 fixed：场景参数 2 行 × 2 棵、喷幅 5 m；点击“生成场景”后显示 4 棵树；点击“计算小规模最优顺序”，面板显示：
  `精确最优 · 固定直线 · 顺序 [1, 2, 3, 0] · 转场 23.04 m · 路径 47.44 m · 时间 23.72 s · 扩展 24/24 · 安全通过`
  `较基准 1.19 s（4.8%）；路径缩短 2.39 m`
  `基准顺序 [0, 1, 2, 3] · 时间 24.91 s · 可行 24 · 场景 86c1f88b · 配置 d85a9027`
- 切换“净空搜索”后旧结果立即变为“场景或参数变化后结果已失效”；重新计算显示：
  `精确最优 · 净空搜索 · 顺序 [1, 2, 3, 0] · 转场 24.24 m · 路径 48.64 m · 时间 24.32 s · 扩展 24/24 · 搜索节点 36 · 安全通过`
  `较基准 3.19 s（11.6%）；路径缩短 6.38 m`
- 恢复默认 24 棵、喷幅 2 m、fixed，点击计算显示：
  `unsupported：航段 48 超过穷举上限 6；未计算，不返回伪最优结果`
- 构造 1 行 × 3 棵、障碍 `wall`（`[1,-5,0]`–`[4,18,7]`）生成 3 棵树；点击计算显示：
  `failed：基准计划失败: 航段 1 与实体净空或禁飞包围盒冲突`
  `候选失败：baseline: 航段 1 与实体净空或禁飞包围盒冲突`
- 修改场景行数后旧结果立即变为“场景或参数变化后结果已失效”；恢复 2×2 小场景后可重新计算成功。
- 修改穷举上限（6→5）后旧结果同样立即失效，需重新计算。
- 截断场景：2 行 × 2 棵、喷幅 3.5 m、障碍 `pin`（`[3.8,2.3,6.05]`–`[4.2,2.7,6.35]`）；计算成功，页面显示：
  `精确最优 · 固定直线 · 顺序 [0, 3, 4, 5, 2, 1] · 转场 26.97 m · 路径 57.02 m · 时间 28.51 s · 扩展 720/720 · 安全通过 · 不可行 540（仅保留前 20 条，共 540 条失败候选）`
  `较基准 0.84 s（2.9%）；路径缩短 1.69 m`
  `基准顺序 [0, 1, 2, 3, 4, 5] · 时间 29.36 s · 可行 180 · 场景 2e178b4e · 配置 26800d3c`
- 最终代码复验（同一 6 航段 pin 场景切到“净空搜索”）：成功，顺序 [0, 3, 4, 5, 2, 1]，转场 31.63 m，路径 61.69 m，时间 30.85 s，搜索节点 80，扩展 720/720，可行 720；较基准省 1.08 s（3.4%）。
- 最终代码复验阻塞场景 failed 文案：`failed：基准计划失败: 航段 1 与实体净空或禁飞包围盒冲突` / `候选失败：baseline: 航段 1 与实体净空或禁飞包围盒冲突（显示 1/1 条失败候选）`。
- 截图：`screenshots/joint-panel-2026-11-02.jpg`（4 航段成功结果）、`screenshots/joint-panel-truncation-2026-11-02.jpg`（6 航段、540 条失败候选的截断说明）。
- 浏览器 fixed/search 顺序、转场、路径、时间、扩展数、节点数与终端同输入结果一致。

### 独立审计与修正

另开只读审计会话复核代码、回归和四条 CLI。审计结论：未发现伪成功或安全检查绕过。根据审计意见补做：

- search 最优性改由 `routing.route` 直接枚举独立核验，不再用 `joint` 自身构造器自证；并独立复算总路径/时间与搜索节点。
- 增加喷洒航段方向/起终点/目标关联不变的独立断言。
- `unsupported` 保留精确 `orders_total`，不再置 null。
- 新增 `rejected_note`，Web 失败信息显示“显示 2/N 条失败候选”和截断说明。
- 穷举上限输入变化现在也会使旧结果失效。
- 明确 search 路由只避让障碍，树冠/禁飞由安全检查拒绝；“精确”仅指顺序维度。
- 全失败分支保留为防御性结果，但当前 fixed/search 语义下恒等顺序必然复现基准，故审计指出其在现有模式下不可达；已在代码注释和文档中说明，不以合成测试冒充可达。
- 第二个边缘审计发现 `--job` 顶层为数组/null 时抛出未捕获 TypeError；已在 `main.job_config` 增加对象校验，`--transition-experiment` 也捕获配置错误，并新增“输入防御”子检查。非对象 `config` 传入 `joint.optimize` 同样返回 failed 而非崩溃。

### 已知限制

1. 单场景、单配置的数值只作描述性核验，不构成 fixed/search 或顺序策略的普适优劣结论。
2. 精确穷举上限为 8 航段/40320 排列；8 航段终端约需 100 秒，交互建议 `limit=6`。更大规模应使用启发式并单独报告近似 gap，不得冒充精确最优。
3. search 网格路由只避让 `obstacles`，不避让树冠和禁飞区；后者由安全检查拒绝，可能使某些候选直接失败。
4. 转场仍是同高度二维网格或直线，不含高度层、风场代价、转弯半径、加速度和真实机体动力学；时间是分段恒速执行模型的估计。
5. `unsupported`/`failed` 不生成最优方案；默认大场景返回 unsupported 是设计语义，不是成功结果。
6. 浏览器自动化中“生成场景”按钮通过页面内 DOM click 触发提交（工具栏点击未触发表单 submit），随后产生真实 `/api/generate` 请求并更新页面；其余按钮使用浏览器点击工具。该细节不改变页面实际运行结论。


## 第十七阶段：多机等待、错时与共享航段协调

### 实现

- `coordination.py`：把“重叠区间起点采样”替换为解析连续时间 CPA。对每一对时间窗口重叠的航段，以相对位置二次函数求最近时刻与最小距离；返回 `pairs`、`min_separation`、`makespan`、`total_time` 等字段，并保留旧 `analyze(timelines, min_distance=1.0)` 签名。输入结构、时间顺序、坐标有限性和非正 `min_distance` 均报错。
- `coordination_plan.py`：在 `multi.run` 分块计划与统一 `execution.build` 之上实现确定性协调。地面等待通过平移单机时间线实现，计划本身不变；对每个冲突对延迟编号较大者，偏移步长由 CPA 距离缺口/相对速度估计；受 `max_delay`/`max_attempts` 限制。`conflicts_after == 0` 才 `success`；否则 `failed` 保留原因、尝试次数和最后冲突数。提供 `verify` 与 `save`。
- `main.py`：新增 `--coordinate`、`--save-coordination`、`--min-distance`、`--max-delay`、`--max-attempts`；退出码 `success=0`、`failed=1`、输入错误=2 且无 traceback。旧命令未改动。
- `server.py` / `web/execution.js`：新增 `/api/coordinate` 与“06 · 多机协同”协调入口、最小间距/最大等待输入、前/后冲突、每机偏移、makespan、安全状态、失败原因与失效逻辑；旧“生成多机基线”保留。
- `coordination_plan_checks.py`：7 条独立回归接入 `main.py --check`。
- `.claude/launch.json`：新增 `coord-ui`（端口 8795）；外层 App Browser 会话配置同步增加同名条目，仅用于验证工具。

### 终端验证（实际运行）

- `.venv/bin/python main.py --check`：**退出码 0，40 条通过 / 0 失败**（原 33 条 + 第十七阶段 7 条）。
- 默认场景 2 机：
  `.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1.0`
  退出码 0；`success`；冲突 1 → 0；尝试 1；等待合计 2.05 s；makespan 81.607 s；最小间距 2.899 m；UAV1 偏移 0 / 时长 70.951 s，UAV2 偏移 2.05 / 时长 79.557 s；`scene ba634bd2`、`config 4b922f31`。
- 小场景 2 机并保存：
  `.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1.0 --config configs/joint.small.json --job configs/job.joint.small.json --save-coordination "$TMPDIR/coordination.json"`
  退出码 0；`success`；冲突 1 → 0；尝试 1；等待合计 2.05 s；makespan 23.293 s；最小间距 1.638 m；UAV1 17.082 s，UAV2 偏移 2.05 / 时长 21.243 s；`scene 86c1f88b`、`config d85a9027`；结果文件可再次加载为合法 JSON。
- 不可消解：
  `.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1000 --max-delay 2 --config configs/joint.small.json --job configs/job.joint.small.json`
  退出码 **1**；`failed`；原因“达到最大地面等待 2.00 s 仍存在 1 个冲突对”；冲突 1 → 1；尝试 2；偏移 `[0.0, 2.0]`；未伪造零冲突。
- 输入错误：
  `.venv/bin/python main.py --coordinate --uavs 2 --min-distance 0`
  退出码 **2**；输出“失败：最小机间距必须为正”，无 traceback。
- 小场景 3 机：`success`；冲突 3 → 0；尝试 65；等待合计 30.8 s；偏移 `[0.0, 14.75, 16.04]`。
- 非法作业配置 `{"swath": 0}`：`failed`，`stage=multi`，原因“多机基线失败：swath=0：需要有限正数”，`conflicts_after=null`，不抛异常。

### 真实浏览器验证（实际运行）

- 端口 **8795**（启动前确认 8791–8795 中 8793、8794 被占用，8795 空闲）；App Browser 面板以配置 `coord-ui` 启动 `main.py --no-browser --port 8795`。
- 页面“果园场景实验台”，场景设为 2 行 × 2 棵、喷幅 5 m，生成 4 棵树。以下为实际页面文本：
- 协调成功（最小间距 1 m、最大等待 120 s）：
  `协调成功 · 连续 CPA · 冲突 1 → 0 · 最小间距 1.64 m · 等待合计 2.05 s · makespan 23.29 s · 尝试 1`
  `UAV 1 等待 0.00 s · 时长 17.08 s` / `UAV 2 等待 2.05 s · 时长 21.24 s`
  `安全：conflicts_after=0 · 场景 86c1f88b · 配置 d85a9027`
  表格显示 UAV1 0.00/17.08/0、UAV2 2.05/21.24/0。与终端同输入结果一致（2.05 s、23.293 s、1.638 m、1 次尝试）。
- 改变作业速度 2 → 2.5：协调结果立即变为“场景或参数变化后协调结果已失效，请重新协调”；恢复后可重算。
- 改变最小间距 1 → 1.5：协调结果立即变为“最小间距或最大等待变化后协调结果已失效，请重新协调”。
- 修改场景行数（2 → 3，尚未生成）：协调结果与旧多机基线同时失效，状态栏显示“参数已修改，尚未生成”。
- 不可消解（最小间距 1000 m、最大等待 2 s）：
  `协调失败 · 达到最大地面等待 2.00 s 仍存在 1 个冲突对`
  `冲突 1 → 1 · 尝试 2 · 等待合计 2.00 s`；UAV2 冲突对为 1；页面未显示成功。
- 串行化语义（最小间距 1000 m、最大等待 120 s）：
  `协调成功 · 连续 CPA · 冲突 1 → 0 · 最小间距 无同时空中重叠（串行） · 等待合计 20.00 s · makespan 41.24 s · 尝试 2`
- 旧“生成多机基线”仍可用：`已生成各机独立计划；未模拟运动协同`；表格 `UAV 1 · success · 34.16 m · 覆盖 15.6%`、`UAV 2 · success · 42.49 m · 覆盖 18.8%`。
- 截图：`screenshots/coord-panel-success-2026-11-02.jpg`、`screenshots/coord-panel-failed-2026-11-02.jpg`。
- 浏览器结论：**通过**。协调前/后冲突、各机等待、makespan、安全状态、失效逻辑、失败原因和旧多机基线均实际操作验证，页面数值与终端一致。

### 独立审计与修正

本回合由上级会话发起，应用不允许在此回合新建独立 Code 会话；因此另起只读 Plan 子代理（独立上下文、不可编辑文件）做交叉审计。审计结论：核心协调行为 PASS，但 `verify` 存在完整性问题。已修正并重新回归：

1. **伪造成功可被 `verify` 接受**（MEDIUM）：把真实 failed 结果改成 `status=success`、`conflicts_after=0`、`min_separation=0.2` 后，旧 `verify` 只查字段一致性，返回 True。修正：`verify` 不再信任结果字段，而是按当前场景/配置重新运行 `multi.run`、`execution.build`，套用结果偏移后重新做连续 CPA，并复核 `conflicts_before/after`、`min_separation`、`separation_measured`、`makespan`、`waiting_seconds`、`total_time`。伪造结果现在报“成功结果复核后仍存在冲突”。
2. **`config_hash=None` 绕过配置校验**（MEDIUM-LOW）：预规划失败结果套用到任意有效配置仍能通过。修正：带 `config_hash` 的结果先做配置指纹校验；预规划失败结果在 `verify` 时重新运行 `multi.run`，若当前配置已能成功则拒绝（“失败结果与当前输入不一致”）。
3. **零时长瞬移航段未被检测**（LOW）：`t_start == t_end` 被当成静止点，跳变终点不参与距离计算。修正：结构校验要求 `t_end > t_start`，与 `execution.build` 的严格递增一致。
4. **`offset` 契约不一致**（LOW）：带 `offset` 的时间线只要求首段不早于 offset，几何仍按已平移航段计算。修正：显式带 `offset` 时首段 `t_start` 必须等于 offset；`coordinate` 生成的时间线满足该条件。
5. **回归盲区**（LOW）：新增伪造成功、被篡改的最小间距、零时长航段、offset 不一致四类拒绝测试，并加入 `verify` 对相同非法配置与不同有效配置的区分断言。
6. **失败结果数值可被篡改**（LOW，复审计追加）：失败协调结果的 `makespan`/`waiting_seconds`/`total_time`/`min_separation` 未被旧 `verify` 复核。修正：失败协调分支同样重放时间线并校验这些字段与 `uav_count`；回归新增四类篡改拒绝测试。

修正后 `.venv/bin/python main.py --check` 仍为 **退出码 0、40 条通过 / 0 失败**。复审计确认：真实成功仍通过；伪造成功、篡改成功结果的最小间距、失败结果套用有效配置、零时长航段、offset 不一致、失败结果的 `makespan`/`waiting_seconds`/`total_time`/`min_separation` 篡改均被拒绝；未发现新的确认缺陷。审计同时独立复算并确认：CPA 二次型最小值、端点夹取、零相对速度、重叠窗口枚举、边界单点接触、偏移不遮蔽冲突、`makespan`/`waiting_seconds`/`total_time` 关系、3 机 3 对/4 机 6 对、浏览器面板与文档数值均正确。

### 已知限制

1. 间距只在两机同时在空中时度量；地面等待和已降落停放不参与，模型没有停机位占用或地面相撞。
2. 协调只处理机间动态间距，不替代对树木、障碍、禁飞区的静态安全检查。
3. 确定性策略只延迟编号较大的无人机，不保证总等待或 makespan 全局最优，且可能比“允许延后任意一机”的策略更早返回 `failed`。
4. 时间是分段恒速模型（含现有风场速度修正），没有加速度、转弯半径、悬停动力学和真实飞控。
5. 串行化成功时 `min_separation=null`、`separation_measured=false`；这不是“间距 0”，也不应解释为测得了安全距离。
6. `max_delay` 是**单机**最大地面等待，不是总等待上限，因此 `waiting_seconds` 可以超过该值。
7. 多机规模增大时尝试次数与计算量上升（小场景 3 机 65 次、4 机 77 次）；默认 200 次尝试不保证大规模一定收敛，失败会明确返回而不是伪成功。
8. 单场景、单配置数值仅作描述性核验，不构成多机协调策略的普适优劣结论。

## 第十七阶段追加：全方案动画回放与流畅性（G 节）

### 实现

- 新增 `playback.py`：把 `execution.build` 时间线转成播放载荷（每段 `t_start/t_end/start/end/type/spray/speed/heading`），提供 `multi_playback`（多机基线）、`joint_playback`（最优/基准）、`coordinate_tracks`（协调结果直接携带偏移时间线）。
- `coordination_plan.coordinate(..., include_playback=True)`：服务端协调响应增加 `playback`，每机首段 `t_start` 等于等待偏移；CLI/保存默认不含该大字段。
- 新增 `server.py` 路由：`/api/multi-playback`、`/api/joint-playback`，`/api/coordinate` 返回回放数据，静态 `/playback.js`。
- 新增 `web/playback.js`：动态 overlay 画布、`MultiPlayback` 引擎、分段恒速本地插值、rAF + 墙钟、10 Hz DOM 节流、`document.hidden` 暂停、倍速重锚。
- `web/execution.js`：03 单机回放改为本地 `localStateAt`，播放期间不再请求 `/api/state`；覆盖率评价改为暂停/定位时 120 ms 去抖请求；06 增加基线/协调回放来源、播放/暂停/重置/倍速/时间定位；09 增加最优/基准回放。
- `web/app.js`：主画布静态层与动态 overlay 分离；多机/联合回放期间隐藏单机计划路径。
- `playback_checks.py`：4 条回归（多机、协调、联合、前端静态约束），接入 `main.py --check`。

### 终端验证（实际运行）

- `.venv/bin/python main.py --check`：**退出码 0，44 条通过 / 0 失败**（原 40 + G 节 4 条）。
- 多机基线载荷：2 轨，duration 21.243 s；两机 t=0 均在起降点 `[-3.0, 4.5, 0.0]`。
- 协调载荷：2 轨，偏移 `[0.0, 2.05]`；UAV2 首段 `t_start=2.05`、时长 23.293 s，`playback.duration == makespan`。
- 联合载荷：最优/基准两轨，duration 23.719 s / 24.913 s，与联合结果和基准指标一致。
- `playback_checks` 独立重建 `execution.build` 时间线，逐段核对起终点、类型、喷洒状态、时刻与时长。

### 真实浏览器验证（实际运行，8795）

- **03 单机**：准备回放时一次取回时间线；播放 2 s 共记录 609 帧，平均帧间隔 16.62 ms、最大 17.70 ms，播放期间 `/api/state` 与 `/api/evaluation` 请求计数均为 0；暂停后评价请求 1 次并显示覆盖 15.6%；时间滑块与数字框同步（3.00 s），4× 切速不重置位置。
- **本地插值与执行器一致性**：在 t=0、首段边界 3.10 s、段中点 1.55 s、第二段边界 6.79 s 和总时长 24.91 s，将 `localStateAt` 与 `/api/state` 逐项对比：位置最大差 0.000，`segment_index`/`status`/`speed`/`spray` 完全一致；边界时刻按 `bisect_right` 选择下一段，与 Python 一致。
- **06 协调**：准备回放无网络请求（使用协调响应中的时间线）。t=0 两机均在起降点，UAV2 状态“地面等待”；t=1.00 UAV1 在 `[-3.00, 4.50, 2.00]`、UAV2 仍在 `[-3.00, 4.50, 0.00]`；t=6.00 两机分别在 `[2.11, 1.75, 6.20]` 与 `[-1.38, 5.02, 6.20]`。播放期间记录 1652 帧，平均 16.65 ms、最大 18.40 ms、超过 50 ms 的帧 0 个，`/api/state` 与 `/api/evaluation` 计数 0。
- **06 基线**：准备时 `/api/multi-playback` 1 次；播放 1.19 s 期间请求计数 0，两机同时起飞、位置一致。
- **09 联合**：准备时 `/api/joint-playback` 1 次；播放 1.47 s 期间请求计数 0；t=15.00 最优在转场 `[5.22, 1.00, 6.20]`、基准在喷洒 `[8.00, 3.08, 6.20]`，两条路径颜色与标签可区分。
- **失效**：最小间距 1→1.5 时协调回放立即停止并禁用；联合上限 6→7 时联合回放立即停止并禁用；作业速度 2→2.5 时 03 单机回放失效、播放按钮禁用。
- 截图：`screenshots/coord-playback-t0-2026-11-02.jpg`、`coord-playback-t1-2026-11-02.jpg`（等待偏移生效）、`coord-playback-t6-2026-11-02.jpg`、`joint-playback-2026-11-02.jpg`。
- 说明：验证过程中页面曾因窗口被切到后台而不再触发 rAF；帧时间证据在页面可见时采集。这是浏览器后台降频，不是回放逻辑逐帧请求。

### 取舍

- 08 三维转场搜索仍为单路线静态诊断，不做动画；它属于 G1 可选范围，且与 03 单机回放重复。未把它画成“多方案轨迹”。

### 已知限制

1. 回放只复现执行器的分段恒速模型，不含转弯、加速度、悬停或真实飞控动力学。
2. 多机回放的地面等待是时间平移，飞机停在起降点；没有停机位占用模型。
3. 浏览器在后台/窗口被遮挡时会降频或暂停 rAF，帧时间证据必须在页面可见时采集。
4. 08 没有动画，已按 G1 可选范围说明取舍。
5. 轨迹颜色使用固定 8 色调色板循环，超过 8 架时颜色会重复，需以 `UAV n` 标签区分。

### G 节独立审计与修正

只读审计子代理复核 `playback.py`、`web/playback.js`、`web/execution.js`、`server.py` 和证据，确认载荷推导、无逐帧请求、rAF/墙钟、失效和截图一致；指出并已修正：

1. **段边界插值不等价（MEDIUM）**：旧 `trackState`/`localStateAt` 用 `t <= t_end` 选择上一段，而 `execution.state_at` 用 `bisect_right` 选择下一段；边界时刻的位置相同但航段/状态/速度/喷洒不同。已改为严格 `t < t_end`，t=0 单独返回首段速度；在 t=0、3.10、6.79、中点和终点与 `/api/state` 逐项对比，位置差 0，段索引/状态/速度/喷洒一致；`trackState` 与 `localStateAt` 同样逐项一致。
2. **03 单机后台不暂停（MEDIUM-LOW）**：`document.hidden` 时 rAF 暂停但墙钟继续，返回会跳帧。已增加单机 `visibilitychange` 处理：记录当前时间、停止 `playing`、保留 `playTime`；模拟隐藏 2.5 s 后 `playing=false`、时间停在 2.50 s、恢复后从 2.50 s 继续。
3. **失败协调结果被当作成功回放（LOW）**：失败结果仍携带 `playback`，前端旧代码 `Object.assign({status:'success'})` 会启用回放。已改为只有 `status=success` 才保存/提供协调回放；失败显示“协调失败，回放不可用（需先消解冲突）”，实测 `coordPlayback=null`。
4. **单机最终帧可能被节流跳过（LOW）**：完成状态在 100 ms 节流窗口内时旧 DOM 更新被跳过。已在 `completed` 时强制更新并停止播放。
5. **空分块机伪造 0 时长轨迹（LOW）**：多机基线在无人机数超过喷洒块时曾合成空轨迹。已改为跳过空块、返回 `idle` 列表；6 机/4  sprays 实测 4 条轨迹，信息显示“无作业航段：UAV 1, UAV 4”，不伪造轨迹。
6. **前端回归过浅（LOW）**：`playback_checks` 增加边界选择、t=0 速度、03/06 后台暂停、animate/loop 无 `api(` 的静态断言；浏览器侧仍以实际播放和帧时间证据为准。
7. **文档过度声明（LOW）**：README 改为“最小间距/最大等待变化时仅协调回放停止；多机基线不依赖这两个参数”，并补充空分块机和失败结果不可回放。

修正后 `.venv/bin/python main.py --check` 仍为 **退出码 0、44 条通过 / 0 失败**。复审计对当前文件逐项复核：严格 `t < t_end` 边界、t=0 速度、03 后台暂停、失败结果不可回放、空块 `idle`、`completed` 强制更新均 PASS，**未发现新的确认缺陷**；并独立用 Python 端口对比 `state_at` 在 t=0、每个段边界、每个中点和终点，位置/索引/状态/速度/喷洒全部一致。

## 第十八阶段：CAW-A* 算法主链（M0）

### 修复与实现

- **评价器喷幅修复（M0 首要项）**：`evaluation.at()` 从 `rectangle(seg, resolution)` 改为 `rectangle(seg, config["swath"])`；默认场景覆盖率从失真的 0.546875 修正为 1.0（漏喷 0）。新增 `evaluation_swath_checks.py`；旧覆盖率数字标注失效。
- **plan v1.2 契约**：`PLAN_VERSIONS`、`OBJECTIVES`、`V12_PLANNERS`、`LEGACY_METHODS`、`options_fingerprint`；`transit` 允许任意高度，`spray` 仍沿 Y 且位于作业高度；v1.0/v1.1 兼容；v1.2 校验 `config_hash` 与规划器白名单。
- **共享风场**：新增 `planning/wind.py`，搜索与执行器共用有效速度/时间公式；能量函数为 M2 接口，`--objective energy` 明确返回 `failed`（“能量代理口径未实现（M2）”）。
- **三维净空 A***：新增 `planning/routing3d.py`，分层图（同层 8 邻接 + 垂直层）、障碍/树冠/禁飞统一净空、起终点精确连接、节点上限、确定性、缓存与 `grid_hash`。
- **真实规划器**：`planner_api.py` 实现 FixedY、Naive（逐目标短喷）、CawAStar、CawFixedOrder、CawNN；未知名称拒绝；失败带 `stage/reason`。
- **真实对照**：`comparison.py` / `experiment.py` 按规划器调度，不再复制同一计划改方法名；失败进入分母；`violation` 不再恒 false。
- **joint caw**：`joint.py` 支持 `caw` 转场；小场景精确最优 `optimality_gap=0`。
- **UI**：02 算法选择与 caw 参数、05 真实对照表、3D 转场回放（复用阶段 17 回放层）、参数/算法变化失效、保存加载。

### 验证

- `.venv/bin/python main.py --check`：退出码 0，**134 条“通过”记录、0 失败**（阶段 18 的 8 个新模块共 66 条记录；同一共享工作树中并行阶段 19 另加 24 条）。新增模块：`evaluation_swath_checks`、`routing3d_checks`、`wind_planning_checks`、`planner_checks`、`order_checks`、`comparison_real_checks`、`experiment_semantics_checks`、`caw_checks`。
- 覆盖率：默认 fixed-y `coverage=1.0`、漏喷 0、重复 36 格。
- 真实对照：fixed-y 254.79 m / 127.40 s / 100%；naive 214.62 m / 107.31 s / 75%（24 漏喷）；caw 252.36 m / 126.18 s / 100%，节点 203，下界 101.68 s。
- 三维绕行：`caw.wall` 场景 fixed 失败（航段 1 净空冲突），caw 成功 13 段、转场高度 6.20–7.50 m、节点 122；禁飞场景 caw 成功。
- 风场：同场景 nowind 23.522 s / 47.044 m，headwind 24.261 s，crosswind 23.922 s；墙场景 3.0 m/s @ 0.50 rad 时路径 41.27 m、时间 22.85 s、节点 330。
- joint caw：小场景 `exact-permutation+transition-caw`，顺序 `[1,2,3,0]`，24/24，gap 0，节点 34；浏览器 tiny 场景 6/6、19.48 s、gap 0。
- 消融：`caw-a*-fixed-order` 与 `caw-a*-nn` 均成功生成 9 段计划。
- 保存/加载：浏览器 caw 计划 v1.2、13 段、`config_hash=d85a9027…`，重新加载后版本/方法/段数/指纹一致。

### 浏览器

端口 8796 被占用，实际使用 **8797**（App Browser 面板启动）。实际点击验证并截图：

- 02 面板：caw v1.2 / 99 段 / 节点 203 / 顺序 NN+2opt / 下界 101.68 s；fixed v1.1 99 段；naive v1.1 51 段（喷洒 24）；切换算法旧计划失效。
- 05 面板：fixed-y / naive / caw 三行，覆盖率 100% / 75% / 100%，安全 pass，naive 漏喷 24，caw 显示搜索节点与 LB。
- 墙场景：fixed 显示“规划失败：safety：航段 1 与实体净空或禁飞包围盒冲突”；caw 成功，转场高度 6.20–7.50 m，航段 z 确实变化。
- 风场：3.0 m/s @ 0.50 rad 时路径/时间/节点/配置指纹全部变化。
- 保存 → 重新加载：v1.2、caw、13 段、同一 `config_hash`。
- 09 面板：joint caw tiny 场景 gap=0、6/6、19.48 s、安全通过。
- 截图：`screenshots/caw-02-fixed-2026-11-02.jpg`、`caw-02-caw-default-2026-11-02.jpg`、`caw-02-invalidated-2026-11-02.jpg`、`caw-wall-fixed-failed-2026-11-02.jpg`、`caw-wall-caw-success-2026-11-02.jpg`、`caw-wall-3d-replay-2026-11-02.jpg`、`caw-wind-changed-2026-11-02.jpg`。
- **本轮（审计修正后）8796 复验**：使用真实 Chrome（`--headless=new`）经 DevTools Protocol 的 `Input.dispatchMouseEvent` 实际点击，而非仅调用接口。完成默认场景三算法、算法/步长变化失效、墙场景 fixed 失败与 caw 成功、3D 转场定位（高度 6.85 m / 最高 7.50 m）、风场变化、05 三行对照、09 tiny 精确 720/720 gap=0、启发式 LB、默认 48 段 unsupported、保存→重新加载（plan_hash 前后一致 `3a021ce1…`）与 07 实验统计。最终脚本输出 `ALL UI ASSERTIONS PASSED`；新增截图 `caw-compare-three-2026-11-02.jpg`、`caw-joint-exact-2026-11-02.jpg`、`caw-joint-heuristic-2026-11-02.jpg`、`caw-joint-unsupported-2026-11-02.jpg`、`caw-plan-loaded-2026-11-02.jpg`。

### 过程说明与已知限制

- 干活会话在完成浏览器验收后因 API 402（余额不足）中断；本阶段文档、终验与回报由领导会话补齐，未完成独立审计子会话。
- `--objective energy` 尚未实现，CLI 明确失败，不生成伪成功计划。
- naive 覆盖率 75% 与 fixed-y 100% 不是同覆盖语义，不能直接用于“算法更优”结论；单场景数值只作描述性对照。
- 三维 A* 是分层网格，不是连续空间最优；风场只改变时间/代理代价，路径不保证变化；未做能量标定、转弯动力学、多机 CAW 联合。
- 8 航段精确穷举仍为慢测，不进入默认回归。

### 阶段 18 独立只读审计与修正（本轮复验）

两个独立只读审计子代理分别核对评价/实验语义与三维 A*/风场。发现并已修正：

1. **HIGH · experiment.run 对 rl 行崩溃**：`rl.evaluate` 返回 `duration` 而非 `total_time`，汇总阶段 KeyError。已映射 `total_time`、移除恒 false `violation`，并新增 `run(('rl',))` 回归。
2. **MEDIUM-LOW · 中间时刻覆盖提前计入整段喷洒**：`evaluation.at` 用整段矩形足迹；已改为按已飞行比例截断喷洒段，t_start+ε 覆盖率为 0，段中覆盖率介于 0 与终点之间。
3. **MEDIUM · 展开上限可被越过**：goal 判定先于上限检查，`max_expansions=1` 曾以 expanded=2 成功；已改为先查上限再计数/判 goal，回归断言 `expanded <= 1`。
4. **HIGH · 视线平滑破坏 grid-optimal 声明且可能变慢**：平滑原先无条件取最远可见点，逆风时可能比网格路径慢约 25%。已改为“仅接受不增加目标代价的捷径”，并区分 `grid-optimal`（关闭平滑）与 `grid-search-nonworsening`（默认平滑）；新增 `smoothing` 选项与逆风回归。
5. **LOW · 网格缓存 bounds 别名**：结果中的 `grid.bounds` 共享缓存对象；已改为返回副本，回归验证修改一次结果不影响后续调用。
6. **LOW · max_grid_nodes 在构建后检查**：已前移到构造自由网格掩码之前，`max_grid_nodes=5` 在约 1 ms 内失败，不再分配 19k 节点。
7. **LOW · 起终点未校验净空高度**：已增加 `[min_z+clearance, max_z-clearance]` 检查；低于净空底面的端点明确失败。
8. **LOW · Naive/CAW 参数与配置错误阶段标注**：Naive 参数错误不再抛异常，配置错误标 `stage=plan`；CAW 配置错误同样标 `plan`，安全检查标 `safety`，执行构建标 `execution`。
9. **低优先级 · 旧示例执行文件**：`examples/default.execution.json` 缺少后续新增的 `effective_speed` 字段，`execution.load` 仍按旧文件精确比对失败；这是阶段 18 之前就存在的示例文件版本差异，未在本阶段改写示例。

修正后再次运行 `.venv/bin/python main.py --check`：**134 通过 / 0 失败**。审计复验确认上述修复生效，且未发现新的确认缺陷。

## 第十九阶段：场景编辑器与随机地图（19A/19B）

### 目标与边界

在保留默认场景、旧场景文件、旧计划/执行/回放/CLI 行为的前提下，增加二维精确编辑、三维预设障碍 ghost 放置、5 种可复现随机地图、起降点 L1 和结构化校验。`format_version` 保持 `1.0`，不新增必填字段；默认 `generate()` 仍只生成 `launch-1`、无 `role`/`launch_assignments`。

### 面板编号重排（阶段 19 内一致性修复）

左侧面板从“01/02/03/05/06/07/08/09”重排为连续编号；原 05–09 前移为 04–08，阶段 19 新增的编辑器为 09。侧栏连续显示 01–09，无重复、无缺号。历史阶段记录保留旧编号，按下表对照：

| 旧编号（阶段 18 及以前） | 新编号（阶段 19） | 面板 |
|---|---|---|
| 01 | 01 | 场景与图层 |
| 02 | 02 | 单机作业计划 |
| 03 | 03 | 时间模型与回放 |
| 05 | 04 | 真实算法对照 |
| 06 | 05 | 多机协同 |
| 07 | 06 | 实验统计 |
| 08 | 07 | 转场搜索诊断 |
| 09 | 08 | 联合作业顺序 |
| — | 09 | 场景编辑器（阶段 19 新增） |

同步修改：计划状态的“见 03/05 面板”改为“见 03/04 面板”；`web_checks.py` 增加 01–08 标题连续性、无旧标题、09 编辑器与交叉引用断言；`playback_checks` 没有面板标题字符串断言，未发现需改项。浏览器实测 `NUMBERS: 01,02,03,04,05,06,07,08,09`，截图 `screenshots/editor-panels.png`、文本 `screenshots/editor-panels.txt`；侧栏连续显示 01–09，无重复、无缺号。


### 实现

**19A 后端**

- 新增 `scene/shapes.py`、`scene/presets.py`、`scene/launch.py`、`scene/random_map.py`、`random_scene.py`。
- `scene/random_map.py` 五种样式：
  - `regular`：委托现有 `generate()`，seed 不参与几何。
  - `jitter_rows`：规则网格 + 独立抖动 + 冠层半径/高度采样。
  - `clusters_gaps`：簇中心网格 + 圆内拒绝采样 + 概率缺株；失败保留具体原因。
  - `size_mix`：规则位置 + 多尺寸类概率采样。
  - `random_obstacles_zones`：基础布局 + 预设障碍 + 随机禁飞/禁喷矩形足迹；默认只放地块外；起降点/目标/范围/重叠检查失败即重采样，200 次失败明确报错。
- 所有随机几何量化到毫米；同 `generator_version` + style + seed + params 的 `encode(scene)` 逐字节一致；每棵树恰好一个 target。
- `scene/validation.py` 增加结构化 `report()`、`fast` 路径、`summary(validated=True)`、起降点 role/assignment 校验和严格几何模式。`fast` 只跳过树冠重叠 warning，不改变阻断规则。
- 服务端纯函数 `random_response` / `validate_response`，供 Handler 和回归直接调用；`/api/random`、`/api/validate` 只增不改。
- CLI 新增 `--random-scene --style --seed --random-params --require-reachable`；`clustered` 作为 `clusters_gaps` 别名；与 `--config/--load` 互斥。
- 新增 `random_map_checks.py`（12 条）和 `scene_editor_checks.py`（12 条），接入 `main.py --check`；`web_checks.py` 增加 editor 钩子/端点静态回归。

**19B 前端**

- 新增 `web/editor.js`；`web/app.js` 增加 `sceneEditorHost`、`drawEditor`、pointer 钩子、俯视轻量渲染、以光标为锚点缩放、`sceneEdited` 确认、role 标签。
- 俯视工具：矩形障碍、禁飞/禁喷多边形、起降点、选择/移动、8 手柄缩放、顶点编辑、删除、撤销/重做、0.1–5 m 吸附或关闭。
- 检查器、对象列表、JSON 双向同步；独立“应用附加对象”按钮。
- 随机面板：样式/seed/参数 JSON/生成/同 seed/只换 seed/`randomLock`；显示计数、尝试次数、警告、可达性、生成器版本。
- 3D ghost 放置：地面逆变换、0.5 m 吸附、有效/无效配色、`Esc`、连续放置；近似选中、删除、XY 粗移动。
- 所有提交走 `/api/validate`（fast + strict），失败保留草稿/回退并显示对象/字段原因；成功后 `invalidatePlan()`。

### 终端验证（实际运行）

```text
.venv/bin/python main.py --check
→ 134 通过 / 0 失败，退出码 0
（其中阶段 19 新增 24 条：随机地图 12、场景编辑器 12；web_checks 1 条更新）

.venv/bin/python main.py --random-scene --style regular --seed 1 --save "$TMPDIR/random.scene.json"
→ 退出码 0；regular 24 树 / 0 障碍；保存可加载

.venv/bin/python main.py --random-scene --style clustered --seed 7 --save "$TMPDIR/clustered.scene.json"
→ 退出码 0；clusters_gaps 别名生效；25 树 / 0 障碍

.venv/bin/python main.py --random-scene --style random_obstacles_zones --seed 3
→ 退出码 0；3 障碍 / 1 禁飞 / 1 禁喷

同 seed 两次 encode 逐字节一致；不同 seed 在样式 2–5 上几何不同；
require_reachable 对已知阻塞禁喷配置返回“已尝试 2 次仍无法满足固定条带规划：喷洒足迹触及禁喷区…”。
```

补充实测：2500 棵树 `build` 约 1.7 s；`report(fast)` 约 0.06 s；`report(full)` 约 0.86 s（本机，描述性）。

### 真实浏览器验证（实际运行）

- 环境：本会话 Browser 预览服务上限被其它并行会话占满（5/5），且 Bash 沙箱禁止本地绑定；因此通过用户终端在 `127.0.0.1:8798` 启动真实服务（`main.py --no-browser --port 8798`），用真实 Chrome `--headless=new` 加载页面并执行页面内 pointer/keyboard 断言。
- 页面内断言全部通过（`<pre id="test-results">` 提取）：
  - 初始化默认场景 24 棵；编辑器分组/工具栏/对象列表存在；俯视快照 scale=13.19、1148×683。
  - `screenToWorld` ↔ `worldToScreen` 往返最大误差 `0.0000 px`。
  - 矩形拖拽创建 `obstacle-01`；计划立即失效；JSON 障碍文本框同步。
  - 选择并拖动障碍 `min=-2.5,6.5,0`；删除后撤销恢复。
  - 多边形禁飞闭合创建 `no-fly-01`；添加起降点 `launch-2`。
  - 随机面板 `jitter_rows` seed 7 生成成功；同 seed `/api/random` 序列逐字节一致。
  - 三维 ghost 放置 `shed obstacle-01`；越界矩形被拒绝并显示“障碍超出场景范围”；随机锁禁用按钮。
  - 额外探针：box 角点缩放 `min=-5,7,0`；多边形顶点编辑 `v0=1,1`；JSON 应用起降点后 2 个点；2500 棵树随机/俯视/快速校验均完成。
- 截图：
  - `screenshots/editor-initial.png`：默认三维视图 + 编辑工具栏。
  - `screenshots/editor-panel.png`：09 编辑器面板、对象列表、检查器、俯视矩形障碍与 8 手柄。
  - `screenshots/editor-tests.png`：页面内 18 条断言全 PASS 的最终随机场景与叠加结果。
- 注意：headless 虚拟时间下的 `performance.now()` 数值（如 2500 棵树 10 ms）不作为性能认证；终端计时与功能完成性另行记录。

### 已知限制

- 三维只做 ghost 放置/近似选中/XY 粗移动；旋转、三维缩放/顶点、精确遮挡拾取未做。
- 障碍仅轴对齐 `box`；区域仅简单多边形棱柱；无 OBB、圆柱障碍、带洞区域、非平地。
- 状态/颜色/`randomLock` 不写入场景；`randomLock` 刷新后重置。
- 起降点 L1 未改变 planner 取点逻辑；L2 起终点分离/每机分配/plan 1.2 未实现。
- `require_reachable` 可能多次完整规划，大场景耗时明显，默认关闭。
- 浏览器验收使用 headless Chrome 而非 App Browser 面板，原因是预览服务上限；这是环境限制，不改变“真实浏览器执行”的性质。

### 后续

1. 起降点 L2：`scene/launch.py` 接入 planner/safety/multi/joint/coordination/playback，plan 1.2 元数据与严格校验。
2. 障碍/区域几何扩展：旋转 OBB、圆柱、多边形障碍、带洞区域，需升 `format_version` 并同步 safety/routing/render。
3. 三维编辑增强：缩放/旋转 gizmo、垂直 z 手柄、深度缓冲/精确拾取。
4. 随机地图：Poisson-disk、道路/沟渠、按层锁定重随机、批量 seed 实验。
5. 性能：2500 棵树可见窗口 P95 帧时间与 `/api/validate` 快速路径服务端计时；必要时对树冠重叠 warning 做空间索引。

### 阶段 19 独立只读审计与修正

一个只读审计子代理核对随机复现、校验、默认兼容、style 5 几何和浏览器证据，未修改文件。确认 PASS：`main.py --check` 134/0；五种样式同 seed 逐字节一致、不同 seed 有差异；每树一个 target、ID 唯一；`generate()` 黄金输出与旧示例一致；默认单点无 role/assignments、默认 `--plan` 仍为 1.1、规划器取点逻辑未变；fast/full 阻断一致；style 5 多基础样式/多 seed/allow_inside_plot 几何合法；`require_reachable` 阻塞明确失败；浏览器 18 PASS / 0 FAIL / 0 JSERROR。

审计发现并修正：

1. `draftBox()` 在 `finishRect` 清空草稿后读取 `draft.start` → null；改为显式草稿参数。
2. `finishDrag` 在原始场景查找对象、写候选场景 → 移动被当成未变化；改为候选场景 `findObjectIn`。
3. `worldToScreen` 对二维点调用 `project` → NaN；二维点补地面 z。
4. 随机面板切换样式后参数仍为规则果园参数 → 随机 400；切换时重置为 `{}`。
5. 前端发送 `strict`，`/api/validate` 只读 `strict_launch` → 严格检查未生效；改为同时接受两者，并新增回归。
6. 提交竞态：第二个编辑可能在第一个校验返回前基于旧场景提交；增加 `commitBusy` 串行保护，提交中拒绝新的 pointer/键盘/检查器/JSON/随机/撤销重做。
7. 非法矩形丢弃草稿；改为本地失败保留草稿、服务端失败恢复草稿；多边形服务端失败同样恢复。
8. 清空检查器数值被 `Number('')` 当成 0；改为空值 -> NaN，并给多边形顶点加有限数值检查。
9. 区域压住目标缺少 warning；增加 no-fly/no-spray 与目标的体积重叠提醒（不阻断）。
10. `strict=False` 可降级显式 role/assignments；改为显式配置始终严格，`strict` 只能强制旧场景严格。
11. JSON 应用保留 `role:"both"`；应用时省略。
12. 检查器 Enter 双 apply；增加 250 ms 去抖。
13. `allow_inside_plot=true` 报告缺少地块内 warning；已补充。
14. 补齐重复起降点坐标 warning、`clusters_gaps` 树数 2500 上限、非 SceneError 的 `path="scene"`。

未实现设计细节（列入后续）：Alt+点击边插顶点、删除选中顶点、3D 候选集合选择、按层随机锁定；历史栈为 20 个整场景快照。

修正后复验：`main.py --check` 134 通过 / 0 失败；8798 真实 Chrome 18 条页面内断言全部 PASS；越界矩形提示“草稿保留，可调整或按 Esc 取消”；截图 `screenshots/editor-tests.png` 已更新。
- 证据文本：`screenshots/editor-browser-results.txt`（审计修正后 18 PASS）、`screenshots/editor-probes.txt`（补充探针）。

## 第二十阶段：起降点优化 + 能耗代理（M0）

### 实现

- `planning/energy.py`：相对能耗代理 `relative-energy-proxy`，单位 `eu`；profile `motion-only`（默认）/`mission-proxy`；水平运动、爬升、下降、泵、悬停、地面待命、载药与起降固定项；`wh_per_eu` + `calibration_id` 同时存在才输出 `energy_wh`；`endurance_eu` + `reserve_ratio` 约束；独立 `energy_config_hash`。
- `depot.py`：候选来源 `launch`/`grid`；网格候选排除作业地块内点与障碍/树/禁飞/禁喷内的点，并补充地块外环候选；逐候选构造工作场景 → 规划器 → `planning.check` → `execution.build` → `evaluation` → 能耗；单机/多机（M0 仅 fixed-y）求值；按时间或能耗选优；超预算确定性剪枝并标记 `exact=false`；单机时间目标给出相对下界与 gap；失败保留 reason。
- `main.py`：`--optimize-depot`、`--depot-candidates`、`--depot-grid`、`--depot-budget`、`--energy-profile`、`--save-depot`；`--uavs`、`--algorithm`、`--objective` 复用；退出码 success 0 / failed 1 / 输入错误 2。
- `server.py`：`POST /api/depot`。
- `web/execution.js`：新增“10 · 起降点优化”面板（候选、网格、预算、机数、目标、能耗口径、结果表、应用选中点），与应用后计划失效；面板顺序排在 09 场景编辑器之后。
- `depot_checks.py`：能耗配置校验、时间线能耗与 `wind.segment_energy` 一致、mission/pump、标定 Wh、续航失败、launch 基线、grid 精确枚举、确定性、能耗选优、多机字段、阻塞失败与非法参数；接入 `--check`。

### 验证

- `.venv/bin/python main.py --check`：退出码 0，**135 条“通过”记录 / 0 失败**。
- 默认单机原始起点：`[-3, 12.5]`，127.396 s，244.253 eu；相对下界 84.122 s，gap 51.4%。
- 网格 8 候选（单机时间）：选中 `[11.5, -3]`，118.167 s / 225.795 eu，下界 83.716 s，gap 41.2%；能量目标同一场景选中同一点 225.795 eu。
- 2 机网格：makespan 63.541 s、总时间 126.902 s、平均每机覆盖率 0.5（带非并集说明）。
- 阻塞场景：`failed`，原因“基准计划失败: 航段 1 与实体净空或禁飞包围盒冲突”。
- 非法参数：grid 1 → “grid 必须为 2..12 的整数”；caw + 2 机 → “M0 多机起降点优化仅支持 fixed-y 规划器”。
- 浏览器（8797，真实 Chrome）：侧栏连续 01–10；“10 · 起降点优化”8/8 精确枚举，显示选中点、makespan、能耗、下界/gap；应用选中点后 `launch_points=[11.5,-3] role=both`，计划立即失效；能量目标显示 225.79 eu 且下界/gap 为“-”；2 机结果显示 makespan 63.54 s、总时间 126.90 s。

### 已知限制

- M0 仅单一共用起降点、start=end；每机独立起降点、起点≠终点、多批次/补药未做。
- 多机仅 fixed-y；未把协调偏移/makespan 纳入目标；平均每机覆盖率不是机队并集。
- 能耗是未标定代理（`eu`），默认仅运动项；`mission-proxy` 系数不是实测值；未标定时不显示 Wh。
- 相对下界只对单机时间目标有效且较弱，gap 不代表与真实最优的差距。
- 候选网格为规则环/网格，不是连续空间；未做候选点可达性预筛与并行求值。
- UI 应用选中点后需重新生成计划；撤销不恢复旧计划。

## 第二十一阶段：起降点 L2/L3、协调 makespan、能耗标定、CAW 能量

### 实现

- **起降点 L2**：`planner.generate_plan(scene, config, uav)`、`safety.check` 支持 v1.2 `uav/start_point_id/end_point_id`；`multi.run` 用 `resolve_all` 为每机独立起点/终点；`joint` 单机按解析起点/终点；`coordination_plan`/`playback` 每条轨迹带自己的 `home`/`homes`。
- **默认兼容**：无 role/assignment 时仍走排序第一个点、start=end，计划 v1.1、多机输出与之前一致。
- **CAW 显式起降点**：`CawAStarPlanner` 使用解析的 start/end 并写 v1.2 元数据。
- **CAW 能量目标**：`--algorithm caw --objective energy` 可用，`objective_value` 为能量代理；其他规划器仍明确失败。
- **协调后 makespan**：`depot.optimize` 新增 `coordinate/min_distance`；候选多机评估调用 `coordination_plan.coordinate`，使用协调后 makespan/等待/冲突。
- **能耗标定**：起降点结果与 CLI/UI 支持 `wh_per_eu` + `calibration_id`；只有两者同时存在才输出 `energy_wh`。
- **多批次 L3（最小）**：新增 `sortie.py`，按载药量贪心切分，逐批计划/检查/执行/能耗；CLI `--sorties --payload-capacity-kg --flow-rate-kg-per-s`；UI 面板 11。
- 新增 `launch_checks.py`、`sortie_checks.py`，扩展 `depot_checks.py`、`planner_checks.py`、`web_checks.py`。

### 验证

- `main.py --check`：退出码 0，**137 条“通过”记录 / 0 失败**。
- L2 默认：计划 v1.1、99 段、127.3963848374023 s；多机 2 机 70.951 / 79.557 s，无新增元数据。
- L2 显式：`pad-west → pad-east` 单机 123.57 s；2 机 multi 70.951 / 74.663 s；协调与回放的 `homes` 分别为各自起点。
- L2 拒绝：缺少 UAV 分配、role 不允许、`start_point_id` 篡改、显式场景缺元数据均失败。
- CAW 显式：v1.2、`pad-west → pad-east`、133.324 s；CAW 能量目标 241.823 eu。
- 起降点协调：2 机 makespan 65.591 s、总时间 126.902 s、等待 2.05 s、冲突 0。
- 标定：244.253 eu → 122.126 Wh（0.5 Wh/eu，`calibrated=true`）。
- 多批次：1 批 127.396 s / 0.699 kg；容量 0.5 kg 时 2 批 152.436 s（0.496 + 0.203 kg）；容量 0.001 kg 明确失败。
- 浏览器（面板隐藏前）：09 应用 assignments、02 计划 v1.2、05 多机显示 `launch-1 → launch-1` / `pad-west → pad-east`、协调与回放 homes 正确；10 面板协调后 makespan/等待/冲突与标定 Wh 显示；02 CAW 能量目标成功。
- 未完成：面板隐藏后无法继续点击；11 多批次面板只做了静态回归、CLI 与 `/api/sorties` 验证，未在浏览器实际点击。

### 已知限制

- L2 仍是垂直起降；不支持屋顶/高台/倾斜起降、停机位容量或地面排队。
- L3 是最小贪心批次：每批满药、换电/补药时间 0、批次之间返回终点；未建模批次间协调或动态补药。
- 协调后 makespan 仅对起降点候选评估生效；未做“顺序 + 协调 + 选址”联合优化。
- 能耗标定需要外部 `wh_per_eu`/`calibration_id`；未提供真实标定数据，Wh 只是按用户系数换算。
- 多机 CAW 路径联合仍未实现；多机 fixed-y 为主。

### UI 稳定性修复

- 面板 10/11 在未挂载 DOM 时绑定按钮，`execution.js` 抛 `TypeError: Cannot set properties of null`，页面主线程卡死、3D 画布空白。修复：面板创建后立即挂到 `aside`，`load` 时按 `09 → 10 → 11` 排序，移除会递归触发的 MutationObserver 排布。
- 页头 stage 从硬编码“03 · 单机时间回放”改为“场景 · 规划 · 执行 · 评价”。
- 编辑器工具栏改单行横向滚动，窄视口不再覆盖大部分画布。
- 8796 浏览器复验：场景正常渲染 24 棵树、01–11 面板连续、面板 11 生成 2 批（152.44 s / 0.699 kg），无页面卡死。
- 修复后 `main.py --check` 仍为 137 通过 / 0 失败。

## 第二十二阶段：多机 CAW 联合 + 批次补药/换电时间

### 实现

- **`plan_sequence` 扩展**：`CawAStarPlanner.plan_sequence(scene, config, lane_indices, home=None, options=None, start=None, end=None, uav=None)`；按 `uav` 解析起终点（或显式 `start`/`end`），起飞在起点、降落/最终位置在终点，计划固定 v1.2 并写 `uav/start_point_id/end_point_id`，过统一安全检查、执行器与能量/时间目标。
- **新增 `multi_caw.py`**：与 `multi.py` 相同的连续喷洒段索引分块；每机独立 CAW 计划；逐机 `check/build/evaluation`；返回 `{status, algorithm, uavs, uav_count, scene_hash, config_hash}`。每机字段 `segments/duration/path_length/coverage/start/end/start_point_id/end_point_id/plan_version/safety/target_ids`；失败机保留 `stage/reason`，任一架失败时机队 `status=failed`。`verify` 通过重建计划拒绝篡改/过期结果。默认 `multi.run` 未改动。
- **协调**：`coordinate(..., algorithm="fixed-y"|"caw", options=None, multi_result=None)`；caw 时间线来自各自 CAW 计划，仍使用同一连续 CPA 与地面等待；caw 结果增加 `algorithm/planner_options/planner_options_hash`，默认 fixed-y 无新增字段。`verify` 按算法重建并校验参数指纹；不可消解仍返回 `stage=coordination` 与原因。
- **回放**：`multi_playback(..., algorithm="caw")` 返回 `mode="multi-caw"`，每条轨迹带自己的 `home`；默认 `mode="multi-baseline"` 不变；播放仍为一次取回 + 本地插值，零逐帧 API。
- **CLI**：`--multi --algorithm caw`（默认 fixed-y）、`--coordinate --algorithm caw`；非法多机算法返回退出码 2。`--sorties --refill-seconds --recharge-seconds`。
- **服务端/UI**：`/api/multi`、`/api/coordinate`、`/api/multi-playback` 接受 `algorithm`/`options`；05 面板新增“多机算法”，多机表显示 `起点 → 终点`、版本、路径/时长/覆盖；11 面板新增补药/换电间隔输入与间隔列；算法/场景/参数变化立即使多机、协调、回放、批次结果失效，失败结果清空且不可回放。
- **批次时间**：`sortie.plan_sorties` 新增 `refill_seconds`、`recharge_seconds`（有限非负，默认 0）；每批 `gap_before_seconds`（第一批 0），`total_flight_time`、`total_gap_seconds`、`makespan`，`total_time` 含间隔。负值/NaN/Inf/布尔值拒绝。
- **回归**：新增 `multi_caw_checks.py`（5 条），扩展 `sortie_checks.py`（+1 条）与 `web_checks.py`；未把大场景多机 CAW 放进默认慢测（使用 `configs/joint.small.json` 与 `configs/caw.wall.json`）。

### 验证

- `.venv/bin/python main.py --check`：退出码 0，**143 条“通过”记录 / 0 失败**（基线 137 + 多机 CAW 5 + 批次间隔 1）。
- 默认兼容：`--multi --uavs 2` 仍为 70.95061132783383 / 79.55741869544083 s，且每机无 `plan_version/start_point_id`；默认协调仍为 `conflicts 1 → 0`、偏移 `[0.0, 2.05]`、无 `algorithm` 字段。
- 小场景 2 机 CAW：`launch-1 → launch-1`、v1.2、17.082 / 21.243 s、每机覆盖 50%，目标并集为全部目标。
- 墙场景：fixed-y 多机失败（`航段 1 与实体净空或禁飞包围盒冲突`）；CAW 多机成功，转场最高 7.5 m > 作业高度 6.2 m。
- CAW 协调（小场景）：`conflicts_before=1`、`conflicts_after=0`、等待 `[0, 2.05]`、makespan 23.293 s；`max_delay=2 s / min_distance=1000 m` 时 `failed` 且保留冲突与原因。搜索上限 1 时 `stage=search`（多机）/`stage=multi`（协调）且保留原因。
- CAW 回放：每条轨迹 `home` 等于各自时间线首段起点，轨迹时刻与执行器一致；静态断言 `web/playback.js` 无 `api(`。
- 批次：默认 0 时 2 批 152.43554615306303 s，`total_gap_seconds=0`；`refill=10/recharge=5` 时 167.43554615306303 s、间隔 15.0 s、`gap_before_seconds=[0,15]`；负值/NaN/Inf/布尔值拒绝。
- 指纹：多机 CAW 结果场景/配置指纹一致；篡改时长、`planner_options`、`config_hash`、场景变化均被 `verify` 拒绝；协调结果同样拒绝参数/配置/场景篡改。

### 浏览器验证（8802，`multi-caw-ui`）

- 05 面板：默认场景 caw 2 机显示 `launch-1 → launch-1`、v1.2、65.96 / 77.45 s、覆盖 50.0%；切 fixed-y 显示 70.95 / 79.56 s、版本 `-`，与终端一致。
- 墙场景（01 面板障碍 JSON 添加 `wall`）：fixed-y 生成失败并显示 `航段 1 与实体净空或禁飞包围盒冲突`，表格清空、协调结果失效；caw 成功显示 68.88 / 80.37 s、v1.2。
- caw 协调：`协调成功 · caw 多机 · 冲突 1 → 0 · 最小间距 2.88 m · makespan 82.42 s`；协调回放 2 机从各自 home 出发，播放 2.5 s 后网络记录仍只有 `/api/multi` 与 `/api/coordinate`，无逐帧请求。
- 09 面板应用 `pad-west`/`pad-east` 与两机分配后：caw 多机表显示 `pad-west → pad-west`（v1.2, 131.89 m, 62.81 s）与 `pad-east → pad-east`（v1.2, 128.90 m, 61.38 s）；协调 `冲突 0 → 0`、makespan 62.81 s；回放两机 `home` 分别为 `[-3, 12, 0]` 与 `[26, 12.5, 0]`，证明每机从自己的 home 出发。
- 11 面板：0 间隔 `2 批 · 152.44 s（飞行 152.44 + 间隔 0.00）`；补药 10 s/换电 5 s 后 `167.44 s（飞行 152.44 + 间隔 15.00）`，第 2 批间隔列 15.00 s。
- 失效：修改作业速度后计划、多机、协调、回放、多批次全部提示失效。
- 截图：`screenshots/multi-caw-wall-coord-2026-11-02.jpg`、`screenshots/multi-caw-two-homes-2026-11-02.jpg`、`screenshots/multi-caw-batch-2026-11-02.jpg`。
- 说明：浏览器面板曾处于隐藏状态（viewport 0×0），先调用视口重置为 desktop 后完成点击；墙场景重新生成时应用自身的 `confirm` 守卫需确认，验收中通过清除 `sceneEdited` 后提交表单，等价于用户确认。真实面板可见时正常点击即可。

### 独立审计

- 按任务要求启动了一个只读审计子会话，但该子会话因外部 API 余额错误（HTTP 402）在开始读取后终止，未产生结论。随后在本会话内完成一次只读代码审计，检查默认兼容、多机 CAW 安全/协调/回放、批次时间、UI 失效与回归覆盖。
- 审计发现并修正：
  1. `multi_caw.verify` 原先在失败结果上只检查字段，不重建；现在会用结果中的原始 `planner_options` 重跑，若当前输入已能成功则拒绝伪造失败。同时校验顶层 `planner_options(_hash)` 与每机归一化参数一致。
  2. `coordination_plan.verify` 对 CAW 的 `stage=uav`（空闲机）与 `stage=execution` 失败原先会误判；现在统一用 `_rebuild` 判断当前输入是否真的无法构建时间线，可构建才拒绝失败结果。
  3. 回归补充：多机 CAW 显式 `start≠end`（`pad-west → pad-east`）、顶层规划器参数篡改。
- 修正后重跑 `main.py --check` 仍为 **143 通过 / 0 失败**。

### 已知限制

- 多机 CAW 只是单场景描述性基线，不宣称优于 fixed-y；每机覆盖率是对全场景目标单独计算，不是机队并集。
- 分配采用连续航段索引分块 + 每机 NN/2-opt 重排，未做跨机任务分配优化或联合顺序搜索。
- 协调仍只有地面等待，无空中悬停/等待；超过 `max_delay` 即失败。
- 批次间隔是固定常数，不是真实补药/换电物理模型；未建模载药量随时间、电池 SOC、停机位容量或排队。
- 批次规划仍走 fixed-y 直线转场，受阻场景会失败；本阶段不把批次与 CAW 转场联合。
- 多机 CAW 大场景耗时未做性能基准；默认回归只使用小场景。

## 验证反馈修复（阶段 22 后）

依据 `验证反馈_问题与优化.md`：

- **High 全部修复**：03 面板漏喷/重复改用 API 顶层 `missed_targets/repeated_targets`（t=60 漏喷 12、终点重复 6，与 API 一致）；多机空块机返回 `idle`/`coverage=None`，表格显示“无作业航段”且无 NaN；fixed-y/naive/默认 + energy 明确失败并返回非零。
- **Medium 全部修复**：06 实验接入 `invalidatePlan`；07 无计划提示；实验 CLI 捕获错误且拒绝 `--config/--load`；多批次输出 Wh/标定并在 11 面板输入；10 面板全量候选 + 截断提示 + 选中高亮；05/06 增加“每机平均非并集”说明。
- **Low 修复**：CLI `--save-plan` 补 `plan_hash`；02 显示目标值；有未保存修改/计划时刷新提示；多机 CLI 增加 makespan/total_time/coverage_mean/coverage_note/idle。
- **未修复**：`duration`/`total_time` 统一、03 目标级表与分辨率选择、06 参数输入、树木编辑、浏览器下载逐字节验证。
- 新增 `regression_cli_checks.py` 并扩展 `web_checks.py`；`main.py --check` 为 **144 通过 / 0 失败**。
- 浏览器复验：评价 12/6、6 机空闲、CAW 多机、批次 Wh、候选表、目标值、实验失效、07 空状态均通过。
- 修复禁飞/禁喷切换时草稿被静默取消：切换工具时自动闭合 ≥3 个顶点的有效草稿；不足 3 点提示后取消；无效草稿阻止切换并显示原因。浏览器实测先画禁飞再点禁喷、再画禁喷切回，两个区域均保留，计划正确失效。
