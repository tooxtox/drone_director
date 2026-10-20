import type { Position } from '../types/simulation';
export interface MotionSample { time_s:number;position:Position;heading:number }
const distance=(a:Position,b:Position)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
const clamp=(v:number,min:number,max:number)=>Math.max(min,Math.min(max,v));

/** A shared buffered clock avoids easing to a stop at every network snapshot. */
export function createMotionClock(){
  let latest=0,render=0,speed=1,tick=1,running=false,received=0,frame=0,rate=1,initialized=false,primed=false;
  return {
    ingest(time:number,nextSpeed:number,nextRunning:boolean,tickSeconds:number,now:number,reset=false){
      const changed=time!==latest||nextRunning!==running||nextSpeed!==speed;
      if(!initialized||reset||time<latest){render=time;frame=now;initialized=true;primed=false;}
      if(changed||reset){latest=time;received=now;}
      speed=nextSpeed;tick=tickSeconds;running=nextRunning;
      if(!running){render=latest;frame=now;primed=false;rate=speed;}
    },
    sample(now:number){
      const elapsed=Math.max(0,(now-frame)/1000);frame=now;
      if(!running)return latest;
      const delay=Math.max(.35,tick/Math.max(speed,.01)+.06);
      if(elapsed>1){render=Math.max(render,latest-delay*speed);primed=false;}
      if(!primed){if(latest-render<Math.min(delay*speed,Math.max(tick,speed*.35))-1e-6)return render;primed=true;rate=speed;}
      const ideal=Math.min(latest,Math.max(0,latest+(now-received)/1000*speed-delay*speed));
      const error=(ideal-render)/Math.max(speed,.01);
      const correction=Math.sign(error)*Math.max(0,Math.abs(error)-.12);
      const wanted=speed*clamp(1+correction*.8,.92,1.08);
      rate+=(wanted-rate)*(1-Math.exp(-elapsed*5));
      render=Math.min(latest,render+elapsed*rate);
      return render;
    },
  };
}

/** Interpolate only along observed segments, retaining real corner/landing points. */
export function createMotionTrack(){
  let points:MotionSample[]=[];
  const add=(sample:MotionSample)=>{
    if(!sample?.position || !Number.isFinite(sample.time_s)||![sample.position.x,sample.position.y,sample.position.z,sample.heading].every(Number.isFinite))return;
    const item={...sample,position:{...sample.position}},last=points.at(-1);
    if(last && item.time_s<last.time_s-1e-8)return;
    if(last && Math.abs(item.time_s-last.time_s)<1e-8)points[points.length-1]=item;else points.push(item);
  };
  return {
    ingest(samples:MotionSample[]|undefined,time:number,position:Position,heading:number,reset=false){
      const last=points.at(-1);
      const discontinuity=!!last && (time<last.time_s || Math.abs(time-last.time_s)<1e-8&&distance(position,last.position)>1e-6);
      if(reset||discontinuity)points=[];
      if(!discontinuity)for(const sample of samples??[])add(sample);
      add({time_s:time,position,heading});points=points.slice(-64);
    },
    sample(time:number):MotionSample|undefined{
      if(!points.length)return;
      if(time<=points[0]!.time_s)return points[0];
      for(let i=1;i<points.length;i++){
        const a=points[i-1]!,b=points[i]!;if(time>b.time_s)continue;
        const t=clamp((time-a.time_s)/Math.max(1e-9,b.time_s-a.time_s),0,1);
        const dx=b.position.x-a.position.x,dy=b.position.y-a.position.y;
        return {time_s:time,position:{x:a.position.x+dx*t,y:a.position.y+dy*t,z:a.position.z+(b.position.z-a.position.z)*t},
          heading:Math.hypot(dx,dy)>1e-7 ? (Math.atan2(dx,dy)*180/Math.PI+360)%360 : a.heading};
      }
      return points.at(-1);
    },
  };
}
