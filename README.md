# 果园场景实验台 · 第一阶段

本工程位于参考工程旁的独立目录 `从0开始写代码/`。实现规则果园生成、统一实际几何、校验、JSON 保存加载、三维/俯视与基础交互。所有示例尺寸是数值实验默认值，**不是实测农艺参数**。

现已实现单机基础几何作业计划；未实现无人机运动、喷洒仿真、覆盖统计、多机协同、研究指标、随机地图、图片导入或复杂地形。页面中没有这些功能的空壳或虚构结果。

## 论文 A 小试：对照基线说明

本仓库 `scripts/a_trial_extra_runs.py` 中的 **B-online** / **B-boundary** 是对照实验用的**简化几何代理，不是原方法复现**。

- **B-online**：参照 Scagnellato 2022（ICAS；葡萄园在线横移 + 开关时机）的几何代理：固定航向 0°，整组条带上风平移 Δ=c·U_⊥，c∈{0.25,0.5} s 为**未标定假设**；不做阀门延迟 τ 补偿。A-trial 为纯侧风时 U_∥=0，纵向开关窗平移项为 0。
- **B-boundary**：参照张昆 2022（《农机化研究》；**本工作只读到摘要**）的几何代理：条带边缘对齐**地块/禁喷区固定边界**（非风致缓冲 F），航向取 {0°,90°}。

结果与配对差值见 `RESULTS_overnight.md` 第 1b 节；完整数字与脚本/CSV/commit 引用见 `results/a_trial_1b_*.report.md`。

## 启动

实际运行环境：macOS、Python **3.9.6**，Python 标准库＋浏览器原生 Canvas；无运行期第三方依赖，无 CDN、npm 或联网资源需求。Python 3.9 及以上可运行，现代 Safari/Chrome/Edge 浏览器可显示。

在 VS Code **打开本目录**（有 `main.py` 的内层目录），选择解释器：

```text
.venv/bin/python
```

打开根目录 `main.py`，点击“运行 Python 文件”；自动启动单个本地服务并打开系统默认浏览器。终端 Ctrl+C 停止。默认由系统分配空闲端口，避免占用冲突。资源路径由 `main.py` / `server.py` 所在目录解析，不受 VS Code 当前工作目录影响。

从本工程根目录运行的准确命令（虚拟环境已就绪时；任意工作目录下用对应绝对路径同样可运行）：

```bash
.venv/bin/python main.py
```

以下简写命令在本工程根目录运行：

```bash
.venv/bin/python main.py --check
.venv/bin/python main.py --no-browser --port 8765
.venv/bin/python main.py --config configs/default.json --save examples/my.scene.json
.venv/bin/python main.py --load examples/with_objects.scene.json --summary
.venv/bin/python main.py --load examples/independent_edit.scene.json --preview
```

`--check` 不打开窗口/浏览器，失败返回非零退出码。`--config` 输入生成参数；`--load` 输入已物化的场景，二者不要同时使用。`--preview` 打开所指定场景的交互预览；单独运行 `main.py` 打开默认场景。相对配置、场景和输出文件路径都相对**项目根目录**，绝对路径也可用。终端参数错误、文件读写错误会返回失败。

全新环境可先运行 `python3 -m venv .venv`。本次仅为整理源码在虚拟环境中安装了 Black 与 jsbeautifier，它们不是运行依赖。

## 使用

- 左侧改行数、每行棵数、行株距、树冠半径/高度；展开高级参数修改树干、边缘留白、外围预留、地面高度。点击“生成场景”才替换当前场景。
- 编辑后显示黄色待生成提示，画面仍对应上一次成功结果。生成/加载失败保留原画面，并显示失败原因，不宣称生成成功。
- “三维”和“俯视”切换正交投影角度；三维左键拖动旋转，滚轮缩放，右键/Shift 拖动平移，也可按“平移”后用左键拖动。俯视固定垂直角度，可缩放平移。“重置视角”恢复合理取景并退出平移工具。
- 左侧图层开关控制树干、树冠、边界、地面网格、范围地面投影、目标轮廓、起降点、障碍与区域、方向标识；透明度滑块仅影响显示。窄窗口/较低窗口中左栏可独立滚动查看其余控件。
- “保存场景”下载**当前画面实际数据**为 JSON，文件去向由浏览器下载设置决定；未点击生成的输入参数不会混入保存结果。
- “加载场景”选择 JSON 文件。加载不调用生成器，不按来源参数重建树木；独立修改的位置、尺寸、对象顺序和目标几何均保留。加载后输入框展示的是**生成来源参数**，不保证与已修改的实际几何相符；界面会提示，再按生成将替换载入几何。“恢复默认”恢复默认 24 棵场景。
- 附加对象可在展开的 JSON 框中配置。参考 `configs/with_objects.json`：障碍为 `box`；禁飞/禁喷为 `polygon_prism`。区域第一份示例使用矩形多边形，可加载其他简单多边形。均以闭合边界所围成的三维体积解释，不用无限高区域代替实体数据。

## 文件职责

```text
main.py                   统一 UI / 终端工具入口
server.py                 仅监听 127.0.0.1 的 HTTP 适配器
scene/schema.py           格式版本、配置默认值、JSON 数据别名与基础校验
scene/config.py           生成参数归一与校验
scene/generator.py        确定性规则果园生成，不启动服务或窗口
scene/validation.py       实际场景校验与摘要，不假设规则排列
scene/geometry.py         平地高度查询、多边形几何判定
scene/storage.py          版本化 JSON 编解码、文件保存加载
web/index.html            控件与页面结构
web/style.css             显示样式
web/app.js                独立显示状态、正交相机、几何网格和交互
checks.py                 有意义的数据/几何行为检查
configs/                  默认及附加对象生成配置
examples/                 默认、附加对象、独立修改的实际场景
references/               概念参考图（非运行结果）
screenshots/              真实运行截图
STAGE_LOG.md              验证记录与下一轮接手说明
```

## 数据约定 · format_version 1.0

场景为 UTF-8 JSON。配置是生成输入，场景是**实际几何数据**；来源参数只作溯源。公共接口采用普通 JSON 字典并标注类型/单位，保持文件可检查，不依赖前端对象、规划算法或体素栅格。

