"""Each preset injects only its chosen disturbance and measures its own outcome."""

from itertools import combinations

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import Event, EventType, Polygon2D, Position3D
from core.repository import create_registry
from simulation.engine import Engine
from simulation.events.demo import TRIGGER_TIME, advance_demo


@pytest.mark.parametrize(("scenario", "event_type"), [
    ("congestion", EventType.ROUTE_CONGESTION),
    ("weather", EventType.WEATHER),
    ("closure", EventType.AIRSPACE_CLOSURE),
    ("failure", EventType.AIRCRAFT_FAILURE),
    ("conflict", EventType.CONFLICT),
])
def test_single_scenario_is_isolated_and_has_observed_result(scenario, event_type):
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(24, 42, scenario)
        assert engine.snapshot()["simulation"]["demo_scenario"] == scenario
        engine.step(TRIGGER_TIME[scenario])
        assert event_type not in {e.type for e in engine.events}
        engine.step(220)
        assert engine.demo_complete and not engine.running and engine.time_s <= 220
        targeted = [e for e in engine.events if e.type == event_type]
        assert targeted and all(e.handled for e in targeted)
        other_disturbances = {EventType.ROUTE_CONGESTION, EventType.WEATHER,
                              EventType.AIRSPACE_CLOSURE, EventType.AIRCRAFT_FAILURE} - {event_type}
        assert not any(e.type in other_disturbances for e in engine.events)
        if scenario in {"congestion", "weather", "closure"}:
            assert targeted[0].result["affected_aircraft"]
            assert targeted[0].result["replanned_aircraft"]
            assert engine.time_s == TRIGGER_TIME[scenario] + 80
        if scenario == "failure":
            assert targeted[0].result["success"]
            assert any(e.type == EventType.EMERGENCY_LANDING and e.result["landed"] for e in engine.events)
        if scenario == "conflict":
            assert engine.resolved_conflicts > 0
        if scenario in {"failure", "conflict"}:
            result_type = EventType.EMERGENCY_LANDING if scenario == "failure" else EventType.CONFLICT
            result = next(e for e in engine.events if e.type == result_type
                          and e.simulation_time >= TRIGGER_TIME[scenario])
            assert engine.time_s == result.simulation_time + 30
        assert engine.report()["simulation"]["demo_scenario"] == scenario
    finally:
        registry.close()


def test_single_scenario_without_result_stops_at_220():
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(2, 42, "failure")
        engine.demo_stage = 1
        engine.time_s = 219
        engine.step(1)
        assert engine.time_s == 220 and not engine.demo_complete
        engine.step(1)
        assert engine.time_s == 220 and engine.demo_complete and not engine.running
        assert engine.events[-1].result["observed"] is False
    finally:
        registry.close()


@pytest.mark.parametrize(("scenario", "result_type"), [
    ("failure", EventType.EMERGENCY_LANDING),
    ("conflict", EventType.CONFLICT),
])
def test_late_observed_result_keeps_full_30_seconds(scenario, result_type):
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(2, 42, scenario)
        engine.demo_stage = 1
        engine.time_s = 200
        engine._record(Event(type=result_type))
        for time_s in (220, 229):
            engine.time_s = time_s
            advance_demo(engine)
            assert not engine.demo_complete
        engine.time_s = 230
        advance_demo(engine)
        assert engine.demo_complete and not engine.running
        assert engine.events[-1].result["observed"] is True
    finally:
        registry.close()


def test_switching_scenarios_resets_previous_events_and_metrics():
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(24, 42, "congestion")
        engine.step(11)
        assert any(e.type == EventType.ROUTE_CONGESTION for e in engine.events)
        engine.prepare_demo(24, 42, "weather")
        assert engine.time_s == 0 and engine.demo_stage == 0
        assert not any(e.type == EventType.ROUTE_CONGESTION for e in engine.events)
        assert engine.snapshot()["metrics"]["alert_count"] == 0
    finally:
        registry.close()


