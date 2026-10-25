import http from 'node:http';
import {spawn} from 'node:child_process';
import {pathToFileURL} from 'node:url';

// Chromium treats loopback as trustworthy. Forward actual HTTP traffic instead
// of replacing application UUID generation or relying on ignored browser flags.
export async function exposeTargets(env) {
  const servers=new Map();
  async function expose(value) {
    const upstream=new URL(value);
    if(upstream.protocol!=='http:')return value;
    let local=servers.get(upstream.origin);
    if(!local) {
      const pending=new Set();
      const server=http.createServer((req,res)=>{
        const target=new URL(req.url,upstream.origin);
        const outgoing=http.request(target,{method:req.method,headers:req.headers},response=>{
          const headers={...response.headers};
          if(headers.location) {
            const redirect=new URL(headers.location,upstream.origin);
            if(redirect.origin===upstream.origin)headers.location=`http://${req.headers.host}${redirect.pathname}${redirect.search}${redirect.hash}`;
          }
          res.writeHead(response.statusCode??502,headers);response.pipe(res);
        });
        pending.add(outgoing);outgoing.once('close',()=>pending.delete(outgoing));
        outgoing.on('error',()=>{if(!res.destroyed){if(!res.headersSent)res.writeHead(502);res.end('Browser target unavailable');}});
        res.on('close',()=>outgoing.destroy());
        req.on('aborted',()=>outgoing.destroy());req.pipe(outgoing);
      });
      await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
      local={server,pending,origin:`http://127.0.0.1:${server.address().port}`};servers.set(upstream.origin,local);
    }
    return local.origin+upstream.pathname.replace(/\/$/,'')+upstream.search;
  }
  try {
    const result={...env};
    if(env.STACK_APPS) {
      const apps=JSON.parse(env.STACK_APPS);
      const exposed=[];
      for(const app of apps)exposed.push({...app,url:await expose(app.url)});
      result.STACK_APPS=JSON.stringify(exposed);
    }
    if(env.TWIN_URL)result.TWIN_URL=await expose(env.TWIN_URL);
    return {env:result,close:async()=>{await Promise.all([...servers.values()].map(({server,pending})=>new Promise(resolve=>{for(const request of pending)request.destroy();server.closeAllConnections();server.close(resolve);})));}};
  } catch(error) {
    for(const {server} of servers.values()){server.closeAllConnections();server.close();}
    throw error;
  }
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  const targets=await exposeTargets(process.env);
  const args=process.argv.slice(2);
  const child=spawn('npx',['playwright','test',...args],{env:targets.env,stdio:'inherit'});
  for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
  const code=await new Promise(resolve=>{child.once('error',()=>resolve(1));child.once('exit',(code)=>resolve(code??1));});
  await targets.close();process.exitCode=code;
}
