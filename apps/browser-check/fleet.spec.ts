import {test,expect,type Page} from '@playwright/test';
import {readFileSync,mkdirSync} from 'node:fs';
const url=process.env.TWIN_URL??'';
test.skip(!url,'No fleet Twin target configured');
const catalog=JSON.parse(readFileSync(new URL('./facility.json',import.meta.url),'utf8'));

function fixture(){
  const run={id:'source-run',epoch:'source-epoch',state:'running',granted:100,requested:101,committed:100};
  const units=catalog.locations.filter((e:any)=>e.kind==='shelf').slice(0,500).map((e:any,i:number)=>({id:`unit-${i}`,barcode:`HU-UNIT-${i}`,run_id:run.id,epoch:run.epoch,category:e.compatible[0],contents:[{sku:'GRID-FIXTURE',quantity:1}],owner:'storage',state:'available',status:'confirmed',position:e.id,connected:true,observations:[]}));
  const robots=Array.from({length:16},(_,i)=>({id:`robot-${i+1}`,pose:[-32+i*3,23,1],parking:[-32+i*3,30.5,0],job_id:`job-${i}`,carried_unit_id:`unit-${i}`,fork_height:.55,fork_offset:[0,0],load_position:[-32+i*3,.91,23]}));
  const jobs=robots.map((r,i)=>({id:r.job_id,unit_id:r.carried_unit_id,robot_id:r.id,state:'carrying',progress:.5,waiting_reason:i===0?'intersection':null,blockers:i===0?['job-1']:[],request:{producer:'storage',source_run_id:run.id,source_epoch:run.epoch,origin:units[i].position,destination:units[i+32].position}}));
  return {revision:1,mode:'live',sources:[{name:'storage',connected:true,stale:false,status:{run},snapshot:{config:{locations:[]},handling:{fleet:{mode:'coordinated',run_id:'fleet-run',epoch:'fleet-epoch'}}},cursor:'1',error:null}],
    events:[{id:'storage:unit-movement:fake-replay',source:'storage',run_id:run.id,epoch:run.epoch,payload:{id:'fake-replay',unit_id:units[0].id,run_id:run.id,epoch:run.epoch,sequence:1,action:'putaway',origin:units[20].position,destination:units[0].position}}],
    aligned:null,controls:[],handling:{version:1,units,unsupported_sources:[]},
    fleet:{configured:true,stale:false,snapshot:{run:{id:'fleet-run',epoch:'fleet-epoch',revision:1,committed:100,state:'running',reason:null,fresh:true,sources:{storage:{run_id:run.id,epoch:run.epoch,offset:0}}},robots,jobs,reservations:Array.from({length:1000},(_,i)=>({resource:`cell:${-130+i%200}:${90+Math.floor(i/200)}`,job_id:'job-1'}))}}};
}

async function open(page:Page,value:ReturnType<typeof fixture>){
  await page.route('**/api/status',r=>r.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
  await page.route('**/api/twin',r=>r.fulfill({json:{...value,revision:Date.now()}}));
  await page.goto(url);
  await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('grid');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('[data-models-ready=true]')).toBeVisible();
}

test('reported fleet shows identity, grid, waiting reason and stays frozen without replay fallback',async({page})=>{
  const value=fixture(),errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setViewportSize({width:1440,height:1000});await open(page,value);
  const stage=page.getByRole('group',{name:'Selectable 3D facility'});
  await expect(stage).toHaveAttribute('data-fleet-robots','16');
  await expect(stage).toHaveAttribute('data-active-journeys','0');
  await expect(page.getByLabel('Visual replay')).toHaveCount(0);
  await page.getByRole('button',{name:'Floor grid',exact:true}).click();
  await expect(page.getByRole('button',{name:'Floor grid',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'robot-1 · carrying',exact:true}).click();
  await expect(page.locator('.fleet-jobs')).toContainText('intersection');
  await expect(page.locator('.fleet-jobs')).toContainText('unit-0');
  mkdirSync('/artifacts',{recursive:true});await page.screenshot({path:'/artifacts/fleet-desktop.png',fullPage:true});
  value.fleet.stale=true;value.fleet.snapshot.run.state='held';value.fleet.snapshot.run.reason='storage: stale or held';
  await expect(stage).toHaveAttribute('data-fleet-frozen','true');
  await expect(stage).toHaveAttribute('data-fleet-loads','16');
  await expect(page.getByLabel('Operational fleet')).toContainText('frozen');
  await page.waitForTimeout(2200);await expect(stage).toHaveAttribute('data-active-journeys','0');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/artifacts/fleet-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('reduced motion retains reported poses and operational identity',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await open(page,fixture());
  await expect(page.locator('[data-fleet-robots="16"]')).toBeVisible();
  await expect(page.getByLabel('Operational fleet')).toContainText('Reported fleet');
  await expect(page.locator('[data-active-journeys="0"]')).toBeVisible();
});

test('operational floor never mixes historical replay robots from another source',async({page})=>{
  const value=fixture(),unit=value.handling.units[499];
  Object.assign(unit,{owner:'shipping',run_id:'legacy-run',epoch:'legacy-epoch',position:'shipping.outbound.dock01'});
  value.sources.push({name:'shipping',connected:true,stale:false,status:{run:{id:'legacy-run',epoch:'legacy-epoch',state:'running',granted:100,committed:100,requested:101}},snapshot:{config:{locations:[]}},cursor:'1',error:null} as any);
  value.events.push({id:'shipping:unit-movement:legacy',source:'shipping',run_id:'legacy-run',epoch:'legacy-epoch',payload:{id:'legacy',unit_id:unit.id,run_id:'legacy-run',epoch:'legacy-epoch',sequence:1,action:'load',origin:'shipping.outbound.dock01',destination:'logistics.outbound.truck01.slot01'}});
  await open(page,value);
  await expect(page.getByLabel('Operational fleet')).toBeVisible();
  const next=page.waitForResponse(response=>response.url().endsWith('/api/twin'));
  value.events.push({...value.events[1],id:'shipping:unit-movement:legacy-next',payload:{...value.events[1].payload,id:'legacy-next',sequence:2}});
  await next;
  await page.waitForTimeout(150);
  expect(await page.getByRole('group',{name:'Selectable 3D facility'}).getAttribute('data-active-journeys')).toBe('0');
});
