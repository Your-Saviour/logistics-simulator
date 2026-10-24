import assert from 'node:assert/strict';
const base='http://api:8000';
const auth='Basic '+Buffer.from('operator:logistics-test-password').toString('base64');
async function req(path,body,key){const r=await fetch(base+path,{method:body?'POST':'GET',headers:{Authorization:auth,'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:body?JSON.stringify(body):undefined});const v=await r.json();assert.equal(r.status,200,JSON.stringify(v));return v;}
const status=()=>req('/api/status');
const control=(action,body={})=>req('/api/control/'+action,body);
const step=process.argv[2];
if(step==='prepare') {let s=await status();await control('reset',{confirm_run_id:s.run.id});await control('hold');await control('speed',{speed:60});s=await status();await req('/api/jobs',{due_at:1,quantity:2},'broker-outage');console.log('prepared broker outage job');}
if(step==='resume') await control('resume');
if(step==='broker-down'){const s=await status();assert.equal(s.effects,0);assert.equal(s.jobs.length,1);assert.equal(s.jobs[0].attempts,0);assert.equal(s.jobs[0].status,'pending');console.log('broker outage retained pending job and retry budget');}
if(step==='broker-recovered'){for(let i=0;i<80;i++){const s=await status();if(s.effects===2){assert.equal(s.jobs[0].status,'completed');await control('hold');const held=await status();await req('/api/jobs',{due_at:Math.max(held.run.granted,held.run.requested)+1,quantity:3},'database-outage');console.log('broker recovery committed exactly one effect; prepared DB outage');process.exit(0)}await new Promise(r=>setTimeout(r,250))}throw Error('broker recovery timed out');}
if(step==='database-down'){const r=await fetch(base+'/api/jobs',{method:'POST',headers:{Authorization:auth,'Content-Type':'application/json','Idempotency-Key':'rejected-during-db-outage'},body:JSON.stringify({due_at:100000,quantity:9})});assert.equal(r.status,503);console.log('real DB outage returned 503 without acceptance');}
if(step==='database-recovered'){await control('resume');for(let i=0;i<100;i++){const s=await status();if(s.effects===5){assert.equal(s.jobs.length,2);assert.ok(s.jobs.every(j=>j.status==='completed'&&j.attempts===0));await control('hold');console.log('DB recovery retained both jobs with exactly 5 item total and zero failure attempts');process.exit(0)}await new Promise(r=>setTimeout(r,250))}throw Error('DB recovery timed out');}
if(step==='web'){const r=await fetch('http://web/');assert.equal(r.status,200);assert.match(await r.text(),/Logistics simulator/);const s=await fetch('http://web/api/status',{headers:{Authorization:auth}});assert.equal(s.status,200);assert.equal((await s.json()).application,'logistics');console.log('port 80 frontend serves Svelte artifact and proxies authenticated API');}
