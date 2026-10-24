import {Component,Input,type OnChanges,type SimpleChanges} from '@angular/core';
import {CommonModule} from '@angular/common';
import {FormsModule} from '@angular/forms';
import {matchingUnits,unitEvidence,type HandlingSnapshot,type HandlingUnit} from './handling';

@Component({selector:'handling-inspector',standalone:true,imports:[CommonModule,FormsModule],template:`
<section class="handling-inspector" aria-labelledby="handling-title">
 <div class="section-heading"><h2 id="handling-title">Handling units</h2><label>Find a handling unit<input type="search" name="unitSearch" [(ngModel)]="query" placeholder="Barcode, SKU or exact position"></label></div>
 <p class="note">Recorded Manufacturing custody, consumption and output. Destination receipt requires evidence from the receiving department.</p>
 @if(handling;as h){
  <div class="table-wrap unit-list-scroll" tabindex="0" role="region" aria-label="Handling-unit records"><table data-unit-list><thead><tr><th>Barcode / contents</th><th>State</th><th>Confirmed position</th><th>Inspection</th></tr></thead><tbody>
   @for(unit of matching();track unit.id){<tr [class.selected-unit]="unit.id===selected"><td><code>{{unit.barcode}}</code>@for(item of unit.contents;track item.sku){<small>{{item.sku}} · {{item.quantity}} items</small>}</td><td>{{unit.state}}</td><td>{{unit.position||'No confirmed position'}}</td><td><button [attr.aria-label]="'Inspect '+unit.barcode" [attr.aria-expanded]="selected===unit.id" [attr.aria-controls]="selected===unit.id?'manufacturing-unit-detail':null" (click)="select(unit.id)">Inspect</button></td></tr>}
   @empty{<tr><td colspan="4">{{query?'No handling units match this search.':'No handling units recorded. Receive whole materials or complete a batch to create records.'}}</td></tr>}
  </tbody></table></div>
  @if(detail();as d){
   <article id="manufacturing-unit-detail" data-unit-detail class="handling-detail" aria-labelledby="handling-detail-title">
    <div class="section-heading"><h3 id="handling-detail-title">{{d.unit.barcode}}</h3><button (click)="selected=''">Close inspection</button></div>
    <p class="custody-status">{{custody(d.unit)}}</p>
    <dl class="handling-facts"><dt>Unit ID</dt><dd>{{d.unit.id}}</dd><dt>Contents</dt><dd>@for(item of d.unit.contents;track item.sku){<span>{{item.sku}} · {{item.quantity}} items</span>}</dd><dt>Category / state</dt><dd>{{d.unit.category}} / {{d.unit.state}}</dd><dt>Confirmed position</dt><dd>{{d.unit.position||'No confirmed position'}}</dd><dt>Origin</dt><dd>{{d.unit.origin||'Not recorded'}}</dd><dt>Destination</dt><dd>{{d.unit.destination||'Not recorded'}}</dd><dt>Custody generation / version</dt><dd>{{d.unit.custody_generation}} / {{d.unit.version}}</dd><dt>Last movement sequence</dt><dd>{{d.unit.last_sequence}}</dd></dl>
    <h4>Production lineage</h4>
    @for(row of d.lineage;track row.id){<div class="lineage-record" data-unit-lineage><p>Batch <code>{{row.batch_id}}</code> · {{row.simulation_time}} s</p><p>Batch quantity: {{row.batch_quantity}} · Good output: {{row.output_quantity}} · Scrap: {{row.scrap_quantity}}</p><h5>Whole inputs</h5>@for(id of row.input_unit_ids;track id){<p><button class="unit-reference" (click)="select(id,true)">{{barcode(id)}}</button></p>}<h5>Fresh outputs</h5>@for(id of row.output_unit_ids;track id){<p><button class="unit-reference" (click)="select(id,true)">{{barcode(id)}}</button></p>}@empty{<p>No good output was created.</p>}<p>Recipe per item: @for(item of row.recipe | keyvalue;track item.key){<span>{{item.key}} × {{item.value}} </span>}</p></div>}
    @empty{<p class="note">No production lineage recorded for this unit.</p>}
    <h4>Custody evidence</h4>
    @for(handoff of d.handoffs;track handoff.id){<div class="custody-record"><p>{{handoff.source}} → {{handoff.destination_owner}} · {{handoff.state}}</p><p>{{handoff.origin}} → {{handoff.destination}}</p><p>Handoff <code>{{handoff.id}}</code></p><p>Receipt: {{handoff.receipt_id||'Not confirmed'}}</p>@if(handoff.reason){<p>{{handoff.reason}}</p>}</div>}
    @empty{<p class="note">No cross-department handoff recorded for this unit.</p>}
    <h4>Movement history</h4><div class="table-wrap"><table><thead><tr><th>Sequence / time</th><th>Action / route</th><th>References</th></tr></thead><tbody>@for(move of d.movements;track move.id){<tr><td>{{move.sequence}} · {{move.simulation_time}} s</td><td>{{move.action}}<small>{{move.origin||'Unplaced'}} → {{move.destination||'Unplaced'}}</small></td><td>@if(move.correlation_id){<small>Correlation: {{move.correlation_id}}</small>}@for(ref of move.references | keyvalue;track ref.key){@if(ref.value){<small>{{ref.key}}: {{ref.value}}</small>}}</td></tr>}@empty{<tr><td colspan="3">No movement history recorded.</td></tr>}</tbody></table></div>
   </article>
  }
  @if(promises().length){<details class="handling-evidence"><summary>Pending capacity and custody · {{promises().length}}</summary><p class="note">Accepted endpoints reserve capacity; they do not establish receipt.</p>@for(handoff of promises();track handoff.id){<p><code>{{handoff.unit.barcode}}</code> · {{handoff.state}} · {{handoff.source}} → {{handoff.destination_owner}}</p><p>{{handoff.destination}}</p>}</details>}
  @if(h.legacy_stock.length){<div class="legacy-handling"><h3>Conversion required</h3><p class="note">An operator must reconcile these unplaced materials with an explicit whole-unit conversion manifest before use.</p>@for(row of h.legacy_stock;track row.sku){<p>{{row.sku}} · {{row.unplaced_quantity}} unplaced items</p>}</div>}
  <div class="handling-quarantine"><h3>Quarantined custody evidence</h3><p class="note">Rejected proofs remain available for reconciliation. They do not establish receipt or change stock.</p>@for(record of h.quarantine;track record.id){<details><summary>{{record.reason}} · {{record.simulation_time}} s</summary><dl class="handling-facts"><dt>Peer endpoint</dt><dd>{{record.endpoint||'Not recorded'}}</dd><dt>Phase</dt><dd>{{record.phase}}</dd><dt>Event ID</dt><dd>{{record.event_id}}</dd></dl><pre tabindex="0" aria-label="Original rejected custody envelope">{{record.envelope | json}}</pre></details>}@empty{<p class="note">No quarantined evidence in this run.</p>}</div>
 }@else{<p class="note" role="status">Handling-unit records are unavailable. Refresh the production board to load current records.</p>}
</section>
`})
export class HandlingInspector implements OnChanges {
 @Input() handling?:HandlingSnapshot;
 @Input() runKey='';
 query='';selected='';
 ngOnChanges(changes:SimpleChanges){if(changes['runKey']){this.query='';this.selected='';}}
 matching(){return this.handling?matchingUnits(this.handling,this.query):[];}
 detail(){return this.handling?unitEvidence(this.handling,this.selected):null;}
 promises(){return this.handling?.handoffs.filter(row=>['offered','accepted'].includes(row.state))??[];}
 select(id:string,reveal=false){this.selected=id;if(reveal)this.query='';}
 barcode(id:string){return this.handling?.units.find(row=>row.id===id)?.barcode??id;}
 custody(unit:HandlingUnit){return unit.state==='consumed'?'Consumed in production':unit.state==='in_transit'?'Destination receipt unconfirmed':unit.state==='dispatched'?'Custody transferred; historical record':'Recorded by Manufacturing';}
}
