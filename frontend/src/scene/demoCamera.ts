/** Coordinates here are scene coordinates (Y up), independent of simulation time. */
export interface CameraPoint { x: number; y: number; z: number }
export interface CameraPose { position: CameraPoint; target: CameraPoint }
export type DemoCameraPhase = 'establish' | 'wide' | 'approach' | 'follow';
const distance = (a: CameraPoint, b: CameraPoint) => Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
const mix = (a: CameraPoint, b: CameraPoint, t: number): CameraPoint => ({ x:a.x+(b.x-a.x)*t, y:a.y+(b.y-a.y)*t, z:a.z+(b.z-a.z)*t });
const subtract = (a: CameraPoint, b: CameraPoint): CameraPoint => ({ x:a.x-b.x, y:a.y-b.y, z:a.z-b.z });
const add = (a: CameraPoint, b: CameraPoint): CameraPoint => ({ x:a.x+b.x, y:a.y+b.y, z:a.z+b.z });
const length = (p: CameraPoint) => Math.hypot(p.x,p.y,p.z);
const scale = (p: CameraPoint, value: number): CameraPoint => ({ x:p.x*value, y:p.y*value, z:p.z*value });
const smooth = (t: number) => t*t*t*(t*(t*6-15)+10);
const copyPose = (pose: CameraPose): CameraPose => ({ position:{...pose.position}, target:{...pose.target} });
export const DEMO_WIDE_SECONDS = .3;
export const DEMO_APPROACH_SECONDS = 1.7;
export const DEMO_ESTABLISH_SECONDS = .6;
/** Reach the target within eight simulation seconds at normal demo speeds. */
export function demoApproachSeconds(speed: number): number {
  return Math.max(.5,Math.min(DEMO_APPROACH_SECONDS,8/(Number.isFinite(speed) && speed>0 ? speed : 1)));
}
export function demoOpeningTiming(eventAt: number, time: number, speed: number) {
  const until=Math.max(0,eventAt-time)/(Number.isFinite(speed) && speed>0 ? speed : 1);
  return {holdSeconds:Math.min(DEMO_WIDE_SECONDS,until*.12),approachSeconds:Math.max(.35,Math.min(DEMO_APPROACH_SECONDS,until*.7))};
}
export const DEMO_CLOSE_OFFSET: CameraPoint = { x:170, y:130, z:210 };

/** Replay starts wide; automatic events approach immediately from the current pose. */
export function createDemoCameraFlight(start: CameraPose, overview: CameraPose, options: { replayOverview?: boolean; approachSeconds?: number; holdSeconds?: number } = {}) {
  const from=copyPose(start), replay=options.replayOverview!==false, wide=copyPose(replay ? overview : start);
  const establishSeconds = replay && distance(from.position,wide.position)+distance(from.target,wide.target) > 1 ? DEMO_ESTABLISH_SECONDS : 0;
  const requestedHold=options.holdSeconds;
  const holdSeconds=replay ? typeof requestedHold==='number' && Number.isFinite(requestedHold) && requestedHold>=0 ? requestedHold : DEMO_WIDE_SECONDS : 0;
  const requestedSeconds=options.approachSeconds;
  const approachSeconds=typeof requestedSeconds==='number' && Number.isFinite(requestedSeconds) && requestedSeconds>0 ? requestedSeconds : DEMO_APPROACH_SECONDS;
  const wideOffset=subtract(wide.position,wide.target), wideDistance=Math.max(1,length(wideOffset));
  const nearDistance=length(DEMO_CLOSE_OFFSET);
  const wideDirection=scale(wideOffset,1/wideDistance), nearDirection=scale(DEMO_CLOSE_OFFSET,1/nearDistance);
  return {
    duration:establishSeconds+holdSeconds+approachSeconds,
    sample(elapsed: number, aircraftPosition: CameraPoint): CameraPose & { phase:DemoCameraPhase; done:boolean } {
      const time=Math.max(0,elapsed);
      if(time<establishSeconds){
        const t=smooth(time/establishSeconds);
        return { position:mix(from.position,wide.position,t),target:mix(from.target,wide.target,t),phase:'establish',done:false };
      }
      const approach=time-establishSeconds-holdSeconds;
      if(approach<0)return {...copyPose(wide),phase:'wide',done:false};
      const t=smooth(Math.min(1,approach/approachSeconds));
      const target=mix(wide.target,aircraftPosition,t);
      // Logarithmic distance makes the final approach visibly gradual too.
      const radius=wideDistance*Math.pow(nearDistance/wideDistance,t);
      const direction=mix(wideDirection,nearDirection,t);
      const offset=scale(direction,radius/Math.max(.001,length(direction)));
      return {position:add(target,offset),target,phase:t===1?'follow':'approach',done:t===1};
    },
  };
}