- `coordinates`：局部米制、右手系，固定原点 `[0,0,0]`。X 跨行、Y 沿行、Z 竖直向上；这是生成坐标方向，不表示地理经纬度。所有长度、半径、高度与坐标单位为 m。
- `terrain`：`{"kind":"flat","height":0}`。后端统一调用 `terrain_height(scene, x, y)` 得到地面绝对 Z，第一版返回常数。显示层目前只渲染平面。后续坡地须同时扩展地形数据、查询、校验与显示，当前不伪称支持。
- `plot`：`{"kind":"polygon","vertices":[[x,y],...]}`，简单多边形，无洞，不重复首点，最后一边自动闭合。顺/逆时针均可。默认矩形 `[0,23]×[0,25]`。摘要 `plot_size` 表示多边形 XY **包围盒**尺寸，非面积。
- `extent`：`min/max` 三维盒，整体允许表达范围。默认 `[-6,-6,0]` 到 `[29,31,12]`。范围外对象会报错。地块和范围之间预留转场/起降表达空间，**地块边界不自动成为禁飞区**；范围也不等于已经完成的航空许可或航行规则。
- `trees`：每棵独立 `id`、`position:[x,y,z]`、`trunk`、`canopy`。树干/树冠当前均为直立圆柱 `kind/center:[x,y]/radius/z_min/z_max`。位置为树干地面中心，树干与树冠同轴且上下衔接；保存后不推断行号、顺序或共同尺寸。绘图用 32 段圆周近似圆柱，计算几何仍为精确半径圆柱，前端不会回写近似网格。
- `targets`：每树一个独立目标对象，有独立 `id`、`tree_id`、`geometry` 和语义说明。生成时目标是树冠体积的深拷贝；之后目标和树冠不通过同一引用联动，不隐含飞机航高或路径。
- `launch_points`：至少一个独立 ID 与地面位置，当前建模规则要求在地块外、范围内，且不得进入实体障碍或禁飞体积。默认 `[-3,12.5,0]`；不会为通过校验而偷偷移动。
- `obstacles`：ID、`kind:"box"`、`min:[x,y,z]`、`max:[x,y,z]`，当前仅轴对齐盒。
- `no_fly_zones` / `no_spray_zones`：ID、`kind:"polygon_prism"`、`footprint`（同地块的多边形结构）、`z_min` / `z_max`，支持非矩形简单多边形。禁喷允许与目标体积重叠；固定条带规划按其 XY 包围盒切割航带——区内关喷头、同高度飞越（禁喷 ≠ 禁飞），区外目标仍须完成喷洒，完全落入区内的目标按任务不完整处理。
- `source`：`kind` 与 `parameters`。规则生成器记录全部有效参数；修改已保存几何不要求重写历史来源。显示和加载不得据此重新生成。

默认：4 行×6 棵，X 行距 6 m、Y 株距 4 m、树冠半径 1.5 m、高 2.4 m，树干半径 0.15 m、高 1.8 m；地面 0 m。`plot_margin=2.5 m` 为最外树心到对应地块边的距离，并非树冠外缘余量；`reserve=6 m` 为地块四周到整体范围的水平余量。范围高度由生成器至少留出 12 m，并高于树冠顶部 3 m。

校验拒绝非有限/非法尺寸、重复 ID、无效引用、缺字段、未知版本、自交/退化多边形、越界实体、树冠越出地块、起降点进入障碍/禁飞区等。树冠相互重叠仅提醒，不统一判错。实体障碍和树冠之间、区域和喷洒目标之间允许重叠；本轮不做全场碰撞分析或任务可行性判定。规则数量与布局由生成检查验证，不作为载入场景必须服从的规则。

## 后续消费与扩展

```python
from scene import generate, load, save, summary, terrain_height

scene = load("examples/default.scene.json")  # 只读取实际几何
for tree in scene["trees"]:
    x, y, _ = tree["position"]
    ground = terrain_height(scene, x, y)
    # 以后读取 tree["trunk"], tree["canopy"] 和关联 targets
```

以后随机生成或图片转换只需产出同版本场景并通过 `validate_scene`，即可复用保存加载和现有支持几何的显示。算法应遍历每棵树与目标、读取多边形及地形查询；如需栅格，由算法侧显式转换，原场景仍保留连续几何。不扩展未使用插件框架或规划器空接口。

## 参考与验证

已检查外层参考工程的 `main.py`、`dashboard.html`、`uav_planner/dashboard.py`、`uav_planner/agri/scene.py`、`uav_planner/coverage/web/index.html` 及 `legacy/` 目录定位，并阅读指定 CAW-A* 研究背景。`legacy/` 未当作活动入口。借鉴了本地 HTTP 服务、相机旋转/缩放/平移的交互思路；**没有复制模板代码或迁入其依赖**，因此无复制代码的许可声明。概念原图可读，保存为 `references/概念参考-非运行结果.png`，只作视觉参照。

`--check` 已实际通过 8 组行为检查；真实浏览器验证项目、截图和已知限制见 `STAGE_LOG.md`。系统浏览器默认三维/俯视截图是 `screenshots/default-3d-system.jpg`、`default-top-system.jpg`；另外保留内置浏览器窄窗口截图。均为实际运行画面，非概念生成图。


## 第二阶段：单机基础计划

左栏下方提供独立作业配置、生成航线、保存/加载计划与航线开关。场景参数或作业参数改变即清除旧计划；失败不保留成功航线。青色实线为喷洒，橙色虚线为关闭喷洒的转场，紫色为重合的垂直起飞/返航下降，箭头表示顺序方向。

作业模型：单机、平地、无风、垂直向下喷洒。默认几何喷幅 2 m，最高实际树冠顶部以上 2 m 作业，安全净空 0.5 m，目标恒速 2 m/s。喷幅未经物理标定，不模拟体积沉积、转弯半径、加速度或执行轨迹。配置文件 `configs/job.default.json` 与地图配置分离。

从全部实际圆柱目标水平投影的最小 X 开始，按喷幅划分 X 带，末带可缩窄；每带中心沿 Y 作业。求每个圆盘在整个带宽内的 Y 投影包络，合并重叠区间，非目标空隙关闭喷洒直连。空带跳过；有任务的带逐带反向。默认为 8 个有效作业带（11 个候选带中跳过空带），不是每树行一条线。该矩形条带包络可能喷到圆盘外；这是明确的几何简化，不声称实测覆盖率。

安全检查器独立读取场景和计划，检查首尾连续、回到起降点、速度、状态、引用及全线段安全。实体圆柱和多边形禁飞体积使用包围盒，按净空各向膨胀后用 slab 法检测完整线段；接触也拒绝。禁喷区使用其 XY 包围盒，与喷洒段的矩形足迹相交（含 1e-9 m 接触容差）即拒绝，不依赖飞机中心点或禁喷区高度。规划器在生成阶段按同一包围盒口径预先切割航带，因此成功计划中不存在触区喷洒段；若切割后仍有目标无法获得合法喷洒关联，则任务不完整、明确失败，失败计划没有航段。连续性/高度容差 1e-8 m，区间合并容差 1e-9 m，平行判定 1e-12。

支持第一阶段平地圆柱目标、盒障碍、多边形柱区域；选择位置字典序最小的起降点。统一高度须在范围内且高于所有目标。飞行器按点加净空表示，未建立机体动力学。地图内容 SHA256 绑定计划（整数与等值浮点统一表示，避免浏览器 JSON 往返误判），重排列表不改变路线几何，但改变文件指纹，需要重新生成或匹配原场景。

```bash
.venv/bin/python main.py --plan --job configs/job.default.json --save-plan examples/default.plan.json
.venv/bin/python main.py --load examples/default.scene.json --plan --save-plan examples/my.plan.json
.venv/bin/python main.py --load examples/default.scene.json --load-plan examples/my.plan.json
.venv/bin/python main.py --check
```

CLI 输出完整计划 JSON（包含状态、原因、有效带数、高度）；失败退出 1。计划版本 1.0 含场景指纹、配置、方法、有序起终点、类型、喷洒布尔、速度及目标 ID。保存/加载均独立检查，不匹配拒绝。`planning/model.py` 为配置/指纹，`planner.py` 为条带和连续计划，`safety.py` 为独立检查，`storage.py` 为持久化。提供最低限度任务结构完整性检查，不提供覆盖率或完整面积覆盖认证。


### 第二阶段复核修正：任务结构与足迹

