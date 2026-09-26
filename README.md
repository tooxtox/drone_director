# 天枢智航——城市低空交通智能规划与自主协同系统

可运行的城市低空交通规划、仿真与三维监控平台。系统从环境和任务状态出发，经航路规划、流量与冲突分析，执行事件处置，再把实际仿真轨迹和指标反馈到控制台。核心算法是可解释的加权 A*、连续轨迹冲突检测和规则解脱；没有已训练的 GNN 或强化学习模型。

## 启动

需要 Windows PowerShell 5.1（或 PowerShell 7+）、Python 3.12+、uv 和 Node.js 22.12+。

首次运行若 PowerShell 提示 "无法加载文件…因为在此系统上禁止运行脚本"，请先以**当前用户**放宽执行策略一次（无需管理员）：

~~~powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
~~~

在仓库根目录执行：

~~~powershell
.\scripts\setup.ps
.\scripts\run_demo.ps1
~~~

无法修改执行策略的机器（公司锁定环境），可以每次都绕过：

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1
# 或自定义端口
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_demo.ps1 -BackendPort 8013 -FrontendPort 5174
~~~

访问 http://127.0.0.1:5173 ，点击“生成 100 机演示场景”，再点击“启动仿真”。默认后端端口 8011；如被占用可运行 .\scripts\run_demo.ps1 -BackendPort 8013 -FrontendPort 5174。退出脚本会停止本次启动的后端。单独启动后端用 .\scripts\run_backend.ps1，单独启动前端用 .\scripts\run_frontend.ps1，测试用 .\scripts\run_tests.ps1。

发布式本地运行：在 frontend 目录执行 npm run build，随后只运行后端并访问 http://127.0.0.1:8011/ 。构建后的 Cesium 资源由同一服务提供。程序化城市不依赖在线地图、Cesium ion token 或外部服务。交互式 API 文档在 http://127.0.0.1:8011/docs ，OpenAPI JSON 在 /openapi.json。

无浏览器运行同一自动演示：

~~~powershell
.venv-runtime\Scripts\python.exe -X utf8 scripts\run_demo_headless.py --aircraft 100 --steps 600 --seed 42 --output data\demo_report.json
~~~

默认 SQLite 文件为 data/tianshu.sqlite3，可在 .env 中设置 TS_DATABASE_PATH。重新生成演示会覆盖当前场景，需要保留的报告应先从控制台导出。

## 项目布局

| 目录 | 职责 |
| --- | --- |
| core/models、core/repository、core/coords | 领域实体、SQLite/内存仓储、ENU/WGS84 坐标 |
| algorithms/path_planning | 五项加权 A*、二维/三维、容量及禁入约束 |
| algorithms/conflict_detection、algorithms/conflict_resolution、algorithms/emergency | 连续时空检测、规则解脱、安全备降 |
| simulation/environment、simulation/aircraft、simulation/engine、simulation/events | 三维城市、航路网、运动、仿真时钟、事件与指标 |
| backend/api、backend/services、backend/websocket、backend/config | HTTP/WS、事务、运行调度、集中配置 |
| frontend/src | Vue、TypeScript、Cesium、ECharts 控制台 |
| tests、docs、scripts、data | 测试、设计、脚本、种子和报告 |

详见 [架构](docs/architecture.md)、[数据模型](docs/data-model.md)、[航路规划](docs/path-planning.md)、[API 与 WebSocket](docs/api.md)、[演示与指标](docs/demo.md)、[阶段验收](docs/iterations.md)。

## 操作与演示

控制台可启动、暂停、单步推进、设定仿真倍率，显示建筑、航路、无人机、轨迹、天气、管制与冲突，并支持四类事件注入。基础实体和任务也可以通过 HTTP API 创建和编辑；运行时基础编辑需先暂停，事件可直接注入。

右侧“单项事件场景”可分别生成 24 机的拥堵、雷暴、临时管制、故障备降和两机冲突场景；点击卡片后前端用真实仿真单步推进到该事件发生后的第一秒并暂停，地图自动放大到实际受影响的飞行器，启动仿真后持续跟踪，点击“退出跟踪 · 总览”恢复城市视角。雷暴或管制预设会覆盖两架正在飞行的无人机：它们立即飞向区域外的安全出口，再沿重新规划的航路继续任务；尚未进入区域的飞机直接绕行。启动前及扰动注入后立即进行全机间距预测，随后每个仿真步均复检预测轨迹和实际运动；无法安全解脱则暂停。单项报告可用无浏览器命令 `--scenario congestion|weather|closure|failure|conflict --steps 180` 分别生成到 data/scenarios/。详情见[演示与指标](docs/demo.md)。

100 机初始场景由随机种子生成，不预置结果。仿真时间约 20 秒收缩航路容量、45 秒注入东部雷暴、70 秒注入单机故障、95 秒构造交汇任务意图；预测器检测冲突并选择安全规则。雷暴 160 秒消散并继续调度。220 秒表示四类扰动已经执行，任务仍继续运行；全部任务进入终态或达到 600 秒时演示停止。失去可达路径的任务会等待或如实报告。报告包含实际事件结果和采样历史。

100 机运行已减少重复的航段约束计算和整队占用扫描；控制台复用静态 Cesium 图形，并对轨迹更新与未变化的 WebSocket 快照做限流。本机无浏览器完整仿真 459 步约 44.7 秒（优化前约 70.5 秒），安全阈值与逐步轨迹复检保持不变。具体结果见[演示与指标](docs/demo.md)。

## 约束与精度

内部使用米制 ENU（x 东、y 北、z 离地）和固定仿真秒。simulation_speed=10 表示目标时间倍率，机器算力不足时墙钟进度可能跟不上。单个 FastAPI worker 持有仿真状态，不能直接加 worker 扩容。SQLite 在暂停、事件和正常关停时保存检查点；异常中断恢复最近检查点。飞行能耗是距离加爬升惩罚的代理量，天气为区域与风惩罚模型，建筑是程序化棱柱。平台适用于竞赛规划与仿真，不能代表真实飞行许可或物理级飞控。PostGIS、GNN、PPO/MAPPO 是后续替换方向，当前未实现。
