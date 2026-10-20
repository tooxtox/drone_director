<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import * as T from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { emergencySites } from '../scene/landingSites';
import { buildUrbanCity } from '../scene/urban';
import { createTrafficLayer, disposeObject, line, world } from '../scene/traffic';
import { createEventFocusTracker, type SceneEventVisual } from '../scene/eventFocus';
import DemoStory from './DemoStory.vue';
import { demoCameraCue, flightChanges, type ComparisonMode } from '../scene/demoStory';
import { createDemoCameraFlight, demoApproachSeconds, demoOpeningTiming, type DemoCameraPhase } from '../scene/demoCamera';
import { buildComparison } from '../scene/comparison';
import { formatTime, statusLabels, type Environment, type Snapshot } from '../types/simulation';

const props = withDefaults(defineProps<{ state: Snapshot | null; selectedId: string; showTracks: boolean; showLabels: boolean; night?: boolean; tour?: boolean; autoFocus?: boolean; busy?: boolean }>(), { night: true, tour: false, autoFocus: true });
const emit = defineEmits<{ select: [id: string]; focus: []; play: []; advance: [steps: number] }>();
const container = ref<HTMLDivElement>();
const aircraftLabel = ref<HTMLDivElement>();
const error = ref('');
const activeEvent = shallowRef<SceneEventVisual | null>(null);
const frameRate = ref(0);
const cameraStage = ref<DemoCameraPhase | ''>('');
const cameraTargetId = ref('');
const cameraStageLabel = computed(() => cameraStage.value==='establish'?'拉回城市远景':cameraStage.value==='wide'?'城市远景':cameraStage.value==='approach'?'平滑推进':'跟随目标');
const storyOpen = ref(true);
const comparisonMode = ref<ComparisonMode>('both');
const openingCue = computed(() => demoCameraCue(props.state));
const changes = computed(() => flightChanges(props.state, visibleEvent.value));
let comparison: ReturnType<typeof buildComparison> | undefined;
let comparisonKey = '';
let introPlan:T.Group | undefined, introPlanKey='', introRunKey='';
const spotlightIds = computed(() => storyOpen.value && visibleEvent.value ? visibleEvent.value.affectedAircraftIds : openingCue.value?.aircraftIds ?? []);
const events = shallowRef<SceneEventVisual[]>([]);
const selected = computed(() => props.state?.aircraft.find(a => a.id === props.selectedId));
const visibleEvent = computed(() => activeEvent.value ? events.value.find(e => e.id === activeEvent.value!.id) ?? activeEvent.value : null);
const environment = computed(() => props.state?.environment || previewEnvironment);
const bounds = computed(() => environment.value.bounds);
const minimapAircraft = computed(() => (props.state?.aircraft ?? []).map(a => ({ ...a, mx: 8 + (a.position.x-bounds.value.min_x)/(bounds.value.max_x-bounds.value.min_x)*144, my: 8 + (1-(a.position.y-bounds.value.min_y)/(bounds.value.max_y-bounds.value.min_y))*104 })));
const minimapSites = computed(() => emergencySites(environment.value,props.state?.waypoints??[]).map(w=>({id:w.id,x:8+(w.position.x-bounds.value.min_x)/(bounds.value.max_x-bounds.value.min_x)*144,y:8+(1-(w.position.y-bounds.value.min_y)/(bounds.value.max_y-bounds.value.min_y))*104})));
const minimapBuildings = computed(() => environment.value.buildings.map(b => ({ id:b.id, points:b.footprint.points.map(p=>`${8+(p.x-bounds.value.min_x)/(bounds.value.max_x-bounds.value.min_x)*144},${8+(1-(p.y-bounds.value.min_y)/(bounds.value.max_y-bounds.value.min_y))*104}`).join(' ') })));
const previewEnvironment: Environment = { name: '城市预览', origin: { latitude:30.5728,longitude:104.0668,altitude:0 }, bounds:{min_x:0,min_y:0,max_x:2400,max_y:2400}, buildings:Array.from({length:144},(_,i)=>{const x=(i%12)*200+36,y=Math.floor(i/12)*200+36;return {id:`preview-${i}`,elevation:0,height:22+(i*37%78),footprint:{points:[{x,y},{x:x+128,y},{x:x+128,y:y+128},{x,y:y+128}]}};}).filter((_,i)=>i%7!==0) };
let renderer: T.WebGLRenderer | undefined, scene: T.Scene, camera:T.PerspectiveCamera, controls:OrbitControls;
let urban:ReturnType<typeof buildUrbanCity> | undefined, traffic:ReturnType<typeof createTrafficLayer> | undefined;
let sun:T.DirectionalLight, ambient:T.HemisphereLight;
let resetFrameClock:(()=>void) | undefined;
let animation=0, observer:ResizeObserver | undefined, cityKey='', previousTime=0, focusedId='', disposed=false;
let previousSceneEnvironment: Environment | undefined;
let previousPortSignature='';
let cameraTween:{ from:T.Vector3; to:T.Vector3; fromTarget:T.Vector3; toTarget:T.Vector3; elapsed:number } | undefined;
let demoFlight:{ aircraftId:string; elapsed:number; updatedAt:number; flight:ReturnType<typeof createDemoCameraFlight> } | undefined;
const tracker=createEventFocusTracker();
const eventLayer=new T.Group();
const raycaster=new T.Raycaster();
let pointerStart={x:0,y:0};
let frameCount=0, frameElapsed=0;

