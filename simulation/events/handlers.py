"""Validate event payloads, update constraints, then replan from actual positions."""

from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field

from algorithms.emergency.diversion import divert_aircraft
from core.models import AirspaceRestriction, EventType, RouteStatus, Weather
from simulation.environment.builder import rectangle_polygon
from simulation.environment.route_network import RouteNetwork
from simulation.events.presentation import capture_flights, decision_evidence


class CongestionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capacity: int = Field(default=1, ge=1)


class FailurePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range_derating: float = Field(default=0.55, gt=0, le=1, allow_inf_nan=False)


def default_area(engine):
    if engine.environment.city is None:
        raise RuntimeError("请先加载城市环境")
    config = engine.environment.city.config
    return rectangle_polygon(config.min_x + config.width * 0.78,
                             config.min_y + config.height * 0.55,
                             config.width * 0.14, config.height * 0.3)


def process_event(engine, event):
    started = perf_counter()
    before = []
    if any(item.id == event.id for item in engine.events) or engine.registry.events.exists(event.id):
        raise ValueError(f"事件 {event.id} 已存在")
    # Parse every trusted value before writing any model or graph state.
    if event.type == EventType.WEATHER:
        payload = dict(event.payload.get("weather", event.payload))
        payload.setdefault("affected_area", default_area(engine).model_dump())
        payload.setdefault("precipitation", "thunderstorm")
        payload.setdefault("wind_speed", 20)
        weather = Weather.model_validate(payload)
        engine.weather[weather.id] = weather
        area = weather.affected_area
        affected = affected_aircraft(engine, lambda a, b: area.intersects_segment(a.xy, b.xy))
        inside = [key for key in affected if area.contains(engine.aircraft[key].position.xy)]
        before = capture_flights(engine, [*inside, *affected])
        changed = mark_routes(engine, lambda a, b: area.intersects_segment(a.xy, b.xy), RouteStatus.RESTRICTED)
        result = replan_affected(engine, affected)
        result.update(weather_id=weather.id, affected_routes=changed)
    elif event.type == EventType.AIRSPACE_CLOSURE:
        payload = dict(event.payload)
        payload.setdefault("polygon", default_area(engine).model_dump())
        payload.setdefault("reason", event.description or "临时空域管制")
        restriction = AirspaceRestriction.model_validate(payload)
        engine.restrictions[restriction.id] = restriction
        intersects = lambda a, b: restriction.active and restriction.polygon.intersects_prism(a, b, restriction.min_altitude, restriction.max_altitude)
        affected = affected_aircraft(engine, intersects)
        inside = [key for key in affected if intersects(engine.aircraft[key].position, engine.aircraft[key].position)]
        before = capture_flights(engine, [*inside, *affected])
        changed = mark_routes(engine, intersects, RouteStatus.RESTRICTED)
        result = replan_affected(engine, affected)
        result.update(restriction_id=restriction.id, affected_routes=changed)
    elif event.type == EventType.ROUTE_CONGESTION:
        parameters = CongestionPayload.model_validate(event.payload)
        if event.related_id not in engine.routes:
            raise KeyError(event.related_id or "missing route id")
        route = engine.routes[event.related_id]
        old_capacity = route.capacity
        route.capacity = parameters.capacity
        route.status = RouteStatus.CONGESTED
        engine.environment.network = RouteNetwork.build(engine.waypoints.values(), engine.routes.values())
        engine.environment.version += 1
        affected = [aircraft_id for aircraft_id, plan in engine.plans.items() if route.id in plan.route_ids[plan.cursor - 1:]]
        before = capture_flights(engine, affected)
        result = replan_affected(engine, affected)
        result.update(route_id=route.id, old_capacity=old_capacity, capacity=route.capacity,
                      observed_flow=engine.occupancy.get(route.id, 0))
    elif event.type == EventType.AIRCRAFT_FAILURE:
        parameters = FailurePayload.model_validate(event.payload)
        if event.related_id not in engine.aircraft:
            raise KeyError(event.related_id or "missing aircraft id")
        before = capture_flights(engine, [event.related_id])
        result = divert_aircraft(engine, event.related_id, parameters.range_derating)
    elif event.type in (EventType.INFO, EventType.CONFLICT):
        result = {"success": True, "recorded": True}
    else:
        raise ValueError("应急着陆事件仅由飞行状态推进生成")
    if event.type in (EventType.WEATHER, EventType.AIRSPACE_CLOSURE,
                      EventType.ROUTE_CONGESTION, EventType.AIRCRAFT_FAILURE):
        # New routes and hovering aircraft join the same fleet-wide safety check
        # immediately; every subsequent movement tick checks again.
        from simulation.engine.safety import manage_conflicts
        safe_to_advance = manage_conflicts(engine)
        result["residual_conflicts"] = len(engine.conflicts)
        result["paused_for_safety"] = not safe_to_advance
    if before:
        result["presentation"] = decision_evidence(engine, before)
    event.result = result
    event.processing_ms = (perf_counter() - started) * 1000
    engine._record(event)
    engine._measure_occupancy()
    return event


def affected_aircraft(engine, intersects):
    affected = []
    for aircraft_id, aircraft in engine.aircraft.items():
        plan = engine.plans.get(aircraft_id)
        if aircraft.position.z > 0 and intersects(aircraft.position, aircraft.position):
            affected.append(aircraft_id)
        elif plan and not plan.complete:
            points = [aircraft.position, *plan.positions[plan.cursor:]]
            if any(intersects(a, b) for a, b in zip(points, points[1:])):
                affected.append(aircraft_id)
    return affected


def mark_routes(engine, intersects, status):
    changed = []
    for route in engine.routes.values():
        nodes = route.waypoint_ids or [route.start, route.end]
        if any(intersects(engine.waypoints[a].position, engine.waypoints[b].position) for a, b in zip(nodes, nodes[1:])):
            if route.status != RouteStatus.CLOSED:
                route.status = status
            changed.append(route.id)
    engine.environment.network = RouteNetwork.build(engine.waypoints.values(), engine.routes.values())
    engine.environment.version += 1
    return changed


def replan_affected(engine, affected):
    replanned, held, evacuating, safe_holding = [], [], [], []
    for aircraft_id in affected:
        old_plan = engine.plans.get(aircraft_id)
        emergency_bay = old_plan.emergency_bay if old_plan else None
        if engine.replan(aircraft_id, emergency_bay=emergency_bay):
            replanned.append(aircraft_id)
            plan = engine.plans[aircraft_id]
            if plan.egress_target:
                evacuating.append(aircraft_id)
            if plan.egress_only:
                safe_holding.append(aircraft_id)
        else:
            held.append(aircraft_id)
    return {"success": not held, "affected_aircraft": affected, "replanned_aircraft": replanned,
            "holding_aircraft": held, "evacuating_aircraft": evacuating,
            "safe_exit_holding_aircraft": safe_holding}
