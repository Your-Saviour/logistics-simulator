import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const configured=(JSON.parse(process.env.STACK_APPS??'[]') as {name:string;url:string}[]).find(app=>app.name==='twin');
const url=process.env.TWIN_URL ?? configured?.url ?? '';
test.skip(!url,'No Twin scene target configured');
test.use({video:{mode:'on',size:{width:1440,height:900}}});
const catalog=JSON.parse(readFileSync(new URL('./facility.json',import.meta.url),'utf8'));

test('fixed manufacturing machines retain their parent cell transforms in the GPU batch',async({page})=>{
  await page.addInitScript(()=>{
    (window as any).__staticMatrices=[];
    const original=WebGL2RenderingContext.prototype.bufferData;
    WebGL2RenderingContext.prototype.bufferData=function(target:any,data:any,...rest:any[]){
      if(target===this.ARRAY_BUFFER&&data instanceof Float32Array&&data.length===1024*16)(window as any).__staticMatrices.push(Array.from(data));
      return (original as any).call(this,target,data,...rest);
    } as any;
  });
  const run={id:'geometry-fixture',epoch:'geometry-epoch',state:'held',granted:0,requested:0,committed:0};
  await page.route('**/api/status',route=>route.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
  await page.route('**/api/twin',route=>route.fulfill({json:{revision:1,mode:'live',sources:[{name:'storage',connected:true,stale:false,status:{run},snapshot:{config:{locations:[]}},cursor:'1',error:null}],events:[],aligned:null,controls:[],handling:{version:1,units:[],unsupported_sources:[]}}}));
  await page.goto(url);await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('geometry');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  const expected=catalog.locations.filter((p:any)=>p.kind==='cell_input'&&p.id.endsWith('input01')).map((p:any)=>[p.position[0]+.6,.15,p.position[2]+1.6]);
  await expect.poll(()=>page.evaluate(expected=>{
    const matrices=(window as any).__staticMatrices.flatMap((buffer:number[])=>Array.from({length:1024},(_,i)=>buffer.slice(i*16,i*16+16)));
    return expected.filter((position:number[])=>matrices.some((m:number[])=>Math.abs(m[0]-2.2)<.0001&&Math.abs(m[5]-.3)<.0001&&Math.abs(m[10]-1.7)<.0001&&position.every((value,index)=>Math.abs(m[12+index]-value)<.0001))).length;
  },expected)).toBe(expected.length);
});

test('500 recorded units replay on at most 64 robots without duplicate placements', async ({page}) => {
  const run={id:'11111111-1111-4111-8111-111111111111',epoch:'22222222-2222-4222-8222-222222222222',state:'running',granted:100,requested:101,committed:100,speed:1};
  const locations=catalog.locations.filter((row:any)=>row.kind==='shelf').slice(0,500);
  const units=locations.map((location:any,index:number)=>({id:`fixture-${index}`,barcode:`HU-FIXTURE-${index}`,run_id:run.id,epoch:run.epoch,category:location.compatible[0],contents:[{sku:'BROWSER-FIXTURE',quantity:1}],owner:'storage',state:'available',status:'confirmed',position:location.id,connected:true,observations:[]}));
  const events=units.map((unit:any,index:number)=>{
    const compatible=locations.filter((location:any)=>location.compatible[0]===unit.category);
    const origin=compatible[(compatible.findIndex((location:any)=>location.id===unit.position)+4)%compatible.length].id;
    return {id:`storage:unit-movement:fixture-${index}`,source:'storage',run_id:run.id,epoch:run.epoch,payload:{id:`storage:unit-movement:fixture-${index}`,unit_id:unit.id,run_id:run.id,epoch:run.epoch,sequence:1,action:'putaway',origin,destination:unit.position}};
  });
  const source={name:'storage',connected:true,stale:false,status:{run},snapshot:{config:{locations:[]}},cursor:'fixture',error:null};
  const errors:string[]=[];page.on('console',message=>{if(message.type()==='error') errors.push(message.text());});page.on('pageerror',error=>errors.push(String(error)));
  const writes:string[]=[];page.on('request',request=>{if(!['GET','HEAD','OPTIONS'].includes(request.method())) writes.push(request.url());});
  await page.route('**/api/status',route=>route.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
  await page.route('**/api/twin',route=>route.fulfill({json:{revision:Date.now(),mode:'live',sources:[source],events,aligned:null,controls:[],handling:{version:1,units,unsupported_sources:[]}}}));
  await page.setViewportSize({width:1440,height:900});await page.goto(url);
  await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('fixture');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  const stage=page.getByRole('group',{name:'Selectable 3D facility'});
  await expect(stage).toHaveAttribute('data-active-journeys','64');
  const counts=await stage.evaluate(element=>({active:Number(element.getAttribute('data-active-journeys')),queued:Number(element.getAttribute('data-queued-journeys')),static:Number(element.getAttribute('data-static-units')),replay:Number(element.getAttribute('data-replay-units'))}));
  expect(counts.queued).toBeLessThanOrEqual(256);expect(counts.static+counts.replay).toBe(500);
  await page.locator('.asset-list summary').click();
  const firstUnit=page.getByRole('button',{name:'handling unit · '+units[0].barcode,exact:true});await firstUnit.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('heading',{name:units[0].barcode,exact:true})).toBeVisible();await expect(stage).toHaveAttribute('data-active-journeys','64');
  await page.getByRole('button',{name:'Clear',exact:true}).click();await page.locator('.asset-list summary').click();
  await expect(stage).toHaveAttribute('data-recorded-units','500');
  await expect(page.getByLabel('Visual replay')).toContainText('Visual estimate');
  await page.screenshot({path:test.info().outputPath('concurrent-desktop.png'),fullPage:true});
  const replayNote=page.getByLabel('Visual replay').locator('span'),before=await replayNote.innerText();
  events.push(...events.slice(0,500).map(event=>({...event,id:event.id+'-hold-check',payload:{...event.payload,id:event.payload.id+'-hold-check',sequence:2}})));
  await expect(replayNote).not.toHaveText(before);await expect(stage).toHaveAttribute('data-active-journeys','64');
  source.status.run.state='held';
  await expect(stage).toHaveAttribute('data-replay-frozen','true');
  const first=await stage.locator('canvas').screenshot();await page.waitForTimeout(300);
  expect(await stage.locator('canvas').screenshot()).toEqual(first);
  await page.emulateMedia({reducedMotion:'reduce'});
  await expect(stage).toHaveAttribute('data-active-journeys','0');await expect(stage).toHaveAttribute('data-static-units','500');
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:test.info().outputPath('reduced-motion-mobile.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
  await page.setViewportSize({width:1440,height:900});
  await page.emulateMedia({reducedMotion:'no-preference'});source.status.run.state='running';
  events.push(...events.slice(0,64).map(event=>({...event,id:event.id+'-next',payload:{...event.payload,id:event.payload.id+'-next',sequence:3}})));
  await expect(stage).toHaveAttribute('data-active-journeys','64');
  await expect(stage).toHaveAttribute('data-active-journeys','0',{timeout:15000});
  await expect(stage).toHaveAttribute('data-static-units','500');
  await expect(stage).toHaveAttribute('data-replay-trails','64');
  await page.screenshot({path:test.info().outputPath('completed-trails-desktop.png'),fullPage:true});
  await expect(stage).toHaveAttribute('data-replay-trails','0',{timeout:5000});
  expect(writes).toEqual([]);expect(errors).toEqual([]);
});
