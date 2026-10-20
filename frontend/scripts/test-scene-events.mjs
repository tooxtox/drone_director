import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

// Exercise the production TypeScript adapter without introducing a test framework.
// `npm run build` supplies strict type checking; this runner checks its behavior.
const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(join(tmpdir(), 'tianshu-scene-events-'));
let passed = 0;
function check(name, test) {
  test(); passed++;
  console.log(`✓ ${name}`);
}
const clone = value => structuredClone(value);

try {
  await writeFile(join(temporary, 'package.json'), '{"type":"commonjs"}');
  for (const relative of ['types/simulation', 'scene/eventFocus']) {
    const source = await readFile(join(frontend, 'src', `${relative}.ts`), 'utf8');
    const output = ts.transpileModule(source, { reportDiagnostics: true,
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } });
    assert.equal(output.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error).length, 0);
    const destination = join(temporary, `${relative}.js`);
    await mkdir(dirname(destination), { recursive: true });
    await writeFile(destination, output.outputText);
  }
  const require = createRequire(import.meta.url);
  const { deriveSceneEvents, createEventFocusTracker } = require(join(temporary, 'scene/eventFocus.js'));
  const { states } = JSON.parse(await readFile(join(frontend, 'scripts/fixtures/scene-events.json'), 'utf8'));
  const visualFor = (state, kind) => {
    const visual = deriveSceneEvents(state).findLast(event => event.kind === kind);
    assert.ok(visual, `Expected a ${kind} visual`);
    return visual;
  };
  const sourceFor = (state, visual) => state.events.find(event => event.id === visual.id);

  check('weather uses actual polygon, affected aircraft and evacuation result', () => {
    const state = states.weather, visual = visualFor(state, 'weather'), source = sourceFor(state, visual);
    assert.deepEqual(visual.area.polygon, state.weather[0].affected_area);
    assert.equal(visual.focus.kind, 'area');
    assert.deepEqual(visual.affectedAircraftIds.sort(), [...source.result.affected_aircraft].sort());
    assert.ok(source.result.evacuating_aircraft.includes(visual.primaryAircraftId));
    assert.match(visual.summary, /受影响 8 架.*改航 8 架.*撤离 2 架/);
    assert.equal(visual.phase, 'active');
  });
  check('closure respects the backend restriction altitude interval', () => {
    const visual = visualFor(states.closure, 'closure');
    assert.deepEqual(visual.area.polygon, states.closure.restrictions[0].polygon);
    assert.equal(visual.area.minAltitude, 120); assert.equal(visual.area.maxAltitude, 230);
    assert.equal(visual.focus.kind, 'area'); assert.equal(visual.label, '空域管制');
  });
  check('congestion focuses the real route and reports capacity reduction', () => {
    const state = states.congestion, visual = visualFor(state, 'congestion'), source = sourceFor(state, visual);
    const route = state.routes.find(route => route.id === source.result.route_id);
    assert.equal(visual.focus.kind, 'route'); assert.equal(visual.focus.routeId, route.id);
    assert.deepEqual(visual.paths[0].points, route.waypoint_ids.map(id => state.waypoints.find(point => point.id === id).position));
    assert.ok(visual.affectedRouteIds.includes(route.id)); assert.match(visual.summary, /容量 8 → 1/);
  });
  check('route endpoints provide geometry when waypoint_ids is empty', () => {
    const state = clone(states.congestion); state.routes[0].waypoint_ids = [];
    assert.equal(visualFor(state, 'congestion').paths[0].points.length, 2);
  });
  check('failure displays backend diversion path without claiming landing', () => {
    const state = states.failure, visual = visualFor(state, 'failure'), source = sourceFor(state, visual);
    assert.deepEqual(visual.paths[0].points, source.result.path);
    assert.equal(visual.paths[0].kind, 'diversion'); assert.equal(visual.focus.kind, 'aircraft');
    assert.equal(visual.primaryAircraftId, source.result.aircraft_id);
    assert.match(visual.summary, /飞往备降点 EB-0/); assert.doesNotMatch(visual.summary, /已抵达|已降落/);
  });
  check('landing is confirmed by an actual backend landing event', () => {
    const visual = visualFor(states.landing, 'landing'), source = sourceFor(states.landing, visual);
    assert.equal(source.result.landed, true); assert.equal(visual.phase, 'resolved');
    assert.match(visual.summary, /已抵达备降点 EB-0/);
  });
  check('conflict focuses the predicted encounter and explains actual resolution', () => {
    const state = states.conflict, visual = visualFor(state, 'conflict'), source = sourceFor(state, visual);
    assert.deepEqual(visual.focus.position, source.result.predicted_conflict.conflict_position);
    assert.ok(visual.affectedAircraftIds.includes(source.result.predicted_conflict.aircraft_a));
    assert.ok(visual.affectedAircraftIds.includes(source.result.predicted_conflict.aircraft_b));
    assert.equal(visual.phase, 'resolved'); assert.match(visual.summary, /延时让行.*预测冲突已解脱/);
  });
  check('a recorded conflict alone never implies successful conflict resolution', () => {
    const state = clone(states.conflict), visual = visualFor(state, 'conflict'), source = sourceFor(state, visual);
    source.result = { success: true, recorded: true };
    const result = visualFor(state, 'conflict');
    assert.doesNotMatch(result.summary, /已解脱/); assert.equal(result.phase, 'attention');
  });
  check('an unhandled weather event never implies a resolved hazard', () => {
    const state = clone(states.weather), source = sourceFor(state, visualFor(state, 'weather'));
    state.weather = []; source.handled = false; source.result = {};
    const visual = visualFor(state, 'weather');
    assert.equal(visual.phase, 'attention'); assert.equal(visual.summary, '等待事件处理');
    assert.equal(visual.success, null);
  });
  check('failed diversion stays explicit and does not fabricate a flight path', () => {
    const state = clone(states.failure), source = sourceFor(state, visualFor(state, 'failure'));
    source.result = { success: false, aircraft_id: source.related_id, reason: 'no_reachable_available_emergency_bay' };
    const visual = visualFor(state, 'failure');
    assert.equal(visual.phase, 'attention'); assert.equal(visual.paths.length, 0);
    assert.match(visual.summary, /无可用备降点.*人工处置/);
  });
  check('partial and nonfinite polygons never create a misleading hazard volume', () => {
    const state = clone(states.weather), source = sourceFor(state, visualFor(state, 'weather'));
    const bad = { points: [{ x: 10, y: 20 }, { x: 20, y: 20 }, { x: Infinity, y: 30 }] };
    state.weather[0].affected_area = bad; source.payload.affected_area = bad;
    assert.equal(visualFor(state, 'weather').area, undefined);
  });
  check('a disappeared weather entity becomes historical and retains recorded geometry', () => {
    const state = clone(states.weather); state.weather = [];
    const visual = visualFor(state, 'weather');
    assert.equal(visual.phase, 'resolved');
    assert.deepEqual(visual.area.polygon, sourceFor(state, visual).payload.affected_area);
  });
  check('safety pauses remain visible instead of reporting an all-clear outcome', () => {
    const state = clone(states.weather), source = sourceFor(state, visualFor(state, 'weather'));
    source.result.paused_for_safety = true; source.result.residual_conflicts = 2;
    const visual = visualFor(state, 'weather');
    assert.equal(visual.phase, 'attention'); assert.match(visual.summary, /剩余冲突 2.*已暂停确保安全/);
  });
  check('future records and nonincident info records cannot trigger a focus', () => {
    const state = clone(states.weather); state.simulation.time_s = 0;
    assert.deepEqual(deriveSceneEvents(state), []);
    assert.deepEqual(deriveSceneEvents(null), []);
  });
  check('derivation never mutates snapshot entities or recorded results', () => {
    const original = clone(states);
    Object.values(states).forEach(state => deriveSceneEvents(state));
    assert.deepEqual(states, original);
  });
  check('repeated snapshots focus each new event exactly once', () => {
    const tracker = createEventFocusTracker();
    assert.ok(tracker.update(states.weather).newlyFocused);
    assert.equal(tracker.update(clone(states.weather)).newlyFocused, null);
    const newState = clone(states.weather), event = clone(newState.events.at(-1));
    event.id += '-new'; newState.events.push(event);
    assert.equal(tracker.update(newState).newlyFocused.id, event.id);
    assert.equal(tracker.update(newState).newlyFocused, null);
  });
  check('route/hazard environment_version changes preserve current scene focus', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); state.environment_version++; state.version++;
    const update = tracker.update(state);
    assert.equal(update.reset, false); assert.equal(update.newlyFocused, null); assert.ok(update.latest);
  });
  check('city geometry changes exclude retained event IDs from the previous city', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); state.environment.buildings[1].height++;
    const update = tracker.update(state);
    assert.equal(update.reset, true); assert.equal(update.latest, null); assert.deepEqual(update.events, []);
  });
  check('a new run marker resets same-scenario focus without suppressing new IDs', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); state.events.forEach(event => { event.id += '-new-run'; });
    const update = tracker.update(state);
    assert.equal(update.reset, true); assert.ok(update.newlyFocused); assert.ok(update.latest.id.endsWith('-new-run'));
  });
  check('time rollback excludes stale events even after simulation time catches up', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); state.simulation.time_s = 0; state.version = 0;
    assert.equal(tracker.update(state).reset, true);
    state.simulation.time_s = states.weather.simulation.time_s;
    assert.equal(tracker.update(state).latest, null);
  });
  check('scenario switches cannot reuse events from an old scenario marker', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); state.simulation.demo_scenario = 'closure';
    assert.deepEqual(deriveSceneEvents(state), []);
    const update = tracker.update(state); assert.equal(update.reset, true); assert.equal(update.latest, null);
  });
  check('stream omissions and rolling event history do not falsely reset a run', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const state = clone(states.weather); delete state.environment;
    state.events = state.events.filter(event => event.type !== 'event_info');
    const update = tracker.update(state); assert.equal(update.reset, false); assert.equal(update.newlyFocused, null);
  });
  check('null state and manual clear remove retained focus lifecycle', () => {
    const tracker = createEventFocusTracker(); tracker.update(states.weather);
    const update = tracker.update(null);
    assert.equal(update.reset, true); assert.equal(update.latest, null); assert.deepEqual(update.events, []);
    assert.ok(tracker.update(states.weather).newlyFocused);
    tracker.clear(); assert.ok(tracker.update(states.weather).newlyFocused);
  });
  console.log(`\n${passed} scene event checks passed.`);
} finally {
  await rm(temporary, { recursive: true, force: true });
}