def test_selected_scenario_survives_sqlite_restart(tmp_path):
    database = tmp_path / "scenario.sqlite3"
    with TestClient(create_app(database_path=database)) as client:
        response = client.post("/api/simulation/demo", json={"aircraft_count": 24, "scenario": "closure"})
        assert response.status_code == 200
        assert response.json()["simulation"]["demo_scenario"] == "closure"
        assert client.post("/api/simulation/demo", json={"scenario": "unknown"}).status_code == 422
        client.post("/api/simulation/step", json={"steps": 26})
    with TestClient(create_app(database_path=database)) as client:
        state = client.get("/api/simulation/state").json()
        assert state["simulation"]["demo_scenario"] == "closure"
        events = [e for e in state["events"] if e["type"] == EventType.AIRSPACE_CLOSURE]
        assert len(events) == 1 and len(events[0]["result"]["evacuating_aircraft"]) >= 2
        area = next(r["polygon"] for r in state["restrictions"] if r["id"] == events[0]["result"]["restriction_id"])
        state = client.post("/api/simulation/step", json={"steps": 19}).json()
        assert sum(e["type"] == EventType.AIRSPACE_CLOSURE for e in state["events"]) == 1
        polygon = Polygon2D.model_validate(area)
        assert all(not polygon.contains(Position3D.model_validate(a["position"]).xy)
                   for a in state["aircraft"] if a["id"] in events[0]["result"]["evacuating_aircraft"])
        assert not state["conflicts"]


@pytest.mark.parametrize(("scenario", "event_type"), [
    ("weather", EventType.WEATHER),
    ("closure", EventType.AIRSPACE_CLOSURE),
])
def test_area_scenario_evacuates_aircraft_inside_and_keeps_separation(scenario, event_type):
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(24, 42, scenario)
        engine.step(26)
        event = next(e for e in engine.events if e.type == event_type)
        assert event.result["affected_aircraft"]
        assert set(event.result["affected_aircraft"]) == set(event.result["replanned_aircraft"])
        assert not event.result["holding_aircraft"]
        assert not event.result["residual_conflicts"]
        assert len(event.result["evacuating_aircraft"]) >= 2
        assert not event.result["safe_exit_holding_aircraft"]
        area = (engine.weather[event.result["weather_id"]].affected_area if scenario == "weather"
                else engine.restrictions[event.result["restriction_id"]].polygon)
        for aircraft_id in event.result["evacuating_aircraft"]:
            aircraft = engine.aircraft[aircraft_id]
            plan = engine.plans[aircraft_id]
            assert area.contains(aircraft.position.xy)
            assert plan.egress_target and not area.contains(plan.egress_target.xy)
            assert aircraft.speed > 0
        for aircraft_id in event.result["replanned_aircraft"]:
            plan = engine.plans[aircraft_id]
            points = plan.positions[1:] if plan.egress_target else [engine.aircraft[aircraft_id].position, *plan.positions[plan.cursor:]]
            assert all(not area.intersects_segment(a.xy, b.xy) for a, b in zip(points, points[1:]))
        while engine.time_s < 80:
            previous = engine.time_s
            engine.step(1)
            assert engine.time_s == previous + engine.tick_seconds
            assert not engine.conflicts
            airborne = [a.position for a in engine.aircraft.values() if a.position.z > 0]
            for left, right in combinations(airborne, 2):
                if abs(left.z - right.z) <= engine.settings.conflict_vertical_separation_m:
                    assert left.horizontal_distance_to(right) > engine.settings.conflict_horizontal_separation_m
            if engine.time_s >= 45:
                assert all(not area.contains(engine.aircraft[aircraft_id].position.xy)
                           for aircraft_id in event.result["evacuating_aircraft"])
        engine.step(24)
        assert engine.time_s == 104 and not engine.demo_complete
        engine.step(1)
        assert engine.time_s == 105 and not engine.demo_complete
        engine.step(1)
        assert engine.time_s == 105 and engine.demo_complete
    finally:
        registry.close()
