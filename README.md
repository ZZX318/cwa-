# 果园场景实验台 · 第一阶段

本工程位于参考工程旁的独立目录 `从0开始写代码/`。实现规则果园生成、统一实际几何、校验、JSON 保存加载、三维/俯视与基础交互。所有示例尺寸是数值实验默认值，**不是实测农艺参数**。

现已实现单机基础几何作业计划；未实现无人机运动、喷洒仿真、覆盖统计、多机协同、研究指标、随机地图、图片导入或复杂地形。页面中没有这些功能的空壳或虚构结果。

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
- `no_fly_zones` / `no_spray_zones`：ID、`kind:"polygon_prism"`、`footprint`（同地块的多边形结构）、`z_min` / `z_max`，支持非矩形简单多边形。禁喷只是场景约束数据，允许与目标体积重叠，不计算扣除后的任务或指标。
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

安全检查器独立读取场景和计划，检查首尾连续、回到起降点、速度、状态、引用及全线段安全。实体圆柱和多边形禁飞体积使用包围盒，按净空各向膨胀后用 slab 法检测完整线段；接触也拒绝。禁喷区使用其 XY 包围盒，与完整喷洒段的矩形足迹相交即拒绝，不依赖飞机中心点或禁喷区高度。此法保守，可能误拒绝凹多边形、圆柱角部等可行路径，不会将这些包围盒外的危险忽略。没有绕障和禁喷切割，受阻明确失败，失败计划没有航段。连续性/高度容差 1e-8 m，区间合并容差 1e-9 m，平行判定 1e-12。

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

统一几何足迹定义在 `planning/footprint.py`：沿 Y 的喷洒航段扫过矩形 `[x-喷幅/2,x+喷幅/2] × [min(y0,y1),max(y0,y1)]`；无圆形端帽、无纵向端部扩展。关闭喷洒段足迹为空。后续几何覆盖累计须使用此定义；若改变喷头模型，应明确升级约定。当前禁喷检查以该矩形对区域 XY 包围盒相交判定（接触及 1e-9 m 容差也拒绝），多边形包围盒可能误拒绝，但不会通过额外端帽扩大喷洒含义。

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
