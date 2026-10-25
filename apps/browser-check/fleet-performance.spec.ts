import {test,expect} from '@playwright/test';
import {existsSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import os from 'node:os';

test.use({trace:'off',video:'off'});
test.skip(process.env.FLEET_BENCHMARK!=='1','Run scripts/check_fleet_performance.sh');
const catalog=JSON.parse(readFileSync(new URL('./facility.json',import.meta.url),'utf8'));

test('synthetic operational fleet rendering, grid enabled, 30 seconds',async({page})=>{
  test.setTimeout(75000);
  await page.setViewportSize({width:1440,height:1000});
  await page.addInitScript(()=>{
    const state={frames:[] as any[],frame:0,last:-1,rafTime:0};
    (window as any).__fleetFrames=state;
    const clock=()=>{state.frame++;state.rafTime=performance.now();requestAnimationFrame(clock);};
    requestAnimationFrame(clock);
    for(const name of ['drawElements','drawArrays','drawElementsInstanced','drawArraysInstanced']){
      const proto=WebGL2RenderingContext.prototype as any,original=proto[name];
      proto[name]=function(...args:any[]){
        const started=performance.now();
        if(state.last!==state.frame){state.last=state.frame;state.frames.push({time:started,prepMs:started-state.rafTime,submissionMs:0,spanMs:0,drawCalls:0});}
        const sample=state.frames.at(-1)!;
        const result=original.apply(this,args);
        sample.drawCalls++;sample.submissionMs+=performance.now()-started;sample.spanMs=performance.now()-sample.time;
        return result;
      };
    }
  });
  const run={id:'benchmark-source',epoch:'benchmark-epoch',state:'running',granted:100,requested:101,committed:100};
  const slots=catalog.locations.filter((e:any)=>e.kind==='shelf').slice(0,500);
  const units=slots.map((slot:any,i:number)=>({id:`unit-${i}`,barcode:`HU-BENCH-${i}`,run_id:run.id,epoch:run.epoch,category:slot.compatible[0],contents:[{sku:'BENCHMARK',quantity:1}],owner:'storage',state:'available',status:'confirmed',position:slot.id,connected:true,observations:[]}));
  // Separate identities leave all 500 recorded static units visible alongside 16 loads.
  const robots=Array.from({length:16},(_,i)=>({id:`robot-${i+1}`,pose:[-32+i*3,23,1],parking:[-32+i*3,23,1],job_id:`job-${i}`,carried_unit_id:`load-${i}`,fork_height:.55,fork_offset:[0,0],load_position:[-32+i*3,.91,23]}));
  const jobs=robots.map((r,i)=>({id:r.job_id,unit_id:r.carried_unit_id,robot_id:r.id,state:'carrying',progress:.5,waiting_reason:null,blockers:[],request:{producer:'storage',source_run_id:run.id,source_epoch:run.epoch,origin:slots[i].id,destination:slots[i+32].id}}));
  const value={mode:'live',sources:[{name:'storage',connected:true,stale:false,status:{run},snapshot:{config:{locations:[]},handling:{fleet:{mode:'coordinated'}}},cursor:'1',error:null}],events:[],aligned:null,controls:[],handling:{version:1,units,unsupported_sources:[]},fleet:{configured:true,stale:false,snapshot:{run:{id:'fleet-benchmark',epoch:'fleet-epoch',revision:1,committed:100,state:'running',reason:null,fresh:true,sources:{storage:{run_id:run.id,epoch:run.epoch,offset:0}}},robots,jobs,reservations:Array.from({length:1000},(_,i)=>({resource:`cell:${-130+i%200}:${90+Math.floor(i/200)}`,job_id:'job-1'}))}}};
  await page.route('**/api/status',r=>r.fulfill({json:{identity:{username:'reader',scopes:['status:read']},heartbeats:[]}}));
  await page.route('**/api/twin',r=>r.fulfill({json:{...value,revision:Date.now()}}));
  const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(process.env.TWIN_URL!);
  await page.getByLabel('Username',{exact:true}).fill('reader');await page.getByLabel('Password',{exact:true}).fill('benchmark');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  const stage=page.locator('[data-models-ready=true]');await expect(stage).toBeVisible();
  await expect(stage).toHaveAttribute('data-fleet-robots','16');await expect(stage).toHaveAttribute('data-recorded-units','500');
  await page.getByRole('button',{name:'Floor grid',exact:true}).click();
  await expect(page.getByRole('button',{name:'Floor grid',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(stage).toHaveAttribute('data-active-journeys','0');
  await page.waitForTimeout(3000);
  mkdirSync('/artifacts',{recursive:true});await page.screenshot({path:'/artifacts/fleet-performance-before.png'});
  const canvas=page.locator('canvas'),box=(await canvas.boundingBox())!;
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  // Exercise OrbitControls on each RAF. Robot and load transforms stay fixed;
  // camera interaction supplies actual demand renders instead of measuring 1 Hz polling gaps.
  const report=await page.evaluate(async({x,y})=>{
    const state=(window as any).__fleetFrames,canvas=document.querySelector('canvas')!;
    const start=performance.now(),startFrame=state.frame;
    await new Promise<void>(resolve=>{
      const move=(now:number)=>{
        const elapsed=now-start;
        canvas.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:1,pointerType:'mouse',buttons:1,clientX:x+Math.sin(elapsed/900)*55,clientY:y+Math.sin(elapsed/1300)*12}));
        if(elapsed<30000)requestAnimationFrame(move);else resolve();
      };requestAnimationFrame(move);
    });
    const frames=state.frames.filter((f:any)=>f.time>=start);
    const stats=(values:number[])=>{const sorted=[...values].sort((a,b)=>a-b);return {p50:sorted[Math.ceil(sorted.length*.5)-1],p95:sorted[Math.ceil(sorted.length*.95)-1],max:sorted.at(-1)};};
    const gl=canvas.getContext('webgl2')!,debug=gl.getExtension('WEBGL_debug_renderer_info');
    return {fixture:'Synthetic rendering benchmark only: 500 static units, 16 reported loaded operational robots, 1000 reserved grid cells; no native acceptance claim',durationMs:performance.now()-start,renderedFrames:frames.length,rafFrames:state.frame-startFrame,preparationMs:stats(frames.map((f:any)=>f.prepMs)),drawCallSubmissionMs:stats(frames.map((f:any)=>f.submissionMs)),renderSubmissionSpanMs:stats(frames.map((f:any)=>f.spanMs)),preparationAndSubmissionMs:stats(frames.map((f:any)=>f.prepMs+f.spanMs)),renderedFrameIntervalMs:stats(frames.slice(1).map((f:any,i:number)=>f.time-frames[i].time)),maxDrawCalls:Math.max(...frames.map((f:any)=>f.drawCalls)),renderer:debug?gl.getParameter(debug.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),browser:navigator.userAgent,viewport:{width:innerWidth,height:innerHeight},drawingBuffer:{width:gl.drawingBufferWidth,height:gl.drawingBufferHeight},metricsNote:'CPU timings include render preparation and WebGL command submission, not GPU completion. Render intervals under camera interaction include browser scheduling and software GPU cost. No 1 Hz poll interval is treated as GPU time.'};
  },{x:box.x+box.width/2,y:box.y+box.height/2});
  await page.mouse.up();await page.getByRole('button',{name:'Reset view',exact:true}).click();await page.waitForTimeout(1000);
  await page.screenshot({path:'/artifacts/fleet-performance-after.png'});
  const packages='/etc/handling-renderer-packages.txt';
  const result={...report,targets:{frameBudgetMs:20},host:JSON.parse(process.env.HOST_HARDWARE_JSON??'{}'),container:{architecture:os.arch(),cpu:os.cpus()[0]?.model,logicalCpus:os.cpus().length,memoryBytes:os.totalmem(),image:process.env.BENCHMARK_BROWSER_IMAGE},softwareRenderer:{rasterThreads:process.env.LP_NUM_THREADS,packages:existsSync(packages)?readFileSync(packages,'utf8').trim().split('\n'):[]},errors};
  writeFileSync('/artifacts/fleet-performance.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  expect(errors).toEqual([]);await expect(stage).toHaveAttribute('data-active-journeys','0');
  expect(report.renderer).toMatch(/llvmpipe/i);expect(report.durationMs).toBeGreaterThanOrEqual(30000);
  expect(report.renderedFrames).toBeGreaterThan(850);
  expect(report.preparationAndSubmissionMs.p95).toBeLessThanOrEqual(20);
  expect(report.renderedFrameIntervalMs.p95).toBeLessThanOrEqual(20);
});