function cityCenter() { const b=environment.value.bounds; return new T.Vector3((b.min_x+b.max_x)/2,35,-(b.min_y+b.max_y)/2); }
function span() { const b=environment.value.bounds; return Math.max(b.max_x-b.min_x,b.max_y-b.min_y); }
function moveCamera(target:T.Vector3,offset:T.Vector3,instant=false) {
  if (!camera || !controls) return;
  if (instant) { camera.position.copy(target).add(offset);controls.target.copy(target);cameraTween=undefined;controls.update();return; }
  cameraTween={from:camera.position.clone(),to:target.clone().add(offset),fromTarget:controls.target.clone(),toTarget:target.clone(),elapsed:0};
}
function cancelDemoFlight() { demoFlight=undefined;cameraStage.value='';cameraTargetId.value='';focusedId=''; }
function startDemoFlight(aircraftId:string,replayOverview=false,opening=false) {
  if(!camera || !controls || !props.state?.aircraft.some(a=>a.id===aircraftId))return false;
  cancelDemoFlight();cameraTween=undefined;
  // Flush previous orbit damping before taking over the camera.
  controls.enableDamping=false;controls.update();controls.enableDamping=true;
  const center=cityCenter(),size=span();
  const wide=center.clone().add(new T.Vector3(size*.63,size*.74,size*.8));
  const timing=opening && openingCue.value ? demoOpeningTiming(openingCue.value.eventAt,props.state.simulation.time_s,props.state.simulation.speed) : {};
  const flight=createDemoCameraFlight({position:camera.position,target:controls.target},{position:wide,target:center},{replayOverview,approachSeconds:replayOverview ? undefined : demoApproachSeconds(props.state.simulation.speed),...timing});
  demoFlight={aircraftId,elapsed:0,updatedAt:performance.now(),flight};focusedId=aircraftId;cameraTargetId.value=aircraftId;
  cameraStage.value=flight.sample(0,traffic?.getPosition(aircraftId)??center).phase;
  emit('focus');emit('select',aircraftId);return true;
}
function setCameraPreset(preset:'overview'|'top'|'street',instant=false) {
  cancelDemoFlight();const size=span(),center=cityCenter();
  const offset=preset==='top'?new T.Vector3(0,size*1.18,size*.025):preset==='street'?new T.Vector3(size*.42,size*.17,size*.45):new T.Vector3(size*.63,size*.74,size*.8);
  moveCamera(center,offset,instant);
}
function frameTarget() {
  if(!camera || !container.value)return;
  const {width,height}=container.value.getBoundingClientRect();
  if(width>0 && height>0 && width<600 && storyOpen.value)camera.setViewOffset(width,height,-width*.3,0,width,height);
  else camera.clearViewOffset();
}
function resetCamera() { setCameraPreset('overview'); }
function showEvent(id:string) { const event=events.value.find(e=>e.id===id);if(event)focusEvent(event,true); }
defineExpose({ resetCamera,setCameraPreset,showEvent });
function syncComparison() {
  const nextKey = JSON.stringify([storyOpen.value,visibleEvent.value?.id,changes.value]);
  if (nextKey !== comparisonKey) {
    comparisonKey=nextKey; if(comparison)disposeObject(comparison.group); comparison=undefined;
    if(storyOpen.value && changes.value.length){comparison=buildComparison(changes.value);scene?.add(comparison.group);}
  }
  comparison?.setMode(comparisonMode.value);
  comparison?.setAircraft(props.selectedId);
  const cue=storyOpen.value && !visibleEvent.value ? openingCue.value : null;
  const nextIntroKey=cue ? JSON.stringify([cue.aircraftId,cue.plan.path]) : '';
  if(nextIntroKey!==introPlanKey){
    introPlanKey=nextIntroKey;if(introPlan)disposeObject(introPlan);introPlan=undefined;
    if(cue && cue.plan.path.length>1){introPlan=new T.Group();introPlan.add(line(cue.plan.path,0x79b9ff,.85,true));scene?.add(introPlan);}
  }
}
function closeStory() { storyOpen.value=false;activeEvent.value=null;[...eventLayer.children].forEach(disposeObject);updateScene(); }

