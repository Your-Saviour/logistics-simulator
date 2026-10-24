export class Api {
 private username:string;private password:string;private transport:typeof fetch;
 constructor(username:string,password:string,transport:typeof fetch=globalThis.fetch.bind(globalThis)){this.username=username;this.password=password;this.transport=transport;}
 async request(path:string,method='GET',body?:unknown,key?:string):Promise<any>{
  const bytes=new TextEncoder().encode(`${this.username}:${this.password}`);
  const headers:Record<string,string>={'Authorization':`Basic ${btoa(String.fromCharCode(...bytes))}`,'Content-Type':'application/json'};
  if(key)headers['Idempotency-Key']=key;
  const reply=await this.transport(`/api${path}`,{method,headers,body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  let value:any;try{value=await reply.json();}catch{throw new Error(`Server returned HTTP ${reply.status}`);}
  if(!reply.ok)throw new Error(typeof value.detail==='string'?value.detail:`Request failed (HTTP ${reply.status})`);
  return value;
 }
}

/** Keep the submitted identity/body across an uncertain HTTP outcome. */
export class PendingCommand {
 body:Record<string,unknown>|null=null;
 key='';
 async send(api:Api,body:Record<string,unknown>){
  if(this.body)throw new Error('Retry or discard the pending command first.');
  this.body=structuredClone(body);
  if(this.body['action']==='supply'&&!('units' in this.body))this.body['units']=[{id:crypto.randomUUID(),quantity:this.body['quantity']}];
  this.key=crypto.randomUUID();return this.retry(api);
 }
 async retry(api:Api){
  if(!this.body)throw new Error('No pending command.');
  const result=await api.request('/production/commands','POST',this.body,this.key);this.discard();return result;
 }
 discard(){this.body=null;this.key='';}
}
