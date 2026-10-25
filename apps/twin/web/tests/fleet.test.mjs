import test from 'node:test';
import assert from 'node:assert/strict';
import {operationalScopes, replayAllowed, activeLoadKeys} from '../src/fleetState.ts';

const source={name:'storage',status:{run:{id:'source-run',epoch:'source-epoch'}},snapshot:{handling:{fleet:{mode:'coordinated',run_id:'fleet-run',epoch:'fleet-epoch'}}}};
const fleet={configured:true,stale:false,snapshot:{run:{id:'fleet-run',epoch:'fleet-epoch',sources:{storage:{run_id:'source-run',epoch:'source-epoch'}}},robots:[{carried_unit_id:'unit',job_id:'job'}],jobs:[{id:'job',unit_id:'unit',request:{source_run_id:'source-run',source_epoch:'source-epoch'}}]}};

test('coordinated scope cannot fall back to visual replay when fleet goes missing',()=>{
  assert.equal(replayAllowed({source:'storage',run_id:'source-run',epoch:'source-epoch'},operationalScopes([source],null)),false);
  assert.equal(replayAllowed({source:'storage',run_id:'old-run',epoch:'old-epoch'},operationalScopes([source],null)),true);
  assert.equal(replayAllowed({source:'shipping',run_id:'r',epoch:'e'},operationalScopes([source],null)),true);
});

test('reported carried loads suppress static copies even when fleet is stale',()=>{
  assert.deepEqual([...activeLoadKeys({...fleet,stale:true})],['source-run/source-epoch/unit']);
  assert.deepEqual([...activeLoadKeys(null)],[]);
});
