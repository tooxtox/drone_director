/**
 * City Tour's instance/prototype building renderer, adapted to registered city footprints,
 * with the Canvas window-texture technique from THREEx.ProceduralCity.
 * Original sources and MIT notices: public/licenses/ and docs/city-sources.md.
 */
import * as THREE from 'three';
import { emergencySites, groundLayout } from './landingSites';
import type { Environment, Waypoint } from '../types/simulation';

type Bounds = { minX: number; maxX: number; minY: number; maxY: number };
type Instance = { x: number; y: number; z: number; sx: number; sy: number; sz: number; rotation?: number; color?: number };
type UrbanCity = { group: THREE.Group; animate(timeSeconds: number): void; setNight(night: boolean): void; dispose(): void };
const COLORS = [0x9babb8, 0xb6c1c9, 0x8b9fac, 0xcccbc3, 0x6e8797, 0xa6b0ad];

function hash(value: string): number {
  let result = 2166136261;
  for (let i = 0; i < value.length; i++) result = Math.imul(result ^ value.charCodeAt(i), 16777619);
  return result >>> 0;
}
function random(seed: number): () => number {
  let value = seed;
  return () => { value = (Math.imul(value, 1664525) + 1013904223) >>> 0; return value / 4294967296; };
}
function canvasTexture(canvas: HTMLCanvasElement): THREE.CanvasTexture {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.generateMipmaps = true;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 8;
  return texture;
}

// Adapted from generateTextureCanvas() in threex.proceduralcity.js: draw a tiny
// deterministic window grid, then enlarge it with interpolation disabled.
function facadeTextures() {
  const create = (emission: boolean) => {
    const tiny = document.createElement('canvas');
    tiny.width = 64; tiny.height = 64;
    const context = tiny.getContext('2d')!;
    context.fillStyle = emission ? '#000000' : '#c1cbd1';
    context.fillRect(0, 0, 64, 64);
    const next = random(4017);
    for (let y = 1; y < 64; y += 2) {
      // Continuous glazing and small, coherent illuminated office suites remain
      // legible as broad floor bands when the camera pulls out to city scale.
      if (!emission) { context.fillStyle = '#466070'; context.fillRect(0, y, 64, 1); }
      for (let x = 0; x < 64; x += 4) {
        const brightness = next();
        context.fillStyle = emission ? (brightness > 0.76 ? (brightness > 0.94 ? '#d7b57b' : '#96683c') : '#000000')
          : (brightness > 0.85 ? '#79909c' : brightness > 0.5 ? '#526d7e' : '#405969');
        context.fillRect(x, y, 3, 1);
      }
    }
    const enlarged = document.createElement('canvas');
    enlarged.width = 512; enlarged.height = 1024;
    const output = enlarged.getContext('2d')!;
    output.imageSmoothingEnabled = false;
    output.drawImage(tiny, 0, 0, enlarged.width, enlarged.height);
    return canvasTexture(enlarged);
  };
  const roof = document.createElement('canvas');
  roof.width = roof.height = 256;
  const context = roof.getContext('2d')!;
  context.fillStyle = '#687987'; context.fillRect(0, 0, 256, 256);
  context.strokeStyle = '#81919a'; context.lineWidth = 1;
  for (let i = 0; i < 256; i += 32) {
    context.beginPath(); context.moveTo(i, 0); context.lineTo(i, 256); context.stroke();
    context.beginPath(); context.moveTo(0, i); context.lineTo(256, i); context.stroke();
  }
  for (const [x, y] of [[36, 36], [132, 148], [36, 180]]) {
    context.fillStyle = '#344954'; context.fillRect(x, y, 44, 24);
    context.fillStyle = '#9cabb0'; context.fillRect(x + 2, y + 2, 40, 20);
    context.strokeStyle = '#475b66';
    for (let i = 5; i < 40; i += 4) { context.beginPath(); context.moveTo(x + i, y + 3); context.lineTo(x + i, y + 20); context.stroke(); }
  }
  return { facade: create(false), windows: create(true), roof: canvasTexture(roof) };
}

