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
