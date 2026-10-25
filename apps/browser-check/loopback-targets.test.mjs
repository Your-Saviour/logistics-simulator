import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {chromium} from 'playwright';
import {exposeTargets} from './loopback-targets.mjs';

test('real loopback targets preserve requests and provide Chromium secure contexts', async () => {
  const requests=[];
  const upstream=http.createServer(async (req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({url:req.url,method:req.method,key:req.headers['idempotency-key'],body});
    res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Actual upstream</title>');
  });
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  const url=`http://127.0.0.1:${upstream.address().port}`;
  let targets,browser;
  try {
    targets=await exposeTargets({STACK_APPS:JSON.stringify([{name:'twin',url,username:'test',password:'test-only'}]),TWIN_URL:url});
    const apps=JSON.parse(targets.env.STACK_APPS);
    assert.equal(apps[0].password,'test-only');assert.notEqual(apps[0].url,url);
    assert.equal(apps[0].url,targets.env.TWIN_URL);
    const response=await fetch(apps[0].url+'/api/control?epoch=1',{method:'POST',headers:{'Idempotency-Key':'stable-command'},body:'{"action":"hold"}'});
    assert.equal(response.status,200);
    assert.deepEqual(requests[0],{url:'/api/control?epoch=1',method:'POST',key:'stable-command',body:'{"action":"hold"}'});
    browser=await chromium.launch();const page=await browser.newPage();await page.goto(apps[0].url);
    assert.deepEqual(await page.evaluate(()=>({secure:isSecureContext,uuid:typeof crypto.randomUUID})),{secure:true,uuid:'function'});
    assert.equal(await page.title(),'Actual upstream');
  } finally {
    await browser?.close();await targets?.close();await new Promise(resolve=>upstream.close(resolve));
  }
});

test('closing an aborted browser request also closes its unanswered upstream request',async()=>{
  let started,closed;
  const requestStarted=new Promise(resolve=>{started=resolve;});
  const responseClosed=new Promise(resolve=>{closed=resolve;});
  const upstream=http.createServer((req,res)=>{res.on('close',closed);started();});
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  let targets,request;
  try {
    targets=await exposeTargets({TWIN_URL:`http://127.0.0.1:${upstream.address().port}`});
    request=http.get(targets.env.TWIN_URL);request.on('error',()=>{});
    await requestStarted;request.destroy();await targets.close();
    await Promise.race([responseClosed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('upstream request leaked after browser closed')),1000))]);
  } finally {
    request?.destroy();await targets?.close();upstream.closeAllConnections();await new Promise(resolve=>upstream.close(resolve));
  }
});
