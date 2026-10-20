"""Join current positions to the graph, with a short authorized exit from new hazards."""

import math

from algorithms.path_planning import CostWeights, PlanningContext, PlanningError, plan_path
from core.models import Position3D, PrecipitationType, WaypointType
from simulation.aircraft.flight import FlightPlan


class CachedCollisionEnvironment:
    """A city is immutable between environment versions, so exact segment checks are reusable."""

    def __init__(self, city):
        self.city = city
        self.cache: dict[tuple, bool] = {}

    def is_segment_clear(self, start, end):
        key = (start.x, start.y, start.z, end.x, end.y, end.z)
        if key not in self.cache:
            if len(self.cache) > 10000:
                self.cache.clear()
            self.cache[key] = self.city.is_segment_clear(start, end)
        return self.cache[key]


def plan_flight(engine, aircraft, destination: Position3D, *, max_distance=None,
                blocked_edges=None, emergency_bay=None, allow_egress=True) -> FlightPlan:
    if allow_egress and _inside_hazard(engine, aircraft.position):
        return _plan_egress(engine, aircraft, destination, max_distance, blocked_edges, emergency_bay)
    if getattr(engine, "_segment_cache_version", None) != engine.environment.version:
        engine._segment_cache = {}
        engine._segment_cache_version = engine.environment.version
    graph = engine.environment.network.graph.copy()
    # Ground terminals are endpoints, never transfer nodes between cruise layers.
    # This also keeps normal reroutes out of an occupied emergency landing lot.
    graph.remove_nodes_from([
        node for node, data in graph.nodes(data=True)
        if data.get("type") in (WaypointType.VERTIPORT.value, WaypointType.EMERGENCY_BAY.value)
        and data["position"].distance_to(aircraft.position) > 1e-7
        and data["position"].distance_to(destination) > 1e-7
    ])
    for _, _, edge in graph.edges(data=True):
        # Occupancy is measured from moving aircraft, not seed counters.
        edge["current_flow"] = max((engine.occupancy.get(r, 0) for r in edge.get("route_ids", [])), default=0)
    connector_count = 4 if allow_egress else 12
    source = _attach(graph, aircraft.position, "@current", outbound=True, count=connector_count)
    target = _attach(graph, destination, "@destination", outbound=False, count=connector_count)
    speed = min(15.0, aircraft.max_speed)
    context = PlanningContext(graph=graph, city=engine.collision_city,
                              restrictions=list(engine.restrictions.values()),
                              weather=list(engine.weather.values()), speed_mps=speed,
                              max_distance_m=max_distance, blocked_edges=blocked_edges or set(),
                              owned_snapshot=True, segment_cache=engine._segment_cache)
    result = plan_path(source, target, context, engine.weights)
    energy_distance = sum(a.distance_to(b)+4*max(0,b.z-a.z)
                          for a,b in zip(result.positions,result.positions[1:]))
    if max_distance is not None and energy_distance > max_distance + 1e-6:
        raise PlanningError("energy_limit", "可行航路的爬升耗能超出剩余能力",
                            {"energy_equivalent_m":energy_distance,"available_m":max_distance})
    routes = []
    for a, b in zip(result.node_ids, result.node_ids[1:]):
        ids = graph.edges[a, b].get("route_ids", [])
        routes.append(ids[0] if ids else None)
    return FlightPlan(positions=result.positions, node_ids=result.node_ids,
                      speed_mps=speed, route_ids=routes, emergency_bay=emergency_bay)


def _inside_hazard(engine, position):
    return any(r.active and r.polygon.intersects_prism(position, position, r.min_altitude, r.max_altitude)
               for r in engine.restrictions.values()) or any(
        w.precipitation == PrecipitationType.THUNDERSTORM and w.affected_area.contains(position.xy)
        for w in engine.weather.values())


