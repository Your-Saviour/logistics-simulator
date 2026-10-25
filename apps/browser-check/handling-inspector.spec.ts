import {test,expect,type Page} from '@playwright/test';
const configured=(JSON.parse(process.env.STACK_APPS??'[]') as {name:string;url:string}[]).find(app=>app.name==='twin');
const url=process.env.TWIN_URL??configured?.url??'';test.skip(!url,'No Twin inspector target configured');
function fixture(){
 const run={id:'11111111-1111-4111-8111-111111111111',epoch:'22222222-2222-4222-8222-222222222222',state:'running',granted:100,requested:101,committed:100,speed:1};
 const raw={id:'33333333-3333-4333-8333-333333333333',barcode:'HU-33333333333343338333333333333333',run_id:run.id,epoch:run.epoch,category:'raw',contents:[{sku:'COMPONENT',quantity:4}],owner:'manufacturing',state:'consumed',status:'confirmed',position:null,connected:true,observations:[{source:'manufacturing',unit:{state:'consumed',position:null}}]};
 const output={id:'44444444-4444-4444-8444-444444444444',barcode:'HU-44444444444444448444444444444444',run_id:run.id,epoch:run.epoch,category:'finished',contents:[{sku:'FINISHED',quantity:2}],owner:'storage',state:'reserved',status:'confirmed',position:'storage.dispatch.dock01',connected:true,observations:[{source:'storage',unit:{state:'reserved',position:'storage.dispatch.dock01',destination:'shipping.outbound.dock01',handoff_id:'handoff-fixture'}}]};
 const lineage={id:'lineage-fixture',run_id:run.id,epoch:run.epoch,batch_id:'batch-fixture',batch_quantity:2,recipe:{COMPONENT:2},input_unit_ids:[raw.id],output_unit_ids:[output.id],simulation_time:50};
 const handoff={id:'handoff-fixture',run_id:run.id,epoch:run.epoch,unit:{...output},source:'storage',destination_owner:'shipping',origin:'storage.dispatch.dock01',destination:'shipping.outbound.dock01',state:'accepted',departure_token:null,receipt_id:null};
 const sources=[{name:'manufacturing',connected:true,stale:false,status:{run:{...run}},snapshot:{handling:{units:[],movements:[],handoffs:[],lineage:[lineage]}},cursor:'fixture',error:null},{name:'storage',connected:true,stale:false,status:{run:{...run}},snapshot:{handling:{units:[],movements:[],handoffs:[handoff],lineage:[]}},cursor:'fixture',error:null}];
 const event={id:'storage:unit-movement:fixture',source:'storage',run_id:run.id,epoch:run.epoch,simulation_time:80,payload:{id:'storage:unit-movement:fixture',run_id:run.id,epoch:run.epoch,unit_id:output.id,sequence:5,action:'retrieve',origin:'storage.finished.r01.b01.l01',destination:output.position,simulation_time:80}};
 return {revision:1,mode:'live',sources,events:[event],aligned:null,controls:[],handling:{version:1,units:[raw,output],unsupported_sources:[] as string[]}};
}
async function open(page:Page,value:ReturnType<typeof fixture>){
 await page.route('**/api/status',route=>route.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
 await page.route('**/api/twin',route=>route.fulfill({json:{...value,revision:Date.now()}}));
 await page.goto(url);await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('fixture');await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.locator('.asset-list summary').click();const unit=page.getByRole('button',{name:'handling unit · HU-44444444444444448444444444444444',exact:true});await unit.focus();await page.keyboard.press('Enter');
}
test('keyboard inspection names recorded placement, contents, pending custody, movement and manufacturing lineage',async({page})=>{
 await page.setViewportSize({width:1440,height:900});const value=fixture();await open(page,value);const panel=page.getByRole('region',{name:'Recorded handling unit'});
 await expect(panel.getByText('FINISHED',{exact:true})).toBeVisible();await expect(panel.getByText('storage.dispatch.dock01',{exact:true}).first()).toBeVisible();
 await expect(panel.getByRole('heading',{name:'Pending custody'})).toBeVisible();await expect(panel.getByText('shipping.outbound.dock01',{exact:true})).toBeVisible();
 await expect(panel.getByRole('heading',{name:'Movement history'})).toBeVisible();await expect(panel.getByText(/Sequence 5/)).toBeVisible();
 await panel.getByRole('button',{name:'Inspect input HU-33333333333343338333333333333333',exact:true}).click();
 await expect(page.getByRole('heading',{name:'HU-33333333333343338333333333333333',exact:true})).toBeVisible();await expect(panel.getByText('consumed',{exact:true}).first()).toBeVisible();
 await panel.getByRole('button',{name:'Inspect output HU-44444444444444448444444444444444',exact:true}).click();await expect(page.getByRole('heading',{name:'HU-44444444444444448444444444444444',exact:true})).toBeVisible();
 const bounds=await page.getByRole('region',{name:'Selection details'}).boundingBox();const clear=await page.getByRole('button',{name:'Clear',exact:true}).boundingBox();expect(clear!.x+clear!.width).toBeLessThanOrEqual(bounds!.x+bounds!.width);
 await page.screenshot({path:test.info().outputPath('inspector-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:test.info().outputPath('inspector-mobile.png'),fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});
test('recorded unit inspection remains usable when WebGL is unavailable',async({page})=>{
 await page.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(kind:any,...args:any[]){if(kind==='webgl2'||kind==='webgl'||kind==='experimental-webgl')return null;return (original as any).apply(this,[kind,...args]);} as any;});
 await open(page,fixture());await expect(page.getByText(/3D graphics are unavailable/)).toBeVisible();await expect(page.getByRole('region',{name:'Recorded handling unit'})).toBeVisible();await expect(page.getByText('Loading 3D facility…')).toHaveCount(0);await page.screenshot({path:test.info().outputPath('inspector-webgl-fallback.png'),fullPage:true});
});
test('unknown placements, conflicting custody and an unobserved custodian retain distinct truthful states',async({page})=>{
 const value=fixture();const unit=value.handling.units[1];unit.position='storage.future.slot';await open(page,value);
 const panel=page.getByRole('region',{name:'Recorded handling unit'});await expect(panel.getByText(/Unmapped endpoint/)).toBeVisible();await expect(panel.getByText('storage.future.slot',{exact:true})).toBeVisible();
 unit.status='conflict';unit.position=null;unit.owner=null as any;await expect(panel.getByText('Custody disputed',{exact:true})).toBeVisible();
 unit.status='unobserved';unit.owner='logistics';await expect(panel.getByText('Custodian record unavailable',{exact:true})).toBeVisible();await expect(panel.getByText('logistics',{exact:true}).first()).toBeVisible();
});
test('source hold, disconnection and epoch replacement cannot turn stale inspection into current stock',async({page})=>{
 const value=fixture();value.sources[1].status.run.state='held';await open(page,value);const panel=page.getByRole('region',{name:'Recorded handling unit'});await expect(panel.getByText(/Source held/)).toBeVisible();
 value.sources[1].connected=false;value.sources[1].stale=true;value.handling.units[1].connected=false;await expect(panel.getByText(/Last recorded state/)).toBeVisible();
 value.handling.units=[];value.sources.forEach(source=>source.status.run.epoch='99999999-9999-4999-8999-999999999999');await expect(panel).toHaveCount(0);await expect(page.getByRole('heading',{name:'HU-44444444444444448444444444444444',exact:true})).toHaveCount(0);
});
test('missing handling extensions remain unavailable rather than empty stock',async({page})=>{
 const value=fixture();value.handling.units=[];value.handling.unsupported_sources=['manufacturing','storage'];
 await page.route('**/api/status',route=>route.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));await page.route('**/api/twin',route=>route.fulfill({json:value}));
 await page.goto(url);await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('fixture');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByText(/Handling data unavailable: manufacturing, storage/)).toBeVisible();
});
