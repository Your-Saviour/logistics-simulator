import {test} from 'node:test';
import assert from 'node:assert/strict';
import catalog from '../../../../contracts/handling/v1/facility.json' with {type: 'json'};
import {endpoint, rackGroups, recordedPlacement, visibleUnits} from '../src/facility.ts';

test('every fixed endpoint retains its exact position and access coordinates', () => {
  assert.equal(catalog.locations.length, 800);
  for (const location of catalog.locations) assert.deepEqual(endpoint(location.id), location);
  assert.equal(endpoint('storage.unknown.slot'), null);
});

test('rack construction retains all four shelf elevations and all 512 slots', () => {
  const racks = rackGroups();
  assert.equal(racks.length, 16);
  assert.equal(racks.reduce((count, rack) => count + rack.slots.length, 0), 512);
  for (const rack of racks) assert.deepEqual(rack.elevations, [.45, 1.95, 3.45, 4.95]);
});

const unit = {id:'unit', barcode:'HU-UNIT', owner:'storage', status:'confirmed', state:'available', position:'storage.raw.r01.b01.l04', connected:true};
test('unit placement uses the recorded shelf elevation without substituting unknown coordinates', () => {
  assert.deepEqual(recordedPlacement(unit), [-28, 4.95, -18]);
  assert.equal(recordedPlacement({...unit, position:'storage.unknown.slot'}), null);
  assert.equal(recordedPlacement({...unit, status:'conflict'}), null);
  assert.equal(recordedPlacement({...unit, status:'unobserved'}), null);
  assert.equal(recordedPlacement({...unit, state:'consumed'}), null);
  assert.equal(recordedPlacement({...unit, state:'dispatched'}), null);
  assert.deepEqual(recordedPlacement({...unit, connected:false}), recordedPlacement(unit));
});

test('all recorded units remain visible without a selected unit or a per-source cap', () => {
  const records = Array.from({length:500}, (_, i) => ({...unit, id:String(i), position:catalog.locations.filter(location => location.kind === 'shelf')[i].id}));
  assert.equal(visibleUnits(records).length, 500);
  assert.equal(visibleUnits([...records, {...unit, status:'conflict'}]).length, 500);
});

test('truck beds group only their own eight slots and never span departments', async () => {
  const {truckGroups} = await import('../src/facility.ts');
  assert.equal(typeof truckGroups, 'function');
  const trucks = truckGroups();
  assert.equal(trucks.length, 8);
  for (const truck of trucks) {
    assert.equal(truck.slots.length, 8);
    assert.equal(new Set(truck.slots.map(slot => slot.position[0])).size, 1);
    const positions=truck.slots.map(slot=>slot.position[2]).sort((a,b)=>a-b);
    assert.ok(Math.abs(positions.at(-1)-positions[0]-7.7)<1e-8);
    for(let index=1;index<positions.length;index++)assert.ok(Math.abs(positions[index]-positions[index-1]-1.1)<1e-8);
  }
});
