<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import { command, connection, exportReport, selectedAircraft, selectedAircraftId, snapshot } from '../stores/simulation';
import { formatTime, statusLabels } from '../types/simulation';

const type = ref('event_route_congestion');
const routeId = ref('');
const aircraftId = ref('');
const capacity = ref(1);
const area = ref('east');
const speed = ref(10);
const routeOptions = shallowRef<string[]>([]);
const scenarios = [
  { id: 'congestion', name: '航路拥堵', detail: '容量下降 · 流量改配', at: 10 },
  { id: 'weather', name: '东部雷暴', detail: '区内撤离 · 航路重算', at: 25 },
  { id: 'closure', name: '临时管制', detail: '区内撤离 · 安全绕行', at: 25 },
  { id: 'failure', name: '飞行故障', detail: '安全航程 · 真实备降', at: 40 },
  { id: 'conflict', name: '两机冲突', detail: '轨迹预测 · 规则解脱', at: 40 },
] as const;
const selectedScenario = computed(() => snapshot.value?.simulation.demo_scenario ?? 'full');
const activeAircraft = computed(() => snapshot.value?.aircraft.filter(a => ['en_route', 'taking_off', 'hovering'].includes(a.status)) ?? []);
const selectedRoute = computed(() => snapshot.value?.routes.find(r => r.id === routeId.value));
const busy = computed(() => connection.busy || connection.state !== 'live');
const running = computed(() => snapshot.value?.simulation.running ?? false);
const metrics = computed(() => {
  const m = snapshot.value?.metrics;
  return [
    ['飞行器', m?.aircraft_count, '架'], ['执行任务', m?.active_mission_count, '项'], ['当前冲突', m?.conflict_count, '处'],
    ['航路', m?.route_count, '条'], ['拥堵航路', m?.congested_route_count, '条'], ['运行告警', m?.alert_count, '条'],
    ['平均延误', m?.average_delay_s?.toFixed(1), 's'], ['平均航程', m ? (m.average_flight_distance_m / 1000).toFixed(2) : undefined, 'km'],
    ['航路利用率', m ? (m.route_utilization * 100).toFixed(1) : undefined, '%'],
  ];
});
watch(() => snapshot.value?.simulation.speed, value => { if (value !== undefined) speed.value = value; });
watch(() => snapshot.value?.environment_version, () => {
  const routes = snapshot.value?.routes ?? [];
  routeOptions.value = routes.map(route => route.id);
  if (routes.length && !routeOptions.value.includes(routeId.value)) routeId.value = [...routes].sort((a, b) => b.current_flow - a.current_flow)[0]!.id;
}, { immediate: true });
watch(activeAircraft, aircraft => {
  if (!aircraft.some(a => a.id === aircraftId.value)) aircraftId.value = aircraft[0]?.id ?? '';
});

async function inject() {
  const environment = snapshot.value?.environment;
  if (!environment) return;
  const bounds = environment.bounds;
  const width = bounds.max_x - bounds.min_x;
  const height = bounds.max_y - bounds.min_y;
  const cx = bounds.min_x + width * (area.value === 'east' ? 0.82 : 0.5);
  const cy = bounds.min_y + height * 0.5;
  const points = [{ x: cx - width * 0.075, y: cy - height * 0.12 }, { x: cx + width * 0.075, y: cy - height * 0.12 },
    { x: cx + width * 0.075, y: cy + height * 0.12 }, { x: cx - width * 0.075, y: cy + height * 0.12 }];
  const common = { type: type.value, severity: type.value === 'event_aircraft_failure' ? 'critical' : 'warning' };
  const options: Record<string, object> = {
    event_weather: { description: '操作员注入雷暴天气', payload: { affected_area: { points }, wind_speed: 20, wind_direction: 90, visibility_m: 1200, precipitation: 'thunderstorm' } },
    event_airspace_closure: { description: '操作员注入临时管制', payload: { polygon: { points }, min_altitude: 0, max_altitude: 300, reason: '临时空域管制' } },
    event_aircraft_failure: { description: `${aircraftId.value} 飞行器故障`, related_id: aircraftId.value, payload: { range_derating: 0.55 } },
    event_route_congestion: { description: `${routeId.value} 航路容量收缩`, related_id: routeId.value, payload: { capacity: Number(capacity.value) } },
  };
  await command('/events', { ...common, ...options[type.value] });
}

