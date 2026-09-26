<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import CityScene from './components/CityScene.vue';
import ControlPanel from './components/ControlPanel.vue';
import MetricsChart from './components/MetricsChart.vue';
import EventTimeline from './components/EventTimeline.vue';
import { command, connection, selectedAircraftId, snapshot, startConnection, stopConnection } from './stores/simulation';
import type { SimulationEvent } from './types/simulation';

const scene = ref<InstanceType<typeof CityScene>>();
const tracks = ref(true);
const labels = ref(true);
const connectedLabel = computed(() => ({ connecting: '正在连接', live: '实时同步', reconnecting: '断线重连中' })[connection.state]);
const scenarioNames: Record<string, string> = { full: '100 机完整演示', congestion: '航路拥堵', weather: '东部雷暴', closure: '临时管制', failure: '故障备降', conflict: '两机冲突' };
const scenarioName = computed(() => snapshot.value?.aircraft.length ? scenarioNames[snapshot.value.simulation.demo_scenario] : '待创建场景');
const trackedEventTypes = new Set(['event_route_congestion', 'event_weather', 'event_airspace_closure', 'event_aircraft_failure', 'event_conflict']);
function targetAircraft(event: SimulationEvent): string {
  const first = (key: string) => Array.isArray(event.result[key]) ? (event.result[key] as unknown[]).find(value => typeof value === 'string') as string | undefined : undefined;
  const resultId = event.result.aircraft_id;
  return first('evacuating_aircraft') || first('replanned_aircraft') ||
    (typeof resultId === 'string' ? resultId : '') || event.related_id || '';
}
let trackedEventId = '';
let trackedConflict = false;
let previousScenario = '';
let previousTime = 0;
watch(snapshot, state => {
  if (!state?.aircraft.length) return;
  if (state.simulation.demo_scenario !== previousScenario || state.simulation.time_s < previousTime) {
    trackedEventId = '';
    trackedConflict = false;
    selectedAircraftId.value = '';
  }
  previousScenario = state.simulation.demo_scenario;
  previousTime = state.simulation.time_s;
  const event = [...state.events].reverse().find(item => trackedEventTypes.has(item.type));
  if (!event || event.id === trackedEventId) return;
  if (state.simulation.demo_scenario === 'full' && event.type === 'event_conflict' && trackedConflict) return;
  trackedEventId = event.id;
  if (event.type === 'event_conflict') trackedConflict = true;
  const target = targetAircraft(event);
  if (state.aircraft.some(aircraft => aircraft.id === target)) selectedAircraftId.value = target;
}, { immediate: true });
function resetView() { selectedAircraftId.value = ''; scene.value?.resetCamera(); }
onMounted(startConnection);
onBeforeUnmount(stopConnection);
</script>

<template>
  <div class="console-shell">
    <header class="topbar">
      <div class="brand"><div class="brand-symbol" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M12 2.5v19M2.5 12h19M5.3 5.3l13.4 13.4M18.7 5.3 5.3 18.7" /></svg></div><div><h1>天枢智航<span>TIANSHU</span></h1><p>城市低空交通智能规划与自主协同系统</p></div></div>
      <div class="topbar-context"><span class="workspace-tag">当前演示 <strong>{{ scenarioName }}</strong></span><span class="connection-status" :class="connection.state"><i />{{ connectedLabel }}</span></div>
    </header>
    <div v-if="connection.error" class="error-banner" role="alert"><span>{{ connection.error }}</span><button aria-label="关闭错误提示" @click="connection.error = ''">×</button></div>
    <main class="workspace">
      <section class="scene-panel" aria-label="城市低空交通监控">
        <div class="scene-heading"><div><h2>{{ snapshot?.environment?.name || '城市低空运行空域' }}<span class="scene-subtitle">三维态势</span></h2></div><div class="map-tools"><label><input v-model="tracks" type="checkbox" />轨迹</label><label><input v-model="labels" type="checkbox" />标注</label><button :title="selectedAircraftId ? '退出飞行器跟踪并恢复城市总览' : '恢复城市总览视角'" :aria-label="selectedAircraftId ? '退出跟踪并恢复总览视角' : '恢复总览视角'" @click="resetView"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="7" /><path d="M12 2.5v3.5M12 18v3.5M2.5 12H6M18 12h3.5" /></svg>{{ selectedAircraftId ? '退出跟踪 · 总览' : '总览' }}</button></div></div>
        <CityScene ref="scene" :state="snapshot" :selected-id="selectedAircraftId" :show-tracks="tracks" :show-labels="labels" @select="selectedAircraftId = $event" />
        <div v-if="!snapshot?.aircraft.length" class="scene-empty"><span class="empty-cross" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21.2s6.8-6.1 6.8-10.6a6.8 6.8 0 1 0-13.6 0c0 4.5 6.8 10.6 6.8 10.6Z" /><circle cx="12" cy="10.4" r="2.5" /></svg></span><h3>建立城市低空运行场景</h3><p>由仿真器生成 100 架飞行器与任务，<br />观察航路规划、协同调度和事件处置。</p><button class="primary" :disabled="connection.busy || connection.state !== 'live'" @click="command('/simulation/demo', { aircraft_count: 100, seed: 42 })">{{ connection.busy ? '正在生成场景…' : '创建演示场景' }}</button></div>
        <div class="map-legend"><span><i class="legend-teal" />正常航路 / 飞行器</span><span><i class="legend-amber" />拥堵 / 备降</span><span><i class="legend-red" />管制 / 冲突</span><span class="legend-note">ENU 米制坐标 · 离线仿真城市</span></div>
        <div class="map-help">拖动旋转视角 · 滚轮缩放 · 单击飞行器查看详情</div>
      </section>
      <ControlPanel />
      <div class="insight-row">
        <section class="analytics-panel">
          <div class="analytics-summary"><div><h2>安全与流量趋势</h2><p>基于实际仿真采样</p></div><div class="summary-stat"><span>累计飞行</span><strong>{{ snapshot ? (snapshot.metrics.total_flight_distance_m / 1000).toFixed(2) : '—' }}<small>km</small></strong></div><div class="summary-stat"><span>应急处理</span><strong>{{ snapshot?.metrics.emergency_response_ms?.toFixed(1) ?? '—' }}<small>ms</small></strong></div><div class="summary-stat"><span>完成任务</span><strong>{{ snapshot?.metrics.completed_missions ?? '—' }}<small>项</small></strong></div></div>
          <MetricsChart :history="snapshot?.history ?? []" />
        </section>
        <section class="events-panel"><div class="panel-heading"><h2>事件与决策记录</h2><span class="small-code">{{ snapshot?.events.length ?? 0 }} 条 · 点击查看处置</span></div><EventTimeline :events="snapshot?.events ?? []" /></section>
      </div>
    </main>
    <footer class="footer"><span>可解释决策：多项加权 A* · 轨迹预测 · 规则解脱</span><span>环境 v{{ snapshot?.environment_version ?? '—' }} · 状态 v{{ snapshot?.version ?? '—' }}<span class="footer-divider">/</span>感知 → 分析 → 决策 → 执行 → 反馈</span></footer>
  </div>
</template>
