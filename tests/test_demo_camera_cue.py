"""Opening targets must come from real planned motion without changing live state."""
from copy import deepcopy

import pytest

from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import EventType
from core.repository import create_registry
from simulation.engine import Engine
from simulation.events.camera import build_camera_cue


@pytest.fixture
def engine():
    registry = create_registry()
    value = Engine(registry, EnvironmentService(), Settings(_env_file=None))
    yield value
    registry.close()


@pytest.mark.parametrize('scenario', ['congestion', 'weather', 'closure', 'failure', 'conflict', 'full'])
@pytest.mark.parametrize('seed', [17, 42])
def test_opening_cue_points_to_an_actual_incident_participant(engine, scenario, seed):
    engine.prepare_demo(24, seed, scenario)
    marker = engine.events[-1]
    cue = marker.result['camera_cue']
    assert cue and engine.time_s == 0 and not engine.running
    assert marker.type == EventType.INFO
    assert cue['aircraft_id'] in engine.aircraft
    assert cue['initial_plan']['path'][0] == engine.aircraft[cue['aircraft_id']].position.model_dump()
    assert cue['initial_plan']['path'][-1] == engine.plans[cue['aircraft_id']].positions[-1].model_dump()
    assert not engine.weather and not engine.restrictions
    frozen = deepcopy(cue)
    engine.step(cue['event_at_s']+1)
    participants = set()
    for event in engine.events:
        if event.type == EventType.INFO:
            continue
        participants.update(event.result.get('affected_aircraft', []))
        if event.related_id:
            participants.add(event.related_id)
        prediction = event.result.get('predicted_conflict', {})
        participants.update(key for key in [prediction.get('aircraft_a'), prediction.get('aircraft_b')] if key)
    assert cue['aircraft_id'] in participants
    assert cue == frozen


def test_computing_a_camera_cue_never_advances_or_replans_live_aircraft(engine):
    engine.prepare_demo(24, 42, 'conflict')
    before = engine.snapshot()
    plans = {key: deepcopy(plan.to_dict()) for key, plan in engine.plans.items()}
    for _ in range(2):
        assert build_camera_cue(engine)['aircraft_id'] in engine.aircraft
    assert engine.snapshot() == before
    assert {key: plan.to_dict() for key, plan in engine.plans.items()} == plans
    assert engine.time_s == 0 and engine.resolved_conflicts == 0


def test_small_fleets_do_not_fabricate_a_missing_conflict_target(engine):
    engine.prepare_demo(2, 42, 'conflict')
    cue = engine.events[-1].result['camera_cue']
    assert cue is None or cue['aircraft_id'] in engine.aircraft
