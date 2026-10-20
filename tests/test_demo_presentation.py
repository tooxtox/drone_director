"""Presentation records must be real, bounded and unchanged by later flight."""
from copy import deepcopy

import pytest

from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import Position3D
from core.repository import create_registry
from simulation.aircraft.flight import FlightPlan
from simulation.engine import Engine
from simulation.events.demo import TRIGGER_TIME
from simulation.events.presentation import capture_flights, decision_evidence, flight_evidence


@pytest.fixture
def engine():
    registry = create_registry()
    value = Engine(registry, EnvironmentService(), Settings(_env_file=None))
    yield value
    registry.close()


@pytest.mark.parametrize('scenario', ['congestion', 'weather', 'closure', 'failure'])
def test_event_captures_original_plan_before_mutation(engine, scenario):
    engine.prepare_demo(24, 42, scenario)
    engine.step(TRIGGER_TIME[scenario])
    originals = {key: flight_evidence(engine, key) for key in engine.aircraft}
    engine.step(1)
    event = next(e for e in engine.events if 'presentation' in e.result)
    evidence = event.result['presentation']
    assert evidence['captured_at_s'] == TRIGGER_TIME[scenario]
    assert 1 <= len(evidence['examples']) <= 3
    changed = False
    for example in evidence['examples']:
        assert example['before'] == originals[example['aircraft_id']]
        assert example['after']['path'][0] == example['before']['position']
        changed |= example['before']['path'] != example['after']['path']
    assert changed
    frozen = deepcopy(evidence)
    engine.step(20)
    assert event.result['presentation'] == frozen
    assert engine.snapshot()['events'][[e.id for e in engine.events].index(event.id)]['result']['presentation'] == frozen


def test_conflict_records_actual_wait_change(engine):
    engine.prepare_demo(24, 42, 'conflict')
    engine.step(41)
    event = next(e for e in engine.events if e.result.get('action') == 'delay')
    change = event.result['presentation']['examples'][0]
    assert change['aircraft_id'] == event.result['aircraft_id']
    assert change['before']['wait_s'] == 0
    assert change['after']['wait_s'] == 12
    assert change['before']['path'] == change['after']['path']
    assert not engine.conflicts


def test_evidence_is_bounded_and_does_not_alias_models(engine):
    engine.prepare_demo(24, 42, 'weather')
    before = capture_flights(engine, [*engine.aircraft, *engine.aircraft])
    assert len(before) == 3
    assert len({v['aircraft_id'] for v in before}) == 3
    record = decision_evidence(engine, before)
    original = deepcopy(record)
    for a in engine.aircraft.values():
        a.position.x += 5
    for plan in engine.plans.values():
        plan.positions[-1].y += 10
    assert record == original
    assert capture_flights(engine, ['missing']) == []


def test_long_routes_are_omitted_without_fake_shortcuts(engine):
    engine.prepare_demo(2, 42)
    key = next(iter(engine.aircraft))
    engine.plans[key] = FlightPlan([Position3D(x=i, y=i % 2, z=150) for i in range(150)], [])
    evidence = flight_evidence(engine, key)
    assert evidence['path_omitted'] is True and evidence['path'] == []
    assert evidence['remaining_distance_m'] > 0
