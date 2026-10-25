import {endpoint,type RecordedUnit} from './facility';
type Row=Record<string,unknown>;
type Source={name:string;connected:boolean;stale:boolean;status:{run:{id:string;epoch:string;state:string}}|null;snapshot:Row|null};
type Event={id:string;source:string;run_id:string;epoch:string;simulation_time?:number;payload:Row};
type Props={unit:RecordedUnit;units:RecordedUnit[];sources:Source[];events:Event[];lost:boolean;choose:(unit:RecordedUnit)=>void};
const object=(value:unknown):Row=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Row:{};
const rows=(value:unknown):Row[]=>Array.isArray(value)?value.map(object):[];
const text=(value:unknown)=>value===null||value===undefined?'Unavailable':String(value);
export default function HandlingInspector({unit,units,sources,events,lost,choose}:Props){
 const source=sources.find(source=>source.name===unit.owner);
 const freshness=lost||!unit.connected||source?.stale||source?.connected===false?'Last recorded state · source unavailable':source?.status?.run.state==='held'?'Source held · recorded state':'Recorded source state';
 const records=sources.flatMap(source=>{
  const handling=object(source.snapshot?.handling);
  return ['handoffs','lineage'].flatMap(kind=>rows(handling[kind]).filter(row=>row.run_id===unit.run_id&&row.epoch===unit.epoch).map(row=>({source:source.name,kind,row})));
 });
 const pending=records.filter(record=>record.kind==='handoffs'&&object(record.row.unit).id===unit.id&&!['acknowledged'].includes(text(record.row.state)));
 const lineage=records.filter(record=>record.kind==='lineage'&&[...Array.isArray(record.row.input_unit_ids)?record.row.input_unit_ids:[],...Array.isArray(record.row.output_unit_ids)?record.row.output_unit_ids:[]].includes(unit.id));
 const history=events.filter(event=>event.run_id===unit.run_id&&event.epoch===unit.epoch&&event.payload.unit_id===unit.id&&event.id.startsWith(event.source+':unit-movement:')).sort((a,b)=>Number(a.payload.sequence)-Number(b.payload.sequence)||a.source.localeCompare(b.source));
 function lineageUnits(ids:unknown,direction:'input'|'output'){
  return (Array.isArray(ids)?ids:[]).map(id=>{
   const related=units.find(record=>record.id===id&&record.run_id===unit.run_id&&record.epoch===unit.epoch);
   return <li key={String(id)}>{related?<button type="button" aria-label={`Inspect ${direction} ${related.barcode}`} onClick={()=>choose(related)}>{related.barcode}</button>:<code>{String(id)} · unit record unavailable</code>}</li>;
  });
 }
 return <section className="handling-inspector" aria-label="Recorded handling unit">
  <p className="badge">{freshness}</p>
  <dl className="record-fields">
   <div><dt>Barcode</dt><dd><code>{unit.barcode}</code></dd></div>
   <div><dt>Recorded state</dt><dd>{unit.state??'Unresolved'}</dd></div>
   <div><dt>Current custodian</dt><dd>{unit.owner??'Unresolved'}</dd></div>
   <div><dt>Custody generation</dt><dd>{unit.custody_generation??'Unavailable'}</dd></div>
   <div><dt>Confirmed position</dt><dd>{unit.status==='conflict'?'Custody disputed':unit.status==='unobserved'?'Custodian record unavailable':unit.position?<><code>{unit.position}</code>{!endpoint(unit.position)&&<span className="note">Unmapped endpoint · no 3D placement</span>}</>:'No confirmed position'}</dd></div>
  </dl>
  <h3>Contents</h3><table><thead><tr><th>SKU</th><th>Quantity</th></tr></thead><tbody>{unit.contents.map(content=><tr key={content.sku}><td>{content.sku}</td><td>{content.quantity}</td></tr>)}</tbody></table>
  {!!unit.conflicts?.length&&<><h3>Custody conflicts</h3><ul>{unit.conflicts.map((conflict,index)=><li key={index}>{text(conflict.reason??'Immutable manifest conflict')}</li>)}</ul></>}
  <h3>Pending custody</h3>
  {pending.length?<ul className="handling-records">{pending.map(({source,row})=><li key={source+':'+text(row.id)}><strong>{source} · {text(row.state)}</strong><span>Intended destination: <code>{text(row.destination)}</code></span><small>Handoff {text(row.id)} · generation {text(object(row.unit).custody_generation)}</small></li>)}</ul>:<p className="note">No unsettled handoff in received records.</p>}
  <p className="note">An accepted destination reserves capacity. It does not confirm arrival or change recorded stock.</p>
  <h3>Movement history</h3>
  {history.length?<ol className="handling-records">{history.map(event=><li key={event.source+':'+event.id}><strong>Sequence {text(event.payload.sequence)} · {text(event.payload.action)}</strong><span>{event.source} · simulation time {text(event.simulation_time??event.payload.simulation_time)} s</span><code>{text(event.payload.origin)} → {text(event.payload.destination)}</code></li>)}</ol>:<p className="note">No durable movements in received records.</p>}
  <h3>Manufacturing lineage</h3>
  {lineage.length?lineage.map(({source,row})=><div className="handling-lineage" key={source+':'+text(row.id)}><p>Batch <code>{text(row.batch_id)}</code> · output quantity {text(row.batch_quantity)}</p><h4>Inputs</h4><ul>{lineageUnits(row.input_unit_ids,'input')}</ul><h4>Outputs</h4><ul>{lineageUnits(row.output_unit_ids,'output')}</ul><details><summary>Recorded recipe</summary><dl className="record-fields">{Object.entries(object(row.recipe)).map(([sku,quantity])=><div key={sku}><dt>{sku}</dt><dd>{text(quantity)} per output</dd></div>)}</dl></details></div>):<p className="note">No manufacturing lineage in received records.</p>}
  <details><summary>Retained departmental records</summary>{unit.observations.map(observation=><div key={observation.source}><p>{observation.source} · {text(observation.unit.state)}</p><p className="note">Historical local position: <code>{text(observation.unit.position)}</code></p></div>)}</details>
 </section>;
}