function focusEvent(event:SceneEventVisual,manual=false) {
  if(event.kind==='landing'){const failure=[...events.value].reverse().find(e=>e.kind==='failure' && e.primaryAircraftId===event.primaryAircraftId && flightChanges(props.state,e).length);if(failure)event=failure;}
  activeEvent.value=event;storyOpen.value=true;comparisonMode.value='both';syncComparison();
  [...eventLayer.children].forEach(disposeObject);
  const color=event.kind==='closure'||event.kind==='conflict'?0xff637d:0xffbd67;
  if (!changes.value.length) event.paths.forEach(path=>{if(path.points.length>1)eventLayer.add(line(path.points,color,.95,true));});
  if (event.focus) {
    const ring=new T.Mesh(new T.RingGeometry(Math.max(36,event.focus.radius*.18),Math.max(40,event.focus.radius*.18+4),64),new T.MeshBasicMaterial({color,transparent:true,opacity:.8,side:T.DoubleSide,depthWrite:false}));
    ring.rotation.x=-Math.PI/2;ring.position.copy(world(event.focus.position));ring.position.y=3;eventLayer.add(ring);
    if (props.autoFocus || manual) {
      const continuing=!manual && event.primaryAircraftId===cameraTargetId.value && focusedId===event.primaryAircraftId;
      if(!continuing && !(event.primaryAircraftId && startDemoFlight(event.primaryAircraftId,manual))) {
        cancelDemoFlight();emit('focus');emit('select','');
        const radius=T.MathUtils.clamp(event.focus.radius*2,360,span()*.7);
        moveCamera(world(event.focus.position),new T.Vector3(radius*.65,radius*.7,radius*.9));
      }
    }
  }
}
function updateScene() {
  if (!renderer || disposed) return;
  const env=environment.value;
  const portSignature=JSON.stringify(props.state?.waypoints.filter(w=>['vertiport','emergency_bay'].includes(w.type)));
  if(env!==previousSceneEnvironment || portSignature!==previousPortSignature) {
    previousPortSignature=portSignature;
    previousSceneEnvironment=env;
    const nextKey=JSON.stringify([env.origin,env.bounds,env.buildings,props.state?.waypoints.filter(w=>['vertiport','emergency_bay'].includes(w.type))]);
    if(cityKey!==nextKey) {
      cityKey=nextKey;urban?.dispose();urban=buildUrbanCity(env,props.state?.waypoints??[]);scene.add(urban.group);urban.setNight(props.night);renderer.shadowMap.needsUpdate=true;
      const center=cityCenter(),size=span();sun.position.copy(center).add(new T.Vector3(-size*.6,size*1.1,size*.4));sun.target.position.copy(center);
      Object.assign(sun.shadow.camera,{left:-size*.7,right:size*.7,top:size*.7,bottom:-size*.7,far:size*4});sun.shadow.camera.updateProjectionMatrix();
      controls.maxDistance=size*3;camera.far=size*15;camera.updateProjectionMatrix();setCameraPreset('overview',true);
    }
  }
  if (!props.state) { traffic?.dispose();traffic=undefined;tracker.update(null);events.value=[];activeEvent.value=null;introRunKey='';cancelDemoFlight();syncComparison();[...eventLayer.children].forEach(disposeObject);return; }
  if(!traffic){traffic=createTrafficLayer();scene.add(traffic.group);}
  const result=tracker.update(props.state);events.value=result.events;
  if(result.reset) {activeEvent.value=null;storyOpen.value=true;syncComparison();focusedId='';emit('select','');[...eventLayer.children].forEach(disposeObject);setCameraPreset('overview',true);}
  traffic.setSpotlight(spotlightIds.value);
  traffic.update(props.state,props.selectedId,props.showTracks,props.showLabels,result.reset||props.state.simulation.time_s<previousTime);
  previousTime=props.state.simulation.time_s;
  let nextEvent=result.newlyFocused;
  if(nextEvent?.kind==='landing') {
    const failure=[...result.events].reverse().find(e=>e.kind==='failure' && e.primaryAircraftId===nextEvent?.primaryAircraftId && flightChanges(props.state,e).length);
    if(failure)nextEvent=visibleEvent.value?.id===failure.id ? null : failure;
  }
  if(nextEvent)focusEvent(nextEvent);
  const cue=openingCue.value;
  const runKey=[...props.state.events].reverse().find(e=>e.result.camera_cue)?.id ?? '';
  if(!visibleEvent.value && cue && props.autoFocus && runKey && runKey!==introRunKey){
    introRunKey=runKey;startDemoFlight(cue.aircraftId,true,true);
  }
  syncComparison();
}
function applyLighting() {
  if(!scene)return;
  scene.background=new T.Color(props.night?0x101e30:0x8eafb9);
  scene.fog=new T.Fog(props.night?0x101e30:0xa5bec4,span()*1.55,span()*4.2);
  sun.color.setHex(props.night?0xb4caff:0xffedcb);sun.intensity=props.night?2.2:3.1;
  ambient.color.setHex(props.night?0x8eb7e8:0xd9f4ff);ambient.groundColor.setHex(props.night?0x263741:0x647966);ambient.intensity=props.night?1.5:2.1;
  urban?.setNight(props.night);renderer!.shadowMap.needsUpdate=true;
}
function onPointerDown(e:PointerEvent){pointerStart={x:e.clientX,y:e.clientY};}
function onPointerUp(e:PointerEvent){
  if(Math.hypot(e.clientX-pointerStart.x,e.clientY-pointerStart.y)>5 || !renderer || !traffic)return;
  const rect=renderer.domElement.getBoundingClientRect();raycaster.setFromCamera(new T.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1),camera);
  const hit=raycaster.intersectObjects(traffic.drones.children,true)[0];
  if(hit?.instanceId!==undefined&&hit.object.userData.aircraftIds){emit('select',hit.object.userData.aircraftIds[hit.instanceId]);return;}
  if(hit){let node:T.Object3D|null=hit.object;while(node&&!node.userData.aircraftId)node=node.parent;if(node?.userData.aircraftId)emit('select',node.userData.aircraftId);}
}
function contextLost(e:Event){e.preventDefault();error.value='三维图形上下文已中断，请重新加载页面恢复。';}
watch(()=>[props.state,props.showTracks,props.showLabels],updateScene,{flush:'post'});
watch(()=>props.night,applyLighting);
watch([comparisonMode,storyOpen],()=>{syncComparison();updateScene();frameTarget();});
watch(activeEvent,()=>{if(traffic && props.state){traffic.setSpotlight(spotlightIds.value);traffic.update(props.state,props.selectedId,props.showTracks,props.showLabels);}});
watch(()=>props.selectedId,()=>{
  if(props.selectedId!==cameraTargetId.value)cancelDemoFlight();
  updateScene();
  const target=traffic?.getPosition(props.selectedId);
  if(target&&focusedId!==props.selectedId){focusedId=props.selectedId;moveCamera(target,new T.Vector3(240,190,290));}
});
watch(()=>props.tour,enabled=>{if(enabled){cancelDemoFlight();cameraTween=undefined;}});
watch(()=>props.autoFocus,enabled=>{if(!enabled && cameraTargetId.value)cancelDemoFlight();else if(enabled)updateScene();});

