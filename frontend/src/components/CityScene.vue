<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as C from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import type { Environment, Position, Snapshot } from '../types/simulation';

const props = defineProps<{ state: Snapshot | null; selectedId: string; showTracks: boolean; showLabels: boolean }>();
const emit = defineEmits<{ select: [id: string] }>();
const container = ref<HTMLDivElement>();
const error = ref('');
let viewer: C.Viewer | undefined;
let handler: C.ScreenSpaceEventHandler | undefined;
let transform = C.Matrix4.IDENTITY;
let sceneVersion = '';
let sceneRevision = 0;
let previousEnvironment: Environment | undefined;
const staticIds = new Set<string>();
const topologyIds = new Set<string>();
const dynamicIds = new Set<string>();
const routeColors = new Map<string, string>();
let topologyKey = '';
let lastTrackFrame = -1;
let lastTrackVersion = -1;
let lastTrackSelection = '';
let lastShowTracks = true;
let followedId = '';
let followedPosition: Position | undefined;
const palette = { teal: C.Color.fromCssColorString('#0e8f83'), amber: C.Color.fromCssColorString('#e8a33d'), red: C.Color.fromCssColorString('#d64545') };
const ink = C.Color.fromCssColorString('#16202a');
const paper = C.Color.WHITE;

function world(position: Position) { return C.Matrix4.multiplyByPoint(transform, new C.Cartesian3(position.x, position.y, position.z), new C.Cartesian3()); }
function upsert(id: string, options: C.Entity.ConstructorOptions, used: Set<string>) {
  if (!viewer) return;
  used.add(id);
  const existing = viewer.entities.getById(id);
  if (existing) {
    if (options.position) existing.position = new C.ConstantPositionProperty(options.position as C.Cartesian3);
    if (options.point) existing.point = new C.PointGraphics(options.point);
    if (options.label) existing.label = new C.LabelGraphics(options.label);
    if (options.polyline) existing.polyline = new C.PolylineGraphics(options.polyline);
    if (options.polygon) existing.polygon = options.polygon instanceof C.PolygonGraphics ? options.polygon : new C.PolygonGraphics(options.polygon);
  } else viewer.entities.add({ ...options, id });
}

function resetCamera() {
  const bounds = props.state?.environment?.bounds;
  if (!viewer || !bounds) return;
  const center = world({ x: (bounds.min_x + bounds.max_x) / 2, y: (bounds.min_y + bounds.max_y) / 2, z: 20 });
  const radius = Math.max(bounds.max_x - bounds.min_x, bounds.max_y - bounds.min_y);
  viewer.camera.lookAt(center, new C.HeadingPitchRange(-0.5, -0.75, radius * 1.45));
  viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
  viewer.scene.requestRender();
}
defineExpose({ resetCamera });

function drawStatic() {
  if (!viewer || !props.state?.environment) return;
  const env = props.state.environment;
  if (env === previousEnvironment) return;
  previousEnvironment = env;
  // Route/weather versions change frequently; preserve the operator's camera unless city geometry changes.
  const key = JSON.stringify([env.origin, env.bounds, env.buildings]);
  if (key === sceneVersion) return;
  sceneVersion = key;
  sceneRevision += 1;
  staticIds.forEach(id => viewer?.entities.removeById(id));
  staticIds.clear();
  const origin = C.Cartesian3.fromDegrees(env.origin.longitude, env.origin.latitude, env.origin.altitude);
  transform = C.Transforms.eastNorthUpToFixedFrame(origin);
  const b = env.bounds;
  const corners = [{ x: b.min_x, y: b.min_y, z: 0 }, { x: b.max_x, y: b.min_y, z: 0 }, { x: b.max_x, y: b.max_y, z: 0 }, { x: b.min_x, y: b.max_y, z: 0 }];
  upsert('ground', { polygon: { hierarchy: new C.PolygonHierarchy(corners.map(world)), perPositionHeight: true, material: C.Color.fromCssColorString('#e0e6ee') } }, staticIds);
  const spacing = Math.max(100, Math.ceil((b.max_x - b.min_x) / 20 / 100) * 100);
  for (let x = b.min_x; x <= b.max_x; x += spacing) upsert(`grid-x-${x}`, { polyline: { positions: [world({ x, y: b.min_y, z: 0.3 }), world({ x, y: b.max_y, z: 0.3 })], width: 1, material: C.Color.fromCssColorString('#c9d3de') } }, staticIds);
  for (let y = b.min_y; y <= b.max_y; y += spacing) upsert(`grid-y-${y}`, { polyline: { positions: [world({ x: b.min_x, y, z: 0.3 }), world({ x: b.max_x, y, z: 0.3 })], width: 1, material: C.Color.fromCssColorString('#c9d3de') } }, staticIds);
  env.buildings.forEach(building => upsert(`building-${building.id}`, { polygon: {
    hierarchy: new C.PolygonHierarchy(building.footprint.points.map(p => world({ ...p, z: building.elevation }))),
    perPositionHeight: true, extrudedHeight: env.origin.altitude + building.elevation + building.height,
    material: C.Color.fromCssColorString('#cfd7e1'), outline: true, outlineColor: C.Color.fromCssColorString('#a6b3c2'),
  } }, staticIds));
  followedPosition = undefined;
  resetCamera();
}

