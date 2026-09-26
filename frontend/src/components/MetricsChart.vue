<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { HistoryPoint } from '../types/simulation';

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);
const props = defineProps<{ history: HistoryPoint[] }>();
const container = ref<HTMLDivElement>();
let chart: echarts.ECharts | undefined;
let observer: ResizeObserver | undefined;
function update() {
  const points = props.history.slice(-240);
  chart?.setOption({
    animation: false, color: ['#e8a33d', '#0e8f83'],
    tooltip: { trigger: 'axis', backgroundColor: '#ffffff', borderColor: '#e3e8ee', textStyle: { color: '#16202a', fontSize: 11 }, extraCssText: 'box-shadow: 0 8px 24px -12px rgba(16,32,48,.4); border-radius: 8px;' },
    legend: { top: 0, right: 10, itemWidth: 12, itemHeight: 5, textStyle: { color: '#5b6b7c', fontSize: 10 } },
    grid: { top: 36, left: 38, right: 36, bottom: 27 },
    xAxis: { type: 'category', data: points.map(p => `${Math.round(p.time_s)}s`), boundaryGap: false,
      axisLabel: { color: '#8794a4', fontSize: 10 }, axisLine: { lineStyle: { color: '#e3e8ee' } }, axisTick: { show: false } },
    yAxis: [{ type: 'value', min: 0, minInterval: 1, axisLabel: { color: '#8794a4', fontSize: 10 },
      splitLine: { lineStyle: { color: '#eef1f5', type: 'dashed' } } },
    { type: 'value', min: 0, axisLabel: { color: '#8794a4', fontSize: 10, formatter: '{value}%' }, splitLine: { show: false } }],
    series: [
      { name: '冲突 / 次', type: 'line', showSymbol: false, step: 'end', data: points.map(p => p.conflicts), lineStyle: { width: 1.8 } },
      { name: '利用率 / %', type: 'line', yAxisIndex: 1, showSymbol: false, data: points.map(p => +(p.route_utilization * 100).toFixed(1)), lineStyle: { width: 1.8 } },
    ],
  });
}
onMounted(() => { chart = echarts.init(container.value); observer = new ResizeObserver(() => chart?.resize()); observer.observe(container.value!); update(); });
watch(() => props.history, update);
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose(); });
</script>

<template><div ref="container" class="metrics-chart" role="img" aria-label="仿真历史：预测冲突数量与航路利用率趋势" /></template>
