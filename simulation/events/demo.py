"""Seeded initial conditions and timed disturbances; all outcomes are simulated."""

import random

from core.models import Event, EventType, Position3D, Severity, WaypointType
from simulation.aircraft.flight import FlightPlan
from simulation.environment.builder import CityBuilder, rectangle_polygon


SCENARIOS = {"full", "congestion", "weather", "closure", "failure", "conflict"}
TRIGGER_TIME = {"congestion": 10, "weather": 25, "closure": 25, "failure": 40, "conflict": 40}


def prepare_demo(engine, aircraft_count=100, seed=42, scenario="full"):
    if not 2 <= aircraft_count <= 500:
        raise ValueError("演示飞行器数量须为 2 至 500")
    if scenario not in SCENARIOS:
        raise ValueError(f"未知演示场景：{scenario}")
    if engine.running:
        raise RuntimeError("请先暂停再生成演示场景")
    rng = random.Random(seed)
    from simulation.events.traffic import build_city_traffic
    config, waypoints, routes, aircraft, missions = build_city_traffic(
        aircraft_count, rng, center_lanes=scenario != "full")
    config.building_seed = seed
    # Cruise points overfly the roofs. Reserve ground clearance for terminals.
    buildings = CityBuilder.generate_buildings(config, [w for w in waypoints.values()
        if w.type in (WaypointType.VERTIPORT, WaypointType.EMERGENCY_BAY)])
    staged=type(engine.environment)()
    with engine.registry.transaction():
        engine.registry.reset()
        for name,items in (("waypoints",waypoints.values()),("routes",routes),("aircraft",aircraft),("missions",missions)):
            for item in items: getattr(engine.registry,name).add(item)
        staged.apply_seed(config,buildings,engine.registry)
        engine.registry.set_metadata("environment", {"city_config":config.model_dump(mode="json"),
            "buildings":[b.model_dump(mode="json") for b in staged.city.buildings]})
    engine.environment.install_from(staged)
    engine.reset_runtime()
    engine.demo_enabled=True
    engine.demo_scenario=scenario
    engine._schedule()
    from simulation.events.camera import build_camera_cue
    camera_cue = build_camera_cue(engine)
    engine._record(Event(type=EventType.INFO,description=f"随机种子 {seed}：已生成 {aircraft_count} 架飞行器及任务，场景 {scenario}",
                         result={"seed":seed,"aircraft_count":aircraft_count,"scenario":scenario,"traffic_pattern":"four_way","camera_cue":camera_cue}))


def advance_demo(engine):
    if not engine.demo_enabled:
        return
    if engine.demo_scenario != "full":
        return _advance_single(engine)
    if engine.demo_stage==0 and engine.time_s>=20:
        _inject_congestion(engine)
        engine.demo_stage=1
    elif engine.demo_stage==1 and engine.time_s>=45:
        _inject_weather(engine)
        engine.demo_stage=2
    elif engine.demo_stage==2 and engine.time_s>=70:
        _inject_failure(engine)
        engine.demo_stage=3
    elif engine.demo_stage==3 and engine.time_s>=95:
        _crossing_intents(engine)
        engine.demo_stage=4
    if engine.demo_stage==4 and engine.time_s>=160 and engine.demo_weather_id in engine.weather:
        expired=engine.weather.pop(engine.demo_weather_id)
        from core.models import RouteStatus
        from simulation.environment.route_network import RouteNetwork
        for route in engine.routes.values():
            if route.status != RouteStatus.RESTRICTED:
                continue
            nodes=route.waypoint_ids or [route.start,route.end]
            intersects=any(expired.affected_area.intersects_segment(
                engine.waypoints[a].position.xy,engine.waypoints[b].position.xy)
                for a,b in zip(nodes,nodes[1:]))
            other_weather=any(any(w.affected_area.intersects_segment(
                engine.waypoints[a].position.xy,engine.waypoints[b].position.xy)
                for a,b in zip(nodes,nodes[1:])) for w in engine.weather.values())
            if intersects and not other_weather and not any(r.active and any(r.polygon.intersects_prism(
                engine.waypoints[a].position,engine.waypoints[b].position,r.min_altitude,r.max_altitude)
                for a,b in zip(nodes,nodes[1:])) for r in engine.restrictions.values()):
                route.status=RouteStatus.OPEN
        engine.environment.network=RouteNetwork.build(engine.waypoints.values(),engine.routes.values())
        engine.environment.version+=1
        engine._record(Event(type=EventType.INFO,description="演示雷暴消散，恢复受影响航路并继续调度",
                             result={"weather_id":expired.id,"affected_area":expired.affected_area.model_dump()}))
        engine._schedule()
    if engine.demo_stage==4 and engine.time_s>=220 and not engine.demo_complete:
        engine.demo_complete=True
        engine._record(Event(type=EventType.INFO,description="四类演示扰动已执行，运行指标已记录；剩余任务继续飞行",
            result={"demo_events_finished":True,"resolved_conflicts":engine.resolved_conflicts}))
        engine.checkpoint()
    if engine.demo_stage==4 and engine.time_s>=220:
        from core.models import MissionStatus
        terminal={MissionStatus.COMPLETED,MissionStatus.DIVERTED,MissionStatus.FAILED}
        if all(m.status in terminal for m in engine.missions.values()) or engine.time_s>=600:
            engine.running=False
            engine._record(Event(type=EventType.INFO,description="自动演示停止；未完成任务保留当前状态供检查",
                result={"completed":sum(m.status==MissionStatus.COMPLETED for m in engine.missions.values()),
                        "diverted":sum(m.status==MissionStatus.DIVERTED for m in engine.missions.values()),
                        "failed":sum(m.status==MissionStatus.FAILED for m in engine.missions.values()),
                        "pending":sum(m.status not in terminal for m in engine.missions.values())}))
            engine.checkpoint()
            return False


