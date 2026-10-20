# API 与实时协议

启动后查看 `/docs`（交互式）和 `/openapi.json`（机器可读完整 schema）。
HTTP API 使用 `/api` 前缀。错误统一为：

```json
{"error":{"code":"invalid_reference","message":"...","details":{}}}
```

请求响应包含 `X-Request-ID`。基本状态码：201 创建、204 删除、404 不存在、409 状态冲突、422 校验或规划失败。

## 基础实体

`/aircraft`、`/waypoints`、`/routes`、`/missions`、`/weather`、`/restrictions`、`/events`
提供 GET 列表、GET `/{id}`；基础编辑使用 POST、PUT `/{id}`、DELETE `/{id}`。
其中 `POST /api/events` 是即时事件注入：返回带 `handled`、`processing_ms` 和 `result` 的已处理记录。已处理事件不可编辑或删除。
PUT 替换可写字段，路径 ID 是固定标识；内部统计字段保留，禁止客户端写入。
删除存在任务/航路引用的实体返回 409。运行中基础编辑返回 409，应先暂停或注入事件。

## 环境与规划

| 方法 | 路径 | 含义 |
| --- | --- | --- |
| GET | `/api/health` | 进程健康与版本 |
| GET | `/api/system/summary` | 持久化实体数量 |
| POST | `/api/system/seed` | 加载小型基础场景，清空原场景 |
| POST | `/api/system/reset` | 清空场景与运行数据 |
| GET | `/api/environment/summary` | 城市原点、边界、栅格统计 |
| GET | `/api/environment/buildings` | 实际生成的建筑 |
| GET | `/api/environment/route-network` | 有向航路图 |
| GET | `/api/environment/validation` | 建筑碰撞检查 |
| POST | `/api/environment/generate-network` | 安全邻接航段生成 |
| POST | `/api/planning/path` | 多项加权 A* |

规划示例：

```json
{"source":"WP01","target":"WP09","dimension":"3d","speed_mps":15,"respect_capacity":true,"weights":{"distance":1,"risk":2,"congestion":1.5,"energy":0.8,"weather":3}}
```

响应包含 node_ids、positions、distance_m、total_cost、cost_breakdown、estimated_duration_s、algorithm、explanation、environment_version。
`dimension=2d` 限制为起点所在高度层。无可行路径返回具体原因，不穿越硬约束强行返回路径。

## 仿真

| 方法 | 路径 | 请求 |
| --- | --- | --- |
| GET | `/api/simulation/state` | 完整运行快照 |
| POST | `/api/simulation/demo` | `{"aircraft_count":100,"seed":42,"scenario":"full"}`，生成后暂停 |
| POST | `/api/simulation/start` | 启动/恢复 |
| POST | `/api/simulation/pause` | 暂停并保存检查点 |
| POST | `/api/simulation/speed` | `{"speed":10}` |
| POST | `/api/simulation/step` | `{"steps":1}`，仅暂停时可用 |
| GET | `/api/simulation/report` | 实际指标、历史序列和事件结果 |

`scenario` 可选 `full`、`congestion`、`weather`、`closure`、`failure`、`conflict`。五个单项场景建议指定 `aircraft_count:24`。返回快照的 `simulation.demo_scenario` 标明当前场景；切换场景清空原运行数据并从仿真零秒重新开始。

事件示例（经 `POST /api/events`）：

```json
{"type":"event_route_congestion","related_id":"R-L0Y0X0-L0Y0X1","severity":"warning","payload":{"capacity":1}}
```

```json
{"type":"event_aircraft_failure","related_id":"UAV-001","severity":"emergency","payload":{"range_derating":0.55}}
```

`event_weather` 的 `payload` 可含 `affected_area`（以局部米制 x/y 定义的 `points` 多边形）、`wind_speed`、`visibility_m` 和 `precipitation`；`event_airspace_closure` 可含 `polygon`、`min_altitude`、`max_altitude` 和 `reason`。完整模型可在 `/docs` 中查看。每次事件记录受影响飞行器、已改航/等待飞行器及处理耗时；雷暴与管制事件的 `result.evacuating_aircraft` 列出事件发生时位于区域内、正在沿安全出口撤离的飞行器。若出口可达但后续航路暂不可达，则列入 `safe_exit_holding_aircraft`，先撤离至区域外再等待；完全没有安全出口的飞行器列入 `holding_aircraft` 并告警。扰动事件还返回全机复检后的 `residual_conflicts` 和 `paused_for_safety`。故障记录备降点与计划航路，实际到达另有 `event_emergency_landing` 记录。

## WebSocket

连接 `/api/ws`，运行状态变化时服务端约每 200ms 发送一个快照；状态不变时约每 2 秒发送一次，以减少重复序列化和浏览器重绘：

```json
{"type":"snapshot","sequence":1,"data":{"version":1,"environment_version":1,"environment":{},"waypoints":[],"simulation":{},"aircraft":[],"metrics":{},"history":[],"events":[]}}
```

首帧包含完整 `environment` 和 `waypoints`；`environment_version` 变化时重新发送两者，版本不变的帧省略它们。客户端保存最近的环境与航点，每次重连从首帧重新获取。
WebSocket 帧不包含前端未使用的 `missions`，`history` 只包含最近 240 条。`GET /api/simulation/state` 仍返回完整任务与历史记录；报告仍返回完整历史记录。
`sequence` 仅在当前连接内递增。其余运行动态数据为完整快照，不需要补放丢失的帧；慢客户端不会让仿真阻塞或无限缓存消息。
