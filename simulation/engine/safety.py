"""Rule candidates are checked for physical continuity, obstacles and fleet separation."""

from copy import copy, deepcopy

from algorithms.conflict_detection import ConflictThresholds, TrajectoryPoint, detect_conflicts
from algorithms.conflict_resolution import ResolutionCandidate, ResolutionEnvironment, ResolutionWeights, resolve_conflict
from algorithms.path_planning import PlanningError
from core.models import AircraftStatus, Event, EventType, Position3D, PrecipitationType, Severity
from simulation.aircraft.flight import FlightPlan
from simulation.engine.planning import plan_flight
from simulation.events.presentation import capture_flights, decision_evidence


def thresholds(engine):
    return ConflictThresholds(horizontal_m=engine.settings.conflict_horizontal_separation_m,
        vertical_m=engine.settings.conflict_vertical_separation_m,
        time_window_s=max(engine.tick_seconds, engine.settings.conflict_time_window_s))


def forecast(engine, limits):
    result = {}
    for aircraft_id, aircraft in engine.aircraft.items():
        plan = engine.plans.get(aircraft_id)
        if aircraft.status == AircraftStatus.OFFLINE or (aircraft.position.z <= 0 and (not plan or plan.complete)):
            continue
        if plan and not plan.complete:
            result[aircraft_id] = forecast_plan(engine, aircraft_id, plan, limits)
        else:
            result[aircraft_id] = [TrajectoryPoint(time=engine.time_s, position=aircraft.position),
                TrajectoryPoint(time=engine.time_s + limits.time_window_s, position=aircraft.position)]
    return result


def forecast_plan(engine, aircraft_id, plan, limits):
    """Prediction uses the same motion, range and capacity gates as execution."""
    aircraft = engine.aircraft[aircraft_id].model_copy(deep=True)
    predicted = copy(plan)  # advance changes cursor/wait only; route and position lists are read-only.
    trace = []
    predicted.advance(aircraft, limits.time_window_s,
        lambda cursor: engine._can_enter(aircraft_id, predicted, cursor, position=aircraft.position), trace)
    return [TrajectoryPoint(time=engine.time_s+offset, position=point) for offset,point in trace]


def feasible(engine, aircraft, plan):
    points = [aircraft.position, *plan.positions[plan.cursor:]]
    energy = 0.0
    for index, (a, b) in enumerate(zip(points, points[1:])):
        energy += a.distance_to(b) + 4 * max(0.0, b.z-a.z)
        if not 0 <= b.z <= 300 or not engine.collision_city.is_segment_clear(a, b):
            return False
        egress = index == 0 and plan.egress_target == b
        if any(r.active and r.polygon.intersects_prism(a, b, r.min_altitude, r.max_altitude)
               and not (egress and r.polygon.intersects_prism(a, a, r.min_altitude, r.max_altitude)
                        and not r.polygon.intersects_prism(b, b, r.min_altitude, r.max_altitude))
               for r in engine.restrictions.values()):
            return False
        if any(w.precipitation == PrecipitationType.THUNDERSTORM and
               w.affected_area.intersects_segment(a.xy, b.xy) and
               not (egress and w.affected_area.contains(a.xy) and not w.affected_area.contains(b.xy))
               for w in engine.weather.values()):
            return False
    return energy <= aircraft.battery * aircraft.max_range_m + 1e-6