onMounted(()=>{
  try {
    scene=new T.Scene();scene.add(eventLayer);
    camera=new T.PerspectiveCamera(43,1,8,40000);
    renderer=new T.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.7));renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;renderer.shadowMap.autoUpdate=false;
    renderer.domElement.setAttribute('aria-label','交互式三维城市与无人机态势');container.value!.appendChild(renderer.domElement);
    controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.075;controls.minDistance=70;controls.maxPolarAngle=Math.PI*.485;controls.screenSpacePanning=false;
    controls.addEventListener('start',()=>{cancelDemoFlight();cameraTween=undefined;});
    sun=new T.DirectionalLight(0xb4caff,2.2);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.0003;sun.shadow.normalBias=1;scene.add(sun,sun.target);
    ambient=new T.HemisphereLight(0x8eb7e8,0x263741,1.5);scene.add(ambient);
    observer=new ResizeObserver(()=>{const {width,height}=container.value!.getBoundingClientRect();if(!width||!height)return;renderer!.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();frameTarget();});observer.observe(container.value!);
    renderer.domElement.addEventListener('pointerdown',onPointerDown);renderer.domElement.addEventListener('pointerup',onPointerUp);renderer.domElement.addEventListener('webglcontextlost',contextLost);
    updateScene();applyLighting();
    let last=performance.now(),time=0;
    resetFrameClock=()=>{last=performance.now();if(demoFlight)demoFlight.updatedAt=last;};document.addEventListener('visibilitychange',resetFrameClock);
    const draw=(now:number)=>{
      if(disposed)return;animation=requestAnimationFrame(draw);
      const frameSeconds=Math.max(0,(now-last)/1000),dt=Math.min(frameSeconds,.06);last=now;time+=frameSeconds;
      if(document.hidden)return;
      frameCount++;frameElapsed+=frameSeconds;if(frameElapsed>1){frameRate.value=Math.round(frameCount/frameElapsed);frameCount=0;frameElapsed=0;}
      traffic?.animate(frameSeconds,time,camera);
      if(demoFlight){
        const target=traffic?.getPosition(demoFlight.aircraftId);
        if(!target)cancelDemoFlight();
        else {
          // Camera time follows wall time, so a low frame rate cannot slow the push.
          demoFlight.elapsed+=Math.max(0,(now-demoFlight.updatedAt)/1000);demoFlight.updatedAt=now;
          const pose=demoFlight.flight.sample(demoFlight.elapsed,target);
          camera.position.set(pose.position.x,pose.position.y,pose.position.z);controls.target.set(pose.target.x,pose.target.y,pose.target.z);cameraStage.value=pose.phase;
          if(pose.done)demoFlight=undefined;
        }
      }
      else if(cameraTween){cameraTween.elapsed+=frameSeconds;const p=Math.min(cameraTween.elapsed/1.4,1),ease=p*p*(3-2*p);camera.position.lerpVectors(cameraTween.from,cameraTween.to,ease);controls.target.lerpVectors(cameraTween.fromTarget,cameraTween.toTarget,ease);if(p===1)cameraTween=undefined;}
      else if(props.tour&&!props.selectedId){const center=cityCenter(),size=span(),angle=time*.065;camera.position.set(center.x+Math.sin(angle)*size*.95,size*.7,center.z+Math.cos(angle)*size*.95);controls.target.copy(center);}
      else if(props.selectedId&&focusedId===props.selectedId){const target=traffic?.getPosition(props.selectedId);if(target){const followWeight=props.state?.simulation.running ? 1-Math.exp(-Math.min(frameSeconds,.5)*9) : 1;const delta=target.clone().sub(controls.target).multiplyScalar(followWeight);controls.target.add(delta);camera.position.add(delta);}}
      controls.update();urban?.animate(time);
      eventLayer.children.filter(o=>o instanceof T.Mesh).forEach(o=>{o.scale.setScalar(1+Math.sin(time*2.2)*.06);});
      if(aircraftLabel.value){const position=traffic?.getPosition(props.selectedId);if(position){const p=position.clone().add(new T.Vector3(0,32,0)).project(camera);const rect=renderer!.domElement.getBoundingClientRect();aircraftLabel.value.style.transform=`translate(${(p.x*.5+.5)*rect.width}px,${(-p.y*.5+.5)*rect.height}px) translate(-50%,-100%)`;aircraftLabel.value.style.visibility=p.z>1||p.x<-1||p.x>1||p.y<-1||p.y>1?'hidden':'visible';}}
      renderer!.render(scene,camera);
    };animation=requestAnimationFrame(draw);
  } catch(e){error.value=`三维场景初始化失败：${e instanceof Error?e.message:String(e)}`;}
});
onBeforeUnmount(()=>{if(resetFrameClock)document.removeEventListener('visibilitychange',resetFrameClock);disposed=true;cancelAnimationFrame(animation);observer?.disconnect();controls?.dispose();urban?.dispose();traffic?.dispose();disposeObject(eventLayer);if(introPlan)disposeObject(introPlan);if(comparison)disposeObject(comparison.group);if(renderer){renderer.domElement.removeEventListener('pointerdown',onPointerDown);renderer.domElement.removeEventListener('pointerup',onPointerUp);renderer.domElement.removeEventListener('webglcontextlost',contextLost);renderer.dispose();renderer.domElement.remove();}});
</script>