function drawTopology(state: Snapshot) {
  if (!viewer) return false;
  const key = `${state.environment_version}:${sceneRevision}:${props.showLabels}`;
  const colorFor = (route: Snapshot['routes'][number]): keyof typeof palette => route.status === 'closed' ? 'red'
    : route.status === 'congested' || route.current_flow >= route.capacity ? 'amber' : 'teal';
  if (key === topologyKey) {
    state.routes.forEach(route => {
      const color = colorFor(route);
      if (routeColors.get(route.id) === color) return;
      const entity = viewer?.entities.getById(`route-${route.id}`);
      if (entity?.polyline) entity.polyline.material = new C.ColorMaterialProperty(palette[color].withAlpha(0.72));
      routeColors.set(route.id, color);
    });
    return false;
  }
  topologyIds.forEach(id => viewer?.entities.removeById(id));
  topologyIds.clear(); routeColors.clear();
  topologyKey = key;
  const waypoints = new Map(state.waypoints.map(w => [w.id, w]));
  state.routes.forEach(route => {
    const positions = (route.waypoint_ids?.length ? route.waypoint_ids : [route.start, route.end]).map(id => waypoints.get(id)?.position).filter((p): p is Position => !!p);
    if (positions.length < 2) return;
    const color = colorFor(route);
    routeColors.set(route.id, color);
    upsert(`route-${route.id}`, { polyline: { positions: positions.map(world), width: 2, material: palette[color].withAlpha(0.72) } }, topologyIds);
  });
  state.waypoints.forEach(point => {
    const bay = point.type === 'emergency_bay';
    const special = bay || point.type === 'vertiport';
    upsert(`waypoint-${point.id}`, { position: world(point.position),
      point: { pixelSize: special ? 10 : 5, color: bay ? palette.amber : palette.teal, outlineColor: paper, outlineWidth: 2 },
      label: { text: point.name || point.id, show: props.showLabels && special, font: '12px sans-serif', fillColor: C.Color.fromCssColorString('#3d4b5a'), pixelOffset: new C.Cartesian2(0, 16), style: C.LabelStyle.FILL_AND_OUTLINE, outlineWidth: 3, outlineColor: paper, distanceDisplayCondition: new C.DistanceDisplayCondition(0, 15000) },
    }, topologyIds);
  });
  return true;
}