def candidates(engine, conflict, limits):
    options, plans = [], {}
    for aircraft_id in (conflict.aircraft_a, conflict.aircraft_b):
        aircraft = engine.aircraft[aircraft_id]
        original = engine.plans.get(aircraft_id)
        if not original or original.complete:
            continue
        proposed = []
        for multiplier in (0.5, 0.75, 1.25):
            plan = deepcopy(original)
            plan.speed_mps = min(aircraft.max_speed, max(1, plan.speed_mps*multiplier))
            proposed.append(("speed", plan))
        delayed = deepcopy(original)
        delayed.wait_s += limits.time_window_s + 2
        proposed.append(("delay", delayed))
        for sign in (1, -1):
            change = engine.settings.conflict_altitude_step_m * sign
            points = [aircraft.position, aircraft.position.model_copy(update={"z": aircraft.position.z+change})]
            points += [p.model_copy(update={"z": p.z+change}) for p in original.positions[original.cursor:]]
            points.append(original.positions[-1])
            plan = FlightPlan(positions=points, node_ids=["@altitude"]*len(points),
                speed_mps=original.speed_mps, route_ids=[None]*(len(points)-1),
                emergency_bay=original.emergency_bay,
                vertical_speed_mps=engine.settings.conflict_max_vertical_speed_mps)
            proposed.append(("altitude", plan))
        if len(original.node_ids) > original.cursor:
            blocked = {(original.node_ids[original.cursor-1], original.node_ids[original.cursor])}
            try:
                rerouted = plan_flight(engine, aircraft, original.positions[-1], blocked_edges=blocked,
                    max_distance=aircraft.battery*aircraft.max_range_m, emergency_bay=original.emergency_bay)
                if rerouted.positions != original.positions:
                    proposed.append(("reroute", rerouted))
            except PlanningError:
                pass
        for action, plan in proposed:
            if not feasible(engine, aircraft, plan):
                continue
            key = f"{aircraft_id}:{len(plans)}"
            plans[key] = plan
            extra = max(0, plan.remaining_energy(aircraft.position)-original.remaining_energy(aircraft.position))
            route_ids = {r for r in plan.route_ids[plan.cursor-1:] if r in engine.routes}
            congestion = sum(engine.occupancy.get(r, 0)/engine.routes[r].capacity for r in route_ids)
            options.append(ResolutionCandidate(action=action, aircraft_id=aircraft_id,
                trajectory=forecast_plan(engine, aircraft_id, plan, limits),
                delay_s=max(0, plan.remaining_time(aircraft.position)-original.remaining_time(aircraft.position)),
                extra_energy=extra/1000, congestion_cost=congestion,
                parameters={"candidate_key": key, "speed_mps": plan.speed_mps,
                            "wait_s": plan.wait_s, "altitude_m": plan.positions[min(plan.cursor,len(plan.positions)-1)].z}))
    return options, plans


def manage_conflicts(engine):
    limits = thresholds(engine)
    trajectories = forecast(engine, limits)
    before = detect_conflicts(trajectories, limits, engine.time_s)
    weights = ResolutionWeights(**{name: getattr(engine.settings, f"conflict_resolution_weight_{name}")
                                  for name in ("delay", "energy", "congestion")})
    for conflict in before[:30]:
        pair = {name: trajectories[name] for name in (conflict.aircraft_a, conflict.aircraft_b)}
        if not detect_conflicts(pair, limits, engine.time_s):
            continue
        options, plans = candidates(engine, conflict, limits)
        decision = resolve_conflict(conflict, ResolutionEnvironment(trajectories=trajectories,
            candidates=options, priorities={key:a.priority for key,a in engine.aircraft.items()},
            thresholds=limits, now=engine.time_s, weights=weights))
        if decision.success:
            aircraft_id = decision.aircraft_id
            previous = capture_flights(engine, [aircraft_id, conflict.aircraft_a, conflict.aircraft_b])
            plan = plans[decision.parameters["candidate_key"]]
            engine.plans[aircraft_id] = plan
            trajectories[aircraft_id] = forecast_plan(engine, aircraft_id, plan, limits)
            engine.resolved_conflicts += 1
            engine._record(Event(type=EventType.CONFLICT, severity=Severity.WARNING,
                location=conflict.conflict_position, related_id=aircraft_id,
                description=f"{conflict.aircraft_a} / {conflict.aircraft_b} 预测冲突，执行 {decision.action}",
                result={**decision.model_dump(mode="json"), "predicted_conflict":conflict.model_dump(mode="json"),
                        "presentation":decision_evidence(engine, previous)}))
        else:
            engine.alert(conflict.aircraft_a, f"与 {conflict.aircraft_b} 的预测冲突尚无安全候选方案")
    engine.conflicts = detect_conflicts(trajectories, limits, engine.time_s)
    engine.detected_conflicts = len(before)
    # Never advance through an unresolved imminent collision just to keep the demo moving.
    if any(c.conflict_time <= engine.time_s+engine.tick_seconds for c in engine.conflicts):
        for plan in engine.plans.values():
            plan.wait_s = max(plan.wait_s, engine.tick_seconds)
        engine.running = False
        engine.alert("fleet", "临近冲突未解脱，仿真已暂停，需调整任务或空域后恢复")
        return False
    return True