<template>
  <div class="city-scene" :class="{ daylight: !night }">
    <div ref="container" class="city-canvas" />
    <div class="city-vignette" />
    <div v-if="error" class="scene-error" role="alert">{{ error }}</div>
    <div v-if="selected" ref="aircraftLabel" class="drone-label"><b>{{ selected.id }}</b><span>{{ statusLabels[selected.status] || selected.status }} · {{ selected.position.z.toFixed(0) }} m</span><button title="退出无人机跟踪" @click="emit('select','')">×</button></div>
    <div class="city-status"><i />{{ state?.simulation.running ? '飞行运行中' : '城市态势就绪' }}<span>{{ formatTime(state?.simulation.time_s ?? 0) }}</span><small>{{ frameRate }} FPS</small></div>
    <div v-if="cameraTargetId" class="camera-story" aria-live="polite" :data-camera-phase="cameraStage" :data-camera-target="cameraTargetId"><i />{{ cameraStageLabel }}<span>{{ cameraTargetId }}</span></div>
    <DemoStory v-if="state?.aircraft.length && storyOpen" :state="state" :event="visibleEvent" :changes="changes" :mode="comparisonMode" :busy="!!busy" :focus-id="cameraTargetId || selectedId" :camera-phase="cameraStage" @inspect="startDemoFlight($event)" @mode="comparisonMode=$event" @play="emit('play')" @advance="emit('advance',$event)" @close="closeStory" @focus="visibleEvent ? focusEvent(visibleEvent,true) : openingCue && startDemoFlight(openingCue.aircraftId,true)" />
    <div v-else-if="state?.aircraft.length" class="event-reopen"><button @click="storyOpen=true;events.length && focusEvent(events[events.length-1]!,true)">展开演示讲解 ↗</button></div>
    <div class="city-minimap" aria-label="城市无人机平面位置图"><div><span>城区鸟瞰</span><b>N ↑</b></div><svg viewBox="0 0 160 120"><polygon v-for="building in minimapBuildings" :key="building.id" :points="building.points" fill="#527183" opacity=".55" /><rect v-for="site in minimapSites" :key="site.id" :x="site.x-1.8" :y="site.y-1.8" width="3.6" height="3.6" fill="#ffcc75" stroke="#152d36" stroke-width=".6"><title>{{ site.id }} 独立备降场地</title></rect><path v-for="a in minimapAircraft" :key="a.id" d="M 0 -4 L 2.8 3 L 0 1.5 L -2.8 3 Z" :transform="`translate(${a.mx},${a.my}) rotate(${a.heading}) scale(${a.id===selectedId || spotlightIds.includes(a.id) ? 1 : .7})`" :opacity="spotlightIds.length && !spotlightIds.includes(a.id) && a.id!==selectedId ? .3 : 1" :fill="a.id===selectedId?'#fff':['emergency','diverting','fault'].includes(a.status)?'#ffbd67':'#54eed2'" tabindex="0" role="button" :aria-label="`查看 ${a.id}`" @click="emit('select',a.id)" @keydown.enter="emit('select',a.id)" /></svg><p>{{ state?.aircraft.length ?? 0 }} 架飞行器 · {{ environment.buildings.length }} 栋建筑</p></div>
    <div class="city-credit"><a href="https://github.com/jstrait/city-tour" target="_blank" rel="noreferrer">City Tour</a> + <a href="https://github.com/jeromeetienne/threex.proceduralcity" target="_blank" rel="noreferrer">Procedural City</a><span>· MIT · 仿真城市</span></div>
  </div>
