import { eventLabels, type Polygon, type Position, type Route, type SimulationEvent, type Snapshot } from '../types/simulation';

/** Extra fields already returned by the backend Event model. */
export type SceneSourceEvent = SimulationEvent & {
  location?: Position | null;
  payload?: Record<string, unknown>;
};

export type SceneEventKind = 'weather' | 'closure' | 'congestion' | 'failure' | 'conflict' | 'landing';
export interface SceneEventArea { polygon: Polygon; minAltitude: number; maxAltitude: number }
export interface SceneEventPath { id: string; points: Position[]; kind: 'route' | 'diversion' | 'resolution' }
export interface SceneFocusTarget {
  kind: 'area' | 'route' | 'aircraft' | 'point';
  position: Position;
  radius: number;
  aircraftId?: string;
  routeId?: string;
}
export interface SceneEventVisual {
  id: string;
  type: string;
  kind: SceneEventKind;
  label: string;
  description: string;
  severity: string;
  simulationTime: number;
  processingMs: number;
  handled: boolean;
  success: boolean | null;
  phase: 'active' | 'resolved' | 'attention';
  summary: string;
  affectedAircraftIds: string[];
  affectedRouteIds: string[];
  primaryAircraftId?: string;
  area?: SceneEventArea;
  paths: SceneEventPath[];
  focus?: SceneFocusTarget;
}

const kinds: Record<string, SceneEventKind> = {
  event_weather: 'weather', event_airspace_closure: 'closure', event_route_congestion: 'congestion',
  event_aircraft_failure: 'failure', event_conflict: 'conflict', event_emergency_landing: 'landing',
};
const actionLabels: Record<string, string> = {
  speed: '调整速度', altitude: '调整高度', reroute: '绕行改航', delay: '延时让行', unresolved: '等待人工处置',
};
const aircraftResultKeys = ['affected_aircraft', 'evacuating_aircraft', 'replanned_aircraft',
  'holding_aircraft', 'safe_exit_holding_aircraft'] as const;

function hasResolutionEvidence(result: Record<string, unknown>): boolean {
  const prediction = record(result.predicted_conflict);
  return !!string(result.action) && !!string(prediction.aircraft_a) && !!string(prediction.aircraft_b)
    && !!position(prediction.conflict_position);
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function string(value: unknown): string | undefined { return typeof value === 'string' && value.length ? value : undefined; }
function number(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) ? value : undefined; }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.length > 0) : []; }
function unique(values: (string | undefined)[]): string[] { return [...new Set(values.filter((item): item is string => !!item))]; }
function position(value: unknown): Position | undefined {
  const item = record(value), x = number(item.x), y = number(item.y), z = number(item.z);
  return x !== undefined && y !== undefined && z !== undefined ? { x, y, z } : undefined;
}
function positions(value: unknown): Position[] {
  return Array.isArray(value) ? value.map(position).filter((item): item is Position => !!item) : [];
}
function polygon(value: unknown): Polygon | undefined {
  const points = record(value).points;
  if (!Array.isArray(points)) return;
  const valid = points.map(value => {
    const item = record(value), x = number(item.x), y = number(item.y);
    return x !== undefined && y !== undefined ? { x, y } : undefined;
  }).filter((item): item is { x: number; y: number } => !!item);
  // Partially invalid polygons should never create misleading hazard volumes.
  return valid.length === points.length && valid.length >= 3 ? { points: valid } : undefined;
}
function target(points: Position[], kind: SceneFocusTarget['kind']): SceneFocusTarget | undefined {
  if (!points.length) return;
  const min = { ...points[0] }, max = { ...points[0] };
  for (const point of points) for (const axis of ['x', 'y', 'z'] as const) {
    min[axis] = Math.min(min[axis], point[axis]); max[axis] = Math.max(max[axis], point[axis]);
  }
  return { kind, position: { x: (min.x + max.x) / 2, y: (min.y + max.y) / 2, z: (min.z + max.z) / 2 },
    radius: Math.max(180, Math.hypot(max.x - min.x, max.y - min.y, max.z - min.z) / 2) };
}
function routePoints(route: Route | undefined, state: Snapshot): Position[] {
  if (!route) return [];
  const nodes = route.waypoint_ids.length ? route.waypoint_ids : [route.start, route.end];
  const byId = new Map(state.waypoints.map(item => [item.id, item.position]));
  return nodes.map(id => byId.get(id)).filter((item): item is Position => !!item);
}
function runStartIndex(state: Snapshot): number {
  // Demo preparation writes this marker after clearing runtime/repositories.
  // Use its position, not a timestamp guess, to omit events from a previous run.
  for (let index = state.events.length - 1; index >= 0; index--) {
    const event = state.events[index];
    if (event.type === 'event_info' && number(event.result.seed) !== undefined
      && number(event.result.aircraft_count) !== undefined && string(event.result.scenario) !== undefined) return index;
  }
  return -1;
}

