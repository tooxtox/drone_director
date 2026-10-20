"""Seeded four-way traffic; all positions and routes enter the real simulator."""

import math

from core.models import (Aircraft, AirRoute, CityConfig, GeoPoint, Mission,
                         Position3D, Waypoint, WaypointType)


from simulation.environment.ground import place_emergency_site


DIRECTIONS = (("E", "向东", 90, 150), ("W", "向西", 270, 210),
              ("N", "向北", 0, 270), ("S", "向南", 180, 330))


def build_city_traffic(aircraft_count, rng, *, center_lanes=False):
    """Opposing/crossing streams use 60 m-separated cruise levels and unique pads.

    Each level has a connected grid, so weather and closures can cause actual
    rerouting. Starting progress varies per lane; no positions are teleported.
    """
    lanes = max(2, math.ceil(aircraft_count / 4))
    extent = max(4000, 800 + (lanes - 1) * 80)
    config = CityConfig(name="天枢试验城区", origin=GeoPoint(latitude=30.5728, longitude=104.0668),
                        min_x=0, min_y=0, max_x=extent, max_y=extent,
                        grid_resolution=40, generate_buildings=True)
    # The caller supplies building_seed so the original seed remains authoritative.
    marks = sorted({200, 800, 1400, 2000, extent - 400, extent - 100})
    lane_span = min(extent - 800, (lanes - 1) * 150)
    lane_origin = (extent-lane_span)/2 if center_lanes else 400
    lane_coordinates = [lane_origin + row * lane_span / (lanes - 1) for row in range(lanes)]
    waypoints, routes, aircraft, missions = {}, [], [], []

    def point(key, position, kind=WaypointType.WAYPOINT, name=None):
        waypoints[key] = Waypoint(id=key, name=name or key, position=position,
                                  type=kind, capacity=1 if kind != WaypointType.WAYPOINT else 8,
                                  risk_level=0.1)
        return key

    def edge(a, b):
        routes.append(AirRoute(id=f"R-{a}-{b}", name=f"{a} ↔ {b}", start=a, end=b,
            waypoint_ids=[a, b], distance=waypoints[a].position.distance_to(waypoints[b].position),
            capacity=8, risk_level=0.1))

    def position(direction, along, cross, altitude):
        if direction == "E":
            x, y = along, cross
        elif direction == "W":
            x, y = extent - along, cross + 40
        elif direction == "N":
            x, y = cross, along
        else:
            x, y = cross + 40, extent - along
        return Position3D(x=x, y=y, z=altitude)

    # Preserve UAV numbering in lane order, interleaving four mission directions.
    for row, cross in enumerate(lane_coordinates):
        for offset, (direction, label, heading, altitude) in enumerate(DIRECTIONS):
            for col, along in enumerate(marks):
                key = point(f"{direction}Y{row}X{col}", position(direction, along, cross, altitude))
                if col:
                    edge(f"{direction}Y{row}X{col-1}", key)
                if row:
                    edge(f"{direction}Y{row-1}X{col}", key)
            index = row * 4 + offset
            if index >= aircraft_count:
                continue
            origin = waypoints[f"{direction}Y{row}X{(row // 2) % 4}"].position
            approach = f"{direction}Y{row}X{len(marks)-1}"
            destination = point(f"PAD{index}", position(direction, marks[-1], cross, 0),
                                WaypointType.VERTIPORT, f"{label}任务起降点 {index+1:03d}")
            edge(approach, destination)
            drone = Aircraft(id=f"UAV-{index+1:03d}", name=f"天枢 {index+1:03d} · {label}",
                position=origin.model_copy(), heading=heading,
                battery=round(rng.uniform(0.8, 1.0), 3), priority=rng.randint(0, 8))
            aircraft.append(drone)
            missions.append(Mission(id=f"MISSION-{index+1:03d}", aircraft_id=drone.id,
                origin=origin.model_copy(), destination=waypoints[destination].position.model_copy(),
                priority=drone.priority))

    # Dedicated off-street lots are allocated before building generation. Their
    # real coordinates also anchor the descent columns and the rendered compounds.
    terminal_points = [w.position for w in waypoints.values() if w.type == WaypointType.VERTIPORT]
    reserved_sites = []

    def reserve_site(preferred):
        site = place_emergency_site(preferred, config, terminal_points, reserved_sites)
        reserved_sites.append(site)
        return site

    # Connect each interior lot to every cruise layer.
    for row in range(0, lanes, 4):
        cross = lane_coordinates[row]
        bay_position = reserve_site(Position3D(x=2200, y=cross + 85, z=0))
        bay = point(f"EB-{row}", bay_position, WaypointType.EMERGENCY_BAY, f"应急备降点 {row//4+1}")
        previous_approach = None
        for direction, _, _, altitude in DIRECTIONS:
            approach = point(f"EB-APP-{direction}-{row}", bay_position.model_copy(update={"z": altitude}))
            edge(approach, bay)
            # Layer changes stay airborne in this clear vertical column.
            if previous_approach is not None:
                edge(previous_approach, approach)
            previous_approach = approach
            nearest = min((w for w in waypoints.values() if w.id.startswith(f"{direction}Y")),
                          key=lambda w: w.position.distance_to(waypoints[approach].position))
            edge(nearest.id, approach)
    # A nearby bay at each departure edge also supports high-layer failures:
    # a 330 m descent takes 165 s at the physical 2 m/s vertical speed.
    for direction, label, _, altitude in DIRECTIONS:
        bay_position = reserve_site(position(direction, marks[0], lane_coordinates[0] + 70, 0))
        bay = point(f"EB-EDGE-{direction}", bay_position, WaypointType.EMERGENCY_BAY, f"{label}边缘备降点")
        approach = point(f"EB-EDGE-APP-{direction}", bay_position.model_copy(update={"z": altitude}))
        edge(f"{direction}Y0X0", approach)
        edge(approach, bay)
    return config, waypoints, routes, aircraft, missions
