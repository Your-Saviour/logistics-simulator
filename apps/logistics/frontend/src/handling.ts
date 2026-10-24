export type TransportUnit={id:string;state:string;contents:{sku:string;quantity:number}[]};
export type UnitContext={unit_id:string;logical_location:string};

/** Select complete units only. The backend rechecks allocation under its run lock. */
export function selectTransportUnits(units:TransportUnit[],context:UnitContext[],sku:string,quantity:number,origin:string):string[]{
 if(!Number.isInteger(quantity)||quantity<1||quantity>10000)throw new Error('Enter a positive whole-unit load quantity.');
 const locations=new Map(context.map(row=>[row.unit_id,row.logical_location]));
 const paths=new Map<number,string[]>([[0,[]]]);
 for(const unit of [...units].sort((a,b)=>a.id.localeCompare(b.id))){
  if(unit.state!=='available'||locations.get(unit.id)!==origin||unit.contents.length!==1||unit.contents[0].sku!==sku)continue;
  const amount=unit.contents[0].quantity;
  if(!Number.isInteger(amount)||amount<1)throw new Error('Handling-unit contents are unavailable. Refresh before requesting transport.');
  for(const [total,ids] of [...paths]){
   const next=total+amount;if(next>quantity||paths.has(next))continue;
   const selected=[...ids,unit.id];if(next===quantity)return selected;paths.set(next,selected);
  }
 }
 throw new Error('No exact available whole-unit load at this origin. Units cannot be split or overfulfilled.');
}
