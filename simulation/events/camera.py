"""Read-only opening-shot cue based on the seeded plans before the first event."""
from copy import copy, deepcopy

from simulation.events.presentation import flight_evidence


def build_camera_cue(engine):
    from simulation.events.demo import TRIGGER_TIME, _area_for_scenario, _congestion_route, _crossing_choice, _failure_target

    trigger = 20 if engine.demo_scenario == "full" else TRIGGER_TIME[engine.demo_scenario]
    # Seeded opening flights are independent, separated corridors. Project copies
    # with the real motion integrator; never advance or edit the live simulation.
    projected = copy(engine)
    projected.aircraft = {key: aircraft.model_copy(deep=True) for key, aircraft in engine.aircraft.items()}
    projected.plans = deepcopy(engine.plans)
    for key, plan in projected.plans.items():
        plan.advance(projected.aircraft[key], trigger)
    projected.occupancy = {}
    for key, plan in projected.plans.items():
        if not plan.complete and plan.current_route:
            projected.occupancy[plan.current_route] = projected.occupancy.get(plan.current_route, 0) + 1
    scenario = engine.demo_scenario
    targets = []
    if scenario in ("congestion", "full"):
        route = _congestion_route(projected)
        targets = [key for key, plan in projected.plans.items() if route.id in plan.route_ids[plan.cursor-1:]]
    elif scenario in ("weather", "closure"):
        area = _area_for_scenario(projected, 2500)
        targets = [key for key, aircraft in projected.aircraft.items()
                   if area.contains(aircraft.position.xy) and 120 <= aircraft.position.z <= 230
                   and key in projected.plans and not projected.plans[key].complete]
    elif scenario == "failure":
        victim = _failure_target(projected)
        targets = [victim.id] if victim else []
    else:
        choice = _crossing_choice(projected)
        targets = list(choice[:2]) if choice else []
    if not targets:
        return None
    primary = targets[0]
    return {"aircraft_id": primary, "aircraft_ids": targets[:3], "event_at_s": trigger,
            "scenario": scenario, "initial_plan": flight_evidence(engine, primary)}
