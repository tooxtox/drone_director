import type { Position, Snapshot } from '../types/simulation';
import type { SceneEventVisual } from './eventFocus';

export type ComparisonMode = 'both' | 'before' | 'after';
export interface FlightEvidence {
  path: Position[]; pathOmitted: boolean; speed: number; wait: number; distance: number;
  destination?: Position; status: string;
}
export interface FlightChange { aircraftId: string; before: FlightEvidence; after: FlightEvidence }
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
function point(v: unknown): Position | undefined {
  const p = object(v); return finite(p.x) && finite(p.y) && finite(p.z) ? { x: p.x, y: p.y, z: p.z } : undefined;
}
function flight(v: unknown): FlightEvidence | undefined {
  const f = object(v);
  if (![f.planned_speed_mps, f.wait_s, f.remaining_distance_m].every(finite) || typeof f.status !== 'string') return;
  const raw = Array.isArray(f.path) ? f.path : [], valid = raw.map(point);
  // Reject the whole geometry if a point is missing; joining across it invents a route.
  const path = valid.length <= 128 && valid.every((p): p is Position => !!p) ? valid : [];
  return { path, pathOmitted: f.path_omitted === true || path.length !== raw.length,
    speed: f.planned_speed_mps as number, wait: f.wait_s as number, distance: f.remaining_distance_m as number,
    destination: point(f.destination), status: f.status };
}
export function flightChanges(state: Snapshot | null, event: SceneEventVisual | null): FlightChange[] {
  const evidence = object(state?.events.find(e => e.id === event?.id)?.result.presentation);
  if (!Array.isArray(evidence.examples)) return [];
  const seen = new Set<string>();
  return evidence.examples.flatMap(value => {
    const item = object(value), before = flight(item.before), after = flight(item.after);
    if (typeof item.aircraft_id !== 'string' || seen.has(item.aircraft_id) || !before || !after) return [];
    seen.add(item.aircraft_id); return [{ aircraftId: item.aircraft_id, before, after }];
  }).slice(0, 3);
}

export interface DemoCameraCue { aircraftId: string; aircraftIds: string[]; eventAt: number; plan: FlightEvidence }
export function demoCameraCue(state: Snapshot | null): DemoCameraCue | null {
  if(!state)return null;
  const marker=[...state.events].reverse().find(e=>e.type==='event_info' && finite(e.result.seed) && finite(e.result.aircraft_count) && typeof e.result.scenario==='string');
  if(marker?.result.scenario!==state.simulation.demo_scenario)return null;
  const cue=object(marker.result.camera_cue), plan=flight(cue.initial_plan);
  if(typeof cue.aircraft_id!=='string' || !finite(cue.event_at_s) || cue.event_at_s<0 || !plan || !state.aircraft.some(a=>a.id===cue.aircraft_id))return null;
  const ids=Array.isArray(cue.aircraft_ids) ? cue.aircraft_ids.filter((id):id is string=>typeof id==='string' && state.aircraft.some(a=>a.id===id)) : [];
  return {aircraftId:cue.aircraft_id,aircraftIds:[...new Set([cue.aircraft_id,...ids])],eventAt:cue.event_at_s,plan};
}

export interface DemoChangeRow { label: string; before: string; after: string }
export function demoChangeRows(state: Snapshot, event: SceneEventVisual, changes: FlightChange[], aircraftId?: string): DemoChangeRow[] {
  const change=changes.find(c=>c.aircraftId===aircraftId) ?? changes[0];
  const result=state.events.find(e=>e.id===event.id)?.result ?? {};
  const rows:DemoChangeRow[]=[];
  if(event.kind==='congestion' && finite(result.old_capacity) && finite(result.capacity))rows.push({label:'航路容量',before:`${result.old_capacity}`,after:`${result.capacity}`});
  if(event.kind==='failure' && typeof result.bay_id==='string')rows.push({label:'任务终点',before:'原运输终点',after:`备降 ${result.bay_id}`});
  if(change){
    if(event.kind==='conflict' || change.before.wait!==change.after.wait)rows.push({label:'计划等待',before:`${change.before.wait.toFixed(0)} s`,after:`${change.after.wait.toFixed(0)} s`});
    if(change.before.speed!==change.after.speed)rows.push({label:'计划速度',before:`${change.before.speed.toFixed(1)} m/s`,after:`${change.after.speed.toFixed(1)} m/s`});
    rows.push({label:'剩余航程',before:`${(change.before.distance/1000).toFixed(2)} km`,after:`${(change.after.distance/1000).toFixed(2)} km`});
  }
  return rows.slice(0,3);
}