function resultSummary(event: SceneSourceEvent, kind: SceneEventKind, state: Snapshot, primaryId?: string): string {
  const result = event.result;
  if (!event.handled) return '等待事件处理';
  let summary = '';
  if (kind === 'failure' || kind === 'landing') {
    const bay = string(result.bay_id);
    const landed = kind === 'landing' && result.landed === true
      || state.aircraft.some(item => item.id === primaryId && item.status === 'landed');
    if (landed) summary = `已抵达备降点${bay ? ` ${bay}` : ''}`;
    else if (result.success === false) summary = result.reason === 'no_reachable_available_emergency_bay'
      ? '剩余航程内无可用备降点，等待人工处置' : '备降规划失败，等待人工处置';
    else if (bay) {
      const distance = number(result.planned_distance_m);
      summary = `飞往备降点 ${bay}${distance !== undefined ? ` · 规划 ${Math.round(distance)} m` : ''}`;
    }
  } else if (kind === 'conflict') {
    const action = string(result.action);
    summary = `${action ? actionLabels[action] || action : '冲突事件已记录'}${primaryId ? ` · ${primaryId}` : ''}`;
    if (hasResolutionEvidence(result) && result.success === true) summary += ' · 预测冲突已解脱';
    else if (result.success === false) summary += ' · 尚未解脱';
  } else {
    const pieces: string[] = [];
    if (kind === 'congestion') {
      const oldCapacity = number(result.old_capacity), capacity = number(result.capacity);
      if (capacity !== undefined) pieces.push(`容量 ${oldCapacity !== undefined ? `${oldCapacity} → ` : ''}${capacity}`);
    }
    const counts: [string, string][] = [['affected_aircraft', '受影响'], ['replanned_aircraft', '改航'],
      ['evacuating_aircraft', '撤离'], ['holding_aircraft', '等待'], ['safe_exit_holding_aircraft', '撤离后等待']];
    for (const [key, label] of counts) {
      const count = strings(result[key]).length;
      if (count) pieces.push(`${label} ${count} 架`);
    }
    summary = pieces.join(' · ');
  }
  if (!summary) summary = result.success === false ? '处理未成功，等待人工处置' : '事件已处理';
  const residual = number(result.residual_conflicts);
  if (residual !== undefined && residual > 0) summary += ` · 剩余冲突 ${residual}`;
  if (result.paused_for_safety === true) summary += ' · 已暂停确保安全';
  return summary;
}

