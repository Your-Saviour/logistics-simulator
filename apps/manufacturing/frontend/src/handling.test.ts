import {test} from 'node:test';
import {strict as assert} from 'node:assert';
import {matchingUnits,unitEvidence,type HandlingSnapshot,type HandlingUnit} from './handling.ts';

const raw:HandlingUnit={id:'raw-a',barcode:'HU-RAW-A',owner:'manufacturing',category:'raw',state:'consumed',position:null,origin:'manufacturing.cell01.input01',destination:null,handoff_id:null,version:4,custody_generation:1,last_sequence:3,contents:[{sku:'COMPONENT',quantity:8}]};
const output:HandlingUnit={...raw,id:'output-a',barcode:'HU-OUTPUT-A',category:'finished',state:'available',position:'manufacturing.cell01.output01',origin:null,last_sequence:1,contents:[{sku:'PRODUCT',quantity:4}]};
const snapshot:HandlingSnapshot={version:1,catalog_version:1,units:[raw,output],movements:[{id:'consume-a',unit_id:raw.id,sequence:3,simulation_time:20,action:'consume',origin:raw.origin,destination:raw.origin,correlation_id:'order-a',references:{batch_id:'batch-a'}}],lineage:[{id:'lineage-a',batch_id:'batch-a',input_unit_ids:[raw.id],output_unit_ids:[output.id],batch_quantity:4,output_quantity:4,scrap_quantity:0,recipe:{COMPONENT:2},simulation_time:40}],handoffs:[],legacy_stock:[{sku:'LEGACY',unplaced_quantity:9}],quarantine:[{id:'q-a',event_id:'rejected',endpoint:'storage/events',phase:'apply',reason:'Conflicting receipt proof',simulation_time:50,envelope:{payload:{unit:{barcode:'HU-REJECTED'}}}}]};

test('lookup finds recorded contents or exact endpoints without turning rejected/legacy evidence into units',()=>{
 assert.deepEqual(matchingUnits(snapshot,' hu-output-a '),[output]);
 assert.deepEqual(matchingUnits(snapshot,'COMPONENT'),[raw]);
 assert.deepEqual(matchingUnits(snapshot,'manufacturing.cell01.output01'),[output]);
 assert.deepEqual(matchingUnits(snapshot,'HU-REJECTED'),[]);
 assert.deepEqual(matchingUnits(snapshot,'LEGACY'),[]);
});
test('inspection connects consumed input to its real output lineage without inventing a position',()=>{
 const before=JSON.stringify(snapshot);const detail=unitEvidence(snapshot,raw.id);
 assert.ok(detail);assert.equal(detail.unit.state,'consumed');assert.equal(detail.unit.position,null);
 assert.deepEqual(detail.movements,snapshot.movements);assert.equal(detail.lineage[0].output_unit_ids[0],output.id);
 assert.equal(detail.lineage[0].output_quantity+detail.lineage[0].scrap_quantity,4);
 assert.deepEqual(unitEvidence(snapshot,output.id)?.lineage,detail.lineage);
 assert.equal(unitEvidence(snapshot,'unknown'),null);assert.equal(JSON.stringify(snapshot),before);
});
