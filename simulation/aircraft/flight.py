"""Piecewise linear motion with a fixed simulation clock, including residual time."""

from dataclasses import dataclass, field
import math
from typing import Callable

from core.models import Aircraft, Position3D


@dataclass
class FlightPlan:
    positions: list[Position3D]
    node_ids: list[str]
    speed_mps: float = 15.0
    cursor: int = 1
    wait_s: float = 0.0
    emergency_bay: str | None = None
    route_ids: list[str | None] = field(default_factory=list)
    vertical_speed_mps: float = 2.0
    egress_target: Position3D | None = None
    egress_only: bool = False

    @property
    def complete(self) -> bool:
        return self.cursor >= len(self.positions)

    @property
    def current_route(self) -> str | None:
        index = self.cursor - 1
        return self.route_ids[index] if 0 <= index < len(self.route_ids) else None

    def remaining_distance(self, position: Position3D) -> float:
        if self.complete:
            return 0.0
        points = [position, *self.positions[self.cursor:]]
        return sum(a.distance_to(b) for a, b in zip(points, points[1:]))

    def segment_speed(self, start, target):
        distance = start.distance_to(target)
        vertical = abs(target.z-start.z)
        return min(self.speed_mps, self.vertical_speed_mps*distance/vertical) if vertical > 1e-9 else self.speed_mps

    def remaining_energy(self, position):
        points = [position, *self.positions[self.cursor:]]
        return sum(a.distance_to(b) + 4 * max(0, b.z-a.z) for a, b in zip(points, points[1:]))

    def remaining_time(self, position):
        points = [position, *self.positions[self.cursor:]]
        return self.wait_s + sum(a.distance_to(b)/max(self.segment_speed(a,b), 0.01)
                                 for a,b in zip(points,points[1:]))

    def advance(self, aircraft: Aircraft, dt: float,
                can_enter: Callable[[int], bool] | None = None, trace: list | None = None) -> tuple[float, float]:
        """Return actual travelled metres and equivalent range consumed (climb costs 4x)."""
        waited = min(dt, self.wait_s)
        self.wait_s -= waited
        remaining = dt - waited
        if trace is not None:
            trace.append((0.0, aircraft.position.model_copy()))
            if waited > 0:
                trace.append((waited, aircraft.position.model_copy()))
        travelled = energy = 0.0
        aircraft.speed = 0.0
        while remaining > 1e-9 and not self.complete:
            if can_enter is not None and not can_enter(self.cursor):
                break
            target = self.positions[self.cursor]
            start = aircraft.position
            length = start.distance_to(target)
            if length < 1e-8:
                self.cursor += 1
                continue
            speed = min(self.segment_speed(start, target), aircraft.max_speed)
            if speed <= 0:
                break
            climb_fraction = max(0.0, target.z - start.z) / length
            available = aircraft.battery * aircraft.max_range_m
            distance = min(length, remaining * speed, available / (1 + 4 * climb_fraction))
            fraction = distance / length
            aircraft.position = Position3D(
                x=start.x + (target.x - start.x) * fraction,
                y=start.y + (target.y - start.y) * fraction,
                z=start.z + (target.z - start.z) * fraction,
            )
            used = distance * (1 + 4 * climb_fraction)
            aircraft.battery = max(0.0, aircraft.battery - used / aircraft.max_range_m)
            # Vertical takeoff/landing has no new horizontal bearing.
            if math.hypot(target.x - start.x, target.y - start.y) > 1e-8:
                aircraft.heading = math.degrees(math.atan2(target.x - start.x, target.y - start.y)) % 360
            aircraft.speed = speed if distance > 0 else 0.0
            remaining -= distance / speed
            if trace is not None and dt-remaining > trace[-1][0]+1e-9:
                trace.append((dt-remaining, aircraft.position.model_copy()))
            travelled += distance
            energy += used
            if distance >= length - 1e-8:
                self.cursor += 1
            else:
                break
        if trace is not None and trace[-1][0] < dt:
            if dt-trace[-1][0] > 1e-9:
                trace.append((dt, aircraft.position.model_copy()))
            else:
                trace[-1] = (dt, aircraft.position.model_copy())
        return travelled, energy

    def predict(self, position: Position3D, now: float, horizon: float) -> list:
        from algorithms.conflict_detection import TrajectoryPoint

        points = [TrajectoryPoint(time=now, position=position)]
        end = now + horizon
        time = min(end, now + self.wait_s)
        if time > now:
            points.append(TrajectoryPoint(time=time, position=position))
        current = position
        for target in self.positions[self.cursor:]:
            if time >= end or self.speed_mps <= 0:
                break
            distance = current.distance_to(target)
            if distance < 1e-8:
                continue
            travel = distance / max(self.segment_speed(current, target), 0.01)
            fraction = min(1.0, (end - time) / travel)
            time = min(end, time + travel)
            current = Position3D(x=current.x + (target.x-current.x)*fraction,
                                 y=current.y + (target.y-current.y)*fraction,
                                 z=current.z + (target.z-current.z)*fraction)
            points.append(TrajectoryPoint(time=time, position=current))
        if points[-1].time < end:
            points.append(TrajectoryPoint(time=end, position=current))
        return points

    def to_dict(self) -> dict:
        return {**self.__dict__, "positions": [p.model_dump() for p in self.positions],
                "egress_target": self.egress_target.model_dump() if self.egress_target else None}

    @classmethod
    def from_dict(cls, data: dict) -> "FlightPlan":
        return cls(**{**data, "positions": [Position3D.model_validate(p) for p in data["positions"]],
                      "egress_target": Position3D.model_validate(data["egress_target"]) if data.get("egress_target") else None})
