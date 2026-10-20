export interface Position { x: number; y: number; z: number }
export interface Polygon { points: { x: number; y: number }[] }
export interface Aircraft {
  id: string; name?: string; position: Position; speed: number; heading: number;
  status: string; battery: number; priority: number; destination?: Position | null;
  motion_samples?: {time_s:number;position:Position;heading:number}[];
  trajectory?: Position[]; flight_plan?: Position[]; mission_id?: string;
  remaining_distance_m?: number; delay_s?: number;
}
export interface Waypoint { id: string; name?: string; type: string; position: Position }
export interface Route { id: string; start: string; end: string; waypoint_ids: string[]; capacity: number; current_flow: number; status: string }
export interface Weather { id: string; name?: string; affected_area: Polygon; precipitation: string; wind_speed: number }
export interface Restriction { id: string; polygon: Polygon; min_altitude: number; max_altitude: number; active: boolean; reason: string }
export interface Conflict { aircraft_a: string; aircraft_b: string; conflict_time: number; conflict_position: Position; severity: string }
export interface SimulationEvent {
  id: string; type: string; timestamp: string; simulation_time: number; processing_ms: number;
  description: string; severity: string; handled: boolean; related_id?: string | null; result: Record<string, unknown>;
}
export interface Environment {
  ground_layout?: { block_period:number;street_width:number;emergency_site_size:number;emergency_road_setback:number;emergency_pad_radius:number;terminal_buffer:number };
  name: string; origin: { latitude: number; longitude: number; altitude: number };
  bounds: { min_x: number; min_y: number; max_x: number; max_y: number };
  buildings: { id: string; footprint: Polygon; height: number; elevation: number }[];
}
export interface Metrics {
  aircraft_count: number; active_mission_count: number; route_count: number;
  conflict_count: number; congested_route_count: number; alert_count: number;
  average_delay_s: number; average_flight_distance_m: number; total_flight_distance_m: number;
  route_utilization: number; emergency_response_ms: number; completed_missions: number;
}
export interface HistoryPoint { time_s: number; conflicts: number; route_utilization: number; average_delay_s: number; total_distance_m: number }
export interface Snapshot {
  version: number; environment_version: number;
  simulation: { time_s: number; running: boolean; speed: number; tick_seconds: number; demo_stage: number; demo_complete: boolean; demo_scenario: 'full' | 'congestion' | 'weather' | 'closure' | 'failure' | 'conflict' };
  aircraft: Aircraft[]; missions?: unknown[]; waypoints: Waypoint[]; routes: Route[];
  weather: Weather[]; restrictions: Restriction[]; conflicts: Conflict[]; events: SimulationEvent[];
  metrics: Metrics; history: HistoryPoint[]; environment?: Environment | null;
}
export const statusLabels: Record<string, string> = {
  grounded: '地面待命', taking_off: '起飞', en_route: '巡航', hovering: '等待',
  landing: '降落', landed: '已降落', diverting: '应急备降', emergency: '应急', fault: '故障', offline: '离线',
};
export const eventLabels: Record<string, string> = {
  event_weather: '气象扰动', event_airspace_closure: '空域管制', event_aircraft_failure: '飞行故障',
  event_route_congestion: '航路拥堵', event_conflict: '冲突解脱', event_emergency_landing: '应急备降', event_info: '运行记录',
};
export function formatTime(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(value / 3600)).padStart(2, '0')}:${String(Math.floor(value / 60) % 60).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}
