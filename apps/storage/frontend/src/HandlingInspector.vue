<script setup lang="ts">
import {computed,ref} from 'vue'

type UnitRecord={id:string,barcode:string,owner:string,category:string,state:string,position:string|null,origin:string|null,destination:string|null,handoff_id:string|null,version:number,custody_generation:number,last_sequence:number,contents:{sku:string,quantity:number}[]}
type Movement={id:string,unit_id:string,sequence:number,simulation_time:number,action:string,origin:string|null,destination:string|null,correlation_id:string,references:Record<string,string|null>}
type Handoff={id:string,unit:UnitRecord,state:string,source:string,destination_owner:string,origin:string,destination:string,receipt_id:string|null,reason?:string|null}
type Quarantine={id:string,event_id:string,endpoint:string,phase:string,reason:string,simulation_time:number,envelope:unknown}
export type HandlingSnapshot={version:number,catalog_version:number,units:UnitRecord[],movements:Movement[],handoffs:Handoff[],quarantine:Quarantine[],legacy_stock:{sku:string,location:string,unplaced_quantity:number}[],lineage:{id:string,batch_id:string,input_unit_ids:string[],output_unit_ids:string[],scrap_quantity:number}[]}

const props=defineProps<{handling?:HandlingSnapshot}>()
const query=ref(''),selected=ref('')
const units=computed(()=>props.handling?.units.filter(unit=>[unit.id,unit.barcode,...unit.contents.map(item=>item.sku),unit.position??'',unit.destination??''].join(' ').toLowerCase().includes(query.value.trim().toLowerCase()))??[])
const detail=computed(()=>props.handling?.units.find(unit=>unit.id===selected.value))
const history=computed(()=>props.handling?.movements.filter(move=>move.unit_id===selected.value)??[])
const handoffs=computed(()=>props.handling?.handoffs.filter(h=>h.unit.id===selected.value)??[])
const promises=computed(()=>props.handling?.handoffs.filter(h=>['offered','accepted'].includes(h.state))??[])
const lineage=computed(()=>props.handling?.lineage.filter(row=>row.input_unit_ids.includes(selected.value)||row.output_unit_ids.includes(selected.value))??[])
function custody(unit:UnitRecord){return unit.state==='in_transit'?'Destination receipt unconfirmed':unit.state==='dispatched'?'Custody transferred; historical record':unit.state==='consumed'?'Consumed in production':'Recorded by '+unit.owner}
function formatEvidence(value:unknown){return JSON.stringify(value,null,2)}
</script>