安全与任务结构由独立检查器验证，不通过重新生成路线比对。成功计划必须含喷洒段，所有目标至少有一次合法喷洒关联；每个声明的关联必须与该段足迹有正面积相交（距离容差 1e-9 m，纯切触不算有效关联）。非喷洒段不允许冒领目标，目标引用必须是无重复字符串列表。此条件用于排除全关喷、漏任务和伪关联，不能证明目标全部面积已喷洒。界面明确显示“安全与任务结构通过，覆盖率未验证”。

统一几何足迹定义在 `planning/footprint.py`：沿 Y 的喷洒航段扫过矩形 `[x-喷幅/2,x+喷幅/2] × [min(y0,y1),max(y0,y1)]`；无圆形端帽、无纵向端部扩展。关闭喷洒段足迹为空。后续几何覆盖累计须使用此定义；若改变喷头模型，应明确升级约定。禁喷检查以该矩形对区域 XY 包围盒相交判定（接触及 1e-9 m 容差也拒绝），切割边界再留 1e-6 m 间隙以保证通过该校验；多边形包围盒可能误拒绝，但不会通过额外端帽扩大喷洒含义。

界面分组改进待下轮处理：将场景与作业控件分组/折叠，避免左栏继续增长；本轮保留现有布局。

## 第三阶段：单机执行时间模型与回放

`execution/` 读取已校验场景和计划，按每段 `length / speed` 编译累计时间。区间采用左闭右开 `[t_start,t_end)`；总时刻 `duration` 表示返航落地完成，状态为 `completed`、喷洒关闭、模型速度为 0。垂直段沿用最近有效水平航向，初始方向为 +X。拐点瞬时变向，没有加速度、转弯半径或真实动力学。

```bash
.venv/bin/python main.py --execute --save-execution examples/default.execution.json --samples examples/default.samples.json --step 5 --time 1
```

样本包含规则时间点、每个航段起止边界和中点，避免短喷洒段被粗步长漏掉。浏览器倍速只改变查询频率，不改变模型时长；暂停、拖动、重置都调用相同 `state_at`。图标为辨识符号，尺寸不代表机体物理尺寸。当前不计算覆盖、沉积、能耗或风场。

## 第四阶段覆盖评价

回放时间查询会调用独立 evaluator，按执行时间累计矩形喷幅与目标水平投影网格，显示覆盖率、漏喷、重复覆盖和喷洒时间。结果是分辨率网格近似，不是实际喷洒覆盖认证；覆盖图层可关闭。计划失效会清空评价。

### 第七阶段：环境接口

`planner_api.py` 提供统一规划器适配器，`env.py` 提供可复现 `MultiUAVEnv`（reset/step/seed、离散作业带动作、非法动作惩罚和终止条件）。`--env-demo` 运行 deterministic random policy；当前不训练模型，也不宣称训练效果。

### 第八阶段：最小训练基线

`rl.py` 提供可复现的表格策略训练/评价基线，不引入训练依赖，不声称优于固定规划或多机基线。命令：`python main.py --train --episodes 50 --seed 0 --save-policy policy.json`，加载评价使用 `--evaluate-policy policy.json`。

### 第九阶段：喷洒语义与目标级评价

作业配置新增 `target_type`、`flow_rate`，旧作业 JSON 仍可加载并使用默认值。评价保留网格近似，同时按每个目标汇总覆盖比例、漏喷/重复目标、喷洒时长和估算喷洒量；仅 spray 航段计入，转场不计入。

### 第十阶段：植保实验统计

`experiment.py` 统一比较 fixed-y、naive、multi 和表格策略，支持多个 seed/UAV 数量，输出逐次结果及覆盖率/时间均值标准差，并保留失败原因与指纹。运行：`python main.py --experiment --seeds 0,1,2 --methods fixed-y,multi --save-results results.json`。统计为描述性结果，不代表训练优越性。

### 第十一阶段：风场方向代价

作业配置支持 `wind_speed`、`wind_direction` 和 `wind_cost`；默认无风。执行时间模型按航段方向计算顺风/逆风代价，保留原几何路径与安全检查。

### 第十二至十五阶段

已加入净空网格转场基线、可核验小规模联合顺序、多机连续时间协同诊断，以及按场景数据划分的轻量监督代理接口。代理只提供剩余代价预测，最终规划必须经过精确安全检查；不代表端到端飞控或 MADDPG 效果。

### 统一入口

默认界面：`.venv/bin/python main.py`。全量回归：`.venv/bin/python main.py --check`。实验：`--experiment --seeds 0,1,2 --methods fixed-y,multi --save-results results.json`。训练基线：`--train --episodes 50 --seed 0 --save-policy policy.json`。工程当前所有新增阶段均保持失败原因、场景指纹和安全检查链路。

回放滑块现在统一处理键盘和拖动输入：输入值会先限制在时间线范围内，再同步定位时间、执行状态和评价查询。

转场模式可通过作业配置 `transition_mode: "fixed"`（默认）或 `"search"` 启用，也可用 CLI 参数覆盖：

```bash
.venv/bin/python main.py --plan --job configs/job.default.json --save-plan fixed.plan.json
.venv/bin/python main.py --plan --job configs/job.default.json --transition-mode search --save-plan search.plan.json
```

`--transition-mode` 未给出时使用作业 JSON 的值，JSON 也未给出时为 `fixed`；显式给出时覆盖 JSON 同名设置。两条路径都经过相同的独立安全检查。搜索模式会替换转场段并重新经过安全检查；搜索或场景校验失败时保留失败原因、返回非零退出码，且不保存计划文件。成功计划版本为 `1.1`，保存实际 `transition_mode`、场景指纹 `scene_hash` 和配置指纹 `config_hash`；加载时会拒绝模式与指纹篡改，`1.0` 旧计划仍可加载。

### 固定/搜索转场对照实验

小场景配置为 `configs/transition.small.json`（2×3 棵、6 个目标）。对照命令：

```bash
.venv/bin/python main.py --transition-experiment --config configs/transition.small.json --save-transition-results transition.results.json
```

结果按 `fixed` 与 `search` 两行记录：`path_length`（执行时间线总长度）、`segments`（航段数）、`total_time`、`search_nodes`（净空网格 A* 扩展节点总数，fixed 恒为 0）、`safety`（独立安全检查结果）、`reason`、`scene_hash`、`config_hash`、`plan_version` 和 `plan_method`。顶层保存场景概况、`scene_hash`、`config_base_hash` 和说明字段；失败行的路径长度与总时间为 `null`，原因完整保留。

单场景结果只作描述性对照，不构成“search 普遍更优或更差”的结论。在默认无遮挡小场景中，搜索转场因网格折线通常得到更长路径、更多航段和节点数，这是搜索离散化的实现代价，不是算法优劣证明。

浏览器加载计划时现在只回填存在对应输入框的配置字段，修复了 `target_type`、`flow_rate` 等字段导致的 `Cannot set properties of null`；加载后可对照实际模式、航段数和 `config_hash`。

### 第十六阶段：作业顺序与转场路径联合精确穷举

`joint.py` 对小规模喷洒航段顺序做**精确穷举 + 完整计划构造**：起飞 → 转场/喷洒交替 → 返航 → 降落。换序时每条喷洒航段的起终点、目标关联和喷洒方向保持不变；`fixed` 模式用同高度直线转场，`search` 模式用与当前 `transition_mode` 一致的净空网格 A* 转场。每个候选计划先经过独立 `planning.check`，通过后再进入统一 `execution.build` 计时；按执行总时间选优，同分时按总路径长度、再按顺序字典序。该模块是可独立核验的小规模精确基准，不是可扩展求解器。

