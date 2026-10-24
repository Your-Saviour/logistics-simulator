import type {TransportUnit,UnitContext} from './handling.ts';

export type RecordedUnit=TransportUnit&{barcode:string;owner:string;category:string;position:string|null;origin:string|null;destination:string|null;handoff_id:string|null;version:number;custody_generation:number;last_sequence:number};
export type RecordedMovement={id:string;unit_id:string;sequence:number;action:string;origin:string|null;destination:string|null;simulation_time:number;correlation_id:string;references:Record<string,string|null>};
export type RecordedHandoff={id:string;unit:RecordedUnit;state:string;source:string;destination_owner:string;origin:string;destination:string;receipt_id:string|null;reason?:string|null};
export type TransportHandling={version:number;catalog_version:number;units:RecordedUnit[];unit_context:(UnitContext&{transfer_id?:string|null})[];movements:RecordedMovement[];handoffs:RecordedHandoff[];quarantine:{id:string;event_id:string;endpoint:string;phase:string;reason:string;simulation_time:number;envelope:unknown}[]};
export type TransportEvidence={unit:RecordedUnit;context:TransportHandling['unit_context'][number]|undefined;movements:RecordedMovement[];handoffs:RecordedHandoff[]};
export function findTransportUnits(handling:TransportHandling,query:string):RecordedUnit[]{
 const term=query.trim().toLowerCase(),locations=new Map(handling.unit_context.map(row=>[row.unit_id,row.logical_location]));
 return handling.units.filter(unit=>[unit.id,unit.barcode,unit.position??'',unit.destination??'',locations.get(unit.id)??'',...unit.contents.map(item=>item.sku)].join(' ').toLowerCase().includes(term));
}
export function transportEvidence(handling:TransportHandling,id:string):TransportEvidence|null{
 const unit=handling.units.find(row=>row.id===id);if(!unit)return null;
 return {unit,context:handling.unit_context.find(row=>row.unit_id===id),movements:handling.movements.filter(row=>row.unit_id===id),handoffs:handling.handoffs.filter(row=>row.unit.id===id)};
}