function draw() {
  if (!viewer) return;
  if (!props.state?.environment) {
    if (previousEnvironment) {
      viewer.entities.removeAll(); staticIds.clear(); topologyIds.clear(); dynamicIds.clear(); routeColors.clear();
      previousEnvironment = undefined; sceneVersion = ''; topologyKey = '';
      followedId = ''; followedPosition = undefined;
      viewer.scene.requestRender();
    }
    return;
  }
  viewer.entities.suspendEvents();
  try {
    drawStatic();
    const state = props.state;
    const topologyChanged = drawTopology(state);
    const trackFrame = Math.floor(state.simulation.time_s / 5);
    const updateTracks = topologyChanged || trackFrame !== lastTrackFrame || props.selectedId !== lastTrackSelection
      || props.showTracks !== lastShowTracks || (!state.simulation.running && state.version !== lastTrackVersion);
    lastTrackFrame = trackFrame; lastTrackVersion = state.version;
    lastTrackSelection = props.selectedId; lastShowTracks = props.showTracks;
    const used = new Set<string>();
    state.aircraft.forEach(aircraft => {
      const selected = aircraft.id === props.selectedId;
      const emergency = ['emergency', 'diverting', 'fault'].includes(aircraft.status);
      const color = emergency ? palette.amber : selected ? ink : palette.teal;
      upsert(`aircraft-${aircraft.id}`, { position: world(aircraft.position),
        point: { pixelSize: selected ? 12 : 7, color, outlineColor: paper, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
        label: { text: `${aircraft.id}  ${aircraft.position.z.toFixed(0)} m`, show: selected, font: '13px sans-serif', fillColor: ink, showBackground: true, backgroundColor: C.Color.fromCssColorString('#ffffffe6'), horizontalOrigin: C.HorizontalOrigin.CENTER, pixelOffset: new C.Cartesian2(0, -24), disableDepthTestDistance: Number.POSITIVE_INFINITY },
      }, used);
      const trail = aircraft.trajectory?.slice(-120) || [];
      if (props.showTracks && trail.length > 1) {
        const id = `track-${aircraft.id}`;
        if (updateTracks || !viewer?.entities.getById(id)) upsert(id, { polyline: { positions: trail.map(world), width: selected ? 2 : 1, material: color.withAlpha(selected ? 0.9 : 0.32) } }, used);
        else used.add(id);
      }
      if (selected && aircraft.flight_plan && aircraft.flight_plan.length > 1) upsert(`plan-${aircraft.id}`, { polyline: { positions: aircraft.flight_plan.map(world), width: 4, material: new C.PolylineDashMaterialProperty({ color: palette.amber }) } }, used);
    });
    state.restrictions.filter(r => r.active).forEach(restriction => upsert(`restriction-${restriction.id}`, { polygon: {
      hierarchy: new C.PolygonHierarchy(restriction.polygon.points.map(p => world({ ...p, z: restriction.min_altitude }))),
      perPositionHeight: true, extrudedHeight: state.environment!.origin.altitude + restriction.max_altitude,
      material: palette.red.withAlpha(0.1), outline: true, outlineColor: palette.red.withAlpha(0.55),
    } }, used));
    state.weather.forEach(weather => upsert(`weather-${weather.id}`, { polygon: {
      hierarchy: new C.PolygonHierarchy(weather.affected_area.points.map(p => world({ ...p, z: 1 }))),
      perPositionHeight: true, extrudedHeight: state.environment!.origin.altitude + 350,
      material: (weather.precipitation === 'thunderstorm' ? palette.amber : C.Color.fromCssColorString('#3b82f6')).withAlpha(0.14),
      outline: true, outlineColor: palette.amber.withAlpha(0.45),
    } }, used));
    state.conflicts.forEach(conflict => upsert(`conflict-${conflict.aircraft_a}-${conflict.aircraft_b}`, {
      position: world(conflict.conflict_position), point: { pixelSize: 20, color: palette.red.withAlpha(0.3), outlineColor: palette.red, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
    }, used));
    dynamicIds.forEach(id => { if (!used.has(id)) viewer?.entities.removeById(id); });
    dynamicIds.clear(); used.forEach(id => dynamicIds.add(id));
    const target = state.aircraft.find(aircraft => aircraft.id === props.selectedId);
    if (target) {
      const moved = !followedPosition || Math.hypot(target.position.x - followedPosition.x,
        target.position.y - followedPosition.y, target.position.z - followedPosition.z) >= 1;
      if (target.id !== followedId || moved) {
        viewer.camera.lookAt(world(target.position), new C.HeadingPitchRange(-0.5, -0.7, 650));
        viewer.camera.lookAtTransform(C.Matrix4.IDENTITY);
        followedId = target.id;
        followedPosition = { ...target.position };
      }
    } else if (followedId) {
      followedId = '';
      followedPosition = undefined;
      resetCamera();
    }
  } finally { viewer.entities.resumeEvents(); viewer.scene.requestRender(); }
}

onMounted(() => {
  try {
    viewer = new C.Viewer(container.value!, { baseLayer: false, terrainProvider: new C.EllipsoidTerrainProvider(),
      animation: false, timeline: false, geocoder: false, homeButton: false, sceneModePicker: false, baseLayerPicker: false,
      navigationHelpButton: false, fullscreenButton: false, selectionIndicator: false, infoBox: false,
      skyBox: false, skyAtmosphere: false, requestRenderMode: true, maximumRenderTimeChange: Number.POSITIVE_INFINITY });
    viewer.scene.backgroundColor = C.Color.fromCssColorString('#eef1f5');
    viewer.scene.globe.baseColor = C.Color.fromCssColorString('#eef1f5');
    viewer.scene.globe.showGroundAtmosphere = false;
    viewer.scene.fog.enabled = false;
    viewer.scene.screenSpaceCameraController.minimumZoomDistance = 80;
    handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((click: { position: C.Cartesian2 }) => {
      const picked = viewer?.scene.pick(click.position);
      if (picked?.id?.id?.startsWith('aircraft-')) emit('select', picked.id.id.slice(9));
    }, C.ScreenSpaceEventType.LEFT_CLICK);
    draw();
  } catch (cause) { error.value = `三维场景初始化失败：${cause instanceof Error ? cause.message : String(cause)}。请确认浏览器已启用 WebGL。`; }
});
watch([() => props.state, () => props.selectedId, () => props.showTracks, () => props.showLabels], draw);
onBeforeUnmount(() => { handler?.destroy(); viewer?.destroy(); viewer = undefined; });
</script>

<template><div ref="container" class="city-scene" aria-label="城市低空交通三维场景" /><div v-if="error" class="scene-error" role="alert">{{ error }}</div></template>
