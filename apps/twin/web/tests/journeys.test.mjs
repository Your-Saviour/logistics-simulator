import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JourneyQueue, routeFor, poseAt} from '../src/journeys.ts';
const running = {name:'storage',run_id:'run',epoch:'epoch',running:true,connected:true};
function movement(unit, sequence=1) {
  return {id:`move-${unit}-${sequence}`,source:'storage',run_id:'run',epoch:'epoch',unit_id:unit,sequence,
    origin:'storage.raw.r01.b01.l04',destination:'storage.raw_dispatch.dock01',action:'retrieve'};
}

function nativeHandoff() {
  const depart={...movement('native-raw',4),source:'logistics',action:'depart',custody_generation:1,
    origin:'logistics.inbound.dock01',destination:'storage.inbound.dock01'};
  return {depart,receive:{...depart,id:'storage-receipt',source:'storage',sequence:5,action:'receive'}};
}

test('native Shipping load and Logistics receipt are one carried trip with recipient takeover',()=>{
  const queue=new JourneyQueue(),sources=[{...running,name:'shipping'},{...running,name:'logistics'}];
  const load={...movement('native-finished',12),source:'shipping',action:'load',custody_generation:4,
    origin:'shipping.outbound.dock01',destination:'logistics.outbound.truck01.slot01'};
  const receive={...load,id:'carrier-receipt',source:'logistics',sequence:13,action:'receive'};
  queue.observe([load],sources,0);queue.tick(0);queue.tick(500);
  queue.observe([load,receive],[{...sources[0],running:false},sources[1]],500);queue.tick(1000);
  assert.equal(queue.active.length,1);assert.equal(queue.active[0].move.source,'logistics');
  assert.equal(queue.active[0].elapsed,1000);assert.equal(queue.queued.length,0);
  queue.tick(2001);assert.equal(queue.active.length,0);assert.equal(queue.trails.length,1);
  const historical=new JourneyQueue();historical.observe([load,receive],sources,0);historical.tick(0);
  assert.equal(historical.active.length,1);assert.equal(historical.queued.length,0);
  const reversed=new JourneyQueue();reversed.observe([receive,load],sources,0);reversed.tick(0);
  assert.equal(reversed.active.length,1);assert.equal(reversed.queued.length,0);
  const completed=new JourneyQueue();completed.observe([load],sources,0);completed.tick(0);completed.tick(2001);
  completed.observe([receive],sources,3000);completed.tick(3000);
  assert.equal(completed.active.length,0);assert.equal(completed.queued.length,0);
});

test('native departure and receipt describe one physical handoff while subsequent putaway remains separate',()=>{
  const queue=new JourneyQueue(),{depart,receive}=nativeHandoff();
  const putaway={...receive,id:'putaway',sequence:6,action:'putaway',origin:receive.destination,destination:'storage.raw.r01.b01.l04'};
  queue.observe([depart,receive,putaway],[{...running,name:'logistics'},running],0);queue.tick(0);
  assert.equal(queue.active.length,1);assert.equal(queue.active[0].move.id,receive.id);
  assert.equal(queue.queued.length,1);assert.equal(queue.queued[0].move.id,putaway.id);
  queue.tick(2001);assert.equal(queue.active[0].move.id,putaway.id);
});

test('a confirmed recipient takes over the same replay without restarting it or replaying it twice',()=>{
  const queue=new JourneyQueue(),{depart,receive}=nativeHandoff();
  queue.observe([depart],[{...running,name:'logistics'},running],0);queue.tick(0);queue.tick(500);
  queue.observe([depart,receive],[{...running,name:'logistics',running:false},running],500);queue.tick(1000);
  assert.equal(queue.active[0].move.source,'storage');assert.equal(queue.active[0].elapsed,1000);assert.equal(queue.queued.length,0);
  queue.tick(2001);assert.equal(queue.active.length,0);assert.equal(queue.trails.length,1);
  queue.observe([depart,receive],[{...running,name:'logistics'},running],3000);queue.tick(3000);
  assert.equal(queue.active.length,0);
});

test('receipt-first delivery coalesces a late departure but retains later custody generations',()=>{
  const queue=new JourneyQueue(),{depart,receive}=nativeHandoff(),sources=[{...running,name:'logistics'},running];
  queue.observe([receive,depart],sources,0);queue.tick(0);queue.tick(2001);
  queue.observe([{...depart,id:'next-custody',sequence:8,custody_generation:3}],sources,3000);queue.tick(3000);
  assert.equal(queue.active.length,1);assert.equal(queue.active[0].move.id,'next-custody');
});

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

test('a shelf pickup clears the rack horizontally before lowering its carried unit',()=>{
  const route=routeFor(movement('shelf-clearance'));
  assert.ok(route);
  for(let progress=.12;progress<.2;progress+=.001){
    const pose=poseAt(route,progress);
    if(pose.forkHeight>=route.origin.position[1]-.001)continue;
    const loadX=pose.position[0]+pose.forkOffset[0];
    assert.ok(Math.abs(loadX-route.origin.position[0])>=1.1,'Lowering before the box clears rack uprights/shelves');
  }
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
