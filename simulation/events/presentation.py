"""Small immutable decision records for explaining real before/after flight changes."""

MAX_EXAMPLES = 3
MAX_PATH_POINTS = 128


def flight_evidence(engine, aircraft_id):
    aircraft = engine.aircraft.get(aircraft_id)
    if aircraft is None:
        return None
    plan = engine.plans.get(aircraft_id)
    points = [aircraft.position, *plan.positions[plan.cursor:]] if plan else []
    # Never decimate a route into straight chords through obstacles. Very long
    # paths are omitted; the actual distance and the omission remain explicit.
    omitted = len(points) > MAX_PATH_POINTS
    return {"position": aircraft.position.model_dump(),
            "path": [] if omitted else [point.model_dump() for point in points],
            "path_omitted": omitted,
            "planned_speed_mps": plan.speed_mps if plan else 0.0,
            "wait_s": plan.wait_s if plan else 0.0,
            "remaining_distance_m": plan.remaining_distance(aircraft.position) if plan else 0.0,
            "destination": aircraft.destination.model_dump() if aircraft.destination else None,
            "status": aircraft.status.value}


def capture_flights(engine, aircraft_ids):
    result = []
    for aircraft_id in dict.fromkeys(aircraft_ids):
        evidence = flight_evidence(engine, aircraft_id)
        if evidence is not None:
            result.append({"aircraft_id": aircraft_id, "before": evidence})
        if len(result) >= MAX_EXAMPLES:
            break
    return result


def decision_evidence(engine, before):
    return {"captured_at_s": engine.time_s,
            "examples": [{**item, "after": flight_evidence(engine, item["aircraft_id"])}
                         for item in before]}
