import {test} from 'node:test';
import assert from 'node:assert/strict';
import {vehicleState} from '../src/sceneState.ts';
const entity={key:'truck',kind:'vehicle',source:{connected:true,stale:false,status:{run:{id:'run',epoch:'epoch',state:'running',granted:15}}},related:[{id:'transfer',status:'in_transit',departed_at:10,planned_eta:20}]};
test('3D travel freezes on source hold and fences cached positions by epoch',()=>{
 const cache=new Map();
 const running=vehicleState(entity,false,cache);
 assert.equal(running.progress,0.5);
 entity.source.status.run={...entity.source.status.run,state:'held',granted:19};
 assert.equal(vehicleState(entity,false,cache).progress,0.5);
 entity.source.status.run={...entity.source.status.run,epoch:'next'};
 assert.equal(vehicleState(entity,false,cache).progress,0.9);
});
test('overdue travel remains awaiting a source confirmation',()=>{
 const overdue={...entity,source:{...entity.source,status:{run:{...entity.source.status.run,state:'running',granted:25}}}};
 const state=vehicleState(overdue,false,new Map());
 assert.equal(state.progress,1);
 assert.equal(state.awaitingConfirmation,true);
 assert.equal(state.estimated,true);
});
