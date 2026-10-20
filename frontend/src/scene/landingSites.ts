import type { Environment, Waypoint } from '../types/simulation';
export function groundLayout(environment: Environment) {
  return { block_period:200,street_width:40,emergency_site_size:80,emergency_road_setback:12,emergency_pad_radius:18,terminal_buffer:30,...environment.ground_layout };
}
/** Never draw an apparently approved pad over a road or a registered building. */
export function emergencySites(environment: Environment, waypoints: Waypoint[]) {
  const layout=groundLayout(environment),half=layout.emergency_site_size/2,b=environment.bounds;
  const roadDistance=(v:number,origin:number)=>{const offset=((v-origin)%layout.block_period+layout.block_period)%layout.block_period;return Math.min(offset,layout.block_period-offset);};
  const required=layout.street_width/2+half+layout.emergency_road_setback;
  return waypoints.filter(site=>{
    const p=site.position;if(site.type!=='emergency_bay'||Math.abs(p.z)>1e-6)return false;
    if(p.x-half<b.min_x||p.x+half>b.max_x||p.y-half<b.min_y||p.y+half>b.max_y)return false;
    if(roadDistance(p.x,b.min_x)<required-1e-6||roadDistance(p.y,b.min_y)<required-1e-6)return false;
    if(environment.buildings.some(building=>{
      const xs=building.footprint.points.map(q=>q.x),ys=building.footprint.points.map(q=>q.y);
      return Math.max(...xs)>=p.x-half&&Math.min(...xs)<=p.x+half&&Math.max(...ys)>=p.y-half&&Math.min(...ys)<=p.y+half;
    }))return false;
    return !waypoints.some(other=>{
      if(other.id===site.id||other.position.z>1)return false;
      const dx=Math.abs(p.x-other.position.x),dy=Math.abs(p.y-other.position.y);
      if(other.type==='vertiport')return Math.hypot(Math.max(dx-half,0),Math.max(dy-half,0))<layout.terminal_buffer-1e-6;
      return other.type==='emergency_bay'&&dx<layout.emergency_site_size+layout.emergency_road_setback-1e-6&&dy<layout.emergency_site_size+layout.emergency_road_setback-1e-6;
    });
  });
}