```bash
.venv/bin/python main.py --joint --config configs/joint.small.json --job configs/job.joint.small.json --limit 8
.venv/bin/python main.py --joint --config configs/joint.small.json --job configs/job.joint.small.json --transition-mode search --limit 8 --save-joint "$TMPDIR/joint.search.json"
.venv/bin/python main.py --joint --job configs/job.default.json --limit 6
.venv/bin/python main.py --joint --config configs/joint.blocked.json --job configs/job.joint.small.json --limit 8
```

`--joint` 可与 `--config`、`--load`、`--job`、`--transition-mode` 组合；`--save-joint` 保存完整结果 JSON（成功、失败、unsupported 都保存）。退出码语义：`success` → 0，`failed` → 1，`unsupported` → 2。旧命令行为不变。

结果字段：

- `status`：`success` / `failed` / `unsupported`。
- `method`：`exact-permutation+transition-fixed` 或 `exact-permutation+transition-search`。
- `order`：最优喷洒航段顺序（基准航段索引的排列）。
- `transition_length`：最优方案全部 `transit` 航段长度之和，包含进入首航段和从末航段返回作业高度起降列的转场，不含垂直起飞/降落。
- `total_path_length`、`total_time`：由统一执行时间线得到的总路径长度与总时间。
- `expanded`、`orders_total`：实际枚举排列数与应有排列数（成功/失败时二者相等，证明穷举完整）；`unsupported` 时 `expanded=0`，但仍保留精确排列数（可能很大），便于判断规模。
- `feasible_orders`：通过安全检查与执行器的候选数量（整数）。
- `rejected`：失败候选的 `{order, stage, reason}`，最多保留 20 条；`rejected_total` 为总失败数，`rejected_truncated` 说明是否截断，`rejected_note` 给出“仅保留前 N 条、共 M 条”的文字说明。
- `scene_hash`、`config_hash`：当前场景与有效作业配置（含实际转场模式）的指纹。
- `baseline`：基准 fixed-y 顺序的 `order`、`transition_length`、`total_path_length`、`total_time`、`safety`、`search_nodes` 和失败原因。
- `improvement`：相对同一场景/配置/转场模式基线的 `total_time_saved`、`total_time_pct`、`total_path_length_saved`、`transition_length_saved`。
- `optimality_gap`：成功时为 `0.0`，表示已枚举全部排列；不可行排列被排除，不做近似。
- `search_nodes`、`search_routes`：search 模式下最优计划的转场搜索节点数与路由数；fixed 为 0。

规模上限与语义：`len(sprays) > limit` 返回 `unsupported`，原因写明航段数与上限；排列数超过硬上限 `40320`（8!）也返回 `unsupported`，防止误传大 `limit` 导致不可控枚举。`unsupported` 不返回 `order`、`total_time` 或伪最优结果。默认 `limit=8`；8 航段约 4 万排列，终端可能需约 100 秒，交互建议 `limit=6`。阻塞场景若基准计划已失败，返回 `failed` 并在 `baseline`/`rejected` 中保留原始失败原因，不伪造成功。

`joint.verify(result, scene, config)` 会拒绝场景或配置指纹不匹配、成功结果缺少完整排列/有限数值、未穷举全部排列或失败结果携带最优方案的输入。`joint_transit_checks.py` 已接入 `main.py --check`，覆盖 3 航段独立暴力最优、执行器一致性、unsupported、全失败与部分候选失败保留、指纹篡改、确定性、非对象 `config`/`job` 输入防御和 fixed/search 两种语义。

浏览器“08 · 联合作业顺序”面板提供穷举上限输入并显示顺序、转场/路径/时间、扩展数、搜索节点、安全状态、基准与改进量、指纹；`unsupported`/`failed` 显示明确原因，不显示伪成功。场景参数、作业参数或穷举上限变化后旧结果立即失效，需重新计算。单场景数值只作描述性核验，不构成 fixed/search 或顺序策略的普适优劣结论；搜索节点数依赖网格步长与净空，横向比较前须固定参数。

边界说明：search 模式的网格路由本身只避让 `obstacles`，不避让树冠或禁飞区；树冠和禁飞区由随后的独立安全检查拒绝。因此本模块的“精确”只指**给定转场语义下的顺序精确最优**，不是三维路径连续性、转弯动力学或绕飞策略的最优。任何排序候选都必须通过同一安全检查，不能因为总时间更短而绕过约束。

### 第十七阶段：多机等待、错时与共享航段协调（连续时间安全回归）

`coordination.py` 从“只在重叠区间起点采样一次位置”升级为连续时间最近接近距离（CPA）检测。每条航段是分段线性运动区间；对两条时间线中时间窗口重叠的每一对航段，把相对位置写成时间的二次函数并解析求最小值，得到该段对的最小距离、最近时刻和相对速度。方法名 `continuous-cpa-analytic`，不依赖帧采样或区间起点，因此可以检测“两端都远、中间交叉”的冲突。

检测结果字段：`status`、`method`、`min_distance`、`conflicts`、`pairs`、`min_separation`、`waiting_seconds`、`makespan`、`total_time`。`conflicts` 按冲突无人机对数计数；`pairs` 每项包含 `uav_a`、`uav_b`、`min_distance`、`time`、`segment_a`、`segment_b`、`relative_speed`、`conflict` 和最多 20 条 `events`。旧签名 `analyze(timelines, min_distance=1.0)` 与旧字段保持兼容。输入防御：`timelines` 必须是非空列表，每段 `t_end > t_start`（不允许零时长瞬移）且同一时间线内不重叠、相邻航段首尾位置连续，坐标必须是有限三维数值；带 `offset` 的时间线首段必须等于该偏移；`min_distance` 必须是有限正数，否则抛 `ValueError`。

`coordination_plan.py` 在统一执行器上实现确定性协调：

```bash
.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1.0
.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1.0 --config configs/joint.small.json --job configs/job.joint.small.json --save-coordination "$TMPDIR/coordination.json"
.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1000 --max-delay 2 --config configs/joint.small.json --job configs/job.joint.small.json
```

流程：

1. 调用 `multi.run` 生成连续作业带分块计划；基准计划或任一无人机计划/执行时间构建失败时，协调结果直接 `failed`，原因与阶段保留在 `reason`/`stage`。
2. 每机时间线由统一执行器 `execution.build` 构建。**等待语义是地面 hold**：通过整体平移该机时间线实现起飞前地面等待，计划本身（航段、速度、顺序、喷洒关联）完全不变。当前没有实现空中悬停，也没有新增 hold 航段。
3. 连续检测冲突后，按无人机编号确定性地延迟冲突对中编号较大者；延迟步长由 CPA 距离缺口与相对速度估计，每次尝试后重新构建全部偏移时间线并重新检测。该策略保证结果可复现，不是全局最优协调器。
4. 受 `--max-delay`（单机最大地面等待，默认 120 s；`waiting_seconds` 是多机之和，因此可超过该值）与 `--max-attempts`（默认 200）限制。达到限制仍有冲突时返回 `failed`，保留最后的 `conflicts_after`、原因和尝试次数，绝不伪造 0 冲突。
5. 只有 `conflicts_after == 0` 才返回 `success`。如果通过串行化（两机从不同时在空中）达成，`min_separation` 为 `null` 且 `separation_measured=false`，页面显示“无同时空中重叠（串行）”。