def _advance_single(engine):
    if engine.demo_complete:
        return
    scenario = engine.demo_scenario
    trigger = TRIGGER_TIME[scenario]
    if engine.demo_stage == 0 and engine.time_s >= trigger:
        if scenario == "congestion":
            _inject_congestion(engine)
        elif scenario == "weather":
            _inject_weather(engine, center_x=2500)
        elif scenario == "closure":
            _inject_closure(engine)
        elif scenario == "failure":
            _inject_failure(engine)
        else:
            _crossing_intents(engine)
        engine.demo_stage = 1
    if engine.demo_stage != 1:
        return
    if scenario in ("congestion", "weather", "closure"):
        observed = True
        ready = engine.time_s >= trigger + 80
    else:
        result_type = EventType.EMERGENCY_LANDING if scenario == "failure" else EventType.CONFLICT
        result = next((e for e in engine.events if e.type == result_type
                       and e.simulation_time >= trigger), None)
        observed = result is not None
        ready = observed and engine.time_s >= result.simulation_time + 30
    if ready or (not observed and engine.time_s >= 220):
        engine.demo_complete = True
        engine.running = False
        engine._record(Event(type=EventType.INFO, description=f"单项场景 {scenario} 已停止；结果来自实际仿真",
            result={"scenario": scenario, "observed": observed,
                    "resolved_conflicts": engine.resolved_conflicts,
                    "emergency_landings": sum(e.type == EventType.EMERGENCY_LANDING for e in engine.events)}))
        engine.checkpoint()
        return False


def _congestion_route(engine):
    return max(engine.routes.values(), key=lambda r: (engine.occupancy.get(r.id, 0), r.id))


def _inject_congestion(engine):
    route = _congestion_route(engine)
    return engine.inject_event(Event(type=EventType.ROUTE_CONGESTION, related_id=route.id,
        severity=Severity.WARNING, description="演示事件：航路容量下降，重新分配流量",
        payload={"capacity": 1}))


def _area_for_scenario(engine, center_x):
    """Place a reproducible disturbance on real eastern traffic in single demos."""
    cfg = engine.environment.city.config
    height = min(700, cfg.height * 0.3)
    center_y = cfg.height * 0.55
    if engine.demo_scenario in ("weather", "closure"):
        active = [a for a in engine.aircraft.values() if 120 <= a.position.z <= 230
                  and a.id in engine.plans and not engine.plans[a.id].complete]
        pairs = [(a, b) for index, a in enumerate(active) for b in active[index+1:]
                 if abs(a.position.z-b.position.z) < 1 and abs(a.heading-b.heading) < 1
                 and a.position.horizontal_distance_to(b.position) <= height * 0.6]
        if pairs:
            a, b = max(pairs, key=lambda pair: ((pair[0].position.x+pair[1].position.x)/2,
                                              -pair[0].position.distance_to(pair[1].position),
                                              pair[0].id, pair[1].id))
            center_x = (a.position.x+b.position.x)/2
            center_y = (a.position.y+b.position.y)/2
        elif active:
            a = max(active, key=lambda a: (a.position.x, a.id))
            center_x, center_y = a.position.x, a.position.y
    center_x = max(cfg.min_x+225, min(cfg.max_x-225, center_x))
    center_y = max(cfg.min_y+height/2, min(cfg.max_y-height/2, center_y))
    return rectangle_polygon(center_x, center_y, 450, height)


