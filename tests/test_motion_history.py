from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import Position3D
from core.repository import create_registry
from simulation.aircraft.flight import FlightPlan
from simulation.engine import Engine


def test_motion_history_retains_real_corner_times_and_stays_bounded():
    registry = create_registry()
    try:
        engine = Engine(registry, EnvironmentService(), Settings(_env_file=None))
        engine.prepare_demo(2, 42, 'congestion')
        engine.demo_enabled = False
        drone = engine.aircraft['UAV-001']
        start = drone.position.model_copy()
        corner = Position3D(x=start.x+5, y=start.y, z=start.z)
        end = Position3D(x=start.x+5, y=start.y+5, z=start.z)
        engine.plans[drone.id] = FlightPlan([start, corner, end], [], speed_mps=15)
        engine.step(1)
        samples = engine.snapshot()['aircraft'][0]['motion_samples']
        assert any(sample['position'] == corner.model_dump() and abs(sample['time_s']-1/3)<1e-6 for sample in samples)
        assert samples[-1]['time_s'] == 1
        assert samples[-1]['position'] == end.model_dump()
        engine.step(50)
        assert len(engine.motion_history[drone.id]) <= 32
        assert len(engine.snapshot()['aircraft'][0]['motion_samples']) <= 32
    finally:
        registry.close()


def test_motion_history_survives_checkpoint_restore(tmp_path):
    database = tmp_path/'motion.sqlite3'
    registry = create_registry(database_path=database)
    environment = EnvironmentService()
    engine = Engine(registry, environment, Settings(_env_file=None))
    engine.prepare_demo(4, 42)
    engine.step(4)
    expected = list(engine.motion_history['UAV-001'])
    engine.checkpoint()
    restored = Engine(registry, environment, Settings(_env_file=None))
    assert restored.restore_runtime()
    assert list(restored.motion_history['UAV-001']) == expected
    assert not restored.running
    registry.close()