</template>

<style scoped>
.city-canvas{position:absolute;inset:0;overflow:hidden}.city-canvas :deep(canvas){display:block;width:100%;height:100%;touch-action:none}.city-vignette{position:absolute;inset:0;pointer-events:none;background:linear-gradient(180deg,#06111b85,transparent 28%,transparent 65%,#06111b9e)}
.camera-story{position:absolute;right:20px;top:137px;z-index:2;display:flex;align-items:center;gap:7px;padding:6px 9px;border:1px solid #6ce6cc35;border-radius:5px;background:#0c1d2bdc;color:#a6d9d1;font-size:10px;pointer-events:none}.camera-story i{width:5px;height:5px;border-radius:50%;background:#63e9d3}.camera-story span{color:#e7fff7;font:10px ui-monospace,monospace}
.city-status{position:absolute;right:20px;top:112px;display:flex;align-items:center;gap:8px;color:#b6cddd;font:10px ui-monospace,monospace;pointer-events:none}.city-status i{width:5px;height:5px;background:#54eed2;border-radius:50%;box-shadow:0 0 10px #54eed2}.city-status span{margin-left:8px;color:#e0edf5}.city-status small{color:#708b9e;margin-left:4px}
.event-reopen{position:absolute;top:112px;left:22px;z-index:3}.event-reopen button{background:#102033d9;color:#9aedd9;border-color:#36695f;font-size:11px}
.drone-label{position:absolute;left:0;top:0;z-index:3;pointer-events:none;white-space:nowrap;background:#0b182bef;border:1px solid #74ecd488;border-radius:8px;padding:9px 31px 9px 11px;box-shadow:0 8px 25px #0005}.drone-label b{display:block;color:#ebfffc;font:600 12px ui-monospace,monospace}.drone-label span{font-size:10px;color:#9eb8c9}.drone-label button{position:absolute;right:8px;top:5px;padding:0;background:none;border:0;color:#b3c9d7;min-height:22px;pointer-events:auto}
.city-minimap{position:absolute;bottom:25px;right:18px;width:162px;border:1px solid #adcde422;border-radius:10px;padding:10px;background:#0e1b2cdc;backdrop-filter:blur(10px);pointer-events:auto}.city-minimap>div{display:flex;justify-content:space-between;color:#8faabd;font-size:9px;letter-spacing:.05em}.city-minimap b{font:10px ui-monospace,monospace;color:#b7c9d8}.city-minimap svg{width:100%;display:block;margin:5px 0}.city-minimap path[role="button"]{cursor:pointer}.city-minimap path[role="button"]:focus{outline:none;stroke:#fff;stroke-width:1.5}.city-minimap p{font-size:8px;color:#809bae;text-align:center}.city-credit{position:absolute;left:22px;bottom:4px;color:#718b9e;font-size:8px;display:flex;gap:4px}.city-credit a{color:#809aac;text-decoration:none}.city-credit a:hover{color:#a4e6d8}.city-credit span{margin-left:3px}.scene-error{position:absolute;z-index:4;top:110px;left:22px;right:22px;padding:15px;background:#411e2bf2;color:#ffdce4;border:1px solid #fc637766;border-radius:9px}
@media(max-width:1050px){.camera-story{top:175px}.event-reopen,.city-status{top:150px}}
@media(max-width:700px){.camera-story{display:none}.city-minimap{width:118px;right:10px;bottom:75px}.city-status{right:12px;top:140px;font-size:9px}.city-status small{display:none}.city-credit{left:12px;font-size:7px}.event-reopen{top:167px;left:12px}}
</style>