def _inject_weather(engine, center_x=2900):
    area = _area_for_scenario(engine, center_x)
    event = engine.inject_event(Event(type=EventType.WEATHER, severity=Severity.CRITICAL,
        description="演示事件：东部雷暴，动态更新禁入区域并重规划",
        payload={"affected_area":area.model_dump(), "wind_speed":22,
                 "visibility_m":1200, "precipitation":"thunderstorm"}))
    engine.demo_weather_id = event.result["weather_id"]
    return event


def _inject_closure(engine):
    area = _area_for_scenario(engine, 2500)
    return engine.inject_event(Event(type=EventType.AIRSPACE_CLOSURE, severity=Severity.WARNING,
        description="演示事件：城市东部临时空域管制",
        payload={"polygon":area.model_dump(), "min_altitude":120,
                 "max_altitude":230, "reason":"临时空域管制演示"}))


def _failure_target(engine):
    available=[a for a in engine.aircraft.values() if a.id in engine.plans and not engine.plans[a.id].complete]
    bays=[w for w in engine.waypoints.values() if w.type==WaypointType.EMERGENCY_BAY]
    return min(available,key=lambda a:min(a.position.distance_to(b.position) for b in bays)) if available and bays else None


def _inject_failure(engine):
    victim = _failure_target(engine)
    if victim is None:
        engine.alert("demo", "当前没有可注入故障的飞行器")
        return None
    return engine.inject_event(Event(type=EventType.AIRCRAFT_FAILURE,related_id=victim.id,
        severity=Severity.EMERGENCY, description="演示事件：动力故障，搜索可达备降点",
        payload={"range_derating":0.55}))


def _crossing_choice(engine):
    """Choose feasible crossing plans without mutating any aircraft or flight intent."""
    from simulation.engine.safety import feasible
    active=[a for a in engine.aircraft.values() if a.id in engine.plans and not engine.plans[a.id].complete
            and not engine.plans[a.id].emergency_bay and a.position.z>=140]
    if engine.demo_scenario == "full":
        # Demonstrate a separate crossing, rather than adding a new shared goal
        # to aircraft still evacuating or recovering from the weather event.
        disturbed = {aircraft_id for event in engine.events
                     if event.type in (EventType.WEATHER, EventType.AIRSPACE_CLOSURE)
                     for aircraft_id in event.result.get("affected_aircraft", [])}
        active = [a for a in active if a.id not in disturbed]
    choices=[]
    for i,a in enumerate(active):
        for b in active[i+1:]:
            distance=a.position.distance_to(b.position)
            if 60<distance<400 and abs(a.position.z-b.position.z)<1:
                choices.append((distance,a.id,b.id))
    for _,a_id,b_id in sorted(choices):
        a,b=engine.aircraft[a_id],engine.aircraft[b_id]
        meeting=Position3D(x=(a.position.x+b.position.x)/2+120,
                          y=(a.position.y+b.position.y)/2,z=a.position.z)
        pa=FlightPlan([a.position.model_copy(),meeting,*engine.plans[a_id].positions[engine.plans[a_id].cursor:]],[],speed_mps=15)
        pb=FlightPlan([b.position.model_copy(),meeting,*engine.plans[b_id].positions[engine.plans[b_id].cursor:]],[],speed_mps=15)
        if feasible(engine,a,pa) and feasible(engine,b,pb):
            return a_id, b_id, pa, pb, meeting
    return None


def _crossing_intents(engine):
    """Change flight intents through a shared point, without moving aircraft positions."""
    choice = _crossing_choice(engine)
    if choice:
        a_id, b_id, pa, pb, meeting = choice
        engine.plans[a_id],engine.plans[b_id]=pa,pb
        engine._record(Event(type=EventType.INFO,description="演示事件 4：两机任务意图出现交汇，交由预测检测与解脱",
            result={"aircraft_a":a_id,"aircraft_b":b_id,"meeting_point":meeting.model_dump()}))
        return True
    engine.alert("demo", "当前场景没有可安全构造交汇意图的两架飞机；未伪造冲突结果")
    return False
