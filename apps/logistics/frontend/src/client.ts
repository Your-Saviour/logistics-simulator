export function can(identity: { scopes:string[] }, scope:string):boolean { return identity.scopes.includes(scope); }
export class Client {
 private authorization:string;
 private base:string;
 constructor(user:string,password:string,base='') {this.base=base;const bytes=new TextEncoder().encode(`${user}:${password}`);this.authorization=`Basic ${btoa(String.fromCharCode(...bytes))}`;}
 async request<T=unknown>(path:string,init:RequestInit={}):Promise<T>{const response=await fetch(this.base+path,{...init,headers:{'Authorization':this.authorization,'Content-Type':'application/json',...init.headers}});const data=await response.json();if(!response.ok){const detail=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail);throw new Error(detail||`Request failed (${response.status})`);}return data as T;}
 transport(command:Record<string,unknown>){const key=crypto.randomUUID();const body=JSON.stringify(command);return {send:()=>this.request<{id:string}>('/api/transport/commands',{method:'POST',headers:{'Idempotency-Key':key},body})};}
 job(due:number,quantity:number){const key=crypto.randomUUID();const body=JSON.stringify({due_at:due,quantity});return {send:()=>this.request('/api/jobs',{method:'POST',headers:{'Idempotency-Key':key},body})};}
}
