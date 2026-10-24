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