<template>
  <section class="unit-inspector" aria-labelledby="unit-inspector-title">
    <div class="section-heading"><h2 id="unit-inspector-title">Handling units</h2><label class="search">Find a handling unit<input data-unit-search type="search" v-model="query" placeholder="Barcode, SKU or exact position"></label></div>
    <p class="muted">Recorded Storage custody. A destination becomes confirmed only when its department records receipt.</p>
    <template v-if="handling">
      <div class="table-scroll"><table data-unit-list><thead><tr><th>Barcode / contents</th><th>State</th><th>Confirmed position</th><th>Inspection</th></tr></thead><tbody>
        <tr v-for="unit in units" :key="unit.id" :class="{selected:unit.id===selected}"><td><code>{{unit.barcode}}</code><small v-for="item in unit.contents" :key="item.sku">{{item.sku}} · {{item.quantity}} items</small></td><td>{{unit.state}}</td><td>{{unit.position||'No confirmed position'}}</td><td><button data-inspect-unit :aria-label="'Inspect '+unit.barcode" :aria-expanded="selected===unit.id" :aria-controls="selected===unit.id?'unit-detail':undefined" @click="selected=unit.id">Inspect</button></td></tr>
        <tr v-if="!units.length"><td colspan="4">{{query?'No handling units match this search.':'No handling units recorded in this run. Plan and confirm a receipt to create one.'}}</td></tr>
      </tbody></table></div>
      <article v-if="detail" id="unit-detail" data-unit-detail class="unit-detail" aria-labelledby="unit-detail-title">
        <div class="section-heading"><h3 id="unit-detail-title">{{detail.barcode}}</h3><button @click="selected=''">Close inspection</button></div>
        <p class="custody-status">{{custody(detail)}}</p>
        <dl class="unit-facts"><dt>Unit ID</dt><dd>{{detail.id}}</dd><dt>Contents</dt><dd><span v-for="item in detail.contents" :key="item.sku">{{item.sku}} · {{item.quantity}} items</span></dd><dt>Category / state</dt><dd>{{detail.category}} / {{detail.state}}</dd><dt>Confirmed position</dt><dd>{{detail.position||'No confirmed position'}}</dd><dt>Origin</dt><dd>{{detail.origin||'Not recorded'}}</dd><dt>Destination</dt><dd>{{detail.destination||'Not recorded'}}</dd><dt>Custody generation / version</dt><dd>{{detail.custody_generation}} / {{detail.version}}</dd><dt>Last movement sequence</dt><dd>{{detail.last_sequence}}</dd></dl>
        <h4>Custody evidence</h4>
        <div v-for="handoff in handoffs" :key="handoff.id" class="custody-evidence"><p>{{handoff.source}} → {{handoff.destination_owner}} · {{handoff.state}}</p><p>{{handoff.origin}} → {{handoff.destination}}</p><p>Handoff <code>{{handoff.id}}</code></p><p>Receipt: {{handoff.receipt_id||'Not confirmed'}}</p><p v-if="handoff.reason">{{handoff.reason}}</p></div>
        <p v-if="!handoffs.length" class="muted">No cross-department handoff recorded for this unit.</p>
        <h4>Movement history</h4>
        <div class="table-scroll"><table><thead><tr><th>Sequence / time</th><th>Action / route</th><th>References</th></tr></thead><tbody><tr v-for="move in history" :key="move.id"><td>{{move.sequence}} · {{move.simulation_time}} s</td><td>{{move.action}}<small>{{move.origin||'Unplaced'}} → {{move.destination||'Unplaced'}}</small></td><td><small>Correlation: {{move.correlation_id}}</small><template v-for="(value,key) in move.references" :key="key"><small v-if="value">{{key}}: {{value}}</small></template></td></tr><tr v-if="!history.length"><td colspan="3">No movement history recorded.</td></tr></tbody></table></div>
        <h4>Production lineage</h4><div v-for="row in lineage" :key="row.id"><p>Batch {{row.batch_id}} · Scrap: {{row.scrap_quantity}}</p><p>Inputs: {{row.input_unit_ids.join(', ')}}</p><p>Outputs: {{row.output_unit_ids.join(', ')}}</p></div><p v-if="!lineage.length" class="muted">No production lineage recorded by Storage. Inspect the batch in Manufacturing for its production records.</p>
      </article>
      <details v-if="promises.length" class="unit-evidence"><summary>Pending capacity and custody · {{promises.length}}</summary><p class="muted">Acceptance reserves an endpoint. It does not confirm that goods have arrived.</p><div v-for="handoff in promises" :key="handoff.id"><p><code>{{handoff.unit.barcode}}</code> · {{handoff.state}} · {{handoff.source}} → {{handoff.destination_owner}}</p><p>{{handoff.destination}}</p></div></details>
      <div v-if="handling.legacy_stock.length" class="legacy-units"><h3>Conversion required</h3><p class="muted">These quantities have no reconciled handling-unit placement. An operator must submit an explicit whole-unit conversion manifest before allocation.</p><div class="table-scroll"><table><thead><tr><th>SKU</th><th>Logical location</th><th>Unplaced quantity</th></tr></thead><tbody><tr v-for="row in handling.legacy_stock" :key="row.sku+row.location"><td>{{row.sku}}</td><td>{{row.location}}</td><td>{{row.unplaced_quantity}}</td></tr></tbody></table></div></div>
      <div class="quarantine-cases"><h3>Quarantined custody evidence</h3><p class="muted">Rejected proofs remain available for reconciliation. They do not establish receipt or change stock.</p><details v-for="record in handling.quarantine" :key="record.id" data-quarantine-evidence><summary>{{record.reason}} · {{record.simulation_time}} s</summary><dl class="unit-facts"><dt>Peer endpoint</dt><dd>{{record.endpoint||'Not recorded'}}</dd><dt>Phase</dt><dd>{{record.phase}}</dd><dt>Event ID</dt><dd>{{record.event_id}}</dd></dl><pre tabindex="0" aria-label="Original rejected custody envelope">{{formatEvidence(record.envelope)}}</pre></details><p v-if="!handling.quarantine.length" class="muted">No quarantined evidence in this run.</p></div>
    </template>
    <p v-else role="status" class="muted">Handling-unit records are unavailable in this warehouse snapshot. Refresh to load current records.</p>
  </section>
</template>

<style scoped>
.unit-inspector{min-width:0}.unit-detail{margin-top:24px;padding:24px;background:#171912;overflow-wrap:anywhere}.unit-detail h3,.legacy-units h3,.quarantine-cases h3{font-size:15px;letter-spacing:normal;color:#deded6}.unit-detail h4{font-size:13px;font-weight:500;margin:28px 0 12px}.unit-facts{grid-template-columns:minmax(140px,1fr) minmax(0,2fr);gap:10px 24px;max-width:900px}.unit-facts dd{text-align:left;overflow-wrap:anywhere}.unit-facts dd span{display:block}.custody-status{font-size:13px;color:#ffb800}.custody-evidence{padding:12px 0;border-top:1px solid #383a30}.custody-evidence p,.unit-evidence p{font-size:12px;margin:5px 0}.selected{background:#171912}.legacy-units,.quarantine-cases{margin-top:32px}.quarantine-cases details{border-top:1px solid #383a30}.quarantine-cases summary{color:#deded6;overflow-wrap:anywhere}.quarantine-cases pre{font-size:11px;max-height:360px;overflow:auto;padding:16px;background:#171912;white-space:pre-wrap;overflow-wrap:anywhere}.unit-inspector summary:focus-visible,.unit-inspector pre:focus-visible{outline:2px solid #ffb800;outline-offset:4px}@media(max-width:600px){.unit-detail{padding:16px}.unit-facts{grid-template-columns:1fr;gap:4px}.unit-facts dd{margin-bottom:12px}.unit-detail .section-heading h3{overflow-wrap:anywhere}}
</style>
