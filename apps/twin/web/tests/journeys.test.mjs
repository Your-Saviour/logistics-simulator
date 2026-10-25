import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JourneyQueue, routeFor, poseAt} from '../src/journeys.ts';
const running = {name:'storage',run_id:'run',epoch:'epoch',running:true,connected:true};
function movement(unit, sequence=1) {
  return {id:`move-${unit}-${sequence}`,source:'storage',run_id:'run',epoch:'epoch',unit_id:unit,sequence,
    origin:'storage.raw.r01.b01.l04',destination:'storage.raw_dispatch.dock01',action:'retrieve'};
}

test('independent units replay concurrently while each unit retains sequence order', () => {
  const queue=new JourneyQueue();
  queue.observe([movement('a',2),movement('b'),movement('a')],[running],0);
  queue.tick(0);
  assert.equal(queue.active.length,2);
  assert.equal(queue.active.find(journey=>journey.move.unit_id==='a').move.sequence,1);
  assert.equal(queue.queued.length,1);
  queue.tick(2001);
  assert.equal(queue.active.find(journey=>journey.move.unit_id==='a').move.sequence,2);
});

test('repeated durable observations cannot create a second robot or replay', () => {
  const queue=new JourneyQueue(); const move=movement('a');
  queue.observe([move],[running],0);queue.tick(0);
  queue.observe([move,move],[running],1000);queue.tick(1000);
  assert.equal(queue.active.length,1);assert.equal(queue.queued.length,0);
  queue.tick(2001);queue.observe([move],[running],3000);queue.tick(3000);
  assert.equal(queue.active.length,0);
});

test('bounded backlog coalesces older movements and converges within 15 seconds', () => {
  const queue=new JourneyQueue();
  queue.observe(Array.from({length:1000},(_,i)=>movement(String(i))),[running],0);queue.tick(0);
  assert.ok(queue.active.length<=64);assert.ok(queue.queued.length<=256);
  assert.ok(queue.skipped>0);
  queue.tick(15001);
  assert.equal(queue.active.length,0);assert.equal(queue.queued.length,0);
});

test('held and disconnected sources freeze poses; epoch changes discard incompatible journeys', () => {
  const queue=new JourneyQueue();const move=movement('a');
  queue.observe([move],[running],0);queue.tick(0);queue.tick(500);
  const progress=queue.active[0].elapsed;
  queue.observe([move],[{...running,running:false}],500);queue.tick(2500);
  assert.equal(queue.active[0].elapsed,progress);
  queue.observe([move],[{...running,connected:false}],2500);queue.tick(5000);
  assert.equal(queue.active[0].elapsed,progress);
  queue.observe([],[{...running,epoch:'new'}],5001);queue.tick(5001);
  assert.equal(queue.active.length,0);assert.equal(queue.queued.length,0);assert.equal(queue.trails.length,0);
});

test('reduced motion retains recorded placement without interpolation or trails', () => {
  const queue=new JourneyQueue();queue.observe([movement('a')],[running],0,true);queue.tick(0);
  assert.equal(queue.active.length,0);assert.equal(queue.queued.length,0);assert.equal(queue.trails.length,0);
});

test('routes use catalog access and vertical shelf/truck poses without guessing unknown endpoints', () => {
  const move=movement('a');const route=routeFor(move);
  assert.ok(route);assert.ok(route.points.some(point=>point[2]===-26||point[2]===26));
  const pickup=poseAt(route,.15), travel=poseAt(route,.5), place=poseAt(route,.9);
  assert.equal(pickup.carrying,true);assert.equal(travel.carrying,true);
  assert.ok(pickup.forkHeight>4);assert.ok(travel.forkHeight<1);
  assert.ok(place.forkHeight<1);
  const truck=routeFor({...move,destination:'logistics.outbound.truck01.slot01'});
  assert.ok(Math.abs(poseAt(truck,.9).forkHeight-.9)<.1);
  assert.equal(routeFor({...move,destination:'unknown.endpoint'}),null);
  assert.equal(routeFor({...move,origin:move.destination}),null);
});

test('completed trails expire after three seconds and never become unit occupancy', () => {
  const queue=new JourneyQueue();queue.observe([movement('a')],[running],0);queue.tick(0);queue.tick(2001);
  assert.equal(queue.trails.length,1);assert.equal(queue.active.length,0);
  assert.equal(queue.trails[0].move.unit_id,'a');
  queue.tick(5002);assert.equal(queue.trails.length,0);
});

test('birth and terminal events are textual history, distinct from unknown endpoint mappings', () => {
  const queue=new JourneyQueue();
  queue.observe([{...movement('birth'),origin:null}, {...movement('unknown'),destination:'unknown.endpoint'}],[running],0);
  assert.equal(queue.unmapped,1);
  assert.equal(queue.queued.length,0);
});

test('a later receiving source cannot overtake a held predecessor for the same unit', () => {
  const queue=new JourneyQueue();
  const next={...running,name:'manufacturing'};
  queue.observe([movement('a'),{...movement('a',2),source:'manufacturing'}],[{...running,running:false},next],0);
  queue.tick(0);assert.equal(queue.active.length,0);assert.equal(queue.queued.length,2);
});

test('late lower sequences coalesce instead of making a unit travel backwards', () => {
  const queue=new JourneyQueue();queue.observe([movement('a',3)],[running],0);queue.tick(0);
  queue.observe([movement('a',1)],[running],100);
  assert.equal(queue.queued.length,0);assert.equal(queue.skipped,1);
});