def _plan_egress(engine, aircraft, destination, max_distance, blocked_edges, emergency_bay):
    source = aircraft.position
    if source.z <= 0:
        raise PlanningError("no_safe_egress", "地面飞行器不得在禁入区域内起飞")
    zones = [r.polygon for r in engine.restrictions.values() if r.active and
             r.polygon.intersects_prism(source, source, r.min_altitude, r.max_altitude)]
    zones += [w.affected_area for w in engine.weather.values() if
              w.precipitation == PrecipitationType.THUNDERSTORM and w.affected_area.contains(source.xy)]
    exits = []
    for polygon in zones:
        points = polygon.points
        ccw = sum(a.x*b.y-b.x*a.y for a,b in zip(points, points[1:]+points[:1])) > 0
        for a,b in zip(points, points[1:]+points[:1]):
            dx,dy = b.x-a.x,b.y-a.y
            length = math.hypot(dx,dy)
            fraction = max(0.0,min(1.0,((source.x-a.x)*dx+(source.y-a.y)*dy)/(length*length)))
            foot_x,foot_y = a.x+fraction*dx,a.y+fraction*dy
            nx,ny = (dy/length,-dx/length) if ccw else (-dy/length,dx/length)
            exit_point = Position3D(x=foot_x+nx*8,y=foot_y+ny*8,z=source.z)
            if (_inside_hazard(engine, exit_point) or
                    not engine.collision_city.is_segment_clear(source, exit_point) or
                    not _continuous_exit(source, exit_point, zones)):
                continue
            if any(r.active and not r.polygon.intersects_prism(source, source, r.min_altitude, r.max_altitude)
                   and r.polygon.intersects_prism(source, exit_point, r.min_altitude, r.max_altitude)
                   for r in engine.restrictions.values()):
                continue
            if any(w.precipitation == PrecipitationType.THUNDERSTORM and
                   not w.affected_area.contains(source.xy) and
                   w.affected_area.intersects_segment(source.xy, exit_point.xy)
                   for w in engine.weather.values()):
                continue
            exits.append((source.distance_to(exit_point), exit_point))
    reachable = [(distance, exit_point) for distance, exit_point in sorted(exits, key=lambda item: item[0])
                 if max_distance is None or distance < max_distance]
    for distance, exit_point in reachable:
        shifted = aircraft.model_copy(update={"position": exit_point})
        try:
            plan = plan_flight(engine, shifted, destination,
                max_distance=None if max_distance is None else max_distance-distance,
                blocked_edges=blocked_edges, emergency_bay=emergency_bay, allow_egress=False)
        except PlanningError:
            continue
        plan.positions.insert(0, source.model_copy())
        plan.node_ids.insert(0, "@egress")
        plan.route_ids.insert(0, None)
        plan.egress_target = exit_point
        return plan
    if reachable:
        _, exit_point = reachable[0]
        return FlightPlan(positions=[source.model_copy(), exit_point], node_ids=["@egress", "@safe_exit"],
                          speed_mps=min(15.0, aircraft.max_speed), route_ids=[None],
                          emergency_bay=emergency_bay, egress_target=exit_point, egress_only=True)
    raise PlanningError("no_safe_egress", "未找到同时满足建筑、空域及剩余航程约束的撤离出口")


def _continuous_exit(source, target, zones):
    """The authorized leg may leave the current hazard union once, never re-enter it."""
    dx, dy = target.x-source.x, target.y-source.y
    crossings = {0.0, 1.0}
    for polygon in zones:
        for a, b in zip(polygon.points, polygon.points[1:]+polygon.points[:1]):
            ex, ey = b.x-a.x, b.y-a.y
            denominator = dx*ey-dy*ex
            if abs(denominator) < 1e-9:
                if abs((a.x-source.x)*dy-(a.y-source.y)*dx) < 1e-9:
                    return False  # Ambiguous boundary following is not a safe exit.
                continue
            ax, ay = a.x-source.x, a.y-source.y
            t = (ax*ey-ay*ex)/denominator
            u = (ax*dy-ay*dx)/denominator
            if 0 <= t <= 1 and 0 <= u <= 1:
                crossings.add(t)
    left = False
    ordered = sorted(crossings)
    for a, b in zip(ordered, ordered[1:]):
        if b-a < 1e-9:
            continue
        midpoint = source.xy.model_copy(update={"x": source.x+dx*(a+b)/2,
                                                "y": source.y+dy*(a+b)/2})
        inside = any(zone.contains(midpoint) for zone in zones)
        if left and inside:
            return False
        left |= not inside
    return left


def _attach(graph, position, name, *, outbound, count=4):
    nodes = sorted(((position.distance_to(data["position"]), node)
                    for node, data in graph.nodes(data=True) if not str(node).startswith("@")))
    if nodes and nodes[0][0] < 1e-7:
        return nodes[0][1]
    graph.add_node(name, position=position, capacity=1000, risk_level=0.0)
    # Current-position connectors are checked by exactly the same hard constraints
    # as graph edges. Keep them local; never fabricate a direct destination jump.
    for distance, node in nodes[:count]:
        attrs = dict(distance=distance, capacity=1000, current_flow=0,
                     risk_level=0.0, status="open", route_ids=[])
        graph.add_edge(name, node, **attrs) if outbound else graph.add_edge(node, name, **attrs)
    return name
