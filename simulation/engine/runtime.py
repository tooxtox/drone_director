"""Single authoritative simulation owner; wall-clock scheduling stays outside this module."""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import math

from algorithms.path_planning import CostWeights, PlanningError
from core.models import AircraftStatus, Event, EventType, MissionStatus, Severity
from simulation.aircraft.flight import FlightPlan
from simulation.engine.metrics import collect_metrics
from simulation.engine.planning import CachedCollisionEnvironment, _inside_hazard, plan_flight


class Engine:
    def __init__(self, registry, environment, settings):
        self.registry, self.environment, self.settings = registry, environment, settings
        self.tick_seconds = settings.simulation_tick_seconds
        self.weights = CostWeights(**{name: getattr(settings, f"cost_weight_{name}") for name in CostWeights.model_fields})
        self.reset_runtime()

    def reset_runtime(self):
        with self.registry.lock:
            self.running = False
            self.speed = self.settings.simulation_default_speed
            self.time_s = 0.0
            self.version = 0
            self.plans: dict[str, FlightPlan] = {}
            self.distances: dict[str, float] = {}
            self.trails: dict[str, deque] = {}
            self.motion_history: dict[str, deque] = {}
            self.history: deque = deque(maxlen=1000)
            self.conflicts = []
            self.resolved_conflicts = 0
            self.detected_conflicts = 0
            self.alert_count = 0
            self.emergency_response_total_ms = 0.0
            self.emergency_response_count = 0
            self.occupancy: dict[str, int] = {}
            self.bay_reservations: dict[str, str] = {}
            self.demo_stage = 0
            self.demo_enabled = False
            self.demo_complete = False
            self.demo_scenario = "full"
            self.demo_weather_id = None
            self._last_alert: dict[str, float] = {}
            self._last_retry = -10.0
            self.sync_entities()

    def sync_entities(self):
        """Paused CRUD refresh invalidates plans whose aircraft/task was changed."""
        with self.registry.lock:
            old_aircraft = getattr(self, "aircraft", {})
            old_missions = getattr(self, "missions", {})
            old_constraints = (getattr(self, "weather", {}), getattr(self, "restrictions", {}))
            self.aircraft = {a.id: a for a in self.registry.aircraft.list()}
            self.missions = {m.id: m for m in self.registry.missions.list()}
            for mission in self.missions.values():
                if mission.id not in old_missions and self.time_s > 0:
                    mission.created_sim_time = self.time_s
            for name in ("routes", "waypoints", "weather", "restrictions"):
                setattr(self, name, {item.id: item for item in getattr(self.registry, name).list()})
            self.events = self.registry.events.list()
            for aircraft_id in list(self.plans):
                if self.aircraft.get(aircraft_id) != old_aircraft.get(aircraft_id) or any(
                    m.aircraft_id == aircraft_id and m != old_missions.get(m.id) for m in self.missions.values()
                ) or any(m.aircraft_id == aircraft_id and m.id not in self.missions for m in old_missions.values()):
                    self.plans.pop(aircraft_id, None)
            if (getattr(self, "_environment_version", self.environment.version) != self.environment.version
                    or old_constraints != (self.weather, self.restrictions)):
                self.plans.clear()
            self.collision_city = CachedCollisionEnvironment(self.environment.city) if self.environment.city else None
            self._segment_cache = {}
            self._segment_cache_version = self.environment.version
            self._environment_version = self.environment.version
            self._measure_occupancy()

    def start(self):
        from simulation.engine.safety import manage_conflicts

        with self.registry.lock:
            if self.environment.city is None or self.environment.network is None:
                raise RuntimeError("请先加载城市与航路网络")
            self._schedule()
            self.running = manage_conflicts(self)
            self.version += 1

    def pause(self):
        with self.registry.lock:
            self.running = False
            self.version += 1
            self.checkpoint()

    def set_speed(self, speed: float):
        if not math.isfinite(speed) or not 0 < speed <= 100:
            raise ValueError("仿真倍速须在 (0,100] 范围")
        with self.registry.lock:
            self.speed = speed
            self.version += 1

    def step(self, steps: int = 1):
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 1000:
            raise ValueError("steps 须为 1 至 1000 的整数")
        with self.registry.lock:
            if self.environment.network is None or self.environment.city is None:
                raise RuntimeError("请先加载城市与航路网络")
            for _ in range(steps):
                if self._tick() is False:
                    break

    def _tick(self):
        from simulation.engine.safety import manage_conflicts
        from simulation.events.demo import advance_demo

        if self._environment_version != self.environment.version:
            self.collision_city = CachedCollisionEnvironment(self.environment.city)
            self._environment_version = self.environment.version
        if self.time_s - self._last_retry >= 5.0:
            self._schedule()
            self._last_retry = self.time_s
        if advance_demo(self) is False:
            self.version += 1
            return False
        if not manage_conflicts(self):
            self.version += 1
            return False
        # Trail entries are appended snapshots and never mutated, so a deque copy preserves rollback.
        saved = (*deepcopy((self.aircraft, self.plans, self.missions)),
                 self.distances.copy(), {key: trail.copy() for key, trail in self.trails.items()})
        event_count = len(self.events)
        actual_trajectories = {}
        for aircraft in sorted(self.aircraft.values(), key=lambda a: (-a.priority, a.id)):
            plan = self.plans.get(aircraft.id)
            if plan is None or plan.complete:
                if aircraft.position.z > 0:
                    actual_trajectories[aircraft.id] = [(0, aircraft.position), (self.tick_seconds, aircraft.position)]
                continue
            trace = []
            previous_route = plan.current_route
            travelled, _ = plan.advance(aircraft, self.tick_seconds,
                                       lambda cursor: self._can_enter(aircraft.id, plan, cursor), trace)
            actual_trajectories[aircraft.id] = trace
            self.distances[aircraft.id] = self.distances.get(aircraft.id, 0.0) + travelled
            trail = self.trails.setdefault(aircraft.id, deque(maxlen=180))
            if travelled:
                trail.append(aircraft.position.model_dump())
            mission = self._mission_for(aircraft.id)
            if mission:
                mission.distance_flown_m += travelled
            if plan.complete:
                aircraft.speed = 0.0
                aircraft.status = AircraftStatus.LANDED if aircraft.position.z < 1 else AircraftStatus.HOVERING
                if plan.egress_only:
                    self.alert(aircraft.id, "已撤离禁入区域，在安全出口等待后续航路")
                    self._measure_occupancy()
                    continue
                if mission:
                    mission.status = MissionStatus.DIVERTED if plan.emergency_bay else MissionStatus.COMPLETED
                    mission.completed_sim_time = self.time_s + self.tick_seconds
                    mission.completed_at = datetime.now(timezone.utc)
                    mission.delay_s = max(0, mission.completed_sim_time - mission.created_sim_time - (mission.baseline_duration_s or 0))
                if plan.emergency_bay:
                    self._record(Event(type=EventType.EMERGENCY_LANDING, related_id=aircraft.id,
                                       location=aircraft.position, description=f"{aircraft.id} 已抵达备降点 {plan.emergency_bay}",
                                       result={"bay_id": plan.emergency_bay, "landed": aircraft.position.z < 1}))
            elif aircraft.battery <= 1e-9:
                aircraft.status = AircraftStatus.FAULT
                plan.wait_s = max(plan.wait_s, 1e9)
                self.alert(aircraft.id, "电量耗尽，无可执行飞行能力；保持最后观测位置，需人工处置")
            elif aircraft.speed <= 0:
                aircraft.status = AircraftStatus.EMERGENCY if plan.emergency_bay else AircraftStatus.HOVERING
            else:
                aircraft.status = AircraftStatus.DIVERTING if plan.emergency_bay else AircraftStatus.EN_ROUTE
            if (None if plan.complete else plan.current_route) != previous_route:
                self._measure_occupancy()
        from algorithms.conflict_detection import ConflictThresholds, TrajectoryPoint, detect_conflicts
        realized = detect_conflicts({key:[TrajectoryPoint(time=self.time_s+t, position=p) for t,p in points]
                                    for key,points in actual_trajectories.items()},
            ConflictThresholds(horizontal_m=self.settings.conflict_horizontal_separation_m,
                               vertical_m=self.settings.conflict_vertical_separation_m,
                               time_window_s=self.tick_seconds), self.time_s)
        if realized:
            self.aircraft, self.plans, self.missions, self.distances, self.trails = saved
            self.events = self.events[:event_count]
            self.running = False
            self.conflicts = realized
            self._measure_occupancy()
            self.alert("fleet", "执行前的整步轨迹复检发现冲突，已取消本步运动并暂停")
        # Keep observed sub-step corners, including the exact touchdown point.
        # A rejected step records only the restored stationary pose.
        for key, aircraft in self.aircraft.items():
            old = saved[0].get(key, aircraft)
            trace = actual_trajectories.get(key) if not realized else None
            trace = trace or [(0.0, old.position), (self.tick_seconds, aircraft.position)]
            history = self.motion_history.setdefault(key, deque(maxlen=32))
            previous, heading = old.position, old.heading
            for offset, position in trace:
                dx, dy = position.x-previous.x, position.y-previous.y
                if math.hypot(dx, dy)>1e-8:
                    heading = math.degrees(math.atan2(dx, dy)) % 360
                sample = {"time_s": self.time_s+offset, "position": position.model_dump(), "heading": heading}
                if history and abs(history[-1]["time_s"]-sample["time_s"])<1e-8:
                    history[-1] = sample
                else:
                    history.append(sample)
                previous = position
        self.time_s += self.tick_seconds
        self.version += 1
        metrics = collect_metrics(self)
        self.history.append({"time_s": self.time_s, "conflicts": self.detected_conflicts,
                             "residual_conflicts": len(self.conflicts),
                             "route_utilization": metrics["route_utilization"],
                             "average_delay_s": metrics["average_delay_s"],
                             "total_distance_m": metrics["total_flight_distance_m"]})
        return not realized

    def _can_enter(self, aircraft_id, plan, cursor, position=None):
        route_id = plan.route_ids[cursor - 1] if cursor <= len(plan.route_ids) else None
        if route_id is None:
            return True
        route = self.routes.get(route_id)
        if route is None or route.status.value == "closed":
            return False
        point = position if position is not None else self.aircraft[aircraft_id].position
        if cursor < len(plan.positions) and point.distance_to(plan.positions[cursor-1]) > 1e-6:
            return True  # Existing occupants may exit after a capacity reduction.
        own = int(self.plans[aircraft_id].current_route == route_id)
        return self.occupancy.get(route_id, 0) - own < route.capacity

    def _measure_occupancy(self):
        self.occupancy = {}
        for aircraft_id, plan in self.plans.items():
            if not plan.complete and plan.current_route and self.aircraft.get(aircraft_id):
                self.occupancy[plan.current_route] = self.occupancy.get(plan.current_route, 0) + 1
        for route in self.routes.values():
            route.current_flow = self.occupancy.get(route.id, 0)

    def _mission_for(self, aircraft_id):
        return next((m for m in self.missions.values() if m.aircraft_id == aircraft_id and m.status in (
            MissionStatus.PENDING, MissionStatus.ASSIGNED, MissionStatus.IN_PROGRESS, MissionStatus.DIVERTED
        ) and m.completed_sim_time is None), None)

    def _schedule(self):
        if self.environment.network is None:
            return
        busy = {m.aircraft_id for m in self.missions.values() if m.status in (MissionStatus.IN_PROGRESS, MissionStatus.DIVERTED)}
        for mission in sorted(self.missions.values(), key=lambda m: (-m.priority, m.id)):
            if mission.status not in (MissionStatus.PENDING, MissionStatus.ASSIGNED, MissionStatus.IN_PROGRESS):
                continue
            if mission.aircraft_id in self.plans and not self.plans[mission.aircraft_id].complete:
                continue
            if mission.aircraft_id is None:
                candidates = [a for a in self.aircraft.values() if a.id not in busy and a.battery > 0.1
                              and a.status not in (AircraftStatus.FAULT, AircraftStatus.OFFLINE)]
                if not candidates:
                    continue
                mission.aircraft_id = min(candidates, key=lambda a: (a.position.distance_to(mission.origin), a.id)).id
            aircraft = self.aircraft.get(mission.aircraft_id)
            if aircraft is None or aircraft.status in (AircraftStatus.FAULT, AircraftStatus.EMERGENCY, AircraftStatus.OFFLINE):
                continue
            try:
                first_target = mission.origin if mission.started_sim_time is None and aircraft.position.distance_to(mission.origin) > 1e-5 else mission.destination
                plan = plan_flight(self, aircraft, first_target, max_distance=aircraft.battery * aircraft.max_range_m)
                if first_target != mission.destination:
                    at_origin = aircraft.model_copy(update={"position": mission.origin})
                    continuation = plan_flight(self, at_origin, mission.destination,
                                               max_distance=aircraft.battery * aircraft.max_range_m-plan.remaining_energy(aircraft.position))
                    plan.positions.extend(continuation.positions[1:])
                    plan.node_ids.extend(continuation.node_ids[1:])
                    plan.route_ids.extend(continuation.route_ids)
                self.plans[aircraft.id] = plan
                aircraft.destination = mission.destination
                aircraft.status = AircraftStatus.EN_ROUTE
                aircraft.speed = plan.speed_mps
                mission.status = MissionStatus.IN_PROGRESS
                mission.started_sim_time = self.time_s if mission.started_sim_time is None else mission.started_sim_time
                mission.assigned_at = mission.assigned_at or datetime.now(timezone.utc)
                if mission.baseline_duration_s is None:
                    mission.baseline_duration_s = plan.remaining_time(aircraft.position)
                busy.add(aircraft.id)
                self._measure_occupancy()
            except PlanningError as exc:
                aircraft.speed = 0.0
                self.alert(aircraft.id, f"任务等待：{exc.reason}")

    def replan(self, aircraft_id, *, destination=None, emergency_bay=None, remaining_range=None):
        aircraft = self.aircraft[aircraft_id]
        target = destination or aircraft.destination
        if target is None:
            if not _inside_hazard(self, aircraft.position):
                return False
            target = aircraft.position
        try:
            plan = plan_flight(self, aircraft, target,
                               max_distance=remaining_range if remaining_range is not None else aircraft.battery * aircraft.max_range_m,
                               emergency_bay=emergency_bay)
            self.plans[aircraft_id] = plan
            if destination is not None or aircraft.destination is not None:
                aircraft.destination = target
            aircraft.status = AircraftStatus.DIVERTING if emergency_bay else AircraftStatus.EN_ROUTE
            self._measure_occupancy()
            return True
        except PlanningError as exc:
            self.plans.pop(aircraft_id, None)
            aircraft.speed = 0
            aircraft.status = AircraftStatus.EMERGENCY if emergency_bay else AircraftStatus.HOVERING
            self.alert(aircraft_id, f"无安全可达航路，等待处置：{exc.reason}")
            return False

    def alert(self, related_id, description):
        key = f"{related_id}:{description}"
        if self.time_s - self._last_alert.get(key, -100) < 30:
            return
        self._last_alert[key] = self.time_s
        self._record(Event(type=EventType.INFO, severity=Severity.WARNING,
                           related_id=related_id, description=description))

    def _record(self, event):
        event.simulation_time = self.time_s
        event.handled = True
        event.processed_at = datetime.now(timezone.utc)
        self.events.append(event)
        if event.severity != Severity.INFO:
            self.alert_count += 1
        if event.type == EventType.AIRCRAFT_FAILURE:
            self.emergency_response_total_ms += event.processing_ms
            self.emergency_response_count += 1
        if len(self.events) > 1000:
            self.registry.events.upsert(self.events.pop(0))
        return event

    def inject_event(self, event):
        from simulation.events.handlers import process_event
        with self.registry.lock:
            result = process_event(self, event)
            self.version += 1
            self.checkpoint()
            return result

    def prepare_demo(self, aircraft_count=100, seed=42, scenario="full"):
        from simulation.events.demo import prepare_demo
        with self.registry.lock:
            prepare_demo(self, aircraft_count, seed, scenario)
            self.checkpoint()

    def snapshot(self, include_environment=True):
        with self.registry.lock:
            aircraft = []
            for item in self.aircraft.values():
                plan = self.plans.get(item.id)
                mission = self._mission_for(item.id)
                aircraft.append({**item.model_dump(mode="json"), "trajectory": list(self.trails.get(item.id, []))[-90:],
                                 "flight_plan": [item.position.model_dump(), *[p.model_dump() for p in plan.positions[plan.cursor:]]] if plan else [],
                                 "motion_samples": list(self.motion_history.get(item.id, []))[-min(32, max(6, math.ceil(self.speed*.5/self.tick_seconds)+3)):],
                                 "mission_id": mission.id if mission else None,
                                 "remaining_distance_m": plan.remaining_distance(item.position) if plan else 0,
                                 "delay_s": mission.delay_s if mission else 0})
            data = {"version": self.version, "environment_version": self.environment.version,
                    "simulation": {"time_s": self.time_s, "running": self.running, "speed": self.speed,
                    "tick_seconds": self.tick_seconds, "demo_stage": self.demo_stage,
                                   "demo_complete": self.demo_complete,
                                   "demo_scenario": self.demo_scenario},
                    "aircraft": aircraft, "metrics": collect_metrics(self), "history": list(self.history),
                    "conflicts": [c.model_dump(mode="json") for c in self.conflicts],
                    "events": [e.model_dump(mode="json") for e in self.events[-100:]]}
            for name in ("missions", "waypoints", "routes", "weather", "restrictions"):
                data[name] = [item.model_dump(mode="json") for item in getattr(self, name).values()]
            if include_environment:
                city = self.environment.city
                data["environment"] = {**city.summary(), "buildings": [b.model_dump(mode="json") for b in city.buildings]} if city else None
            return data

    def report(self):
        """Export every event, including archived entries outside the live timeline."""
        with self.registry.lock:
            snapshot = self.snapshot(include_environment=False)
            events = {event.id: event for event in self.registry.events.list()}
            events.update({event.id: event for event in self.events})
            result = {key: snapshot[key] for key in ("simulation", "metrics", "history")}
            result["events"] = [event.model_dump(mode="json") for event in
                                sorted(events.values(), key=lambda e: (e.simulation_time, e.timestamp))]
            return result

    def checkpoint(self):
        with self.registry.transaction():
            for name in ("aircraft", "missions", "routes", "weather", "restrictions"):
                for item in getattr(self, name).values():
                    getattr(self.registry, name).upsert(item)
            for event in self.events:
                self.registry.events.upsert(event)
            self.registry.set_metadata("simulation_runtime", {
                "time_s": self.time_s, "speed": self.speed, "version": self.version,
                "plans": {key: plan.to_dict() for key, plan in self.plans.items()},
                "distances": self.distances, "trails": {key: list(value) for key, value in self.trails.items()},
                "motion_history": {key: list(value) for key, value in self.motion_history.items()},
                "history": list(self.history), "bay_reservations": self.bay_reservations,
                "demo_stage": self.demo_stage, "demo_enabled": self.demo_enabled,
                "demo_complete": self.demo_complete, "demo_scenario": self.demo_scenario,
                "resolved_conflicts": self.resolved_conflicts,
                "demo_weather_id": self.demo_weather_id,
                "alert_count": self.alert_count,
                "emergency_response_total_ms": self.emergency_response_total_ms,
                "emergency_response_count": self.emergency_response_count,
            })

    def restore_runtime(self):
        with self.registry.lock:
            data = self.registry.get_metadata("simulation_runtime")
            if not data:
                return False
            self.sync_entities()
            for key in ("time_s", "speed", "version", "distances", "bay_reservations", "demo_stage", "demo_enabled", "demo_complete", "resolved_conflicts"):
                setattr(self, key, data[key])
            for key in ("demo_weather_id", "alert_count", "emergency_response_total_ms", "emergency_response_count"):
                if key in data:
                    setattr(self, key, data[key])
            self.demo_scenario = data.get("demo_scenario", "full")
            if "alert_count" not in data:
                self.alert_count = sum(e.severity != Severity.INFO for e in self.events)
            if "emergency_response_count" not in data:
                failure_events = [e for e in self.events if e.type == EventType.AIRCRAFT_FAILURE]
                self.emergency_response_total_ms = sum(e.processing_ms for e in failure_events)
                self.emergency_response_count = len(failure_events)
            self.plans = {key: FlightPlan.from_dict(value) for key, value in data["plans"].items() if key in self.aircraft}
            self.trails = {key: deque(value, maxlen=180) for key, value in data["trails"].items()}
            self.motion_history = {key: deque(value, maxlen=32) for key, value in data.get("motion_history", {}).items() if key in self.aircraft}
            self.history = deque(data["history"], maxlen=1000)
            self.running = False
            self._measure_occupancy()
            return True
