import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { Api } from './api.ts';
test('job retries retain command identity and surface server errors',async()=>{
 const seen:RequestInit[]=[];
 const api=new Api('employee','secret',async(_url,init)=>{seen.push(init!);return new Response('{"detail":"Database unavailable"}',{status:503});});
 for(let i=0;i<2;i++)await assert.rejects(api.request('/jobs','POST',{due_at:4,quantity:2},'stable-key'),/Database unavailable/);
 assert.equal((seen[0].headers as Record<string,string>)['Idempotency-Key'],'stable-key');
 assert.equal(seen[0].body,seen[1].body);
 assert.ok((seen[0].headers as Record<string,string>).Authorization.startsWith('Basic '));
});
test('successful server values are returned without fabricated defaults',async()=>{
 const api=new Api('operator','secret',async()=>new Response('{"effects":0}'));
 assert.deepEqual(await api.request('/status'),{effects:0});
});
test('default browser transport retains its global receiver',async()=>{
 const original=globalThis.fetch;
 globalThis.fetch=async function(this:unknown){
  assert.equal(this,globalThis,'browser fetch must be called on its global receiver');
  return new Response('{"application":"manufacturing"}');
 };
 try{assert.deepEqual(await new Api('operator','secret').request('/status'),{application:'manufacturing'});}
 finally{globalThis.fetch=original;}
});
test('uncertain production commands retain the exact body and key until acknowledged',async()=>{
 const { PendingCommand }=await import('./api.ts');
 const pending=new PendingCommand();const seen:RequestInit[]=[];let attempts=0;
 const api=new Api('employee','secret',async(_url,init)=>{seen.push(init!);if(attempts++===0)return new Response('{"detail":"Try again"}',{status:503});return new Response('{"id":"accepted"}');});
 await assert.rejects(pending.send(api,{action:'create',quantity:4,due_at:2}),/Try again/);
 assert.equal(pending.body?.quantity,4);
 await assert.rejects(pending.send(api,{action:'hold',quantity:1,due_at:9}),/Retry or discard/);
 await pending.retry(api);assert.equal(seen[0].body,seen[1].body);assert.equal((seen[0].headers as any)['Idempotency-Key'],(seen[1].headers as any)['Idempotency-Key']);assert.equal(pending.body,null);
});
test('material receipt retries preserve the explicit whole-unit identity and contents',async()=>{
 const {PendingCommand}=await import('./api.ts');const pending=new PendingCommand();const seen:RequestInit[]=[];
 const api=new Api('employee','secret',async(_url,init)=>{seen.push(init!);return seen.length===1?new Response('{"detail":"Try again"}',{status:503}):new Response('{"id":"accepted"}');});
 await assert.rejects(pending.send(api,{action:'supply',sku:'COMPONENT',quantity:6,due_at:2}),/Try again/);
 const sent=JSON.parse(seen[0].body as string);assert.ok(Array.isArray(sent.units),'Receipt must send an explicit whole-unit manifest');assert.equal(sent.units.length,1);assert.equal(sent.units[0].quantity,6);assert.match(sent.units[0].id,/^[0-9a-f-]{36}$/);
 await pending.retry(api);assert.equal(seen[0].body,seen[1].body);assert.equal((seen[0].headers as Record<string,string>)['Idempotency-Key'],(seen[1].headers as Record<string,string>)['Idempotency-Key']);
});
test('command IDs and retries work on HTTP hosts without randomUUID',async()=>{
 const own=Object.getOwnPropertyDescriptor(globalThis.crypto,'randomUUID');
 Object.defineProperty(globalThis.crypto,'randomUUID',{value:undefined,configurable:true});
 try{
  const {PendingCommand}=await import('./api.ts');const command=new PendingCommand();
  const api=new Api('operator','secret',async()=>new Response('{"status":"pending"}'));
  await command.send(api,{action:'supply',quantity:4});
  assert.equal(command.body,null);
 }finally{if(own)Object.defineProperty(globalThis.crypto,'randomUUID',own);else delete (globalThis.crypto as any).randomUUID;}
});
