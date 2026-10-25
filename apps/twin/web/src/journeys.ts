/** Visual replay only. No business callbacks, timers, HTTP or inventory writes. */
import {endpoint, type Endpoint, type Vec3} from './facility.ts';
export type Movement = {
  id: string; source: string; run_id: string; epoch: string; unit_id: string;
  sequence: number; origin: string | null; destination: string | null; action: string;
  custody_generation?: number;
};
export type MotionSource = {name: string; run_id: string; epoch: string; running: boolean; connected: boolean};
export type Route = {origin: Endpoint; destination: Endpoint; points: Vec3[]};
export type Journey = {move: Movement; route: Route; observed: number; elapsed: number; duration: number};
export type Trail = {move: Movement; route: Route; elapsed: number};
export const LIMITS = {active:64, queued:256, catchup:15000, trail:3000, duration:2000} as const;
const clamp = (value: number) => Math.max(0,Math.min(1,value));
const interpolate = (a: number,b: number,t: number) => a+(b-a)*clamp(t);
const mix = (a: Vec3,b: Vec3,t: number): Vec3 => a.map((value,index)=>interpolate(value,b[index],t)) as Vec3;
const distance = (a: Vec3,b: Vec3) => Math.hypot(a[0]-b[0],a[2]-b[2]);
function workingPosition(location: Endpoint): Vec3 {
  const length = distance(location.position,location.access);
  const reach = Math.min(length,1.2);
  return [location.position[0]+(location.access[0]-location.position[0])*(length ? reach/length : 0),0,
    location.position[2]+(location.access[2]-location.position[2])*(length ? reach/length : 0)];
}
export function routeFor(move: Pick<Movement,'origin'|'destination'>): Route | null {
  const origin=endpoint(move.origin),destination=endpoint(move.destination);
  if (!origin||!destination||origin.id===destination.id) return null;
  const a=origin.access,b=destination.access;
  const points: Vec3[]=[workingPosition(origin),a];
  if (a[0]!==b[0]) {
    // Aisles join the fixed north/south lanes; never cut through rack rows.
    const north=Math.abs(a[2]+26)+Math.abs(b[2]+26);
    const south=Math.abs(a[2]-26)+Math.abs(b[2]-26);
    const z=north<=south ? -26 : 26;
    points.push([a[0],0,z],[b[0],0,z]);
  }
  points.push(b,workingPosition(destination));
  return {origin,destination,points:points.filter((point,index)=>index===0||distance(point,points[index-1])>.001)};
}
function along(points: Vec3[],progress: number): Vec3 {
  const lengths=points.slice(1).map((point,index)=>distance(point,points[index]));
  let remaining=lengths.reduce((sum,value)=>sum+value,0)*clamp(progress);
  for (let index=0;index<lengths.length;index++) {
    if (remaining<=lengths[index]) return mix(points[index],points[index+1],lengths[index] ? remaining/lengths[index] : 1);
    remaining-=lengths[index];
  }
  return points.at(-1)!;
}
export function poseAt(route: Route,progress: number) {
  const p=clamp(progress),start=route.points[0],end=route.points.at(-1)!;
  if (p<.2) {
    const retract=clamp((p-.15)/.02),lower=clamp((p-.17)/.03);
    return {position:start,forkHeight:p<.15 ? interpolate(.15,route.origin.position[1],p/.1) : interpolate(route.origin.position[1],.55,lower),
      forkOffset:[(route.origin.position[0]-start[0])*(1-retract),0,(route.origin.position[2]-start[2])*(1-retract)] as Vec3,
      carrying:p>=.12,phase:'pickup' as const};
  }
  if (p<.8) return {position:along(route.points,(p-.2)/.6),forkHeight:.55,forkOffset:[0,0,0] as Vec3,carrying:true,phase:'travel' as const};
  const extend=clamp((p-.87)/.06);
  return {position:end,forkHeight:interpolate(.55,route.destination.position[1],(p-.8)/.07),
    forkOffset:[(route.destination.position[0]-end[0])*extend,0,(route.destination.position[2]-end[2])*extend] as Vec3,
    carrying:p<.95,phase:'place' as const};
}
const unitKey = (move: Movement) => `${move.run_id}/${move.epoch}/${move.unit_id}`;
const eventKey = (move: Movement) => `${move.source}/${move.run_id}/${move.epoch}/${move.id}`;
function handoffLegKey(move: Movement): string | null {
  if (!['depart','load','receive'].includes(move.action)||!Number.isInteger(move.custody_generation)||move.custody_generation!<1) return null;
  const origin=endpoint(move.origin),destination=endpoint(move.destination);
  if (!origin||!destination||origin.owner===destination.owner) return null;
  return `${unitKey(move)}/${move.custody_generation}/${origin.id}/${destination.id}`;
}
export class JourneyQueue {
  active: Journey[]=[];
  queued: Journey[]=[];
  trails: Trail[]=[];
  skipped=0;
  unmapped=0;
  private seen=new Set<string>();
  private sources=new Map<string,MotionSource>();
  private sequences=new Map<string,number>();
  private handoffLegs=new Map<string,string>();
  private previous: number | null=null;
  private reduced=false;
  private matches(move: Movement) {
    const source=this.sources.get(move.source);
    return !!source&&source.run_id===move.run_id&&source.epoch===move.epoch;
  }
  private running(move: Movement) {
    const source=this.sources.get(move.source);
    return !!source&&source.connected&&source.running;
  }
  observe(movements: Movement[],sources: MotionSource[],now: number,reducedMotion=false) {
    const next=new Map(sources.map(source=>[source.name,source]));
    for (const [name,old] of this.sources) {
      const current=next.get(name);
      if (!current||current.run_id!==old.run_id||current.epoch!==old.epoch) {
        for (const key of this.seen) if (key.startsWith(name+'/')) this.seen.delete(key);
      }
    }
    this.sources=next;
    this.reduced=reducedMotion;
    this.active=this.active.filter(journey=>this.matches(journey.move));
    this.queued=this.queued.filter(journey=>this.matches(journey.move));
    this.trails=this.trails.filter(trail=>this.matches(trail.move));
    const scopes=new Set(sources.map(source=>`${source.run_id}/${source.epoch}/`));
    for (const key of this.sequences.keys()) if (![...scopes].some(scope=>key.startsWith(scope))) this.sequences.delete(key);
    for (const key of this.handoffLegs.keys()) if (![...scopes].some(scope=>key.startsWith(scope))) this.handoffLegs.delete(key);
    if (reducedMotion) {this.active=[];this.queued=[];this.trails=[];}
    for (const move of movements) {
      if (!this.matches(move)||this.seen.has(eventKey(move))) continue;
      this.seen.add(eventKey(move));
      const route=routeFor(move);
      if (!route) {if (move.origin!==null&&move.destination!==null&&move.origin!==move.destination&&(!endpoint(move.origin)||!endpoint(move.destination))) this.unmapped++;continue;}
      if (reducedMotion) continue;
      const leg=handoffLegKey(move);
      if (leg&&this.handoffLegs.has(leg)) {
        // Departure and receipt are two durable observations of one physical
        // trip. A recipient confirmation can take over its existing estimate;
        // it must not send the unit back to the origin for a second trip.
        if (move.action==='receive'&&['depart','load'].includes(this.handoffLegs.get(leg)!)) {
          const active=this.active.find(journey=>handoffLegKey(journey.move)===leg);
          const queued=this.queued.find(journey=>handoffLegKey(journey.move)===leg);
          if (active) {active.move=move;this.sequences.set(unitKey(move),Math.max(move.sequence,this.sequences.get(unitKey(move))??0));}
          if (queued) queued.move=move;
          this.handoffLegs.set(leg,'receive');
        }
        this.skipped++;continue;
      }
      if (move.sequence<=(this.sequences.get(unitKey(move))??0)) {this.skipped++;continue;}
      if (leg) this.handoffLegs.set(leg,move.action);
      this.queued.push({move,route,observed:now,elapsed:0,duration:LIMITS.duration});
    }
    this.queued.sort((a,b)=>a.move.sequence-b.move.sequence||a.observed-b.observed||eventKey(a.move).localeCompare(eventKey(b.move)));
    while (this.queued.length>LIMITS.queued) {this.queued.shift();this.skipped++;}
  }
  tick(now: number) {
    const delta=this.previous===null ? 0 : Math.max(0,now-this.previous);
    this.previous=now;
    if (this.reduced) return;
    this.trails=this.trails.filter(trail=>{
      if (this.running(trail.move)) trail.elapsed+=delta;
      return trail.elapsed<LIMITS.trail;
    });
    this.active=this.active.filter(journey=>{
      if (!this.running(journey.move)) return true;
      journey.elapsed+=delta;
      if (now-journey.observed>=LIMITS.catchup) {this.skipped++;return false;}
      if (journey.elapsed<journey.duration) return true;
      this.trails.push({move:journey.move,route:journey.route,elapsed:0});return false;
    });
    this.trails=this.trails.slice(-LIMITS.queued);
    this.queued=this.queued.filter(journey=>{
      if (this.running(journey.move)&&now-journey.observed>=LIMITS.catchup) {this.skipped++;return false;}
      return true;
    });
    const busy=new Set(this.active.map(journey=>unitKey(journey.move)));
    const remaining: Journey[]=[];
    for (const journey of this.queued) {
      const key=unitKey(journey.move);
      if (busy.has(key)||this.active.length>=LIMITS.active) {remaining.push(journey);continue;}
      busy.add(key);
      if (!this.running(journey.move)) {remaining.push(journey);continue;}
      if (journey.move.sequence<=(this.sequences.get(key)??0)) {this.skipped++;continue;}
      this.sequences.set(key,journey.move.sequence);this.active.push(journey);
    }
    this.queued=remaining;
  }
}
