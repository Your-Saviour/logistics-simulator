import {test,expect} from '@playwright/test';
import {copyFileSync,existsSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {dirname} from 'node:path';
import os from 'node:os';
test.use({trace:'off',video:'off'});
test.skip(process.env.HANDLING_BENCHMARK!=='1','Run the explicit handling-performance-check target');
const catalog=JSON.parse(readFileSync(new URL('./facility.json',import.meta.url),'utf8'));
test('500 units and 64 concurrent journeys meet the 30-second frame budget',async({page})=>{
 test.setTimeout(60000);
 await page.setViewportSize({width:1440,height:900});
 await page.addInitScript(()=>{
  const state={frames:[] as {time:number;active:number;queued:number;units:number;drawCalls:number;prepMs:number;spanMs:number}[],frame:0,startFrame:0,last:-1,rafTime:0};(window as any).__handlingFrames=state;
  const clock=()=>{state.frame++;state.rafTime=performance.now();requestAnimationFrame(clock);};requestAnimationFrame(clock);
  const sample=()=>{if(state.last===state.frame){state.frames.at(-1)!.drawCalls++;state.frames.at(-1)!.spanMs=performance.now()-state.frames.at(-1)!.time;return;}state.last=state.frame;const root=document.querySelector<HTMLElement>('.facility-stage');if(root)state.frames.push({prepMs:performance.now()-state.rafTime,spanMs:0,drawCalls:1,time:performance.now(),active:Number(root.dataset.activeJourneys),queued:Number(root.dataset.queuedJourneys),units:Number(root.dataset.staticUnits)+Number(root.dataset.replayUnits)});};
  for(const name of ['drawElements','drawArrays','drawElementsInstanced','drawArraysInstanced']){
   const proto=WebGL2RenderingContext.prototype as any,original=proto[name];proto[name]=function(...args:any[]){sample();return original.apply(this,args);};
  }
 });
 const run={id:'benchmark-run',epoch:'benchmark-epoch',state:'running',granted:100,requested:101,committed:100,speed:1};
 const slots=catalog.locations.filter((slot:any)=>slot.kind==='shelf').slice(0,500);
 const units=slots.map((slot:any,index:number)=>({id:`benchmark-${index}`,barcode:`HU-BENCHMARK-${index}`,run_id:run.id,epoch:run.epoch,category:slot.compatible[0],contents:[{sku:'BENCHMARK',quantity:1}],owner:'storage',state:'available',status:'confirmed',position:slot.id,connected:true,observations:[]}));
 const groups=['raw','finished'].map(category=>slots.map((slot:any,index:number)=>({slot,index})).filter((row:any)=>row.slot.compatible[0]===category).map((row:any)=>row.index));
 const moving=groups.flatMap(indices=>Array.from({length:32},(_,i)=>{const bay=i<16?i:i+16;return indices[bay*4+bay%4];}));
 const partners=new Map<number,number>(),initialOrigins=new Map<number,string>();
 for(const indices of groups){
  indices.forEach((index:number,ordinal:number)=>initialOrigins.set(index,slots[indices[(ordinal+Math.floor(indices.length/2))%indices.length]].id));
  for(const index of moving.filter(index=>indices.includes(index)))partners.set(index,indices[indices.indexOf(index)^128]);
 }
 expect(moving.length).toBe(64);expect(new Set(moving.map(index=>`${slots[index].position[0]}/${slots[index].position[2]}`)).size).toBe(64);
 const events:any[]=[];let round=0;
 function append(count:number){round++;for(const index of count===500?units.map((_,index)=>index):moving){
  const unit=units[index],origin=unit.position;if(round>1)unit.position=round%2 ? slots[index].id : slots[partners.get(index)!].id;
  events.push({id:`storage:unit-movement:${index}-${round}`,source:'storage',run_id:run.id,epoch:run.epoch,payload:{id:`storage:unit-movement:${index}-${round}`,run_id:run.id,epoch:run.epoch,unit_id:unit.id,sequence:round,action:'putaway',origin:round===1?initialOrigins.get(index):origin,destination:unit.position}});
 }}
 append(500);
 await page.route('**/api/status',route=>route.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
 await page.route('**/api/twin',route=>{if(round>1||events.length===500)append(64);return route.fulfill({json:{revision:Date.now(),mode:'live',sources:[{name:'storage',connected:true,stale:false,status:{run},snapshot:{config:{locations:[]}},cursor:String(round),error:null}],events,aligned:null,controls:[],handling:{version:1,units,unsupported_sources:[]}}});});
 await page.goto(process.env.TWIN_URL!);await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('benchmark');await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.locator('[data-active-journeys="64"]')).toBeVisible();await page.waitForTimeout(5000);
 const floorReference=test.info().snapshotPath('performance-floor.png');mkdirSync(dirname(floorReference),{recursive:true});
 copyFileSync(new URL('./fixtures/facility-floor.png',import.meta.url),floorReference);
 async function visibleFacility(){
  const box=(await page.locator('canvas').boundingBox())!;
  // Outside robot routes: the fixed outbound floor/markers must survive cache hits.
  expect(await page.screenshot({clip:{x:box.x+600,y:box.y+320,width:90,height:60}})).toMatchSnapshot('performance-floor.png',{threshold:.08,maxDiffPixelRatio:.05});
 }
 await visibleFacility();
 const start=await page.evaluate(()=>{const state=(window as any).__handlingFrames;state.startFrame=state.frame;return performance.now();});await page.waitForTimeout(30000);
 const report=await page.evaluate(start=>{
  const frames=(window as any).__handlingFrames.frames.filter((frame:any)=>frame.time>=start);
  const intervals=frames.slice(1).map((frame:any,index:number)=>frame.time-frames[index].time).sort((a:number,b:number)=>a-b);
  const gl=document.querySelector('canvas')!.getContext('webgl2')!,debug=gl.getExtension('WEBGL_debug_renderer_info');
  return {fixture:'synthetic rendering workload: 500 units, 64 mixed-height inter-rack journeys across raw and finished storage; no native acceptance claim',viewport:{width:innerWidth,height:innerHeight},drawingBuffer:{width:gl.drawingBufferWidth,height:gl.drawingBufferHeight},durationMs:performance.now()-start,frameCount:frames.length,rafFrameCount:(window as any).__handlingFrames.frame-(window as any).__handlingFrames.startFrame,maxDrawCalls:Math.max(...frames.map((frame:any)=>frame.drawCalls)),maxPreparationMs:Math.max(...frames.map((frame:any)=>frame.prepMs)),maxRenderSubmissionMs:Math.max(...frames.map((frame:any)=>frame.spanMs)),p95Ms:intervals[Math.ceil(intervals.length*.95)-1],maxIntervalMs:intervals.at(-1),minActive:Math.min(...frames.map((frame:any)=>frame.active)),maxActive:Math.max(...frames.map((frame:any)=>frame.active)),maxQueued:Math.max(...frames.map((frame:any)=>frame.queued)),minUnits:Math.min(...frames.map((frame:any)=>frame.units)),maxUnits:Math.max(...frames.map((frame:any)=>frame.units)),renderer:debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),browser:navigator.userAgent};
 },start);
 const driverPackages='/etc/handling-renderer-packages.txt';
 const result={...report,softwareRenderer:{requested:process.env.HANDLING_RENDERER??'swiftshader',configuredRasterThreads:process.env.LP_NUM_THREADS?Number(process.env.LP_NUM_THREADS):null,packages:existsSync(driverPackages)?readFileSync(driverPackages,'utf8').trim().split('\n'):[]},host:JSON.parse(process.env.HOST_HARDWARE_JSON??'{}'),container:{architecture:os.arch(),cpu:os.cpus()[0]?.model,logicalCpus:os.cpus().length,memoryBytes:os.totalmem()}};
 writeFileSync(test.info().outputPath('performance.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 await visibleFacility();
 expect(report.renderer).toMatch(process.env.HANDLING_RENDERER==='mesa'?/llvmpipe/i:/SwiftShader/i);
 expect(report.frameCount).toBeGreaterThan(850);expect(report.minActive).toBe(64);expect(report.maxActive).toBe(64);expect(report.maxQueued).toBeLessThanOrEqual(256);expect(report.minUnits).toBe(500);expect(report.maxUnits).toBe(500);expect(report.p95Ms).toBeLessThanOrEqual(33.4);
});