const scripts: Record<string, { at: number; title: string; intent: string }> = {
  full: { at: 20, title: '城市协同处置', intent: '依次观察拥堵、雷暴、备降与冲突解脱。' },
  congestion: { at: 10, title: '拥堵后的分流', intent: '航路容量下降，观察受影响任务如何重新规划。' },
  weather: { at: 25, title: '雷暴中的撤离与绕行', intent: '观察区域内飞机撤离、区域外任务绕开雷暴。' },
  closure: { at: 25, title: '临时管制下的改航', intent: '观察受限航路关闭后，飞机如何撤出与绕行。' },
  failure: { at: 40, title: '故障后的自主备降', intent: '观察任务终点切换到备降点，并跟踪真实落地。' },
  conflict: { at: 40, title: '交汇时的主动让行', intent: '观察系统如何改变飞行计划，解除预测冲突。' },
};
export function demoIntro(state: Snapshot) {
  const script = scripts[state.simulation.demo_scenario] ?? scripts.full!;
  const headings = [90, 270, 0, 180].map(heading => state.aircraft.filter(a => Math.abs(a.heading - heading) < 1).length);
  return { ...script, headings, countdown: Math.max(0, script.at - state.simulation.time_s),
    steps: Math.max(1, Math.ceil((script.at + 1 - state.simulation.time_s) / state.simulation.tick_seconds)) };
}
function inArea(position: Position, event: SceneEventVisual): boolean {
  const a = event.area; if (!a || position.z < a.minAltitude || position.z > a.maxAltitude) return false;
  const pts = a.polygon.points; let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const p = pts[i]!, q = pts[j]!;
    if ((p.y > position.y) !== (q.y > position.y) && position.x < (q.x - p.x) * (position.y - p.y) / (q.y - p.y) + p.x) inside = !inside;
  }
  return inside;
}
export function demoOutcome(state: Snapshot, event: SceneEventVisual, changes: FlightChange[]) {
  const source = state.events.find(e => e.id === event.id), result = source?.result ?? {};
  const ids = (key: string) => Array.isArray(result[key]) ? result[key] as string[] : [];
  const n = (key: string) => finite(result[key]) ? result[key] as number : undefined;
  const first = changes[0];
  let before = '原飞行计划', decision = event.summary, current = event.summary;
  if (event.kind === 'congestion') {
    before = n('old_capacity') !== undefined ? `航路容量 ${n('old_capacity')}` : '按原航路执行任务';
    decision = `容量降至 ${n('capacity') ?? '—'} · ${ids('replanned_aircraft').length} 架重规划`;
    current = `受影响 ${ids('affected_aircraft').length} 架 · 当前预测冲突 ${state.conflicts.length} 起`;
  } else if (event.kind === 'weather' || event.kind === 'closure') {
    const evac = ids('evacuating_aircraft');
    before = `${ids('affected_aircraft').length} 架原计划受区域影响 · ${evac.length} 架需撤出`;
    decision = `${ids('replanned_aircraft').length} 架重规划 · 优先撤离区域内飞机`;
    const known = evac.map(id => state.aircraft.find(a => a.id === id));
    const exited = known.filter(a => a && !inArea(a.position, event)).length;
    current = evac.length && event.area ? `已撤出 ${exited}/${evac.length} 架${known.some(a => !a) ? ' · 部分飞机状态不可用' : ''} · ${event.phase === 'resolved' ? '区域已解除' : '区域仍生效'}`
      : `当前预测冲突 ${state.conflicts.length} 起 · ${event.phase === 'resolved' ? '区域已解除' : '区域仍生效'}`;
  } else if (event.kind === 'failure' || event.kind === 'landing') {
    before = `${first?.aircraftId ?? event.primaryAircraftId ?? '故障飞机'} · 执行原运输任务`;
    decision = result.bay_id ? `切换至 ${result.bay_id} · 备降规划 ${Math.round(n('planned_distance_m') ?? first?.after.distance ?? 0)} m` : event.summary;
    current = event.summary;
  } else if (event.kind === 'conflict') {
    before = first ? `原等待 ${first.before.wait.toFixed(0)} s · 速度 ${first.before.speed.toFixed(1)} m/s` : '两架飞机存在预测冲突';
    decision = first ? `${event.summary.split(' · ')[0]} · 等待 ${first.before.wait.toFixed(0)} → ${first.after.wait.toFixed(0)} s · 速度 ${first.before.speed.toFixed(1)} → ${first.after.speed.toFixed(1)} m/s` : event.summary;
    current = `当前预测冲突 ${state.conflicts.length} 起${event.phase === 'resolved' ? ' · 此次预测已解脱' : ' · 需要继续处置'}`;
  }
  if (result.success === false || result.paused_for_safety === true) current = event.summary;
  const delta = first ? first.after.distance - first.before.distance : undefined;
  return { before, decision, current, distanceChange: delta === undefined ? '' : `${delta >= 0 ? '+' : '−'}${Math.abs(delta).toFixed(0)} m`,
    sample: first?.aircraftId ?? '', processing: event.processingMs.toFixed(1) };
}

export function demoLandingSite(state: Snapshot,event: SceneEventVisual | null){
  const site=object(state.events.find(e=>e.id===event?.id)?.result.landing_site);
  return site.kind==='dedicated_offstreet_lot'&&finite(site.size_m)&&finite(site.road_setback_m) ? {size:site.size_m,setback:site.road_setback_m} : null;
}