CLI 选项：`--coordinate`、`--save-coordination`、`--min-distance`、`--max-delay`、`--max-attempts`，可与 `--config`、`--load`、`--job`、`--transition-mode`、`--uavs` 组合。退出码：`success` → 0，`failed` → 1，输入错误（非法参数、非法作业 JSON 等）→ 2 且不打印 traceback。`--save-coordination` 在成功和失败状态下都写出合法 JSON（`null` 表示未测量，不使用 `Infinity`）。

结果字段：

- `status`、`reason`、`stage`：`success`/`failed`；失败阶段为 `scene`/`multi`/`plan`/`uav`/`execution`/`coordination`/`done`。
- `method`：`sequential-ground-hold+continuous-cpa`；`waiting_semantics`：固定的地面等待语义说明。
- `min_distance`、`max_delay`、`max_attempts`：本次调用参数；`max_delay` 是单机地面等待上限。
- `uavs`：每机 `{uav, offset_seconds, plan_duration, duration, makespan, conflicts}`；`duration`/`plan_duration` 为同一计划时长，`offset_seconds` 非负。
- `conflicts_before`、`conflicts_after`：协调前后冲突无人机对数。
- `min_separation`、`separation_measured`：协调后同时在空中时测得的最小距离；无同时空中时段时为 `null`/`false`。
- `waiting_seconds`：各机地面等待偏移之和；`makespan`：`max(offset + plan_duration)`；`total_time`：各机计划时长之和（不含地面等待）。
- `attempts`：实际消解尝试次数。
- `scene_hash`、`config_hash`：场景与有效作业配置指纹。`verify(result, scene, config)` **不信任结果字段**：它会按当前场景/配置重新生成 `multi.run` 计划、经 `execution.build` 重建各机时间线，并按结果中的偏移重新做连续 CPA 复核。因此它拒绝场景/配置指纹不匹配、成功但复核仍有冲突、伪造成功状态、失败却声称零冲突、失败结果套用到当前已成功的配置、偏移为负、`makespan`/`waiting_seconds`/`total_time`/`min_separation` 与复核不一致的结果。
- `diagnostics_before`/`diagnostics_after`：每对无人机的最小间距与冲突对摘要。

`coordination_plan_checks.py` 已接入 `main.py --check`，覆盖：解析 CPA 与“区间起点采样会漏掉”的交叉冲突、协调后 `conflicts_after=0` 与独立密采样复核、偏移非负与 makespan 一致性、受限等待下的 `failed` 原因保留、确定性、场景/配置指纹与篡改拒绝、保存加载、多机基线失败传播、旧 `analyze` 字段兼容和输入防御。

浏览器“05 · 多机协同”面板保留“生成多机基线”，并新增“协调（连续时间）”入口、最小机间距与最大地面等待输入。页面显示协调前/后冲突、每机等待与时长、最小间距、makespan、尝试次数、安全状态和指纹；`failed` 显示原因，不显示成功；场景、作业参数、最小间距或最大等待变化后旧协调结果立即失效。“生成多机基线”的旧行为不变。

边界说明：

- 间距只在“两机同时在空中”的时间段内度量；起飞前地面等待和已降落停放不参与空中间距计算。模型只有一个共用起降点，没有停机位占用模型，因此不模拟地面相撞。
- 协调只处理无人机之间的动态间距，不替代对树木、障碍、禁飞区的静态安全检查；后者仍由 `planning.check` 对每个计划独立执行。
- 时间来自分段恒速执行模型（含现有风场速度修正），没有加速度、转弯半径、悬停动力学或真实飞控。
- 确定性策略只延迟编号较大的无人机，不保证总等待时间或 makespan 全局最优；在某些场景下可能比“允许延后任意一机”的策略更早返回 `failed`。单场景数值只作描述性核验。
- 若结果依赖完全串行化，则不存在可报告的最小空中间距，应读取 `separation_measured=false` 而不是把 `null` 当成 0。

### 第十七阶段追加：多机与联合轨迹动画回放（G 节）

可回放轨迹不再逐帧请求后端。回放数据在“准备回放”时一次取回，来源只能是统一执行器 `execution.build` 的编译时间线：

- 03 单机：`/api/execution` 返回一次时间线；前端按与 `execution.state_at` 相同的分段恒速规则本地插值。播放期间不请求 `/api/state`；覆盖率评价在暂停/定位时以 120 ms 去抖请求 `/api/evaluation`，不逐帧重算网格。
- 06 多机基线：`/api/multi-playback` 用同一 `multi.run` 计划逐机 `execution.build`，返回每机 `{label,color,offset,duration,home,segments}`。
- 06 协调结果：`/api/coordinate` 的 `playback` 字段直接携带协调后的偏移时间线；每机首段 `t_start` 等于其地面等待偏移，等待期间无人机停在起降点。
- 09 联合最优/基准：`/api/joint-playback` 用最优顺序重建完整计划，并用基准计划构造第二条轨迹；两条轨迹都经过 `execution.build`。

前端使用 `requestAnimationFrame` + `performance.now()` 墙钟推进，位置按时间插值而不是按帧累加；画布分两层，主画布只画静态场景/路径，动态 overlay 每帧只重绘无人机和标签，DOM 文本与滑块约 10 Hz 节流。03 单机与 05/08 回放都在 `document.hidden` 时记录当前时间并暂停，恢复后从该时间继续，不按隐藏时长跳帧；倍速切换只重锚时间，不重置位置。分段边界严格按 `execution.state_at` 的 `bisect_right` 语义选择下一段，t=0 的速度/航段/喷洒状态与执行器一致。

“05 · 多机协同”面板提供回放来源（多机基线/协调结果）、准备回放、播放/暂停/重置、倍速、时间数字框和滑块，显示当前时间、各机状态、航段、喷洒状态与位置。每架机使用固定调色板颜色和 `UAV n` 标签；协调回放的路径来自偏移后的时间线，单机计划路径在多机回放期间隐藏，避免把协调前轨迹误画成协调后轨迹。“08 · 联合作业顺序”面板在成功结果后提供“最优/基准”轨迹回放，最优和基准用不同颜色与标签。

场景、作业参数或无人机数量变化时 06 回放停止；最小间距/最大等待变化时仅协调回放停止（多机基线不依赖这两个参数）；回放来源或联合结果变化时相应回放停止并禁用控制。旧结果不会被继续播放。多机基线若无人机数超过喷洒分块数，空块机不会生成伪造轨迹，回放信息标注“无作业航段”。失败或 unsupported 的协调结果不提供“成功回放”。

07 三维转场搜索仍只是单条起降—目标路线的静态诊断，没有动画。它是可选的 G1 项，且与 03 单机回放和搜索面板的单路线检查高度重叠；本阶段明确不做，避免为重复能力牺牲主回放的正确性和流畅性。

边界：回放插值只使用执行器的分段恒速模型，不补间转弯、加速度或悬停动力学；多机回放的“地面等待”是停在起降点的时间平移，没有停机位占用模型。轨迹颜色使用固定 8 色调色板循环，超过 8 架时颜色会重复，需以 `UAV n` 标签区分。浏览器在后台或窗口被遮挡时可能被浏览器降频，G4 的帧时间证据应在页面可见时采集。

### 第十八阶段：CAW-A* 算法主链（M0）

**先修评价器**：`evaluation.at()` 改用 `config["swath"]`，不再把网格分辨率当喷幅。默认场景覆盖率由失真的 `0.546875` 修正为 `1.0`（漏喷 0）；历史 `0.546875` / `0.2734375` 不再作为有效基线。

