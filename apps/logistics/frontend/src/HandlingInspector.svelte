<script lang="ts">
 import {findTransportUnits,transportEvidence,type TransportHandling} from './inspection.ts';
 let {handling}:{handling?:TransportHandling}=$props();
 let query=$state(''),selected=$state('');
 const units=$derived(handling?findTransportUnits(handling,query):[]);
 const detail=$derived(handling?transportEvidence(handling,selected):null);
 const promises=$derived(handling?.handoffs.filter(row=>['offered','accepted'].includes(row.state))??[]);
 function custody(state:string){return state==='in_transit'?'Destination receipt unconfirmed':state==='dispatched'?'Custody transferred; historical record':'Recorded by Logistics'}
</script>

<section class="unit-inspector" aria-labelledby="transport-handling-title">
 <div class="section-title"><h2 id="transport-handling-title">Handling units</h2><label>Find a handling unit<input type="search" bind:value={query} placeholder="Barcode, SKU or exact position" /></label></div>
 <p>Recorded Logistics custody. Logical locations group goods; a confirmed physical slot is shown separately.</p>
 {#if handling}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex (This overflow region needs keyboard focus for scrolling.) -->
  <div class="table-wrap unit-list-scroll" role="region" aria-label="Handling-unit records" tabindex="0"><table data-unit-list><thead><tr><th>Barcode / contents</th><th>State</th><th>Confirmed position</th><th>Inspection</th></tr></thead><tbody>
   {#each units as unit (unit.id)}<tr class:selected-unit={unit.id===selected}><td><code>{unit.barcode}</code>{#each unit.contents as item}<small>{item.sku} · {item.quantity} items</small>{/each}</td><td>{unit.state}</td><td>{unit.position??'No confirmed position'}</td><td><button aria-label={'Inspect '+unit.barcode} aria-expanded={selected===unit.id} aria-controls={selected===unit.id?'transport-unit-detail':undefined} onclick={()=>selected=unit.id}>Inspect</button></td></tr>
   {:else}<tr><td colspan="4">{query?'No handling units match this search.':'No handling units recorded. Receive a whole-unit manifest before requesting transport.'}</td></tr>{/each}
  </tbody></table></div>
  {#if detail}
   <article id="transport-unit-detail" data-unit-detail class="unit-detail" aria-labelledby="transport-unit-title">
    <div class="section-title"><h3 id="transport-unit-title">{detail.unit.barcode}</h3><button onclick={()=>selected=''}>Close inspection</button></div>
    <p class="custody-status">{custody(detail.unit.state)}</p>
    <dl><dt>Unit ID</dt><dd>{detail.unit.id}</dd><dt>Contents</dt><dd>{#each detail.unit.contents as item}<span>{item.sku} · {item.quantity} items</span>{/each}</dd><dt>Category / state</dt><dd>{detail.unit.category} / {detail.unit.state}</dd><dt>Confirmed position</dt><dd>{detail.unit.position??'No confirmed position'}</dd><dt>Logical location</dt><dd>{detail.context?.logical_location??'Not recorded'}</dd><dt>Origin</dt><dd>{detail.unit.origin??'Not recorded'}</dd><dt>Destination</dt><dd>{detail.unit.destination??'Not recorded'}</dd><dt>Transfer reference</dt><dd>{detail.context?.transfer_id??'Not recorded'}</dd><dt>Custody generation / version</dt><dd>{detail.unit.custody_generation} / {detail.unit.version}</dd><dt>Last movement sequence</dt><dd>{detail.unit.last_sequence}</dd></dl>
    <h4>Custody evidence</h4>
    {#each detail.handoffs as handoff (handoff.id)}<div class="custody-record"><p>{handoff.source} → {handoff.destination_owner} · {handoff.state}</p><p>{handoff.origin} → {handoff.destination}</p><p>Handoff <code>{handoff.id}</code></p><p>Receipt: {handoff.receipt_id??'Not confirmed'}</p>{#if handoff.reason}<p>{handoff.reason}</p>{/if}</div>{:else}<p>No cross-department handoff recorded for this unit.</p>{/each}
    <h4>Movement history</h4><div class="table-wrap"><table><thead><tr><th>Sequence / time</th><th>Action / route</th><th>References</th></tr></thead><tbody>{#each detail.movements as move (move.id)}<tr><td>{move.sequence} · {move.simulation_time} s</td><td>{move.action}<small>{move.origin??'Unplaced'} → {move.destination??'Unplaced'}</small></td><td><small>Correlation: {move.correlation_id}</small>{#each Object.entries(move.references) as [key,value]}{#if value}<small>{key}: {value}</small>{/if}{/each}</td></tr>{:else}<tr><td colspan="3">No movement history recorded.</td></tr>{/each}</tbody></table></div>
    <p>Production lineage is recorded by Manufacturing. Transfer and shipment references above link this unit to its transport history.</p>
   </article>
  {/if}
  {#if promises.length}<details><summary>Pending capacity and custody · {promises.length}</summary><p>Accepted endpoints reserve capacity. They do not confirm arrival.</p>{#each promises as handoff (handoff.id)}<p><code>{handoff.unit.barcode}</code> · {handoff.state} · {handoff.source} → {handoff.destination_owner}</p><p>{handoff.destination}</p>{/each}</details>{/if}
  <div class="quarantine-cases"><h3>Quarantined custody evidence</h3><p>Rejected proofs remain available for reconciliation. They do not establish receipt or change stock.</p>{#each handling.quarantine as record (record.id)}<details><summary>{record.reason} · {record.simulation_time} s</summary><dl><dt>Peer endpoint</dt><dd>{record.endpoint||'Not recorded'}</dd><dt>Phase</dt><dd>{record.phase}</dd><dt>Event ID</dt><dd>{record.event_id}</dd></dl>
<!-- svelte-ignore a11y_no_noninteractive_tabindex (The original envelope is a scrollable document for keyboard readers.) -->
<pre tabindex="0" aria-label="Original rejected custody envelope">{JSON.stringify(record.envelope,null,2)}</pre></details>{:else}<p>No quarantined evidence in this run.</p>{/each}</div>
 {:else}<p role="status">Handling-unit records are unavailable. Refresh transport records to load current data.</p>{/if}
</section>

<style>
 .unit-inspector{min-width:0}.unit-inspector>.section-title>label{width:min(100%,380px)}.unit-list-scroll{max-height:340px}.unit-inspector small{display:block;font-size:11px;white-space:normal;overflow-wrap:anywhere}.unit-detail{padding:24px;background:#171912;margin-top:24px;overflow-wrap:anywhere}.unit-inspector h3{font-size:15px;font-weight:500;margin:0}.unit-detail h4{font-size:13px;font-weight:500;margin:28px 0 12px}.unit-detail dd span{display:block}.unit-detail dl{grid-template-columns:minmax(140px,1fr) minmax(0,2fr);max-width:900px}.unit-detail .custody-status{color:#ffb800}.selected-unit{background:#171912}.custody-record{border-top:1px solid #46483d;padding:12px 0}.custody-record p{margin:5px 0}.quarantine-cases{margin-top:28px}.quarantine-cases pre{max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;background:#171912;padding:16px}.unit-inspector summary:focus-visible,.unit-inspector pre:focus-visible,.unit-list-scroll:focus-visible{outline:2px solid #ffb800;outline-offset:3px}@media(max-width:600px){.unit-detail>.section-title{flex-direction:column;align-items:flex-start}.unit-inspector>.section-title{flex-direction:column;align-items:stretch}.unit-inspector>.section-title>label{width:100%}.unit-detail{padding:16px}.unit-detail dl{grid-template-columns:1fr}.unit-detail dd{margin-bottom:12px}}
</style>
