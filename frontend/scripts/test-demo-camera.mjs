import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/scene/demoCamera.ts',import.meta.url),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {createDemoCameraFlight,demoApproachSeconds,demoOpeningTiming,DEMO_CLOSE_OFFSET,DEMO_WIDE_SECONDS,DEMO_ESTABLISH_SECONDS}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const overview={position:{x:3600,y:2800,z:1200},target:{x:1600,y:35,z:-1600}};
const target={x:2700,y:150,z:-1200};
const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
const flight=createDemoCameraFlight(overview,overview);
for(const t of [0,DEMO_WIDE_SECONDS/2]){
 const pose=flight.sample(t,target);assert.equal(pose.phase,'wide');assert.deepEqual(pose.position,overview.position);assert.deepEqual(pose.target,overview.target);
}
let previous=Infinity;
for(let time=DEMO_WIDE_SECONDS;time<=flight.duration;time+=.025){
 const pose=flight.sample(time,target),radius=distance(pose.position,pose.target);
 assert(radius<=previous+1e-6,'camera must progressively close in');previous=radius;
 assert(Object.values(pose.position).every(Number.isFinite));
}
const end=flight.sample(flight.duration,target);assert.equal(end.phase,'follow');assert.equal(end.done,true);assert.deepEqual(end.target,target);
assert(distance(end.position,{x:target.x+DEMO_CLOSE_OFFSET.x,y:target.y+DEMO_CLOSE_OFFSET.y,z:target.z+DEMO_CLOSE_OFFSET.z})<1e-6);
const moved={x:target.x+450,y:target.y+70,z:target.z-300};assert.deepEqual(flight.sample(flight.duration,moved).target,moved);
const near={position:end.position,target:end.target},replay=createDemoCameraFlight(near,overview);
assert.equal(replay.sample(0,target).phase,'establish');assert.deepEqual(replay.sample(0,target).position,near.position);
assert.equal(replay.sample(DEMO_ESTABLISH_SECONDS,target).phase,'wide');
for(const boundary of [DEMO_ESTABLISH_SECONDS,DEMO_ESTABLISH_SECONDS+DEMO_WIDE_SECONDS,replay.duration]){
 assert(distance(replay.sample(boundary-1e-4,target).position,replay.sample(boundary+1e-4,target).position)<.01,'no jump between phases');
}
for(const [speed,seconds] of [[1,1.7],[5,1.6],[10,.8],[20,.5],[50,.5],[0,1.7],[NaN,1.7]])assert.equal(demoApproachSeconds(speed),seconds);
const automatic=createDemoCameraFlight(overview,overview,{replayOverview:false,approachSeconds:demoApproachSeconds(10)});
assert.equal(automatic.sample(0,target).phase,'approach','automatic events must start without another overview hold');
assert.equal(automatic.sample(.8,target).done,true,'a 10x demo must reach its target within 0.8 seconds');
assert(automatic.sample(.4,target).target.x>overview.target.x);
// A new event retargets immediately from the exact in-progress pose, never back to the overview.
const interrupted=automatic.sample(.4,target),retarget=createDemoCameraFlight(interrupted,overview,{replayOverview:false,approachSeconds:.8});
assert.equal(retarget.sample(0,moved).phase,'approach');assert(distance(retarget.sample(0,moved).position,interrupted.position)<1e-6);
assert.deepEqual(retarget.sample(.8,moved).target,moved);
// Sparse frames still sample elapsed wall time instead of extending the flight.
assert.equal(automatic.sample(1.1,target).phase,'follow');
assert.deepEqual(overview,{position:{x:3600,y:2800,z:1200},target:{x:1600,y:35,z:-1600}});
console.log('Demo camera checks passed: immediate event approach, 5x/10x/50x timing, continuous retargeting, replay, moving subject and sparse frames.');

const opening=demoOpeningTiming(10,0,10);
const openingFlight=createDemoCameraFlight(overview,overview,{replayOverview:true,...opening});
assert(openingFlight.duration<1,'the first congestion shot must reach its aircraft before a 10x event at 10 simulation seconds');
assert.equal(openingFlight.sample(0,target).phase,'wide');
assert.equal(openingFlight.sample(openingFlight.duration,target).phase,'follow');
console.log('Opening timing check passed: camera starts at selection and finishes before the first normal-speed event.');
