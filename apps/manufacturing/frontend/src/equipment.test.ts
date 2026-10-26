import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {equipmentState, trendSegments, EquipmentCommand, syntheticReading, completionTimeline} from './equipment.ts';
import {Api} from './api.ts';
const snapshot=(extra:Record<string,unknown>={})=>({mode:'openplc',run_id:'run',epoch:'epoch',stale:false,cell:{initialized:true,observed_at:new Date().toISOString(),error:null,telemetry:{cell:{enabled:false,faults:[],batch:{duration_seconds:20}},actuators:{}}},...extra});
test('stale and uninitialized equipment cannot be operated',()=>{
 assert.equal(equipmentState(snapshot(),false).live,true);
 assert.equal(equipmentState(snapshot({stale:true}),false).live,false);
 assert.equal(equipmentState(snapshot(),true).live,false);
 assert.equal(equipmentState(snapshot({cell:null}),false).live,false);
});
test('trends break at nulls, reversed time, quality failures and missing seconds',()=>{
 const points=[{simulation_time:0,value:10},{simulation_time:1,value:11},{simulation_time:2,value:null},{simulation_time:3,value:12},{simulation_time:9,value:13},{simulation_time:10,value:14}];
 assert.deepEqual(trendSegments(points).map(s=>s.length),[2,1,2]);
});
test('uncertain equipment command preserves exact scope, endpoint and identity',async()=>{
 const seen:{path:unknown;init:RequestInit}[]=[];let fail=true;
 const api=new Api('operator','secret',async(path,init)=>{seen.push({path,init:init!});if(fail)throw new Error('Disconnected');return new Response('{"status":"pending"}');});
 const storage=new Map<string,string>();const persistence={getItem:(key:string)=>storage.get(key)??null,setItem:(key:string,value:string)=>{storage.set(key,value);},removeItem:(key:string)=>{storage.delete(key);}};
 const command=new EquipmentCommand(persistence,'operator');
 await assert.rejects(command.send(api,'/ot/commands',{action:'start',run_id:'old',epoch:'old'}));
 const reloaded=new EquipmentCommand(persistence,'operator');assert.equal(reloaded.body?.['run_id'],'old');
 fail=false;await reloaded.retry(api);assert.deepEqual(seen[0],seen[1]);assert.equal(reloaded.body,null);
 assert.equal(new EquipmentCommand(persistence,'another').body,null);
});

test('fresh gateway responses cannot refresh an old synthetic sample',()=>{
 const at='2026-10-26T08:00:00Z';const reading=syntheticReading([{observed_at:at,signals:{quality:'synthetic',motor_temperature:25}}],Date.parse(at)+60000);
 assert.equal(reading.observedAt,at);assert.equal(reading.quality,'Stale synthetic sample');assert.equal(reading.age,60000);
 assert.equal(syntheticReading([]).quality,'No sample');
});

test('disconnect continuity markers break a trend even at consecutive simulation seconds',()=>{
 assert.equal(trendSegments([{simulation_time:1,value:25,continuity:0},{simulation_time:2,value:26,continuity:1}]).length,2);
});

test('a durable completion carried by later samples appears once with its own order and time',()=>{
 const completion={event_id:'event',order_id:'batch',simulation_time:10};
 const result=completionTimeline([{id:1,order_id:'batch',observed_at:'first',telemetry:{completion}},{id:2,order_id:'batch',observed_at:'later',telemetry:{completion}},{id:3,order_id:null,observed_at:'cleared',telemetry:{completion}}]);
 assert.equal(result.length,1);assert.equal(result[0].at,'first');assert.equal(result[0].detail,'batch · 10 s');
});
