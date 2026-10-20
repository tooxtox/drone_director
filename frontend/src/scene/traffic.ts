import * as T from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { createMotionClock, createMotionTrack } from './motionPlayback';
import { headingToYaw, turnToward } from './flightPose';
import type { Position, Snapshot } from '../types/simulation';

// Preserve the backend's ENU metre coordinates; Three uses Y as its up axis.
export const world = (p: Position) => new T.Vector3(p.x, p.z, -p.y);
const colors = { normal: 0x54eed2, warning: 0xffb656, danger: 0xff637d, selected: 0xffffff };

export function disposeObject(object: T.Object3D) {
  const geometries = new Set<T.BufferGeometry>();
  const materials = new Set<T.Material>();
  const textures = new Set<T.Texture>();
  object.traverse(child => {
    const mesh = child as T.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    if (mesh.material) (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach(m => materials.add(m));
  });
  materials.forEach(m => {
    Object.values(m).forEach(value => { if (value instanceof T.Texture) textures.add(value); });
    m.dispose();
  });
  geometries.forEach(g => g.dispose()); textures.forEach(t => t.dispose());
  object.removeFromParent();
}

export function line(points: Position[], color: number, opacity = 1, dashed = false) {
  const geometry = new T.BufferGeometry().setFromPoints(points.map(world));
  const material = dashed ? new T.LineDashedMaterial({ color, transparent: true, opacity, dashSize: 16, gapSize: 10, depthWrite: false })
    : new T.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false });
  const result = new T.Line(geometry, material);
  if (dashed) result.computeLineDistances();
  return result;
}

function volume(points: {x:number; y:number}[], bottom: number, top: number, color: number) {
  const shape = new T.Shape(points.map(p => new T.Vector2(p.x, p.y)));
  const geometry = new T.ExtrudeGeometry(shape, { depth: top - bottom, bevelEnabled: false, steps: 1 });
  geometry.rotateX(-Math.PI / 2); geometry.translate(0, bottom, 0);
  const group = new T.Group();
  group.add(new T.Mesh(geometry, new T.MeshBasicMaterial({ color, transparent: true, opacity: .095, side: T.DoubleSide, depthWrite: false })));
  group.add(new T.LineSegments(new T.EdgesGeometry(geometry), new T.LineBasicMaterial({ color, transparent: true, opacity: .65 })));
  return group;
}

function label(text: string, color: string) {
  const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 64;
  const c = canvas.getContext('2d')!;
  c.fillStyle = '#0a1824d9'; c.roundRect(0, 0, 256, 64, 14); c.fill();
  c.font = '500 26px sans-serif'; c.textAlign = 'center'; c.fillStyle = color; c.fillText(text, 128, 41);
  const texture = new T.CanvasTexture(canvas); texture.colorSpace = T.SRGBColorSpace;
  const sprite = new T.Sprite(new T.SpriteMaterial({ map: texture, depthTest: false, transparent: true }));
  sprite.scale.set(110, 27.5, 1); sprite.renderOrder = 4; return sprite;
}

type Drone = { group:T.Group; material:T.MeshStandardMaterial; target:T.Vector3; heading:number; status:string; speed:number; motion:ReturnType<typeof createMotionTrack> };

