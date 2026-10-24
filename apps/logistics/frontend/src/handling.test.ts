import {test} from 'node:test';
import assert from 'node:assert/strict';
import {selectTransportUnits} from './handling.ts';

const units=[
 {id:'a',state:'available',contents:[{sku:'PRODUCT',quantity:4}]},
 {id:'b',state:'available',contents:[{sku:'PRODUCT',quantity:6}]},
 {id:'c',state:'reserved',contents:[{sku:'PRODUCT',quantity:5}]},
 {id:'d',state:'available',contents:[{sku:'PRODUCT',quantity:5}]},
];
const context=[{unit_id:'a',logical_location:'WAREHOUSE'},{unit_id:'b',logical_location:'WAREHOUSE'},{unit_id:'c',logical_location:'WAREHOUSE'},{unit_id:'d',logical_location:'DISPATCH'}];
test('selects an exact whole load at its origin without using reserved or remote units',()=>{
 assert.deepEqual(selectTransportUnits(units,context,'PRODUCT',6,'WAREHOUSE'),['b']);
 assert.deepEqual(selectTransportUnits(units,context,'PRODUCT',10,'WAREHOUSE'),['a','b']);
 assert.throws(()=>selectTransportUnits(units,context,'PRODUCT',5,'WAREHOUSE'),/whole/);
});
test('does not select a mixed unit that would overfulfil another SKU',()=>{
 assert.throws(()=>selectTransportUnits([{id:'a',state:'available',contents:[{sku:'PRODUCT',quantity:4},{sku:'OTHER',quantity:1}]}],context,'PRODUCT',4,'WAREHOUSE'),/whole/);
});
