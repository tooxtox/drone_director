import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const code=ts.transpileModule(await readFile(new URL('../src/scene/motionPlayback.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {createMotionClock,createMotionTrack}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const p=(x,y=0,z=150)=>({x,y,z});
const track=createMotionTrack();
track.ingest([{time_s:0,position:p(0),heading:90},{time_s:1,position:p(10),heading:90},{time_s:2,position:p(10,10),heading:0}],2,p(10,10),0);
assert.deepEqual(track.sample(.5).position,p(5));assert.deepEqual(track.sample(1.5).position,p(10,5));
assert.equal(track.sample(1.5).heading,0);assert.deepEqual(track.sample(100).position,p(10,10),'never extrapolate past the latest safe observation');
track.ingest([{time_s:3,position:p(10,10,0),heading:270}],3,p(10,10,0),270);
assert.equal(track.sample(2.5).position.z,75);
track.ingest([],0,p(900),180,true);assert.deepEqual(track.sample(0).position,p(900));
// A same-time external reposition must not replay old samples into the new pose.
track.ingest([{time_s:0,position:p(0),heading:90}],0,p(1000),270);
assert.deepEqual(track.sample(-1).position,p(1000));
const clock=createMotionClock(),moving=createMotionTrack();
clock.ingest(0,5,false,1,0,true);moving.ingest([],0,p(0),90,true);clock.ingest(0,5,true,1,0);
let packetAt=.19,last=-1,prevX=0,velocities=[];
for(let frame=1;frame<=600;frame++){
 const wall=frame/60;
 if(wall>=packetAt){
  const time=Math.floor(wall*5),samples=[];for(let t=Math.max(0,time-5);t<=time;t++)samples.push({time_s:t,position:p(t*15),heading:90});
  clock.ingest(time,5,true,1,wall*1000);moving.ingest(samples,time,p(time*15),90);
  packetAt+= [.17,.23,.19,.21][Math.floor(wall*4)%4];
 }
 const time=clock.sample(wall*1000),pose=moving.sample(time),x=pose.position.x;
 assert(x>=prevX-1e-8,'displayed motion must never move backwards');
 if(wall>3)velocities.push((x-prevX)*60);
 prevX=x;last=time;
}
const mean=velocities.reduce((a,b)=>a+b,0)/velocities.length,cv=Math.sqrt(velocities.reduce((a,b)=>a+(b-mean)**2,0)/velocities.length)/mean;
assert(Math.abs(mean-75)<6);assert(cv<.09,`steady flight has visible speed pulses: CV=${cv}`);
clock.ingest(51,5,false,1,10001);assert.equal(clock.sample(10100),51);
moving.ingest([],51,p(765),90,true);assert.deepEqual(moving.sample(51).position,p(765));
console.log(`Motion playback checks passed: real corner geometry, no extrapolation, reset/pause, jittered packets; steady-flight speed CV=${(cv*100).toFixed(1)}%.`);
