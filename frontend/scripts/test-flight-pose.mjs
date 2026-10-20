import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
const code = ts.transpileModule(await readFile(new URL('../src/scene/flightPose.ts', import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {headingToYaw,turnToward}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
for(const [bearing,x,z] of [[0,0,-1],[90,1,0],[180,0,1],[270,-1,0]]){
 const yaw=headingToYaw(bearing);
 assert(Math.abs(Math.cos(yaw)-x)<1e-9);
 assert(Math.abs(-Math.sin(yaw)-z)<1e-9);
}
const from=headingToYaw(359),to=headingToYaw(1),next=turnToward(from,to,.1);
assert(Math.abs(Math.atan2(Math.sin(next-to),Math.cos(next-to)))<1e-9);
assert.equal(turnToward(0,Math.PI,0),0);
assert(Math.abs(turnToward(0,Math.PI,.1))<=Math.PI*.75*.1+1e-9);
assert.equal(turnToward(0,Math.PI,-1),0);
console.log('Flight pose checks passed: north/east/south/west mapping, heading seam, bounded turn rate, pause.');