**计划与算法**：

- plan v1.2：新增 `planner`、`objective`、`planner_options`、`planner_options_hash`、`search`、`order_search`；`transit` 允许任意高度，`spray` 仍沿 Y 且在作业高度；v1.0/v1.1 全兼容。
- `planning/wind.py`：共享风场时间模型；搜索与执行器使用同一公式。`--objective energy` 目前返回 `failed`，原因“能量代理口径未实现（M2）”，不会静默成功。
- `planning/routing3d.py`：分层三维净空 A*（同层 8 邻接 + 垂直层），统一避让障碍、树冠、禁飞区；节点数、`grid_hash`、确定性、节点上限和失败原因。
- `planner_api.py`：真实 FixedY、Naive（逐目标短喷）、CawAStar、CawFixedOrder、CawNN；未知名称拒绝。
- `comparison.py` / `experiment.py` 按规划器真实调度，不再是“同一计划改名字”；失败原因保留，失败进入实验分母。
- `joint.py` 支持 `caw` 转场，小规模精确结果 `optimality_gap=0`。

**CLI 示例**：

```bash
.venv/bin/python main.py --plan --job configs/job.default.json --algorithm caw
.venv/bin/python main.py --plan --config configs/caw.wall.json --job configs/job.caw.tiny.json --algorithm caw
.venv/bin/python main.py --compare --method all --save-comparison compare.json
.venv/bin/python main.py --joint --joint-transition caw --config configs/joint.small.json --job configs/job.joint.small.json --limit 8
.venv/bin/python main.py --order --config configs/caw.tiny.json --job configs/job.caw.tiny.json --order-strategy nn+2opt
.venv/bin/python main.py --route3d --config configs/caw.wall.json --job configs/job.caw.tiny.json --step-xy 1
```

**观测（描述性，不代表普遍优劣）**：默认场景 fixed-y 254.79 m / 127.40 s / 覆盖率 100%；naive 214.62 m / 107.31 s / 覆盖率 75%（24 个目标漏喷，不是同覆盖语义）；caw 252.36 m / 126.18 s / 覆盖率 100%，搜索节点 203，相对下界 101.68 s。墙场景 fixed 失败（净空冲突），caw 成功绕行、转场高度 6.20–7.50 m。风场 3.0 m/s / 0.5 rad 时路径 41.27 m、时间 22.85 s、节点 330。

**独立审计修正**：两个只读审计确认了评价器、实验失败分母、三维净空、确定性与指纹行为，并推动修正：中间时刻只评价已飞行喷洒足迹；`max_expansions` 不再越界；结果 `grid.bounds` 不再共享缓存；`max_grid_nodes` 在建网格前拦截；起终点净空高度显式校验；视线平滑只在目标代价不增加时接受（`optimality` 区分 `grid-optimal` 与 `grid-search-nonworsening`）。修正后共享工作树 `--check` 为 **134 通过 / 0 失败**（含并行阶段 19 的 24 条；阶段 18 新增 66 条记录）。

**边界**：单场景和小规模结果只作描述性对照；三维 A* 是分层网格，不是连续空间最优；风场只改变时间与代理代价，路径不一定变化；未做能量标定、转弯动力学、多机 CAW 联合；8 航段精确穷举仍为慢测，不进入默认回归。

### 第十九阶段：场景编辑器与随机地图（19A 后端 / 19B 前端）

本阶段在 `format_version 1.0` 上增量增加鼠标编辑与可复现随机地图，默认规则果园、旧场景、旧计划、旧 CLI 行为保持不变。

**左侧面板编号（阶段 19 重排）**：原 05–09 依次前移为 04–08，阶段 19 新增的场景编辑器为 09；侧栏连续显示 01–09，无缺号。旧阶段记录中的编号按历史原样保留，按下表对照：

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


**后端与数据（19A）**

- `scene/shapes.py`：矩形/正多边形足迹、棱柱构造、点包含、自交/越界检查、AABB 重叠；供随机地图和前端预览复用。
- `scene/presets.py`：障碍预设库 `shed / wall / container / post`，全部生成轴对齐 `box`；可选 `preset` 仅作来源提示，几何仍由 `min/max` 决定。
- `scene/random_map.py`：5 种随机样式 `regular / jitter_rows / clusters_gaps / size_mix / random_obstacles_zones`；单 `random.Random(seed)`、固定调用序、毫米量化；每棵树恰好一个目标；`source.kind="random_orchard"` 记录 `generator_version/style/seed/parameters`；同版本 + 同 seed + 同参数编码逐字节一致。
- `random_scene.py`：随机入口与可选固定条带可达性检查；`require_reachable=true` 时按上限重试，全部失败返回“已尝试 N 次…”而不返回伪成功场景。
- `scene/validation.py`：新增 `report(scene, mode="fast"|"full", strict=...)`；错误带 `code/path/message`；`fast` 只跳过非阻断的树冠重叠提醒，阻断结论与完整模式一致；`summary(..., validated=True)` 复用一次校验。
- 起降点 L1：`launch_points[].role`（`both/start/return`）和顶层 `launch_assignments` 均为可选；无字段时仍取排序第一个点、`start=end`；显式配置或 `strict=true` 时启用禁喷/禁飞 XY 严格检查；规划器取点逻辑不变。
- `scene/launch.py`：统一 `resolve/resolve_all` 回退解析；L1 只用于校验/预览，未接入 planner。
- `POST /api/random`：`{style, seed, params, require_reachable}` → `scene/summary/serialized/report/config`；非法参数 400，不返回空场景。
- `POST /api/validate`：`{scene, mode, strict}` → `{ok, errors, warnings, summary}`；内容非法仍 HTTP 200 + `ok:false`，请求非法 400。

**CLI**

```bash
.venv/bin/python main.py --random-scene --style regular --seed 1 --save random.scene.json
.venv/bin/python main.py --random-scene --style clustered --seed 7 --save clustered.scene.json
.venv/bin/python main.py --random-scene --style random_obstacles_zones --seed 3
.venv/bin/python main.py --random-scene --style jitter_rows --seed 7 --random-params params.json --require-reachable
```

`clustered` 是 `clusters_gaps` 的别名；`--random-scene` 与 `--config/--load` 互斥。参数文件缺失/顶层非对象返回失败原因和退出码 1，未知样式由 argparse 返回退出码 2。

**前端（19B）**

- `web/editor.js`：俯视精确编辑（矩形障碍、多边形禁飞/禁喷、起降点）、选择/移动/角点缩放/顶点编辑/删除、撤销重做、网格吸附、光标坐标、以光标为锚点的滚轮缩放。
- 检查器/对象列表/JSON 双向同步：画布提交后同步三个附加对象文本框及起降点/分配文本框；独立“应用附加对象”按钮走服务端校验；错误定位到对象/字段。
- 随机面板：样式、seed、参数 JSON、生成、同 seed 重生成、只换 seed、`randomLock` 整场景锁；显示计数、尝试次数、警告、可达性状态和生成器版本。
- 三维 ghost 放置：预设障碍跟随光标、0.5 m 吸附、有效/无效配色、`Esc` 取消、连续放置；三维近似选中、删除、XY 粗移动；精确尺寸回二维或检查器。
- 任何几何提交调用现有 `invalidatePlan()`，旧计划、执行、比较、多机、协调、联合结果立即失效；撤销不恢复旧计划（现有语义）。
- `app.js` 增加 `window.sceneEditorHost` 最小宿主接口、`drawEditor`/pointer 钩子、俯视轻量圆/平面渲染、`sceneEdited` 确认、按 role 的起降点标签。

