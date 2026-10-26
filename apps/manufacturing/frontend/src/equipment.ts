import type {Api} from './api';
export interface EquipmentSnapshot {
 mode:string;hmi_url?:string;run_id:string;epoch:string;stale:boolean;
 cell:{initialized:boolean;observed_at:string|null;error:string|null;active_order?:string;settled?:number;telemetry:any}|null;
 commands?:any[];
}
export function equipmentState(snapshot:EquipmentSnapshot|null,failed:boolean,now=Date.now()){
 const cell=snapshot?.cell;const age=cell?.observed_at?now-Date.parse(cell.observed_at):Infinity;
 const live=!!snapshot&&snapshot.mode==='openplc'&&!snapshot.stale&&!failed&&!!cell?.initialized&&!cell.error&&Number.isFinite(age)&&age>=-1000&&age<16000;
 const model=cell?.telemetry?.cell;const faults:string[]=model?.faults??[];
 const label=!snapshot?'Loading equipment':snapshot.mode==='disabled'?'OT disabled':failed?'Gateway unavailable':cell?.error?'Equipment / PLC unavailable':!cell?.initialized?'Initializing equipment':!live?'Stale observation':faults.length?'Faulted':model?.latched?'Reset required':model?.enabled?'Running':model?.batch?'Awaiting Start':'Idle';
 return {live,label,age,faults};
}
export interface TrendPoint {simulation_time:number;value:number|null;quality?:string;continuity?:number;}
export function trendSegments(points:TrendPoint[]):TrendPoint[][]{
 const segments:TrendPoint[][]=[];let current:TrendPoint[]=[];let previous=-Infinity;let continuity:number|undefined;
 for(const point of points){
  if(point.value===null||!Number.isFinite(point.value)||point.quality==='missing'){if(current.length)segments.push(current);current=[];previous=-Infinity;continue;}
  if(point.simulation_time<=previous||point.simulation_time-previous>1||point.continuity!==continuity){if(current.length)segments.push(current);current=[];}
  current.push(point);previous=point.simulation_time;continuity=point.continuity;
 }
 if(current.length)segments.push(current);return segments;
}
interface Persistence {getItem(key:string):string|null;setItem(key:string,value:string):void;removeItem(key:string):void;}
/** Persist uncertain commands per actor. Retrying never retargets a new run or epoch. */
export class EquipmentCommand {
 body:Record<string,unknown>|null=null;key='';path='';private storage:Persistence;private storageKey:string;
 constructor(storage:Persistence,actor:string){this.storage=storage;this.storageKey='manufacturing.ot.pending:'+actor;try{const saved=JSON.parse(storage.getItem(this.storageKey)??'null');if(saved&&saved.body&&typeof saved.key==='string'&&['/ot/commands','/ot/insights'].includes(saved.path)){this.body=saved.body;this.key=saved.key;this.path=saved.path;}}catch{/* unavailable storage must not invent a command */}}
 async send(api:Api,path:string,body:Record<string,unknown>){
  if(this.body)throw new Error('Retry or discard the retained command first.');
  const saved={body:structuredClone(body),key:api.commandId(),path};
  this.storage.setItem(this.storageKey,JSON.stringify(saved));this.body=saved.body;this.key=saved.key;this.path=path;return this.retry(api);
 }
 async retry(api:Api){if(!this.body)throw new Error('No retained command.');const result=await api.request(this.path,'POST',this.body,this.key);this.discard();return result;}
 discard(){this.storage.removeItem(this.storageKey);this.body=null;this.key='';this.path='';}
}

export function syntheticReading(observations:{observed_at:string;signals:Record<string,unknown>}[],now=Date.now()){
 const last=observations.at(-1);const age=last?now-Date.parse(last.observed_at):Infinity;
 return {observedAt:last?.observed_at??null,age,signals:last?.signals??{},quality:!last?'No sample':!Number.isFinite(age)||age>=16000||age< -1000?'Stale synthetic sample':String(last.signals['quality']??'Unknown')};
}
/** A repeated completion fact is one event, not a new completion on each scan. */
export function completionTimeline(observations:any[]){
 const seen=new Set<string>();const result:{key:string;at:string;action:string;detail:string}[]=[];
 for(const observation of observations){const event=observation.telemetry?.completion;if(!event?.event_id||observation.order_id!==event.order_id||seen.has(event.event_id))continue;seen.add(event.event_id);result.push({key:'completion:'+event.event_id,at:observation.observed_at,action:'Equipment completion observed',detail:event.order_id+' · '+event.simulation_time+' s'});}
 return result;
}
