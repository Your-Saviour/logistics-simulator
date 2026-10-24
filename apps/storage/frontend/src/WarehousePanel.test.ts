import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,expect,it,vi} from 'vitest'
import WarehousePanel from './WarehousePanel.vue'
afterEach(()=>vi.useRealTimers())
const run={id:'11111111-1111-4111-8111-111111111111',epoch:'22222222-2222-4222-8222-222222222222',granted:2,requested:2,state:'running'}
const snapshot={run_id:run.id,epoch:run.epoch,inventory:[{sku:'PRODUCT',location:'FINISHED-A',on_hand:10,reserved:4,available:6,kind:'finished'}],locations:[{code:'FINISHED-A',capacity:50,used:10},{code:'DISPATCH',capacity:50,used:0}],receipts:[{id:'receipt',sku:'PRODUCT',location:'FINISHED-A',quantity:10,correlation_id:'order',status:'expected'}],reservations:[],transfers:[],movements:[],commands:[]}
it('shows authoritative stock and filters inventory by SKU or location',async()=>{
  const page=mount(WarehousePanel,{props:{api:async()=>snapshot,run,quantum:1,canWrite:true}});await flushPromises()
  expect(page.get('[data-inventory]').text()).toContain('PRODUCT');expect(page.get('[data-inventory]').text()).toContain('6')
  await page.get('input[type=search]').setValue('missing');expect(page.get('[data-inventory]').text()).not.toContain('PRODUCT');page.unmount()
})
it('retains the exact body and key after an uncertain request outcome',async()=>{
  const calls:{body:unknown,key?:string}[]=[]
  const api=async(path:string,body?:unknown,key?:string)=>{if(path==='warehouse')return snapshot;if(path==='status')return {run:{...run,granted:50,requested:50,speed:20,mode:'standalone'}};calls.push({body,key});if(calls.length===1)throw new Error('Connection lost');return {id:'accepted'}}
  const page=mount(WarehousePanel,{props:{api,run,quantum:1,canWrite:true}});await flushPromises()
  await page.get('[data-receive]').trigger('click');await flushPromises();expect(page.text()).toContain('Connection lost')
  await page.get('[data-retry]').trigger('click');await flushPromises();expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0]);expect((calls[0].body as {due_at:number}).due_at).toBe(72);page.unmount()
})
it('shows durable rejection reasons and excludes mutations for observers',async()=>{
  const page=mount(WarehousePanel,{props:{api:async()=>({...snapshot,commands:[{id:'rejected',command:{action:'reserve'},status:'rejected',error:'Insufficient available stock',due_at:3}]}),run,quantum:1,canWrite:false}});await flushPromises()
  expect(page.text()).toContain('Insufficient available stock');expect(page.find('[data-receive]').exists()).toBe(false);page.unmount()
})
it('plans one explicit whole unit and retains its identity on an uncertain retry',async()=>{
  const calls:{body:Record<string,unknown>,key?:string}[]=[]
  const api=async(path:string,body?:unknown,key?:string)=>{if(path==='warehouse')return snapshot;if(path==='status')return {run};calls.push({body:body as Record<string,unknown>,key});if(calls.length===1)throw new Error('Connection lost');return {id:'accepted'}}
  const page=mount(WarehousePanel,{props:{api,run,quantum:1,canWrite:true}});await flushPromises()
  await page.get('.warehouse-form input[type=number]').setValue('7');await page.get('.warehouse-form').trigger('submit');await flushPromises()
  expect(calls[0].body.units).toEqual([{id:expect.stringMatching(/^[0-9a-f-]{36}$/),quantity:7}])
  await page.get('[data-retry]').trigger('click');await flushPromises();expect(calls[1]).toEqual(calls[0]);page.unmount()
})
it('inspects whole-unit contents, unconfirmed custody and recorded history without sending commands',async()=>{
  const unit={id:'unit-a',barcode:'HU-UNIT-A',owner:'storage',category:'finished',state:'in_transit',position:null,origin:'storage.outbound.dock01',destination:'shipping.receiving.dock01',handoff_id:'handoff-a',version:4,custody_generation:1,last_sequence:2,contents:[{sku:'PRODUCT',quantity:7}]}
  const calls:string[]=[]
  const handling={version:1,catalog_version:1,units:[unit],movements:[{id:'move-a',unit_id:'unit-a',sequence:2,simulation_time:12,action:'depart',origin:unit.origin,destination:unit.destination,correlation_id:'order-a',references:{transfer_id:'transfer-a'}}],handoffs:[{id:'handoff-a',unit,state:'departed',source:'storage',destination_owner:'shipping',origin:unit.origin,destination:unit.destination,receipt_id:null}],lineage:[],legacy_stock:[],quarantine:[]}
  const page=mount(WarehousePanel,{props:{api:async path=>{calls.push(path);return {...snapshot,handling}},run,quantum:1,canWrite:false}});await flushPromises()
  expect(page.find('[data-unit-search]').exists()).toBe(true)
  await page.get('[data-unit-search]').setValue('hu-unit-a');expect(page.get('[data-inspect-unit]').attributes('aria-label')).toBe('Inspect HU-UNIT-A');await page.get('[data-inspect-unit]').trigger('click')
  const detail=page.get('[data-unit-detail]');expect(detail.text()).toContain('PRODUCT');expect(detail.text()).toContain('7');expect(detail.text()).toContain('Destination receipt unconfirmed');expect(detail.text()).toContain('No confirmed position');expect(detail.text()).toContain('transfer-a');expect(detail.text()).toContain('12')
  expect(detail.find('button[data-mutate-unit]').exists()).toBe(false);expect(calls.every(path=>path==='warehouse')).toBe(true)
  await page.get('[data-unit-search]').setValue('missing');expect(page.text()).toContain('No handling units match');page.unmount()
})
it('keeps legacy stock and quarantined evidence inspectable without inventing a placed unit',async()=>{
  const handling={version:1,catalog_version:1,units:[],movements:[],handoffs:[],lineage:[],legacy_stock:[{sku:'PRODUCT',location:'FINISHED-A',unplaced_quantity:9}],quarantine:[{id:'case-a',event_id:'bad-event',endpoint:'manufacturing/events',phase:'apply',reason:'Conflicting receipt proof',simulation_time:18,envelope:{payload:{unit:{barcode:'HU-REJECTED'}}}}]}
  const page=mount(WarehousePanel,{props:{api:async()=>({...snapshot,handling}),run,quantum:1,canWrite:false}});await flushPromises()
  expect(page.text()).toContain('Conversion required');expect(page.text()).toContain('9');expect(page.text()).toContain('Conflicting receipt proof');expect(page.text()).toContain('manufacturing/events');expect(page.findAll('[data-inspect-unit]')).toHaveLength(0)
  await page.get('[data-quarantine-evidence] summary').trigger('click');expect(page.get('[data-quarantine-evidence]').text()).toContain('HU-REJECTED');page.unmount()
})
