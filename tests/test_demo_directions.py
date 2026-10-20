"""Four-way tasks must create real separated motion, not only turn the models."""
from collections import Counter
from itertools import combinations

import pytest

from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import Aircraft, EventType, Position3D
from core.repository import create_registry
from simulation.aircraft.flight import FlightPlan
from simulation.engine import Engine


@pytest.fixture
def engine():
    registry = create_registry()
    value = Engine(registry, EnvironmentService(), Settings(_env_file=None))
    yield value
    registry.close()


@pytest.mark.parametrize("count", [2, 4, 9, 100])
def test_full_demo_distributes_real_tasks_across_four_directions(engine, count):
    engine.prepare_demo(count, 42)
    headings = Counter(a.heading for a in engine.aircraft.values())
    assert set(headings) == ({90, 270} if count == 2 else {0, 90, 180, 270})
    assert max(headings.values()) - min(headings.values()) <= 1
    assert len(engine.plans) == count
    if count == 100:
        assert engine.environment.city.building_count >= 150
        assert not engine.environment.network.validate_against_city(engine.environment.city)
    assert len({(m.destination.x, m.destination.y) for m in engine.missions.values()}) == count
    for mission in engine.missions.values():
        drone = engine.aircraft[mission.aircraft_id]
        dx, dy = mission.destination.x - mission.origin.x, mission.destination.y - mission.origin.y
        assert {0: dy > 0 and abs(dx) < 1e-6, 90: dx > 0 and abs(dy) < 1e-6,
                180: dy < 0 and abs(dx) < 1e-6, 270: dx < 0 and abs(dy) < 1e-6}[drone.heading]
        assert mission.destination.z == 0
    assert engine.events[-1].result["traffic_pattern"] == "four_way"


def test_four_directions_are_observed_in_actual_motion_and_respect_separation(engine):
    engine.prepare_demo(100, 42)
    engine.demo_enabled = False
    starts = {key: a.position.model_copy() for key, a in engine.aircraft.items()}
    directions = {key: a.heading for key, a in engine.aircraft.items()}
    for _ in range(12):
        previous = engine.time_s
        engine.step(1)
        assert engine.time_s == previous + 1
        assert not engine.conflicts
        for a, b in combinations(engine.aircraft.values(), 2):
            if abs(a.position.z-b.position.z) <= engine.settings.conflict_vertical_separation_m:
                assert a.position.horizontal_distance_to(b.position) > engine.settings.conflict_horizontal_separation_m
    for key, aircraft in engine.aircraft.items():
        start = starts[key]
        dx, dy = aircraft.position.x-start.x, aircraft.position.y-start.y
        assert {0: dy > 0, 90: dx > 0, 180: dy < 0, 270: dx < 0}[directions[key]]
        assert aircraft.heading == pytest.approx(directions[key])
        assert engine.distances[key] > 0


def test_four_way_initial_conditions_are_seed_reproducible(engine):
    engine.prepare_demo(20, 17)
    first = [(a.id, a.position, a.heading, a.battery, a.priority) for a in engine.aircraft.values()]
    buildings = list(engine.environment.city.buildings)
    engine.prepare_demo(20, 17)
    assert first == [(a.id, a.position, a.heading, a.battery, a.priority) for a in engine.aircraft.values()]
    assert buildings == list(engine.environment.city.buildings)


@pytest.mark.parametrize("heading", [0, 90, 180, 270])
def test_vertical_flight_preserves_last_horizontal_heading(heading):
    drone = Aircraft(position=Position3D(x=50, y=60, z=100), heading=heading)
    plan = FlightPlan([drone.position.model_copy(), Position3D(x=50, y=60, z=0)], [])
    plan.advance(drone, 2)
    assert drone.position.z == 96
    assert drone.heading == heading


def test_four_way_demo_still_injects_a_real_crossing_intent(engine):
    engine.prepare_demo(24, 42)
    engine.step(100)
    intents = [event for event in engine.events if "meeting_point" in event.result]
    assert intents and intents[0].simulation_time == 95
    assert engine.resolved_conflicts > 0
    assert not engine.conflicts


def test_crossing_intent_avoids_aircraft_already_diverted_by_weather(engine):
    engine.prepare_demo(100, 42)
    engine.step(96)
    disturbed = {aircraft_id for event in engine.events if event.type == EventType.WEATHER
                 for aircraft_id in event.result.get("affected_aircraft", [])}
    intent = next(event for event in engine.events if "meeting_point" in event.result)
    assert disturbed
    assert {intent.result["aircraft_a"], intent.result["aircraft_b"]}.isdisjoint(disturbed)
    assert not engine.conflicts


@pytest.mark.parametrize("scenario", ["congestion", "weather", "closure", "failure", "conflict"])
def test_single_demos_have_four_actual_flight_directions(engine, scenario):
    engine.prepare_demo(24, 42, scenario)
    assert Counter(a.heading for a in engine.aircraft.values()) == {0: 6, 90: 6, 180: 6, 270: 6}
    assert engine.events[-1].result["traffic_pattern"] == "four_way"
    assert not engine.environment.network.validate_against_city(engine.environment.city)
    starts = {key: a.position.model_copy() for key, a in engine.aircraft.items()}
    bearings = {key: a.heading for key, a in engine.aircraft.items()}
    engine.step(8)
    assert engine.time_s == 8 and not engine.conflicts
    for key, aircraft in engine.aircraft.items():
        dx, dy = aircraft.position.x-starts[key].x, aircraft.position.y-starts[key].y
        assert {0: dy > 0, 90: dx > 0, 180: dy < 0, 270: dx < 0}[bearings[key]]
