/** Reported fleet state only: browser time never authorizes physical motion. */
export type FleetRobot = {
  id: string; pose: [number,number,number]; parking: [number,number,number];
  job_id: string|null; carried_unit_id: string|null; fork_height: number;
  fork_offset: [number,number]; load_position?: [number,number,number]|null;
  load_heading?: number;
};
export type FleetJob = {
  id: string; unit_id: string; robot_id: string|null; state: string; progress: number;
  waiting_reason: string|null; blockers: string[];
  request: {producer:string; source_run_id:string; source_epoch:string; origin:string; destination:string};
};
export type FleetObservation = {
  configured: boolean; stale: boolean;
  snapshot: {run: {id:string;epoch:string;revision:number;committed:number;state:string;reason:string|null;fresh:boolean;
    sources:Record<string,{run_id:string;epoch:string;offset:number}>};
    robots:FleetRobot[];jobs:FleetJob[];reservations:{resource:string;job_id:string}[]} | null;
};
export type ScopeSource = {name:string;status:{run:{id:string;epoch:string}}|null;
  snapshot?:Record<string,unknown>|null};
const scopeKey=(name:string,run:string,epoch:string)=>`${name}/${run}/${epoch}`;

export function operationalScopes(sources:ScopeSource[], fleet:FleetObservation|null|undefined):Set<string> {
  const result=new Set<string>();
  for(const source of sources) {
    const handling=source.snapshot?.handling as {fleet?:{mode?:string}}|undefined;
    if(handling?.fleet?.mode==='coordinated'&&source.status)
      result.add(scopeKey(source.name,source.status.run.id,source.status.run.epoch));
  }
  for(const [name,scope] of Object.entries(fleet?.snapshot?.run.sources??{}))
    result.add(scopeKey(name,scope.run_id,scope.epoch));
  return result;
}

export function replayAllowed(move:{source:string;run_id:string;epoch:string}, scopes:Set<string>):boolean {
  return !scopes.has(scopeKey(move.source,move.run_id,move.epoch));
}

export function activeLoadKeys(fleet:FleetObservation|null|undefined):Set<string> {
  const result=new Set<string>();
  for(const robot of fleet?.snapshot?.robots??[]) {
    if(!robot.carried_unit_id) continue;
    const job=fleet?.snapshot?.jobs.find(job=>job.id===robot.job_id);
    if(!job) continue;
    result.add(`${job.request.source_run_id}/${job.request.source_epoch}/${robot.carried_unit_id}`);
    for(const scope of Object.values(fleet?.snapshot?.run.sources??{}))
      result.add(`${scope.run_id}/${scope.epoch}/${robot.carried_unit_id}`);
  }
  return result;
}