/** Derive event evidence from the actual snapshot, without inventing outcomes. */
export function deriveSceneEvents(state: Snapshot | null | undefined): SceneEventVisual[] {
  if (!state) return [];
  const start = runStartIndex(state);
  if (start >= 0 && state.events[start].result.scenario !== state.simulation.demo_scenario) return [];
  return state.events.slice(start < 0 ? 0 : start + 1).flatMap((source: SceneSourceEvent) => {
    const kind = kinds[source.type];
    if (!kind || source.simulation_time > state.simulation.time_s) return [];
    const result = source.result, payload = source.payload ?? {};
    const prediction = record(result.predicted_conflict);
    const directId = string(result.aircraft_id) || (['failure', 'landing', 'conflict'].includes(kind) ? string(source.related_id) : undefined);
    const affectedAircraftIds = unique([...aircraftResultKeys.flatMap(key => strings(result[key])), directId,
      string(prediction.aircraft_a), string(prediction.aircraft_b)]);
    const aircraftById = new Map(state.aircraft.map(item => [item.id, item]));
    const primaryAircraftId = unique([...strings(result.evacuating_aircraft), ...strings(result.replanned_aircraft),
      directId, ...affectedAircraftIds]).find(id => aircraftById.has(id));
    const routeId = string(result.route_id) || (kind === 'congestion' ? string(source.related_id) : undefined);
    const affectedRouteIds = unique([...strings(result.affected_routes), routeId]);
    const paths: SceneEventPath[] = [];
    let area: SceneEventArea | undefined;
    let focus: SceneFocusTarget | undefined;
    let phase: SceneEventVisual['phase'] = source.handled && result.success !== false ? 'active' : 'attention';
    if (kind === 'weather') {
      const weather = state.weather.find(item => item.id === result.weather_id);
      const shape = polygon(weather?.affected_area) || polygon(payload.affected_area) || polygon(record(payload.weather).affected_area);
      if (shape) area = { polygon: shape, minAltitude: 0, maxAltitude: 300 };
      if (string(result.weather_id) && !weather) phase = 'resolved';
    } else if (kind === 'closure') {
      const restriction = state.restrictions.find(item => item.id === result.restriction_id);
      const shape = polygon(restriction?.polygon) || polygon(payload.polygon);
      if (shape) area = { polygon: shape, minAltitude: restriction?.min_altitude ?? number(payload.min_altitude) ?? 0,
        maxAltitude: restriction?.max_altitude ?? number(payload.max_altitude) ?? 300 };
      if (string(result.restriction_id) && !restriction?.active) phase = 'resolved';
    } else if (kind === 'congestion') {
      const route = state.routes.find(item => item.id === routeId), points = routePoints(route, state);
      if (route && points.length >= 2) {
        paths.push({ id: route.id, points, kind: 'route' });
        focus = target(points, 'route');
        if (focus) focus.routeId = route.id;
      }
      if (!route || !['congested', 'closed', 'restricted'].includes(route.status)) phase = 'resolved';
    } else if (kind === 'failure') {
      const points = positions(result.path);
      if (points.length >= 2) paths.push({ id: `${source.id}-diversion`, points, kind: 'diversion' });
      if (aircraftById.get(primaryAircraftId ?? '')?.status === 'landed') phase = 'resolved';
    } else if (kind === 'landing') phase = result.landed === true ? 'resolved' : 'attention';
    else if (kind === 'conflict') {
      const point = position(prediction.conflict_position) || position(source.location);
      if (point) focus = { kind: 'point', position: point, radius: 280 };
      const points = positions(aircraftById.get(primaryAircraftId ?? '')?.flight_plan);
      if (points.length >= 2) paths.push({ id: `${source.id}-resolution`, points, kind: 'resolution' });
      phase = result.success === true && hasResolutionEvidence(result) ? 'resolved' : 'attention';
    }
    if (area) focus = target(area.polygon.points.flatMap(point => [
      { ...point, z: area!.minAltitude }, { ...point, z: area!.maxAltitude },
    ]), 'area');
    if (!focus && primaryAircraftId) focus = {
      kind: 'aircraft', aircraftId: primaryAircraftId, position: { ...aircraftById.get(primaryAircraftId)!.position }, radius: 250,
    };
    if (!focus && paths.length) focus = target(paths.flatMap(path => path.points), 'point');
    if (!focus) {
      const point = position(source.location);
      if (point) focus = { kind: 'point', position: point, radius: 250 };
    }
    if (!source.handled || result.success === false || result.paused_for_safety === true) phase = 'attention';
    return [{ id: source.id, type: source.type, kind, label: eventLabels[source.type] || source.type,
      description: source.description, severity: source.severity, simulationTime: source.simulation_time,
      processingMs: source.processing_ms, handled: source.handled,
      success: typeof result.success === 'boolean' ? result.success : null, phase,
      summary: resultSummary(source, kind, state, primaryAircraftId), affectedAircraftIds, affectedRouteIds,
      primaryAircraftId, area, paths, focus }];
  });
}

export interface EventFocusUpdate { events: SceneEventVisual[]; latest: SceneEventVisual | null; newlyFocused: SceneEventVisual | null; reset: boolean }

/** Own one tracker per scene; no stale focus survives reset/scenario/city changes. */
export function createEventFocusTracker() {
  let previous: { scenario: string; time: number; version: number; city: string; marker: string; eventIds: string[] } | undefined;
  let lastFocusedId = '';
  const excludedIds = new Set<string>();
  return {
    clear() { previous = undefined; lastFocusedId = ''; excludedIds.clear(); },
    update(state: Snapshot | null | undefined): EventFocusUpdate {
      if (!state) {
        const reset = !!previous;
        previous = undefined; lastFocusedId = ''; excludedIds.clear();
        return { events: [], latest: null, newlyFocused: null, reset };
      }
      const markerIndex = runStartIndex(state);
      const marker = markerIndex >= 0 ? state.events[markerIndex].id : previous?.marker ?? '';
      const environment = state.environment;
      // environment_version also increments for route capacity/hazard changes.
      // Compare city identity instead so a real disturbance does not reset focus.
      const city = environment ? JSON.stringify([environment.name, environment.origin, environment.bounds,
        environment.buildings]) : previous?.city ?? '';
      const current = { scenario: state.simulation.demo_scenario, time: state.simulation.time_s,
        version: state.version, city, marker, eventIds: state.events.map(event => event.id) };
      const reset = !!previous && (current.scenario !== previous.scenario || current.time < previous.time
        || current.version < previous.version || current.city !== previous.city || current.marker !== previous.marker);
      if (reset) {
        lastFocusedId = '';
        // Some environment CRUD operations retain the event repository. Those
        // historic IDs must not become the new city's active presentation.
        previous?.eventIds.forEach(id => excludedIds.add(id));
      }
      previous = current;
      const events = deriveSceneEvents(state).filter(event => !excludedIds.has(event.id));
      const latest = events.at(-1) ?? null;
      const newlyFocused = latest && latest.id !== lastFocusedId ? latest : null;
      lastFocusedId = latest?.id ?? '';
      return { events, latest, newlyFocused, reset };
    },
  };
}
