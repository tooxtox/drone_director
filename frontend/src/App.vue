<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import CityScene from './components/CityScene.vue';
import ControlPanel from './components/ControlPanel.vue';
import MetricsChart from './components/MetricsChart.vue';
import EventTimeline from './components/EventTimeline.vue';
import { command, connection, selectedAircraftId, snapshot, startConnection, stopConnection } from './stores/simulation';

const scene = ref<InstanceType<typeof CityScene>>();
const tracks = ref(true);
const labels = ref(true);
const night = ref(true);
const tour = ref(false);
const autoFocus = ref(true);
const cameraPreset = ref<'overview' | 'top' | 'street' | 'event'>('overview');
const connectedLabel = computed(() => ({ connecting: '正在连接', live: '实时同步', reconnecting: '断线重连中' })[connection.state]);
const scenarioNames: Record<string, string> = { full: '100 机完整演示', congestion: '航路拥堵', weather: '东部雷暴', closure: '临时管制', failure: '故障备降', conflict: '两机冲突' };
const scenarioName = computed(() => snapshot.value?.aircraft.length ? scenarioNames[snapshot.value.simulation.demo_scenario] : '待创建场景');
const activeCount = computed(() => snapshot.value?.aircraft.filter(aircraft => ['taking_off', 'en_route', 'hovering', 'diverting', 'landing', 'emergency'].includes(aircraft.status)).length ?? 0);

function setCameraPreset(preset: 'overview' | 'top' | 'street') {
  selectedAircraftId.value = '';
  cameraPreset.value = preset;
  tour.value = false;
  scene.value?.setCameraPreset(preset);
}
function resetView() {
  selectedAircraftId.value = '';
  cameraPreset.value = 'overview';
  tour.value = false;
  scene.value?.resetCamera();
}
function toggleTour() {
  tour.value = !tour.value;
  if (tour.value) selectedAircraftId.value = '';
}
async function playStory() {
  if(snapshot.value?.simulation.running){await command('/simulation/pause');return;}
  if(await command('/simulation/speed',{speed:5}))await command('/simulation/start');
}
onMounted(startConnection);
onBeforeUnmount(stopConnection);
</script>

