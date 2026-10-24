import {test} from 'node:test';
import assert from 'node:assert/strict';
import {findTransportUnits,transportEvidence,type TransportHandling,type RecordedUnit} from './inspection.ts';

const unit:RecordedUnit={id:'unit-a',barcode:'HU-UNIT-A',state:'in_transit',owner:'logistics',category:'finished',contents:[{sku:'PRODUCT',quantity:8}],position:null,origin:'logistics.outbound.truck01.slot01',destination:'logistics.dispatch.dock01',handoff_id:'handoff-a',version:5,custody_generation:2,last_sequence:4};
const handling:TransportHandling={version:1,catalog_version:1,units:[unit],unit_context:[{unit_id:unit.id,logical_location:'WAREHOUSE',transfer_id:'transfer-a'}],movements:[{id:'departure-a',unit_id:unit.id,sequence:4,action:'depart',origin:unit.origin,destination:unit.destination,simulation_time:25,correlation_id:'order-a',references:{transfer_id:'transfer-a',shipment_id:'shipment-a',batch_id:null}}],handoffs:[],quarantine:[{id:'q-a',event_id:'rejected',endpoint:'shipping/events',phase:'apply',reason:'Conflicting receipt proof',simulation_time:26,envelope:{payload:{unit:{barcode:'HU-REJECTED'}}}}]};
test('transport lookup uses recorded barcode, contents and grouping without inventing rejected units',()=>{
 assert.deepEqual(findTransportUnits(handling,' hu-unit-a '),[unit]);
 assert.deepEqual(findTransportUnits(handling,'PRODUCT'),[unit]);
 assert.deepEqual(findTransportUnits(handling,'WAREHOUSE'),[unit]);
 assert.deepEqual(findTransportUnits(handling,'HU-REJECTED'),[]);
});
test('transport inspection preserves unconfirmed placement and durable transfer/shipment references',()=>{
 const before=JSON.stringify(handling);const detail=transportEvidence(handling,unit.id);
 assert.ok(detail);assert.equal(detail.unit.position,null);assert.equal(detail.unit.destination,'logistics.dispatch.dock01');assert.equal(detail.context?.transfer_id,'transfer-a');
 assert.equal(detail.movements[0].references.shipment_id,'shipment-a');assert.equal(detail.movements[0].simulation_time,25);assert.equal(transportEvidence(handling,'missing'),null);assert.equal(JSON.stringify(handling),before);
});
