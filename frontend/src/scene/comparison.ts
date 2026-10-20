import * as T from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { line, world } from './traffic';
import type { FlightChange, ComparisonMode } from './demoStory';

/** These are recorded plans at decision time, never fabricated aircraft motion. */
export function buildComparison(changes: FlightChange[]) {
  const group = new T.Group(), before = new T.Group(), after = new T.Group();
  group.add(before, after);
  for (const change of changes) {
    const beforeCount=before.children.length,afterCount=after.children.length;
    if (change.before.path.length > 1) before.add(line(change.before.path, 0xf493be, .85, true));
    if (change.after.path.length < 2) {before.children.slice(beforeCount).forEach(o=>o.userData.aircraftId=change.aircraftId);continue;}
    const parts: T.BufferGeometry[] = [];
    const points = change.after.path.map(world);
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1]!, b = points[i]!, distance = a.distanceTo(b);
      if (distance < .01) continue;
      const direction = b.clone().sub(a).normalize(), rotation = new T.Quaternion().setFromUnitVectors(new T.Vector3(0, 1, 0), direction);
      const segment = new T.CylinderGeometry(.9, .9, distance, 6);
      segment.applyQuaternion(rotation); segment.translate((a.x+b.x)/2, (a.y+b.y)/2, (a.z+b.z)/2); parts.push(segment);
      // A few arrows indicate planned travel direction, not moving vehicles.
      if (distance > 180) {
        const arrow = new T.ConeGeometry(4, 12, 8);
        arrow.applyQuaternion(rotation); const center = a.clone().lerp(b, .58); arrow.translate(center.x, center.y, center.z); parts.push(arrow);
      }
    }
    if (parts.length) {
      after.add(new T.Mesh(mergeGeometries(parts)!, new T.MeshBasicMaterial({ color: 0x72ffda, transparent: true, opacity: .9 })));
      parts.forEach(p => p.dispose());
    }
    const marker = new T.Mesh(new T.RingGeometry(4, 5.5, 32), new T.MeshBasicMaterial({ color: 0xffffff, side:T.DoubleSide, transparent:true, opacity:.7, depthWrite:false }));
    marker.rotation.x=-Math.PI/2;marker.position.copy(points[0]!); after.add(marker);
    [...before.children.slice(beforeCount),...after.children.slice(afterCount)].forEach(o=>o.userData.aircraftId=change.aircraftId);
  }
  return { group, setAircraft(id:string) {
    const hasFocus=changes.some(c=>c.aircraftId===id);
    for(const layer of [before,after])for(const child of layer.children){
      const mesh=child as T.Mesh;const material=mesh.material as T.MeshBasicMaterial;
      if(material){if(child.userData.baseOpacity===undefined)child.userData.baseOpacity=material.opacity;material.opacity=child.userData.baseOpacity*(hasFocus && child.userData.aircraftId!==id ? .18 : 1);}
    }
  }, setMode(mode: ComparisonMode) { before.visible = mode !== 'after'; after.visible = mode !== 'before'; } };
}
