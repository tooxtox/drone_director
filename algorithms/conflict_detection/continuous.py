"""Exact conflict detection on piecewise linear, overlapping time intervals."""

from __future__ import annotations

import math

from core.models.geometry import Position3D

from .models import Conflict, ConflictThresholds, TrajectoryPoint, validate_trajectory

_EPS = 1e-9


def _position_at(a: TrajectoryPoint, b: TrajectoryPoint, time: float) -> Position3D:
    ratio = (time - a.time) / (b.time - a.time) if b.time != a.time else 0.0
    return Position3D(**{
        axis: getattr(a.position, axis)
        + (getattr(b.position, axis) - getattr(a.position, axis)) * ratio
        for axis in ("x", "y", "z")
    })


def _velocity(a: TrajectoryPoint, b: TrajectoryPoint) -> tuple[float, float, float]:
    if a.time == b.time:
        return 0.0, 0.0, 0.0
    return tuple((getattr(b.position, axis) - getattr(a.position, axis)) / (b.time - a.time)
                 for axis in ("x", "y", "z"))


def _entry_time(
    relative: tuple[float, float, float], velocity: tuple[float, float, float],
    duration: float, thresholds: ConflictThresholds,
) -> float | None:
    """Intersect horizontal quadratic and vertical linear separation intervals."""
    x, y, z = relative
    vx, vy, vz = velocity
    a = vx * vx + vy * vy
    b = x * vx + y * vy
    c = x * x + y * y - thresholds.horizontal_m ** 2
    if a == 0:
        if c > _EPS:
            return None
        horizontal = (-math.inf, math.inf)
    else:
        discriminant = b * b - a * c
        # Floating-point roundoff at exact tangency must not create a missed conflict.
        tolerance = 1e-12 * max(1.0, b * b, abs(a * c))
        if discriminant < -tolerance:
            return None
        root = math.sqrt(max(0.0, discriminant))
        horizontal = ((-b - root) / a, (-b + root) / a)
    if vz == 0:
        if abs(z) > thresholds.vertical_m + _EPS:
            return None
        vertical = (-math.inf, math.inf)
    else:
        vertical = sorted(((-thresholds.vertical_m - z) / vz,
                           (thresholds.vertical_m - z) / vz))
    start = max(0.0, horizontal[0], vertical[0])
    end = min(duration, horizontal[1], vertical[1])
    return min(start, duration) if start <= end + _EPS else None


def _first_overlap(
    left: list[TrajectoryPoint], right: list[TrajectoryPoint],
    thresholds: ConflictThresholds, now: float,
) -> tuple[float, Position3D] | None:
    if not left or not right:
        return None
    left_segments = list(zip(left, left[1:])) or [(left[0], left[0])]
    right_segments = list(zip(right, right[1:])) or [(right[0], right[0])]
    i = j = 0
    while i < len(left_segments) and j < len(right_segments):
        a, b = left_segments[i]
        c, d = right_segments[j]
        lo = max(now, a.time, c.time)
        hi = min(now + thresholds.time_window_s, b.time, d.time)
        if lo <= hi:
            p, q = _position_at(a, b, lo), _position_at(c, d, lo)
            va, vb = _velocity(a, b), _velocity(c, d)
            delta = _entry_time((p.x - q.x, p.y - q.y, p.z - q.z),
                                tuple(u - v for u, v in zip(va, vb)), hi - lo, thresholds)
            if delta is not None:
                time = lo + delta
                p, q = _position_at(a, b, time), _position_at(c, d, time)
                return time, Position3D(x=(p.x + q.x) / 2, y=(p.y + q.y) / 2,
                                        z=(p.z + q.z) / 2)
        if b.time <= d.time:
            i += 1
        if d.time <= b.time:
            j += 1
    return None


def detect_conflicts(
    trajectories: dict[str, list[TrajectoryPoint]],
    thresholds: ConflictThresholds | None = None, now: float = 0.0,
) -> list[Conflict]:
    """Return earliest separation loss per pair in [now, now + time_window_s].

    Paths are interpolated only inside their supplied time domains. Horizontal
    AND vertical thresholds must be breached at the same absolute timestamp.
    """
    if not math.isfinite(now):
        raise ValueError("Current simulation time must be finite")
    limits = thresholds or ConflictThresholds()
    if not math.isfinite(now + limits.time_window_s):
        raise ValueError("Prediction horizon must be finite")
    for trajectory in trajectories.values():
        validate_trajectory(trajectory)
    # Conservative swept bounds reject distant pairs before exact interpolation.
    bounds = {key: tuple((min(getattr(p.position, axis) for p in path),
                          max(getattr(p.position, axis) for p in path))
                         for axis in ("x", "y", "z"))
              for key, path in trajectories.items() if path}
    conflicts = []
    # Sorted swept bounds let distant pairs stop at the first x gap.
    ordered = sorted(bounds, key=lambda aircraft_id: bounds[aircraft_id][0][0])
    for index, first in enumerate(ordered):
        left = bounds[first]
        for other_index in range(index + 1, len(ordered)):
            second = ordered[other_index]
            right = bounds[second]
            if right[0][0] > left[0][1] + limits.horizontal_m + _EPS:
                break
            if (left[1][0] > right[1][1] + limits.horizontal_m + _EPS
                    or right[1][0] > left[1][1] + limits.horizontal_m + _EPS
                    or left[2][0] > right[2][1] + limits.vertical_m + _EPS
                    or right[2][0] > left[2][1] + limits.vertical_m + _EPS):
                continue
            aircraft_a, aircraft_b = (first, second) if first < second else (second, first)
            overlap = _first_overlap(trajectories[aircraft_a], trajectories[aircraft_b], limits, now)
            if overlap is not None:
                time, position = overlap
                conflicts.append(Conflict(
                    aircraft_a=aircraft_a, aircraft_b=aircraft_b,
                    conflict_time=time, conflict_position=position,
                    severity="critical" if time <= now + _EPS else "warning",
                ))
    return sorted(conflicts, key=lambda conflict: (
        conflict.conflict_time, conflict.aircraft_a, conflict.aircraft_b,
    ))