function footprintBounds(points: { x: number; y: number }[]): Bounds {
  return { minX: Math.min(...points.map(p => p.x)), maxX: Math.max(...points.map(p => p.x)),
    minY: Math.min(...points.map(p => p.y)), maxY: Math.max(...points.map(p => p.y)) };
}

export function buildUrbanCity(environment: Environment, waypoints: Waypoint[]): UrbanCity {
  const layout=groundLayout(environment), PERIOD=layout.block_period, STREET=layout.street_width;
  const landingLots=emergencySites(environment,waypoints);
  const group = new THREE.Group();
  group.name = 'registered-urban-city';
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  const nightUniform = { value: 1 };
  const box = new THREE.BoxGeometry(1, 1, 1); geometries.add(box);
  const trunk = new THREE.CylinderGeometry(0.6, 0.9, 1, 5); geometries.add(trunk);
  const crown = new THREE.IcosahedronGeometry(1, 1); geometries.add(crown);
  const prototype = new THREE.Object3D();
  const color = new THREE.Color();
  const material = (settings: THREE.MeshStandardMaterialParameters) => {
    const result = new THREE.MeshStandardMaterial(settings); materials.add(result); return result;
  };
  const instances = (name: string, records: Instance[], geometry: THREE.BufferGeometry, surface: THREE.Material, shadows = false) => {
    const mesh = new THREE.InstancedMesh(geometry, surface, records.length);
    mesh.name = name; mesh.castShadow = shadows; mesh.receiveShadow = true;
    records.forEach((record, index) => {
      prototype.position.set(record.x, record.y, record.z);
      prototype.rotation.set(0, record.rotation || 0, 0);
      prototype.scale.set(record.sx, record.sy, record.sz);
      prototype.updateMatrix(); mesh.setMatrixAt(index, prototype.matrix);
      if (record.color !== undefined) mesh.setColorAt(index, color.set(record.color));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (records.length) mesh.computeBoundingSphere();
    group.add(mesh); return mesh;
  };
  const block = (name: string, x: number, y: number, z: number, width: number, height: number, depth: number, surface: THREE.Material) =>
    instances(name, [{ x, y, z, sx: width, sy: height, sz: depth }], box, surface);
  const bounds = environment.bounds;
  const width = bounds.max_x - bounds.min_x;
  const depth = bounds.max_y - bounds.min_y;
  const centerX = (bounds.min_x + bounds.max_x) / 2;
  const centerY = (bounds.min_y + bounds.max_y) / 2;
  const paving = material({ color: 0x6c7d81, roughness: 0.95 });
  const barkSurface = material({ color: 0x475146, roughness: 1 });
  const foliageSurface = material({ color: 0x71957b, roughness: 1 });
  const lightSurface = material({ color: 0xffdf9a, emissive: 0xffba62, emissiveIntensity: 1.4 });
  const metalSurface = material({ color: 0x637985, metalness: 0.6, roughness: 0.5 });

  // The base and waterfront extend outside the simulation bounds; the interior
  // street grid uses exactly CityBuilder's 200 m period / 40 m street corridors.
  block('diorama-foundation', centerX, -22, -centerY, width + 240, 36, depth + 240,
    material({ color: 0x172f39, roughness: 0.8, metalness: 0.18 }));
  const horizontal: number[] = [];
  const vertical: number[] = [];
  for (let x = bounds.min_x; x <= bounds.max_x + 0.1; x += PERIOD) vertical.push(x);
  for (let y = bounds.min_y; y <= bounds.max_y + 0.1; y += PERIOD) horizontal.push(y);
  const sidewalkRecords: Instance[] = [];
  const roadRecords: Instance[] = [];
  const lineRecords: Instance[] = [];
  const centerlineRecords: Instance[] = [];
  for (const x of vertical) {
    sidewalkRecords.push({ x, y: 0.12, z: -centerY, sx: STREET, sy: 0.22, sz: depth + 100 });
    roadRecords.push({ x, y: 0.27, z: -centerY, sx: 26, sy: 0.08, sz: depth + 100 });
    for (let y = bounds.min_y - 40; y < bounds.max_y + 40; y += 24) {
      if (horizontal.some(crossing => Math.abs(crossing - y) < 25)) continue;
      lineRecords.push({ x: x + 6.5, y: 0.34, z: -y, sx: 0.32, sy: 0.02, sz: 10 },
        { x: x - 6.5, y: 0.34, z: -y, sx: 0.32, sy: 0.02, sz: 10 });
      centerlineRecords.push({ x, y: 0.34, z: -y, sx: 0.25, sy: 0.02, sz: 18 });
    }
  }
  for (const y of horizontal) {
    sidewalkRecords.push({ x: centerX, y: 0.12, z: -y, sx: width + 100, sy: 0.22, sz: STREET });
    roadRecords.push({ x: centerX, y: 0.275, z: -y, sx: width + 100, sy: 0.08, sz: 26 });
    for (let x = bounds.min_x - 40; x < bounds.max_x + 40; x += 24) {
      if (vertical.some(crossing => Math.abs(crossing - x) < 25)) continue;
      lineRecords.push({ x, y: 0.34, z: -y + 6.5, sx: 10, sy: 0.02, sz: 0.32 },
        { x, y: 0.34, z: -y - 6.5, sx: 10, sy: 0.02, sz: 0.32 });
      centerlineRecords.push({ x, y: 0.34, z: -y, sx: 18, sy: 0.02, sz: 0.25 });
    }
  }
  // Zebra crossings sit just outside the junction square.
  for (const x of vertical) for (const y of horizontal) {
    for (let stripe = -10; stripe <= 10; stripe += 4) {
      lineRecords.push({ x: x + stripe, y: 0.35, z: -y + 23, sx: 2, sy: 0.02, sz: 6 },
        { x: x + stripe, y: 0.35, z: -y - 23, sx: 2, sy: 0.02, sz: 6 },
        { x: x - 23, y: 0.35, z: -y + stripe, sx: 6, sy: 0.02, sz: 2 },
        { x: x + 23, y: 0.35, z: -y + stripe, sx: 6, sy: 0.02, sz: 2 });
    }
  }

  const facade = facadeTextures();
  Object.values(facade).forEach(texture => textures.add(texture));
  const buildingSurface = material({ color: 0xffffff, roughness: 0.74, metalness: 0.14,
    map: facade.facade, emissive: 0xffffff, emissiveMap: facade.windows, emissiveIntensity: 0.52 });
  // Window size is measured in world metres, independently of building instance
  // scale. The roofs retain the exact registered height; their HVAC detail is texture.
  buildingSurface.onBeforeCompile = shader => {
    shader.uniforms.cityNight = nightUniform;
    shader.uniforms.cityRoof = { value: facade.roof };
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vCityPosition;\nvarying vec3 vCityNormal;');
    shader.vertexShader = shader.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
      vec4 cityVertex = vec4(transformed, 1.0);
      #ifdef USE_INSTANCING
        cityVertex = instanceMatrix * cityVertex;
      #endif
      vCityPosition = (modelMatrix * cityVertex).xyz;
      vCityNormal = normalize(mat3(modelMatrix) * objectNormal);`);
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>
      varying vec3 vCityPosition;
      varying vec3 vCityNormal;
      uniform float cityNight;
      uniform sampler2D cityRoof;
      vec2 cityWindowUV() {
        float facadeX = abs(vCityNormal.x) > abs(vCityNormal.z) ? vCityPosition.z : vCityPosition.x;
        return vec2(facadeX / 112.0, vCityPosition.y / 128.0);
      }`);
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
      if (abs(vCityNormal.y) > 0.5) {
        diffuseColor.rgb *= texture2D(cityRoof, vCityPosition.xz / 128.0).rgb;
      } else {
        diffuseColor.rgb *= texture2D(map, cityWindowUV()).rgb;
      }`);
    shader.fragmentShader = shader.fragmentShader.replace('#include <emissivemap_fragment>', `
      if (abs(vCityNormal.y) < 0.5) {
        totalEmissiveRadiance *= texture2D(emissiveMap, cityWindowUV()).rgb * cityNight;
      } else { totalEmissiveRadiance *= 0.0; }`);
  };
  buildingSurface.customProgramCacheKey = () => 'registered-city-world-facade-v1';
  const rectangles: Instance[] = [];
  const buildingBounds: Bounds[] = [];
  for (const building of environment.buildings) {
    const points = building.footprint.points.filter((point, index, all) =>
      index === 0 || point.x !== all[0].x || point.y !== all[0].y);
    if (points.length < 3 || building.height <= 0) continue;
    const bb = footprintBounds(points); buildingBounds.push(bb);
    const tint = COLORS[hash(building.id) % COLORS.length]!;
    const isRectangle = points.length === 4 && points.every(p =>
      (p.x === bb.minX || p.x === bb.maxX) && (p.y === bb.minY || p.y === bb.maxY));
    if (isRectangle) {
      rectangles.push({ x: (bb.minX + bb.maxX) / 2, y: building.elevation + building.height / 2,
        z: -(bb.minY + bb.maxY) / 2, sx: bb.maxX - bb.minX, sy: building.height, sz: bb.maxY - bb.minY, color: tint });
    } else {
      const shape = new THREE.Shape(points.map(p => new THREE.Vector2(p.x, p.y)));
      const geometry = new THREE.ExtrudeGeometry(shape, { depth: building.height, bevelEnabled: false, steps: 1 });
      geometry.rotateX(-Math.PI / 2);
      // Keep one material/shader, with per-vertex building tint for nonrectangular lots.
      const values = new Float32Array(geometry.getAttribute('position').count * 3);
      const tintColor = new THREE.Color(tint);
      for (let i = 0; i < values.length; i += 3) tintColor.toArray(values, i);
      geometry.setAttribute('color', new THREE.BufferAttribute(values, 3));
      geometries.add(geometry);
      const surface = buildingSurface.clone(); surface.vertexColors = true;
      surface.onBeforeCompile = buildingSurface.onBeforeCompile;
      surface.customProgramCacheKey = buildingSurface.customProgramCacheKey;
      materials.add(surface);
      const mesh = new THREE.Mesh(geometry, surface); mesh.position.y = building.elevation;
      mesh.castShadow = mesh.receiveShadow = true; mesh.name = `registered-building-${building.id}`; group.add(mesh);
    }
  }
  instances('registered-building-instances', rectangles, box, buildingSurface, true);

  const clear = (x: number, y: number, margin = 4) => !buildingBounds.some(b =>
    x > b.minX - margin && x < b.maxX + margin && y > b.minY - margin && y < b.maxY + margin)
    && !waypoints.some(w => Math.hypot(w.position.x - x, w.position.y - y) < 65);
  const parks: Instance[] = [];
  const trees: Instance[] = [];
  const treeTrunks: Instance[] = [];
  const parkPaths: Instance[] = [];
  const addTree = (x: number, y: number, seed: number) => {
    if (!clear(x, y, 7)) return;
    const next = random(seed);
    const size = 3.4 + next() * 2;
    treeTrunks.push({ x, y: 2.5, z: -y, sx: 1, sy: 5, sz: 1 });
    trees.push({ x, y: 4.3 + size * 0.18, z: -y, sx: size, sy: size * 0.76, sz: size,
      rotation: next() * Math.PI, color: [0x618875, 0x7a9981, 0x456b5c][seed % 3] });
  };
  for (let x = bounds.min_x + 100; x < bounds.max_x - 30; x += PERIOD) {
    for (let y = bounds.min_y + 100; y < bounds.max_y - 30; y += PERIOD) {
      const occupied = buildingBounds.some(b => b.minX < x + 76 && b.maxX > x - 76 && b.minY < y + 76 && b.maxY > y - 76);
      if (occupied) continue;
      parks.push({ x, y: 0.02, z: -y, sx: 148, sy: 0.04, sz: 148, color: ((x + y) % 400 ? 0x436b57 : 0x395d4f) });
      parkPaths.push({ x, y: 0.08, z: -y, sx: 142, sy: 0.1, sz: 5 }, { x, y: 0.08, z: -y, sx: 5, sy: 0.1, sz: 142 });
      for (let tx = -52; tx <= 52; tx += 52) for (let ty = -52; ty <= 52; ty += 52) {
        if (tx || ty) addTree(x + tx, y + ty, hash(`${x}:${y}:${tx}:${ty}`));
      }
    }
  }
  for (const x of vertical) for (let y = bounds.min_y + 60; y < bounds.max_y; y += 80) {
    if (horizontal.some(crossing => Math.abs(y - crossing) < 38)) continue;
    addTree(x + 16, y, hash(`avenue:${x}:${y}`));
    addTree(x - 16, y + 15, hash(`avenue:${x}:${y}:b`));
  }
  // Bake all coplanar city ground into one mipmapped texture. Several layers
  // only centimetres apart cause depth fighting at a multi-kilometre overview.
  // This also lets lane markings blend into asphalt smoothly at a distance.
  const groundCanvas = document.createElement('canvas');
  groundCanvas.width = groundCanvas.height = 4096;
  const groundContext = groundCanvas.getContext('2d')!;
  // PlaneGeometry's +V side becomes north after rotating it onto the ground.
  groundContext.translate(0, groundCanvas.height); groundContext.scale(1, -1);
  const groundWidth = width + 235, groundDepth = depth + 235;
  const originX = bounds.min_x - 117.5, originY = bounds.min_y - 117.5;
  const scaleX = groundCanvas.width / groundWidth, scaleY = groundCanvas.height / groundDepth;
  groundContext.fillStyle = '#3e5952';
  groundContext.fillRect(0, 0, groundCanvas.width, groundCanvas.height);
  const drawGround = (records: Instance[], fill: string) => {
    for (const record of records) {
      groundContext.fillStyle = record.color === undefined ? fill : `#${record.color.toString(16).padStart(6, '0')}`;
      groundContext.fillRect((record.x - record.sx / 2 - originX) * scaleX,
        (-record.z - record.sz / 2 - originY) * scaleY, record.sx * scaleX, record.sz * scaleY);
    }
  };
  drawGround(parks, '#446d58');
  drawGround(parkPaths, '#768684');
  drawGround(sidewalkRecords, '#67787c');
  drawGround(roadRecords, '#2c3d44');
  drawGround(lineRecords, '#929e9d');
  drawGround(centerlineRecords, '#a88f59');
  // Real, off-street lots share the simulator's coordinates and safety footprint.
  // Ground markings stay at z=0; a raised display platform would falsify touchdown height.
  const siteBorders:Instance[]=[];
  const siteLights:Instance[]=[];
  for(const site of landingLots){
    const p=site.position,size=layout.emergency_site_size,half=size/2;
    drawGround([{x:p.x,y:0,z:-p.y,sx:size,sy:1,sz:size}], '#b79652');
    drawGround([{x:p.x,y:0,z:-p.y,sx:size-3,sy:1,sz:size-3}], '#475a54');
    const px=(p.x-originX)*scaleX,py=(p.y-originY)*scaleY;
    groundContext.save();groundContext.translate(px,py);groundContext.scale(scaleX,scaleY);
    groundContext.fillStyle='#293f3e';groundContext.beginPath();groundContext.arc(0,0,layout.emergency_pad_radius,0,Math.PI*2);groundContext.fill();
    groundContext.strokeStyle='#f2c96b';groundContext.lineWidth=1.2;groundContext.beginPath();groundContext.arc(0,0,layout.emergency_pad_radius,0,Math.PI*2);groundContext.stroke();
    groundContext.setLineDash([3,2]);groundContext.lineWidth=.6;groundContext.beginPath();groundContext.arc(0,0,layout.emergency_pad_radius+8,0,Math.PI*2);groundContext.stroke();
    groundContext.setLineDash([]);groundContext.fillStyle='#e9f6ee';groundContext.font='bold 21px sans-serif';groundContext.textAlign='center';groundContext.textBaseline='middle';groundContext.fillText('H',0,0);
    groundContext.restore();
    for(const dx of [-half+2,half-2])for(const dy of [-half+2,half-2]){
      siteBorders.push({x:p.x+dx,y:.45,z:-p.y-dy,sx:1.4,sy:.9,sz:1.4});
      siteLights.push({x:p.x+dx,y:1,z:-p.y-dy,sx:1.2,sy:.25,sz:1.2});
    }
  }
  instances('emergency-site-corner-bollards',siteBorders,box,metalSurface);
  instances('emergency-site-perimeter-lights',siteLights,box,lightSurface);

  drawGround([{ x: centerX, z: -bounds.max_y - 30, y: 0, sx: width + 100, sy: 1, sz: 10 }], '#73847f');
  // The water occupies a hole in the ground plane, so its surface never
  // competes with a nearly coincident terrain triangle in the depth buffer.
  groundContext.clearRect(0, (bounds.max_y + 35 - originY) * scaleY, groundCanvas.width, 78 * scaleY);
  const groundTexture = canvasTexture(groundCanvas); textures.add(groundTexture);
  groundTexture.wrapS = groundTexture.wrapT = THREE.ClampToEdgeWrapping;
  const groundGeometry = new THREE.PlaneGeometry(groundWidth, groundDepth); geometries.add(groundGeometry);
  groundGeometry.rotateX(-Math.PI / 2);
  const ground = new THREE.Mesh(groundGeometry, material({ color: 0xffffff, map: groundTexture, roughness: 0.92, alphaTest: 0.5 }));
  ground.name = 'mipmapped-city-ground'; ground.position.set(centerX, -0.03, -centerY);
  ground.receiveShadow = true; group.add(ground);
  const poles: Instance[] = [];
  const bulbs: Instance[] = [];
  for (const y of horizontal) for (let x = bounds.min_x + 56; x < bounds.max_x; x += 88) {
    if (!clear(x, y + 16, 1) || vertical.some(crossing => Math.abs(x - crossing) < 28)) continue;
    poles.push({ x, y: 4.2, z: -y - 16, sx: 0.75, sy: 8.4, sz: 0.75 },
      { x, y: 8.1, z: -y - 13.5, sx: 0.6, sy: 0.6, sz: 5 });
    bulbs.push({ x, y: 7.8, z: -y - 11.3, sx: 2, sy: 0.45, sz: 2 });
  }
  instances('avenue-light-poles', poles, box, metalSurface);
  instances('avenue-light-fixtures', bulbs, box, lightSurface);

  // Water and promenade are entirely beyond max_y, clear of registered buildings.
  const waterCanvas = document.createElement('canvas'); waterCanvas.width = waterCanvas.height = 128;
  const waterContext = waterCanvas.getContext('2d')!;
  waterContext.fillStyle = '#385d6d'; waterContext.fillRect(0, 0, 128, 128);
  waterContext.strokeStyle = '#638490'; waterContext.lineWidth = 1;
  const waterRandom = random(88);
  for (let i = 0; i < 65; i++) {
    const x = waterRandom() * 128, y = waterRandom() * 128;
    waterContext.beginPath(); waterContext.moveTo(x, y); waterContext.lineTo(x + 8 + waterRandom() * 18, y); waterContext.stroke();
  }
  const waterTexture = canvasTexture(waterCanvas); waterTexture.repeat.set(Math.max(1, width / 110), 2); textures.add(waterTexture);
  const water = material({ color: 0x527d8c, map: waterTexture, roughness: 0.27, metalness: 0.45 });
  block('north-waterfront', centerX, -0.12, -bounds.max_y - 74, width + 235, 0.2, 78, water);
  const quayLights: Instance[] = [];
  for (let x = bounds.min_x; x <= bounds.max_x; x += 48) {
    quayLights.push({ x, y: 0.5, z: -bounds.max_y - 34, sx: 2, sy: 0.18, sz: 1 });
    addTree(x, bounds.max_y + 21, hash(`quay:${x}`));
  }
  instances('waterfront-guide-lights', quayLights, box, lightSurface);
  instances('street-tree-trunks', treeTrunks, trunk, barkSurface);
  instances('street-tree-canopies', trees, crown, foliageSurface, true);

  // A small batched ground-traffic layer makes the city feel occupied. Cars
  // stay in the street corridors and never change simulation aircraft state.
  const carCount = Math.min(32, Math.max(8, Math.round(width / 80)));
  const carColors = [0xa4b5c0, 0xe3d3b0, 0x3c7882, 0xb56353, 0x748999];
  const records = Array.from({ length: carCount }, (_, i) => ({ x: 0, y: 1.3, z: 0, sx: 7.2, sy: 1.8, sz: 3.2, color: carColors[i % carColors.length] }));
  const carBodies = instances('moving-city-traffic', records, box, material({ color: 0xffffff, metalness: 0.35, roughness: 0.5 }));
  const carRoofs = instances('moving-city-traffic-glass', records, box, material({ color: 0x213b4d, roughness: 0.3, metalness: 0.4 }));
  const headlights = instances('moving-city-traffic-lights', [...records, ...records], box, lightSurface);
  carBodies.frustumCulled = carRoofs.frustumCulled = headlights.frustumCulled = false;
  const traffic = records.map((_, index) => {
    const next = random(293 + index * 81);
    const alongX = index % 2 === 0;
    const lines = alongX ? horizontal : vertical;
    return { alongX, line: lines[Math.floor(next() * lines.length)]!, direction: index % 4 < 2 ? 1 : -1,
      offset: next(), speed: 7 + next() * 8 };
  });
  const move = (mesh: THREE.InstancedMesh, index: number, x: number, y: number, z: number, sx: number, sy: number, sz: number, rotation: number) => {
    prototype.position.set(x, y, z); prototype.rotation.set(0, rotation, 0); prototype.scale.set(sx, sy, sz);
    prototype.updateMatrix(); mesh.setMatrixAt(index, prototype.matrix);
  };
  let lastTrafficTime = -1;
  const animate = (timeSeconds: number) => {
    waterTexture.offset.x = timeSeconds * 0.004;
    waterTexture.offset.y = timeSeconds * 0.001;
    // 20 Hz is sufficient for ground traffic; drone interpolation uses the scene loop.
    const frame = Math.floor(timeSeconds * 20);
    if (frame === lastTrafficTime) return;
    lastTrafficTime = frame;
    traffic.forEach((car, index) => {
      const span = (car.alongX ? width : depth) + 80;
      const start = (car.alongX ? bounds.min_x : bounds.min_y) - 40;
      const progress = ((car.offset * span + timeSeconds * car.speed * car.direction) % span + span) % span;
      const position = start + progress;
      const x = car.alongX ? position : car.line + car.direction * 6;
      const z = car.alongX ? -car.line - car.direction * 6 : -position;
      const rotation = car.alongX ? (car.direction > 0 ? 0 : Math.PI) : (car.direction > 0 ? Math.PI / 2 : -Math.PI / 2);
      move(carBodies, index, x, 1.3, z, 7.2, 1.8, 3.2, rotation);
      move(carRoofs, index, x, 2.4, z, 3.8, 1.15, 2.8, rotation);
      for (let side = 0; side < 2; side++) {
        const dx = 3.65, dz = side ? 1.05 : -1.05;
        move(headlights, index * 2 + side, x + Math.cos(rotation) * dx + Math.sin(rotation) * dz, 1.25,
          z - Math.sin(rotation) * dx + Math.cos(rotation) * dz, 0.12, 0.45, 0.65, rotation);
      }
    });
    carBodies.instanceMatrix.needsUpdate = carRoofs.instanceMatrix.needsUpdate = headlights.instanceMatrix.needsUpdate = true;
  };
  animate(0);
  return { group, animate, setNight: night => { nightUniform.value = night ? 1 : 0.07; lightSurface.emissiveIntensity = night ? 1.4 : 0.1; },
    dispose: () => { group.traverse(object => { if (object instanceof THREE.InstancedMesh) object.dispose(); });
      geometries.forEach(geometry => geometry.dispose()); materials.forEach(surface => surface.dispose());
      textures.forEach(texture => texture.dispose()); group.clear(); } };
}