export function createTrafficLayer() {
  const group = new T.Group(), drones = new T.Group(), topology = new T.Group(), tracks = new T.Group(), hazards = new T.Group();
  group.add(topology, tracks, hazards, drones);
  const aircraft = new Map<string, Drone>();
  const motionClock=createMotionClock();
  let topologyKey = '', hazardsKey = '', trackKey = '', selected = '';
  let activeState: Snapshot | undefined;
  let spotlight = new Set<string>();
  const bodyGeometry = new T.BoxGeometry(10, 3.5, 5.5);
  const armGeometry = new T.BoxGeometry(18, 1.2, 1.4);
  const motorGeometry = new T.CylinderGeometry(2, 2, 2, 8);
  const bladeGeometry = new T.BoxGeometry(8.5, .25, .7);
  const haloGeometry = new T.RingGeometry(14, 16, 40); haloGeometry.rotateX(-Math.PI / 2);
  // Merge each chassis; all propellers share one instanced draw for up to 500 aircraft.
  const chassisParts:T.BufferGeometry[]=[bodyGeometry.clone()];
  for(const rotation of [-Math.PI/4,Math.PI/4])chassisParts.push(armGeometry.clone().rotateY(rotation));
  for(const x of [-6,6])for(const z of [-6,6])chassisParts.push(motorGeometry.clone().translate(x,1,z));
  const noseGeometry = new T.ConeGeometry(2.2, 4, 6);
  noseGeometry.rotateZ(-Math.PI/2); noseGeometry.translate(6.5, 0, 0); chassisParts.push(noseGeometry);
  const chassis=mergeGeometries(chassisParts)!;chassisParts.forEach(g=>g.dispose());
  const rotorCross=bladeGeometry.clone().rotateY(Math.PI/2);
  const rotorGeometry=mergeGeometries([bladeGeometry,rotorCross])!;rotorCross.dispose();
  const bladeMat = new T.MeshStandardMaterial({ color: 0xc7d6dc, transparent: true, opacity: .5 });
  const rotors=new T.InstancedMesh(rotorGeometry,bladeMat,2000);rotors.count=0;rotors.frustumCulled=false;drones.add(rotors);
  const rotorTransform=new T.Object3D();
  const pulseObjects: T.Object3D[] = [];

  function makeDrone(id: string, position: Position) {
    const root = new T.Group(); root.userData.aircraftId = id;
    const material = new T.MeshStandardMaterial({ color: colors.normal, emissive: colors.normal, emissiveIntensity: .4, roughness: .35, metalness: .4 });
    root.add(new T.Mesh(chassis, material));
    const halo = new T.Mesh(haloGeometry, new T.MeshBasicMaterial({ color: colors.normal, transparent: true, opacity: .6, side: T.DoubleSide, depthWrite: false }));
    halo.name = 'halo'; halo.visible = false; root.add(halo);
    root.position.copy(world(position)); drones.add(root);
    const drone = { group: root, material, target: world(position), heading: 0, status: '', speed: 0, motion:createMotionTrack() }; aircraft.set(id, drone); return drone;
  }

  function segments(paths:Position[][],color:number,opacity:number,dashed=false) {
    const vertices:number[]=[];
    paths.forEach(points=>{for(let i=1;i<points.length;i++){world(points[i-1]!).toArray(vertices,vertices.length);world(points[i]!).toArray(vertices,vertices.length);}});
    const material=dashed?new T.LineDashedMaterial({color,transparent:true,opacity,dashSize:16,gapSize:10,depthWrite:false}):new T.LineBasicMaterial({color,transparent:true,opacity,depthWrite:false});
    const mesh=new T.LineSegments(new T.BufferGeometry().setAttribute('position',new T.Float32BufferAttribute(vertices,3)),material);
    if(dashed)mesh.computeLineDistances();return mesh;
  }

  function clear(layer: T.Group) { [...layer.children].forEach(disposeObject); }

  function update(state: Snapshot, selectedId: string, showTracks: boolean, showLabels: boolean, snap = false) {
    activeState = state; selected = selectedId;
    motionClock.ingest(state.simulation.time_s,state.simulation.speed,state.simulation.running,state.simulation.tick_seconds,performance.now(),snap);
    const ids = new Set(state.aircraft.map(a => a.id));
    aircraft.forEach((drone, id) => { if (!ids.has(id)) { const tag=drone.group.getObjectByName('spotlight-label');if(tag)disposeObject(tag);drone.material.dispose(); (drone.group.getObjectByName('halo') as T.Mesh).material && ((drone.group.getObjectByName('halo') as T.Mesh).material as T.Material).dispose(); drone.group.removeFromParent(); aircraft.delete(id); } });
    state.aircraft.forEach(a => {
      const isNew = !aircraft.has(a.id);
      const drone = aircraft.get(a.id) ?? makeDrone(a.id, a.position);
      drone.motion.ingest(a.motion_samples,state.simulation.time_s,a.position,a.heading,snap||isNew||!state.simulation.running);
      drone.target.copy(world(a.position)); if (snap || !state.simulation.running) drone.group.position.copy(drone.target);
      drone.status = a.status; drone.heading = headingToYaw(a.heading); drone.speed = a.speed;
      if (isNew || snap || !state.simulation.running) drone.group.rotation.set(0, drone.heading, 0, 'YXZ');
      const emergency = ['emergency', 'diverting', 'fault'].includes(a.status);
      const highlighted = spotlight.has(a.id), dimmed = spotlight.size > 0 && !highlighted && a.id !== selectedId;
      const color = a.id === selectedId ? colors.selected : emergency ? colors.warning : colors.normal;
      drone.material.transparent = dimmed; drone.material.opacity = dimmed ? .28 : 1;
      drone.material.emissiveIntensity = highlighted ? .9 : dimmed ? .08 : .4;
      let tag=drone.group.getObjectByName('spotlight-label');
      if(highlighted && !tag){tag=label(a.id,'#b5ffe9');tag.name='spotlight-label';tag.position.set(0,28,0);tag.scale.set(62,15.5,1);drone.group.add(tag);}
      if(tag)tag.visible=highlighted && showLabels && a.id!==selectedId;
      drone.material.color.setHex(color); drone.material.emissive.setHex(color);
      drone.group.getObjectByName('halo')!.visible = a.id === selectedId || emergency || highlighted;
      ((drone.group.getObjectByName('halo') as T.Mesh).material as T.MeshBasicMaterial).color.setHex(color);
    });
    const focusEndpoint=state.aircraft.find(a=>a.id===selectedId)?.flight_plan?.at(-1);
    const endpointKey=spotlight.size ? JSON.stringify([selectedId,focusEndpoint]) : 'all';
    const nextTopology = `${endpointKey}:${state.environment_version}:${showLabels}:${state.routes.map(r => `${r.id}:${r.status}:${r.current_flow >= r.capacity}`).join('|')}`;
    if (topologyKey !== nextTopology) {
      topologyKey = nextTopology; clear(topology);
      const byId = new Map(state.waypoints.map(w => [w.id, w]));
      const routesByColor=new Map<number,Position[][]>();
      state.routes.forEach(r => {
        const points = (r.waypoint_ids.length ? r.waypoint_ids : [r.start,r.end]).map(id => byId.get(id)?.position).filter((p):p is Position => !!p);
        if (points.length < 2) return;
        const color = ['closed','restricted'].includes(r.status) ? colors.danger : r.status === 'congested' || r.current_flow >= r.capacity ? colors.warning : colors.normal;
        if(!routesByColor.has(color))routesByColor.set(color,[]);routesByColor.get(color)!.push(points);
      });
      routesByColor.forEach((paths,color)=>topology.add(segments(paths,color,color===colors.normal ? .12 : .75,true)));
      const ports = state.waypoints.filter(w => ['vertiport', 'emergency_bay'].includes(w.type) && (!spotlight.size || focusEndpoint && Math.hypot(w.position.x-focusEndpoint.x,w.position.y-focusEndpoint.y,w.position.z-focusEndpoint.z)<1));
      const sampleEvery = Math.max(1, Math.ceil(ports.length / 8));
      if (showLabels) ports.filter((w, i) => w.type === 'emergency_bay' || i % sampleEvery === 0).slice(0, 16).forEach(w => {
        const tag = label(w.type === 'emergency_bay' ? `备降 ${w.id}` : w.name || w.id, w.type === 'emergency_bay' ? '#ffca7d' : '#a6eee3');
        tag.position.copy(world({ ...w.position, z: Math.max(w.position.z, 20) + 45 })); topology.add(tag);
      });
    }
    const nextTracks = `${[...spotlight].join(',')}:${Math.floor(state.simulation.time_s / 2)}:${state.simulation.running ? '' : state.version}:${selectedId}:${showTracks}`;
    if (nextTracks !== trackKey || snap) {
      trackKey = nextTracks; clear(tracks);
      if (showTracks) {
        const normalPaths=state.aircraft.filter(a=>a.id!==selectedId && (!spotlight.size || spotlight.has(a.id))).map(a=>a.trajectory?.slice(-100)??[]).filter(p=>p.length>1);
        if(normalPaths.length)tracks.add(segments(normalPaths,colors.normal,.22));
        const selectedTrack=state.aircraft.find(a=>a.id===selectedId)?.trajectory?.slice(-100);
        if(selectedTrack&&selectedTrack.length>1)tracks.add(line(selectedTrack,colors.selected,.9));
      }
      const target = state.aircraft.find(a => a.id === selectedId);
      if (!spotlight.size && target?.flight_plan?.length) tracks.add(line([target.position, ...target.flight_plan], colors.warning, .95, true));
      if (target) tracks.add(line([{...target.position,z:1},target.position], colors.selected, .35, true));
    }
    const nextHazards = JSON.stringify([state.weather, state.restrictions, state.conflicts]);
    if (nextHazards !== hazardsKey) {
      hazardsKey = nextHazards; clear(hazards); pulseObjects.length = 0;
      state.restrictions.filter(r => r.active).forEach(r => hazards.add(volume(r.polygon.points, r.min_altitude, r.max_altitude, colors.danger)));
      state.weather.filter(w => w.precipitation !== 'none' || w.wind_speed >= 12).forEach(w => {
        hazards.add(volume(w.affected_area.points, 1, 310, colors.warning));
        const xs = w.affected_area.points.map(p => p.x), ys = w.affected_area.points.map(p => p.y);
        const positions = new Float32Array(160 * 3);
        for (let i = 0; i < 160; i++) { positions[i*3] = Math.min(...xs) + ((i * .618033) % 1) * (Math.max(...xs)-Math.min(...xs)); positions[i*3+1] = ((i * .75488) % 1)*300; positions[i*3+2] = -(Math.min(...ys) + ((i * .414214) % 1)*(Math.max(...ys)-Math.min(...ys))); }
        const rain = new T.Points(new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(positions,3)), new T.PointsMaterial({color:0xa8c8ef,size:3,transparent:true,opacity:.65})); rain.name='rain'; hazards.add(rain);
      });
      state.conflicts.forEach(c => {
        const ring = new T.Mesh(new T.TorusGeometry(23, 1.7, 6, 40),new T.MeshBasicMaterial({ color:colors.danger,transparent:true,opacity:.9,depthTest:false }));
        ring.position.copy(world(c.conflict_position)); hazards.add(ring); pulseObjects.push(ring);
      });
    }
  }

  return { group, drones, update, setSpotlight(ids: string[]) { spotlight = new Set(ids); }, getPosition: (id:string) => aircraft.get(id)?.group.position,
    animate(dt:number, time:number, camera:T.Camera) {
      dt=Math.min(Math.max(dt,0),.25);
      const renderTime=motionClock.sample(performance.now());
      let rotorIndex=0;const rotorIds:string[]=[];
      aircraft.forEach((d,id) => {
        const pose=d.motion.sample(renderTime);
        if(pose){d.group.position.copy(world(pose.position));d.heading=headingToYaw(pose.heading);}
        const previousYaw=d.group.rotation.y;
        const yaw=turnToward(previousYaw,d.heading,dt);
        const moving=!!activeState?.simulation.running && d.speed>0 && !['landed','grounded','offline'].includes(d.status);
        const bank=moving ? T.MathUtils.clamp((yaw-previousYaw)/Math.max(dt,.001)*.08,-.16,.16) : 0;
        d.group.rotation.order='YXZ';
        d.group.rotation.y=yaw;
        d.group.rotation.x=T.MathUtils.lerp(d.group.rotation.x,bank,1-Math.exp(-dt*6));
        d.group.rotation.z=T.MathUtils.lerp(d.group.rotation.z,moving ? -.055 : 0,1-Math.exp(-dt*6));
        const scale = T.MathUtils.clamp(camera.position.distanceTo(d.group.position)/700, 1, 3.6);
        d.group.scale.setScalar(id === selected ? scale*1.15 : scale);
        d.group.updateMatrixWorld();
        const spin=activeState?.simulation.running && !['landed','grounded','offline'].includes(d.status)?time*50:0;
        for(const x of [-6,6])for(const z of [-6,6]){
          rotorTransform.position.set(x,2.3,z);rotorTransform.rotation.set(0,spin*(x*z>0?1:-1),0);rotorTransform.scale.setScalar(1);rotorTransform.updateMatrix();
          rotors.setMatrixAt(rotorIndex++,d.group.matrixWorld.clone().multiply(rotorTransform.matrix));rotorIds.push(id);
        }
      });
      rotors.count=rotorIndex;rotors.instanceMatrix.needsUpdate=true;rotors.userData.aircraftIds=rotorIds;
      pulseObjects.forEach(o => { o.scale.setScalar(1 + Math.sin(time*3)*.12); o.lookAt(camera.position); });
      hazards.children.filter(o => o.name === 'rain').forEach(o => {
        if (!activeState?.simulation.running) return;
        const attribute = (o as T.Points).geometry.getAttribute('position');
        for (let i=0;i<attribute.count;i++) attribute.setY(i,(attribute.getY(i)-dt*130+300)%300); attribute.needsUpdate=true;
      });
    },
    dispose() {
      clear(topology);clear(tracks);clear(hazards);
      aircraft.forEach(d=>{ const tag=d.group.getObjectByName('spotlight-label');if(tag)disposeObject(tag);d.material.dispose(); ((d.group.getObjectByName('halo') as T.Mesh).material as T.Material).dispose(); });
      [bodyGeometry,armGeometry,motorGeometry,bladeGeometry,haloGeometry,chassis,rotorGeometry].forEach(g=>g.dispose());bladeMat.dispose(); group.removeFromParent(); aircraft.clear();
    }
  };
}
