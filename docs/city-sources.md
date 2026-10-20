# 3D 城市来源与改造说明

本次从 GitHub 实际检索、阅读并比较了下面的城市演示。最终采用两个 MIT 项目的具体渲染方法，改造成项目内的 TypeScript 城市模块，而不是嵌入外部网站。运行不需要地图 API key、在线瓦片或外部模型下载。

| 项目 | 完成度与可取之处 | 许可 / 取舍 |
| --- | --- | --- |
| [jstrait/city-tour](https://github.com/jstrait/city-tour) | 完整的地形、道路、建筑分区、自动飞行巡览，仓库有渲染与生成器测试；建筑用 InstancedMesh 批量生成 | MIT；采用建筑原型矩阵 / 实例渲染方法，直接读取本项目登记建筑 |
| [jeromeetienne/threex.proceduralcity](https://github.com/jeromeetienne/threex.proceduralcity) | 经典程序城市，极少代码生成密集楼宇和随机窗格，无模型依赖 | MIT；采用低分辨率 Canvas 窗格并关闭平滑放大的方法，升级到 Three.js 0.180、确定性纹理与夜间发光 |
| [furic/unmask-the-city](https://github.com/furic/unmask-the-city) | 有昼夜主题、水面、公园和实例建筑，独立完整浏览器游戏 | 仓库说明声明 MIT；玩法、战争迷雾及控制器与无人机控制台差异较大，本次未复制代码 |
| [RoySung/thress-building-playground](https://github.com/RoySung/thress-building-playground) | 街景 GLB、天气、车流与多种巡航模式 | README 声明代码 MIT，但 MODEL_CREDITS.md 明确原始模型不可重新分发；本次未使用其代码或模型 |
| [rebollo507/Metropolis](https://github.com/rebollo507/Metropolis) | 建筑生成、滨水、昼夜、街景和完整城市建设系统 | README 声明 ISC；系统体量大、约 1300 draw calls，且作者说明真实硬件帧率未实测，本次未复制代码 |

## 实际采用的上游文件

- City Tour: [src/meshes/building_mesh_builder.js](https://github.com/jstrait/city-tour/blob/master/src/meshes/building_mesh_builder.js)，读取时文件 SHA 为 `59d170c6d99a8ffe765da602831377b8ec8e338f`。采用 `Object3D` 原型的位置/缩放矩阵、`InstancedMesh.setMatrixAt` 及每实例颜色的建筑批量渲染结构。
- THREEx: [threex.proceduralcity.js](https://github.com/jeromeetienne/threex.proceduralcity/blob/master/threex.proceduralcity.js)，读取时文件 SHA 为 `8020c7c6b3c1d1c7567139a19f9fe737cac6436f`。采用 `generateTextureCanvas()` 的小尺寸 Canvas 窗格、亮度变化和不平滑放大过程。

两份完整原始文件保存在 `frontend/public/licenses/sources/`，两份完整 MIT 版权及许可文本保存在 `frontend/public/licenses/`。版权属于 Joel Strait 与 Jerome Etienne。改造文件为 `frontend/src/scene/urban.ts`。

## 本项目适配

建筑位置、平面轮廓、楼底 elevation 与高度都来自 `environment.buildings`。矩形建筑批量渲染，任意多边形以原始 footprint 精确挤出。屋顶设备以表面纹理表现，没有额外加高楼宇。固定世界尺度的窗格保证不同楼高不会把窗口拉伸；夜间窗光单独控制。

路网严格跟随 `CityBuilder` 的 200 米街区周期和 40 米街道宽度，街树、斑马线、灯具与地面车流采用实例绘制。未开发街区布置草坪和低矮植被，起降点附近保留净空，滨水景观位于仿真 bounds 以外。地面车流只是城市装饰，不改变无人机的模拟状态。

无人机模型、真实航路、轨迹、空域管制、气象、冲突和应急事件由 `CityScene.vue` 叠加，继续使用服务端的 Snapshot 数据。

## 效果与验证

- [城市昼夜与街景截图](assets/city-demo-preview.png)
- [故障备降与事件镜头截图](assets/drone-event-preview.png)
- `npm run build`：Vue/TypeScript 检查及正式构建通过。
- `npm run test:scene-events`：23 项基于真实事件快照的检查通过。
- 后端单项场景、闭环仿真、安全与城市生成回归：55 项通过。
- 实际浏览器检查：100 架无人机、昼夜切换、三种镜头、选机与退出跟踪、五类事件及跨场景清理、巡游被新事件正确中止、390px 手机布局均通过，无页面或着色器错误。

浏览器验收使用独立临时 SQLite 数据库，不改动原有运行数据。截图中的地面车流和街景仅作城市装饰；飞行状态、事件影响数量、备降路径和指标均来自后端。
