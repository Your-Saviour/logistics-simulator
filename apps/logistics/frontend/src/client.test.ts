import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { Client, can } from './client.ts';
test('service and employee controls require explicit operator permission', () => {
 assert.equal(can({ scopes: ['jobs:write','status:read'] }, 'runs:control'), false);
 assert.equal(can({ scopes: ['runs:control'] }, 'runs:control'), true);
});
test('a command retry retains its idempotency key and propagates server errors', async () => {
 const keys: Array<string | string[] | undefined> = [];
 const server = createServer((request,response) => {keys.push(request.headers['idempotency-key']);response.setHeader('Content-Type','application/json');if(keys.length===1){response.statusCode=503;response.end(JSON.stringify({detail:'Database unavailable'}));}else{response.end(JSON.stringify({id:'saved-job'}));}});
 await new Promise<void>(resolve => server.listen(0,'0.0.0.0',resolve));
 try {const address=server.address() as {port:number};const c=new Client('operator','secret',`http://127.0.0.1:${address.port}`);const command=c.job(10,2);await assert.rejects(command.send(),/Database unavailable/);assert.deepEqual(await command.send(),{id:'saved-job'});assert.equal(keys.length,2);assert.equal(keys[0],keys[1]);assert.ok(keys[0]);} finally {server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}
});
test('transport retry keeps the original command body and idempotency key', async () => {
 const received:{key:string| string[] |undefined;body:string}[]=[];
 const server=createServer(async(request,response)=>{let body='';for await(const chunk of request)body+=chunk;received.push({key:request.headers['idempotency-key'],body});response.setHeader('Content-Type','application/json');response.statusCode=received.length===1?503:200;response.end(JSON.stringify(received.length===1?{detail:'retry'}:{id:'transfer'}));});
 await new Promise<void>(resolve=>server.listen(0,'0.0.0.0',resolve));
 try {const port=(server.address() as {port:number}).port;const client=new Client('employee','secret',`http://127.0.0.1:${port}`);const body={run_id:'run',epoch:'epoch',due_at:5,action:'assign',reference:'transfer',vehicle:'TRUCK-1'};const command=client.transport(body);body.vehicle='VAN-1';await assert.rejects(command.send(),/retry/);await command.send();assert.deepEqual(received[0],received[1]);assert.equal(JSON.parse(received[1].body).vehicle,'TRUCK-1');}finally{server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}
});
