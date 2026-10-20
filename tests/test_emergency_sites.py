import random
from itertools import combinations

import pytest

from backend.config.settings import Settings
from backend.services.environment_service import EnvironmentService
from core.models import Event, EventType, Position3D, Waypoint, WaypointType
from core.repository import create_registry
from simulation.engine import Engine
from simulation.events.traffic import build_city_traffic
from simulation.environment.ground import (EMERGENCY_SITE_SIZE, EMERGENCY_ROAD_SETBACK,
    STREET_WIDTH, off_street, place_emergency_site, road_distance, terminal_clear, validate_emergency_site)


@pytest.mark.parametrize('count', [2,24,100,500])
@pytest.mark.parametrize('center', [False,True])
def test_generated_emergency_lots_are_off_street_and_do_not_share_terminal_space(count,center):
    config, waypoints, _, _, _ = build_city_traffic(count, random.Random(42), center_lanes=center)
    bays=[w for w in waypoints.values() if w.type==WaypointType.EMERGENCY_BAY]
    terminals=[w.position for w in waypoints.values() if w.type==WaypointType.VERTIPORT]
    for bay in bays:
        assert off_street(bay.position,config)
        assert terminal_clear(bay.position,terminals)
        for value,origin in [(bay.position.x,config.min_x),(bay.position.y,config.min_y)]:
            assert road_distance(value,origin)-EMERGENCY_SITE_SIZE/2-STREET_WIDTH/2 >= EMERGENCY_ROAD_SETBACK-1e-6
    for a,b in combinations(bays,2):
        assert abs(a.position.x-b.position.x)>=EMERGENCY_SITE_SIZE+EMERGENCY_ROAD_SETBACK-1e-6 or abs(a.position.y-b.position.y)>=EMERGENCY_SITE_SIZE+EMERGENCY_ROAD_SETBACK-1e-6


def test_lots_are_clear_of_registered_buildings_and_invalid_road_bay_is_not_selected():
    registry=create_registry()
    try:
        engine=Engine(registry,EnvironmentService(),Settings(_env_file=None))
        engine.prepare_demo(24,42,'failure')
        for bay in engine.waypoints.values():
            if bay.type==WaypointType.EMERGENCY_BAY:
                assert not validate_emergency_site(engine.environment.city,bay,engine.waypoints.values())
        engine.step(40)
        drone=engine.aircraft['UAV-021']
        invalid=Waypoint(id='BAD-ROAD',type=WaypointType.EMERGENCY_BAY,position=Position3D(x=2200,y=2310,z=0))
        engine.waypoints[invalid.id]=invalid
        assert 'road_or_boundary_overlap' in validate_emergency_site(engine.environment.city,invalid,engine.waypoints.values())
        event=engine.inject_event(Event(type=EventType.AIRCRAFT_FAILURE,related_id=drone.id,payload={'range_derating':.55}))
        assert event.result['success'] and event.result['bay_id']!='BAD-ROAD'
        assert any(item['bay_id']=='BAD-ROAD' for item in event.result['rejected_sites'])
        assert event.result['landing_site']['kind']=='dedicated_offstreet_lot'
    finally:
        registry.close()


def test_placement_respects_shifted_grid_origins():
    config,_,_,_,_=build_city_traffic(2,random.Random(42))
    config.min_x=35;config.max_x=4035;config.min_y=70;config.max_y=4070
    site=place_emergency_site(Position3D(x=235,y=270,z=0),config)
    assert off_street(site,config)


def test_full_demo_finishes_without_using_ground_lots_as_layer_transfers():
    registry=create_registry()
    try:
        engine=Engine(registry,EnvironmentService(),Settings(_env_file=None))
        engine.prepare_demo(100,42,'full')
        engine.step(600)
        snapshot=engine.snapshot()
        assert engine.time_s < 600
        assert snapshot['metrics']['completed_missions'] == 99
        assert snapshot['metrics']['active_mission_count'] == 0
        assert not engine.conflicts
        assert any(e.type==EventType.EMERGENCY_LANDING and e.result['landed'] for e in engine.events)
        for plan in engine.plans.values():
            assert all(p.z > 0 for p in plan.positions[1:-1]), 'Cruise transfers must stay airborne'
    finally:
        registry.close()
