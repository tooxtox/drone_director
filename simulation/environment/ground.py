"""Shared metre-based geometry for the demo's streets and dedicated landing lots."""
from math import floor, hypot

from core.models import Position3D, WaypointType

BLOCK_PERIOD = 200.0
STREET_WIDTH = 40.0  # Entire road corridor, including sidewalks.
EMERGENCY_SITE_SIZE = 80.0
EMERGENCY_ROAD_SETBACK = 12.0
EMERGENCY_PAD_RADIUS = 18.0
TERMINAL_BUFFER = 30.0


def ground_layout():
    return {"block_period": BLOCK_PERIOD, "street_width": STREET_WIDTH,
            "emergency_site_size": EMERGENCY_SITE_SIZE,
            "emergency_road_setback": EMERGENCY_ROAD_SETBACK,
            "emergency_pad_radius": EMERGENCY_PAD_RADIUS, "terminal_buffer": TERMINAL_BUFFER}


def road_distance(value, origin):
    offset = (value-origin) % BLOCK_PERIOD
    return min(offset, BLOCK_PERIOD-offset)


def off_street(position, config):
    half = EMERGENCY_SITE_SIZE/2
    required = STREET_WIDTH/2+half+EMERGENCY_ROAD_SETBACK
    return (config.min_x+half <= position.x <= config.max_x-half
            and config.min_y+half <= position.y <= config.max_y-half
            and road_distance(position.x, config.min_x) >= required-1e-6
            and road_distance(position.y, config.min_y) >= required-1e-6)


def terminal_clear(position, terminal_points):
    half = EMERGENCY_SITE_SIZE/2
    return all(hypot(max(abs(position.x-point.x)-half, 0), max(abs(position.y-point.y)-half, 0))
               >= TERMINAL_BUFFER-1e-6 for point in terminal_points)


def separate_sites(position, sites):
    limit = EMERGENCY_SITE_SIZE+EMERGENCY_ROAD_SETBACK
    return all(abs(position.x-site.x) >= limit-1e-6 or abs(position.y-site.y) >= limit-1e-6
               for site in sites)


def place_emergency_site(preferred, config, terminal_points=(), occupied=()):
    """Find the nearest available lot in a block interior, never a road fallback."""
    inset = STREET_WIDTH/2+EMERGENCY_SITE_SIZE/2+EMERGENCY_ROAD_SETBACK
    columns, rows = int(config.width//BLOCK_PERIOD), int(config.height//BLOCK_PERIOD)
    col = floor((preferred.x-config.min_x)/BLOCK_PERIOD)
    row = floor((preferred.y-config.min_y)/BLOCK_PERIOD)

    def search(cells):
        candidates = []
        for ix, iy in cells:
            x0, y0 = config.min_x+ix*BLOCK_PERIOD, config.min_y+iy*BLOCK_PERIOD
            xs = {x0+inset, x0+BLOCK_PERIOD/2, x0+BLOCK_PERIOD-inset,
                  min(max(preferred.x, x0+inset), x0+BLOCK_PERIOD-inset)}
            ys = {y0+inset, y0+BLOCK_PERIOD/2, y0+BLOCK_PERIOD-inset,
                  min(max(preferred.y, y0+inset), y0+BLOCK_PERIOD-inset)}
            for x in xs:
                for y in ys:
                    position = Position3D(x=x, y=y, z=0)
                    if terminal_clear(position, terminal_points) and separate_sites(position, occupied):
                        candidates.append(position)
        return min(candidates, key=lambda p: ((p.x-preferred.x)**2+(p.y-preferred.y)**2, p.x, p.y)) if candidates else None

    nearby = [(ix, iy) for ix in range(max(0,col-2), min(columns,col+3))
              for iy in range(max(0,row-2), min(rows,row+3))]
    site = search(nearby)
    if site is None:
        site = search((ix, iy) for ix in range(columns) for iy in range(rows))
    if site is None:
        raise ValueError("没有满足道路退距及起降点隔离要求的独立备降场地")
    return site


def validate_emergency_site(city, bay, waypoints):
    """Reject a whole lot that overlaps roads, buildings or another ground terminal."""
    if city is None:
        return ["missing_city"]
    from simulation.environment.builder import rectangle_polygon
    position = bay.position
    errors = []
    if abs(position.z) > 1e-6:
        errors.append("not_ground_site")
    if not off_street(position, city.config):
        errors.append("road_or_boundary_overlap")
    terminals = [w.position for w in waypoints if w.id!=bay.id and w.type==WaypointType.VERTIPORT and w.position.z<=1]
    other_bays = [w.position for w in waypoints if w.id!=bay.id and w.type==WaypointType.EMERGENCY_BAY and w.position.z<=1]
    if not terminal_clear(position, terminals) or not separate_sites(position, other_bays):
        errors.append("ground_terminal_overlap")
    lot = rectangle_polygon(position.x, position.y, EMERGENCY_SITE_SIZE, EMERGENCY_SITE_SIZE)
    edges = list(zip(lot.points, lot.points[1:]+lot.points[:1]))
    if any(any(lot.contains(point) for point in b.footprint.points)
           or any(b.footprint.intersects_segment(a, end) for a, end in edges) for b in city.buildings):
        errors.append("building_overlap")
    return errors