<template>
  <div class="console-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-symbol" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 21 8v8l-9 5-9-5V8Z" /><path d="m3 8 9 5 9-5M12 13v8M7.5 5.5l9 5" /></svg>
        </div>
        <div><h1>天枢智航<span>TIANSHU</span></h1><p>城市低空交通 · 智能协同指挥</p></div>
      </div>
      <div class="topbar-context">
        <span class="workspace-tag">演示场景<strong>{{ scenarioName }}</strong></span>
        <span class="connection-status" :class="connection.state"><i />{{ connectedLabel }}</span>
      </div>
    </header>

    <div v-if="connection.error" class="error-banner" role="alert"><span>{{ connection.error }}</span><button aria-label="关闭错误提示" @click="connection.error = ''">×</button></div>

    <main class="workspace">
      <section class="scene-panel" aria-label="城市低空交通监控">
        <div class="scene-heading">
          <div class="scene-title-row">
            <div><p class="scene-eyebrow">CITY AIRSPACE / 城市空域</p><h2>{{ snapshot?.environment?.name || '城市低空运行空域' }}<span class="scene-subtitle">三维态势</span></h2></div>
            <div class="scene-live-count"><i /><strong>{{ activeCount }}</strong><span>架执行任务</span></div>
          </div>
          <div class="map-tools" aria-label="三维场景控制">
            <div class="camera-presets" role="group" aria-label="镜头预设">
              <button :class="{ active: cameraPreset === 'overview' && !selectedAircraftId && !tour }" :aria-pressed="cameraPreset === 'overview' && !selectedAircraftId && !tour" @click="setCameraPreset('overview')"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" aria-hidden="true"><path d="m8 2 6 3.5v5L8 14l-6-3.5v-5Z" /><path d="m2 5.5 6 3.4 6-3.4M8 9v5" /></svg>城市总览</button>
              <button :class="{ active: cameraPreset === 'top' && !selectedAircraftId && !tour }" :aria-pressed="cameraPreset === 'top' && !selectedAircraftId && !tour" @click="setCameraPreset('top')">垂直俯瞰</button>
              <button :class="{ active: cameraPreset === 'street' && !selectedAircraftId && !tour }" :aria-pressed="cameraPreset === 'street' && !selectedAircraftId && !tour" @click="setCameraPreset('street')">近地视角</button>
            </div>
            <span class="tool-divider" />
            <button class="environment-toggle" :aria-pressed="night" :title="night ? '切换日间城市' : '切换夜间城市'" @click="night = !night"><svg v-if="night" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" aria-hidden="true"><path d="M13.5 9.1a5.8 5.8 0 0 1-6.6-6.6 5.7 5.7 0 1 0 6.6 6.6Z" /></svg><svg v-else viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" aria-hidden="true"><circle cx="8" cy="8" r="3" /><path d="M8 1v2m0 10v2M1 8h2m10 0h2M3 3l1.4 1.4m7.2 7.2L13 13M3 13l1.4-1.4m7.2-7.2L13 3" /></svg>{{ night ? '夜间' : '日间' }}</button>
            <button :class="{ active: tour }" :aria-pressed="tour" @click="toggleTour">{{ tour ? '结束巡游' : '镜头巡游' }}</button>
            <span class="tool-divider" />
            <label><input v-model="tracks" type="checkbox" />轨迹</label>
            <label><input v-model="labels" type="checkbox" />标注</label>
            <label class="auto-focus-toggle"><input v-model="autoFocus" type="checkbox" />事件聚焦</label>
            <button v-if="selectedAircraftId" class="exit-tracking" @click="resetView">退出跟踪</button>
          </div>
        </div>

        <CityScene ref="scene" :state="snapshot" :selected-id="selectedAircraftId" :show-tracks="tracks" :show-labels="labels" :night="night" :tour="tour" :auto-focus="autoFocus" :busy="connection.busy" @play="playStory" @advance="command('/simulation/step', { steps: $event })" @select="selectedAircraftId = $event" @focus="tour = false; cameraPreset = 'event'" />

        <div v-if="!snapshot?.aircraft.length" class="scene-empty">
          <span class="empty-cross" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></svg></span>
          <div><span class="empty-kicker">准备就绪</span><h3>让城市空域开始运行</h3></div>
          <p>生成 100 架无人机与飞行任务，观看城市航路、动态事件与自主协同处置。</p>
          <button class="primary" :disabled="connection.busy || connection.state !== 'live'" @click="command('/simulation/demo', { aircraft_count: 100, seed: 42 })">{{ connection.busy ? '正在生成场景…' : '创建 100 机演示' }}<span aria-hidden="true">↗</span></button>
        </div>

        <div class="map-legend"><span><i class="legend-teal" />正常运行</span><span><i class="legend-amber" />拥堵 / 备降</span><span><i class="legend-red" />管制 / 冲突</span></div>
        <div class="map-help">拖动旋转 · 滚轮缩放 · 点击无人机跟踪</div>
      </section>

      <ControlPanel />

      <div class="insight-row">
        <section class="analytics-panel">
          <div class="analytics-summary">
            <div><h2>安全与流量趋势</h2><p>实际仿真采样</p></div>
            <div class="summary-stat"><span>累计飞行</span><strong>{{ snapshot ? (snapshot.metrics.total_flight_distance_m / 1000).toFixed(2) : '—' }}<small>km</small></strong></div>
            <div class="summary-stat"><span>应急处理</span><strong>{{ snapshot?.metrics.emergency_response_ms?.toFixed(1) ?? '—' }}<small>ms</small></strong></div>
            <div class="summary-stat"><span>完成任务</span><strong>{{ snapshot?.metrics.completed_missions ?? '—' }}<small>项</small></strong></div>
          </div>
          <MetricsChart :history="snapshot?.history ?? []" />
        </section>
        <section class="events-panel"><div class="panel-heading"><h2>事件与决策记录</h2><span class="small-code">{{ snapshot?.events.length ?? 0 }} 条 · 点击查看处置</span></div><EventTimeline :events="snapshot?.events ?? []" @inspect="scene?.showEvent($event)" /></section>
      </div>
    </main>

    <footer class="footer"><span><i />可解释决策 · 多项加权 A* / 轨迹预测 / 规则解脱</span><span>环境 v{{ snapshot?.environment_version ?? '—' }} · 状态 v{{ snapshot?.version ?? '—' }}<span class="footer-divider">/</span>感知 → 分析 → 决策 → 执行 → 反馈</span></footer>
  </div>
</template>