**验证（实际运行）**

- 终端：`.venv/bin/python main.py --check` → **134 通过 / 0 失败**（含并行阶段 18 的既有项）。
- CLI：`regular --seed 1`、`clustered --seed 7`、`random_obstacles_zones --seed 3` 均退出码 0；保存文件可重新加载；同 seed 编码一致。
- 浏览器：通过真实 Chrome（headless，8798 端口，终端启动服务）执行页面内 pointer/keyboard 断言，覆盖矩形、移动、缩放、顶点、删除+撤销、多边形、起降点、随机 `jitter_rows` seed 7 与同 seed 复现、三维 ghost、越界拒绝、随机锁、2500 棵树俯视与快速校验；并确认侧栏连续显示 01–09（01–08 原面板 + 09 场景编辑器，无重复/缺号）。5 种随机样式的合法性与复现由终端回归覆盖。截图见 `screenshots/editor-initial.png`、`editor-panel.png`、`editor-tests.png`、`editor-panels.png`；断言文本见 `screenshots/editor-browser-results.txt`、`editor-probes.txt`、`editor-panels.txt`。
- 预览应用端口说明：本会话的 Browser 预览服务上限被其它并行会话占满，因此改用真实 Chrome + 终端服务完成浏览器验收；不是把终端通过当作浏览器通过。

**已知限制**

- 三维只做 ghost 放置/近似选中/XY 粗移动；旋转、三维缩放、三维顶点、精确遮挡拾取未做。
- 障碍仍仅轴对齐 `box`；区域仍为简单多边形棱柱；不支持 OBB、圆柱障碍、区域带洞、非平地。
- 三维拾取无深度缓冲，AABB 投影存在歧义，以对象列表和二维选择兜底。
- 2500 棵树终端校验/绘制路径已验证不阻塞，但未在可见窗口采集 P95 帧时间；headless 虚拟时间下的耗时数字不作为性能认证。
- `randomLock` 是 UI 状态，不写入场景，刷新后重置。
- `regular` 样式的 seed 不参与几何（确定性对照）；跨 `generator_version` 不承诺同 seed 一致。
- `require_reachable=true` 可能多次完整规划，树/障碍较多时耗时明显；默认关闭。
- 起降点 L2（起点/终点分离、每机分配、planner/safety 1.2）未在本阶段实现；L1 规划仍取排序第一个点、start=end。

### 第二十阶段：起降点优化与能耗代理（M0）

**起降点优化**：对候选起降点逐一构造完整计划，经过统一安全检查、执行器和评价器，按时间或能耗代理选优。默认单一起降点、旧场景和旧计划行为不变；优化必须显式启用。

```bash
.venv/bin/python main.py --optimize-depot --depot-candidates launch --uavs 1 --objective time
.venv/bin/python main.py --optimize-depot --depot-candidates grid --depot-grid 3 --uavs 1 --objective energy --save-depot depot.json
.venv/bin/python main.py --optimize-depot --depot-candidates grid --uavs 2 --objective time
```

- 候选来源 `launch`（场景已有起降点）或 `grid`（地块外围候选，含边界环与外部网格；落在作业地块内的点会被排除）。
- `--depot-budget` 限制完整求值数量；超预算时按最近航段端点做确定性剪枝，结果标记 `exact=false`、`optimality=budget-limited`。
- M0 只支持单一共用起降点（start=end）；多机只支持 fixed-y 规划器，makespan 为各机最大时长，`total_time` 为各机时长之和。
- 多机 `coverage` 是各机对全场景目标的平均值，不是机队并集覆盖率，结果带 `coverage_note`。
- 单机时间目标给出相对下界（喷洒时间 + 起降最少往返），`gap` 只表示相对该下界的差距；能耗目标与多机不下结论（`lower_bound=null`）。
- 失败保留 `stage/reason`；无可信可行候选时返回 `failed`，不生成伪成功。

**能耗代理**：新增 `planning/energy.py`，单位 `eu`（等效米），不是 Wh/电池模型。

- 默认 `motion-only`：水平运动、爬升、下降；`mission-proxy` 额外启用泵/悬停/地面待命/载药等项，仍为未标定代理。
- 只有同时提供 `wh_per_eu` 与 `calibration_id` 才输出 `energy_wh`；否则只显示 `eu`。
- 支持 `endurance_eu` + `reserve_ratio` 约束；超限候选返回失败原因。
- 起降点优化与 CAW 规划器均支持 `--objective energy`；fixed-y/naive 等未实现能量口径的规划器仍明确失败，不会静默回退成 time。

**观测（描述性）**：默认场景单机，原始起降点 `[-3, 12.5]` 为 127.40 s / 244.25 eu；网格 8 个外围候选精确枚举后选中 `[11.5, -3]`，118.17 s / 225.79 eu，相对下界 80.49 s、gap 46.8%。2 机同一候选 makespan 63.54 s、总时间 126.90 s、平均每机覆盖率 50%（非并集）。这些数字只说明本场景候选比较，不构成通用选址结论。

**UI**：“10 · 起降点优化”面板支持候选来源、网格、预算、无人机数、目标与能耗口径；显示选中点、makespan/总时间/能耗/下界/gap 与候选表；可将选中点应用回场景（启动点变为该点，计划/回放立即失效）。

### 第二十一阶段：起降点 L2/L3、协调 makespan、能耗标定、CAW 能量目标

**起降点 L2**：每架无人机可使用各自的起点/终点，起点可以不同于终点。

- 场景可选字段：`launch_points[].role`（`both/start/return`）与 `launch_assignments[]`（`uav/start/end`）；默认无字段时仍是排序第一个点、start=end。
- 显式 role/assignment 或 start≠end 时，计划升级为 v1.2 并携带 `uav`、`start_point_id`、`end_point_id`；默认计划仍为 v1.1 且逐字段不变。
- `planner/safety/multi/joint/coordination/playback` 全部按 UAV 解析起点/终点；回放每条轨迹带自己的 `home`。
- 缺失 UAV 分配、角色不允许、元数据篡改均明确失败；“共用点/重复引用”允许。
- UI：09 场景编辑器可编辑 `launch_points`/`launch_assignments` JSON；05 多机表显示 `起点 → 终点`；02 计划状态显示 v1.2 元数据。

```bash
# 示例场景通过 09 面板 JSON 应用；CLI 可用 --load 加载带 assignments 的场景
.venv/bin/python main.py --multi --uavs 2 --load "$TMPDIR/assigned.scene.json"
.venv/bin/python main.py --coordinate --uavs 2 --min-distance 1.0 --load "$TMPDIR/assigned.scene.json"
.venv/bin/python main.py --joint --joint-transition caw --config configs/joint.small.json --job configs/job.joint.small.json --limit 8
```

**协调后 makespan**：起降点优化新增 `--depot-coordinate` 与 `--min-distance`；多机候选评估调用同一连续时间协调，`makespan` 使用协调后的等待偏移，结果记录 `waiting_seconds`、`conflicts_after`。协调失败候选保留原因，不参与选优。

