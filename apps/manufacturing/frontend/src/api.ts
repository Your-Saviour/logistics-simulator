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
