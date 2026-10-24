export interface HandlingUnit {id:string;barcode:string;owner:string;category:string;state:string;position:string|null;origin:string|null;destination:string|null;handoff_id:string|null;version:number;custody_generation:number;last_sequence:number;contents:{sku:string;quantity:number}[];}
export interface UnitMovement {id:string;unit_id:string;sequence:number;simulation_time:number;action:string;origin:string|null;destination:string|null;correlation_id?:string;references:Record<string,string|null>;}
export interface UnitLineage {id:string;batch_id:string;input_unit_ids:string[];output_unit_ids:string[];batch_quantity:number;output_quantity:number;scrap_quantity:number;recipe:Record<string,number>;simulation_time:number;}
export interface UnitHandoff {id:string;unit:HandlingUnit;state:string;source:string;destination_owner:string;origin:string;destination:string;receipt_id:string|null;reason?:string|null;}
export interface HandlingSnapshot {version:number;catalog_version:number;units:HandlingUnit[];movements:UnitMovement[];lineage:UnitLineage[];handoffs:UnitHandoff[];legacy_stock:{sku:string;unplaced_quantity:number}[];quarantine:{id:string;event_id:string;endpoint:string;phase:string;reason:string;simulation_time:number;envelope:unknown}[];}
export interface UnitEvidence {unit:HandlingUnit;movements:UnitMovement[];lineage:UnitLineage[];handoffs:UnitHandoff[];}

export function matchingUnits(snapshot:HandlingSnapshot, query:string):HandlingUnit[]{
 const term=query.trim().toLowerCase();
 return snapshot.units.filter(unit=>[unit.id,unit.barcode,unit.position??'',unit.destination??'',...unit.contents.map(item=>item.sku)].join(' ').toLowerCase().includes(term));
}
export function unitEvidence(snapshot:HandlingSnapshot, unitId:string):UnitEvidence|null{
 const unit=snapshot.units.find(row=>row.id===unitId);if(!unit)return null;
 return {unit,movements:snapshot.movements.filter(row=>row.unit_id===unitId),lineage:snapshot.lineage.filter(row=>row.input_unit_ids.includes(unitId)||row.output_unit_ids.includes(unitId)),handoffs:snapshot.handoffs.filter(row=>row.unit.id===unitId)};
}