**能耗标定**：起降点、CAW 算法与多批次支持 `wh_per_eu` + `calibration_id`；两者同时存在才输出 `energy_wh`，否则只显示 `eu`。`--energy-wh-per-eu` / `--energy-calibration-id`（起降点 CLI）与 10 面板输入已接入。

**CAW 能量目标**：`--algorithm caw --objective energy` 现在可用，路径搜索、顺序代价与 `objective_value` 均按能量代理；“其他规划器 + energy”仍明确失败。

**多批次（L3 最小版）**：按载药量贪心切分喷洒航段，每批独立起降、规划、安全检查、计时与能耗。

```bash
.venv/bin/python main.py --sorties --payload-capacity-kg 0.5 --flow-rate-kg-per-s 0.01
.venv/bin/python main.py --sorties --payload-capacity-kg 10 --flow-rate-kg-per-s 0.01 --save-sorties sorties.json
```

- 结果含每批 `lane_indices/duration/payload_kg/safety/energy_eu`、总时间、总载药、总能耗；单条航段超过载药上限或参数非法时明确失败。
- 假设：每批满药起飞、换电/补药时间为 0、批次之间返回终点；不是完整电池/停机位模型。
- UI：“11 · 多批次（载药）”面板可输入载药上限与流量并查看批次表。

**观测（描述性）**：默认场景 1 批 127.396 s / 0.699 kg；容量 0.5 kg 时 2 批 152.436 s（0.496 + 0.203 kg）；容量 0.001 kg 时单航段超限失败。CAW 能量口径默认场景 241.823 eu。2 机起降点协调后 makespan 65.591 s（等待 2.05 s、冲突 0）。标定 0.5 Wh/eu 时 244.253 eu → 122.126 Wh。

**边界**：L2 仍是垂直起降；L3 是最小贪心批次，不建模换电/补药时间、停机位容量或批次间协调；CAW 能量为未标定代理；多机 CAW 联合仍未实现。

### 第二十二阶段：多机 CAW 联合与批次补充时间

**多机 CAW（`multi_caw.py`）**

- `CawAStarPlanner.plan_sequence(scene, config, lane_indices, start=None, end=None, uav=None, options=None)` 为单机生成完整 v1.2 计划：显式 `start`/`end` 或按 `uav` 从场景 `launch_assignments` 解析；计划始终带 `uav`、`start_point_id`、`end_point_id`，并过统一 `planning.safety.check` / `execution.build` / 评价器。
- `multi_caw.run(scene, config, uavs, options)` 沿用 `multi.py` 的连续喷洒航段索引分块，每机独立调用 `plan_sequence`，使用自己的起点/终点与三维净空转场；每机返回 `segments/duration/path_length/coverage/start/end/start_point_id/end_point_id/plan_version/safety`，失败保留 `stage/reason`。任一架失败时机队结果 `status=failed`，不伪造成功。`multi_caw.verify` 会重建每机计划，并拒绝伪造失败、顶层参数/配置/场景篡改。
- 默认 `multi.run`（fixed-y）行为与输出逐字段不变；`--multi` 不指定算法仍是 fixed-y。

```bash
# 多机 CAW（小场景）
.venv/bin/python main.py --multi --algorithm caw --uavs 2 \
  --config configs/joint.small.json --job configs/job.joint.small.json

# 多机 CAW 协调（同一连续 CPA / 地面等待）
.venv/bin/python main.py --coordinate --algorithm caw --uavs 2 --min-distance 1.0 \
  --config configs/joint.small.json --job configs/job.joint.small.json

# 多机 CAW 变体
.venv/bin/python main.py --multi --algorithm caw-a*-nn --order-strategy nn --uavs 2
```

- 协调 `coordinate(..., algorithm="caw")` 可选接收 `multi_result` 或 `options`，每机时间线来自各自 CAW 计划；结果在 caw 时增加 `algorithm`、`planner_options(_hash)`，默认 fixed-y 结果不增加字段。`conflicts_after=0` 才算成功；不可消解时保留 `stage/reason`。
- 回放 `multi_playback(..., algorithm="caw")` 返回 `mode="multi-caw"`，每条轨迹带自己的 `home`；仍一次取回、本地插值、播放期间零逐帧 API。
- `/api/multi`、`/api/coordinate`、`/api/multi-playback` 接受 `algorithm`/`options`；05 面板新增多机算法选择，表格显示每机 `起点 → 终点`、版本、路径/时长/覆盖；切换算法、场景或参数立即使多机/协调/回放失效，失败结果清空表格且不可回放。
- 限制：单场景描述性结果，不宣称 CAW 普遍优于 fixed-y；多机覆盖率仍是每机对全场景目标的单独值，不是机队并集；未建模空中悬停/等待，协调仍只做地面等待。

**批次补药/换电间隔（`sortie.py`）**

- `plan_sorties` 选项新增 `refill_seconds`、`recharge_seconds`（有限非负数，默认 0）。第 i 批（i>1）开始前增加固定 `gap_before_seconds = refill + recharge`；第一批为 0。
- 结果新增 `total_flight_time`、`total_gap_seconds = (sortie_count-1)*(refill+recharge)`、`makespan`；`total_time = total_flight_time + total_gap_seconds`。默认 0 时 `total_time` 与旧版一致，仅新增字段。
- 负值、NaN/Inf、布尔值明确拒绝；起降点分配、L2 元数据与单批载药上限行为不变。
- CLI `--sorties --refill-seconds --recharge-seconds`；`/api/sorties` 接受同名字段；11 面板新增输入与“间隔/飞行/总时间”显示，参数变化后旧结果失效。

```bash
.venv/bin/python main.py --sorties --payload-capacity-kg 0.5 --flow-rate-kg-per-s 0.01 \
  --refill-seconds 10 --recharge-seconds 5
```

**回归**：新增 `multi_caw_checks.py`（5 条），扩展 `sortie_checks.py`（+1 条）与 `web_checks.py`；覆盖多机 CAW 成功/失败、起降元数据、越墙高度、协调消解与不可消解、回放与执行器一致、默认 fixed-y 兼容、批次间隔与非法值拒绝。`main.py --check` 为 **143 通过 / 0 失败**。浏览器实测（8802）：05 面板 fixed-y/caw 切换、墙场景 fixed-y 失败/caw 成功、caw 协调 `冲突 1 → 0`、协调回放每机从自己的 home 出发且播放期无逐帧请求（pad-west/pad-east 两台不同 home）、11 面板 0 间隔 152.44 s → 15 s 间隔 167.44 s、参数变化后全部失效；截图 `screenshots/multi-caw-wall-coord-2026-11-02.jpg`、`screenshots/multi-caw-two-homes-2026-11-02.jpg`、`screenshots/multi-caw-batch-2026-11-02.jpg`。

### 验证反馈修复（阶段 22 后）

针对独立验证反馈的 High/Medium 已修复：03 漏喷/重复改用 API 顶层数组；多机空闲机显示“无作业航段”且不再 NaN；fixed-y/naive + energy 明确失败；06 实验失效、07 无计划空状态、实验 CLI 无 traceback、实验拒绝 `--config`；多批次 Wh/标定落地；起降点候选表全量显示并高亮选中；多机覆盖口径提示；CLI 计划补 `plan_hash`；02 显示目标值；多机增加机队摘要。回归增至 **144 通过 / 0 失败**。未修复项：时间字段命名统一、03 目标级表/分辨率 UI、06 参数输入、树木编辑、浏览器下载逐字节验证。详见 `验证反馈_修复记录.md`。