const canInject = computed(() => !!snapshot.value?.aircraft.length && !busy.value &&
  (type.value !== 'event_aircraft_failure' || !!aircraftId.value) &&
  (type.value !== 'event_route_congestion' || (!!routeId.value && Number.isInteger(capacity.value) && capacity.value > 0)));

async function previewScenario(item: (typeof scenarios)[number]) {
  const created = await command('/simulation/demo', { aircraft_count: 24, seed: 42, scenario: item.id });
  if (created) await command('/simulation/step', { steps: item.at + 1 });
}
</script>

<template>
  <aside class="control-panel" aria-label="运行指标与仿真控制">
    <div class="panel-heading"><span>演示驾驶台</span></div>
    <section class="control-section playback-section">
      <div class="section-title"><h2>仿真进程</h2><span class="status-pill" :class="{ active: running }">{{ running ? '运行中' : '已暂停' }}</span></div>
      <div class="sim-clock"><span>仿真时间</span><strong>{{ formatTime(snapshot?.simulation.time_s ?? 0) }}</strong><small>{{ snapshot?.simulation.speed ?? 1 }}×</small></div>
      <div class="button-row">
        <button v-if="!running" class="primary" :disabled="busy || !snapshot?.aircraft.length" @click="command('/simulation/start')"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5 19 12 7 19.5Z" /></svg>启动仿真</button>
        <button v-else class="primary" :disabled="busy" @click="command('/simulation/pause')"><svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="4.5" width="4" height="15" rx="1" /><rect x="14" y="4.5" width="4" height="15" rx="1" /></svg>暂停</button>
        <button :disabled="busy || running || !snapshot?.aircraft.length" @click="command('/simulation/step', { steps: 1 })">单步推进</button>
      </div>
      <div class="speed-row"><label for="simulation-speed">时间倍率</label><select id="simulation-speed" v-model.number="speed" :disabled="busy" @change="command('/simulation/speed', { speed })"><option :value="1">1× 实时</option><option :value="5">5×</option><option :value="10">10×</option><option :value="20">20×</option><option :value="50">50×</option></select></div>
      <button class="wide secondary" :disabled="busy || running" @click="command('/simulation/demo', { aircraft_count: 100, seed: 42, scenario: 'full' })">{{ snapshot?.aircraft.length && selectedScenario === 'full' ? '重置 100 机完整演示' : '生成 100 机完整演示' }}</button>
      <p class="control-note">{{ !snapshot?.aircraft.length ? '可先选择下方单项场景，直接查看事件。' : selectedScenario === 'full' ? (snapshot.simulation.demo_complete ? '四类扰动已执行，任务仍在继续调度。' : `完整演示阶段 ${snapshot.simulation.demo_stage} / 4`) : (snapshot.simulation.demo_complete ? '本场景已结束，可检查结果。' : snapshot.simulation.demo_stage ? '事件已触发。点击启动，观察后续处置。' : '场景已生成，点击启动。') }}</p>
    </section>
    <section class="control-section scenario-section">
      <div class="section-title"><h2>单项事件场景</h2></div>
      <p class="scenario-intro">点击后停在事件发生的第一秒；启动仿真，观察后续行动。</p>
      <div class="scenario-grid">
        <button v-for="item in scenarios" :key="item.id" class="scenario-card" :class="{ selected: selectedScenario === item.id && !!snapshot?.aircraft.length }"
          :disabled="busy || running" @click="previewScenario(item)">
          <span class="scenario-title">{{ item.name }}<small>{{ item.at }} s</small></span><span class="scenario-detail">{{ item.detail }}</span>
        </button>
      </div>
      <p class="control-note">切换会重置当前运行；需要保留结果时先导出报告。</p>
    </section>
    <div class="metrics-heading"><h2>运行指标</h2></div>
    <div class="metric-grid">
      <div v-for="(item, index) in metrics" :key="String(item[0])" class="metric" :class="{ 'primary-metric': index < 3, caution: [2, 4, 5].includes(index) && Number(item[1]) > 0 }">
        <span>{{ item[0] }}</span><strong>{{ item[1] ?? '—' }}<small>{{ item[2] }}</small></strong>
      </div>
    </div>
    <section class="control-section">
      <div class="section-title"><h2>动态事件注入</h2></div>
      <label class="field-label" for="event-type">事件类型</label>
      <select id="event-type" v-model="type" :disabled="busy"><option value="event_route_congestion">航路拥堵 · 收缩容量</option><option value="event_weather">雷暴天气 · 东部扰动</option><option value="event_aircraft_failure">飞行器故障 · 应急备降</option><option value="event_airspace_closure">临时空域管制 · 封闭区域</option></select>
      <div v-if="type === 'event_route_congestion'" class="event-fields">
        <label>目标航路 <small v-if="selectedRoute">{{ selectedRoute.current_flow }}/{{ selectedRoute.capacity }}</small><select v-model="routeId" :disabled="busy"><option v-for="id in routeOptions" :key="id" :value="id">{{ id }}</option></select></label>
        <label class="compact-field">新容量<input v-model.number="capacity" type="number" min="1" step="1" :disabled="busy" /></label>
      </div>
      <label v-else-if="type === 'event_aircraft_failure'" class="field-label">目标飞行器<select v-model="aircraftId" :disabled="busy"><option v-if="!activeAircraft.length" value="">暂无可注入故障的飞行器</option><option v-for="aircraft in activeAircraft" :key="aircraft.id" :value="aircraft.id">{{ aircraft.id }} · {{ statusLabels[aircraft.status] || aircraft.status }}</option></select></label>
      <label v-else class="field-label">影响区域<select v-model="area" :disabled="busy"><option value="east">城市东部</option><option value="center">城市中心</option></select></label>
      <button class="wide event-button" :disabled="!canInject" @click="inject">注入事件并自动处置<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" /></svg></button>
    </section>
    <section class="control-section fleet-section">
      <div class="section-title"><h2>飞行器详情</h2></div>
      <label class="sr-only" for="aircraft-select">查看飞行器</label>
      <select id="aircraft-select" v-model="selectedAircraftId"><option value="">在场景中选择，或按编号查找</option><option v-for="aircraft in snapshot?.aircraft" :key="aircraft.id" :value="aircraft.id">{{ aircraft.id }} · {{ statusLabels[aircraft.status] || aircraft.status }}</option></select>
      <div v-if="selectedAircraft" class="aircraft-details">
        <div><span>状态</span><b>{{ statusLabels[selectedAircraft.status] || selectedAircraft.status }}</b></div>
        <div><span>高度 / 速度</span><b>{{ selectedAircraft.position.z.toFixed(0) }} m / {{ selectedAircraft.speed.toFixed(1) }} m/s</b></div>
        <div><span>剩余电量</span><b>{{ (selectedAircraft.battery * 100).toFixed(1) }}%</b></div>
        <progress :value="selectedAircraft.battery" :max="1" aria-label="飞行器剩余电量" />
        <div><span>优先级 / 目的地</span><b>P{{ selectedAircraft.priority }} / {{ selectedAircraft.destination ? `${selectedAircraft.destination.x.toFixed(0)}, ${selectedAircraft.destination.y.toFixed(0)}, ${selectedAircraft.destination.z.toFixed(0)} m` : '—' }}</b></div>
        <div><span>延误 / 待飞距离</span><b>{{ selectedAircraft.delay_s?.toFixed(1) ?? '—' }} s / {{ selectedAircraft.remaining_distance_m?.toFixed(0) ?? '—' }} m</b></div>
      </div>
    </section>
    <button class="report-button" :disabled="!snapshot?.aircraft.length" @click="exportReport">↓ 导出本次运行报告 <small>JSON</small></button>
  </aside>
</template>
