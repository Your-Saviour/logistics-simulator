<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
type Stock={sku:string,location:string,on_hand:number,reserved:number,available:number,kind:string}
type Work={id:string,sku:string,location:string,quantity:number,correlation_id:string,status:string,purpose?:string,origin?:string,destination?:string}
type Command={id:string,command:{action:string,reference?:string},status:string,error?:string,due_at:number,job_status?:string}
type Snapshot={run_id:string,epoch:string,inventory:Stock[],locations:{code:string,capacity:number,used:number}[],receipts:Work[],reservations:Work[],transfers:Work[],commands:Command[],movements:{id:string,action:string,sku:string,location:string,on_hand_delta:number,reserved_delta:number,quantity:number,correlation_id:string,simulation_time:number}[]}
const props=defineProps<{api:(path:string,body?:unknown,key?:string)=>Promise<any>,run:{id:string,epoch:string,granted:number,requested:number,state:string},quantum:number,canWrite:boolean}>()
const snapshot=ref<Snapshot|null>(null),search=ref(''),error=ref(''),loadError=ref(''),busy=ref(false),notice=ref('')
const workflowStatus=ref('all'),workSearch=ref('')
const sku=ref(''),location=ref(''),quantity=ref(1),purpose=ref('customer'),correlation=ref(crypto.randomUUID()),action=ref('expect')
const destinations=ref<Record<string,string>>({})
const pending=ref<{body:unknown,key:string}|null>(null)
const filtered=computed(()=>snapshot.value?.inventory.filter(row=>(row.sku+' '+row.location).toLowerCase().includes(search.value.toLowerCase()))??[])
const products=computed(()=>[...new Set(snapshot.value?.inventory.map(x=>x.sku)??[])])
const active=computed(()=>['running','held'].includes(props.run.state))
let timer:ReturnType<typeof setInterval>|undefined,loading=false,disposed=false
async function refresh(){if(loading)return;loading=true;try{const value:Snapshot=await props.api('warehouse');if(!disposed&&value.run_id===props.run.id&&value.epoch===props.run.epoch){snapshot.value=value;loadError.value='';if(!sku.value)sku.value=products.value[0]??'';if(!location.value)location.value=value.locations[0]?.code??''}}catch(e){if(!disposed)loadError.value=(e as Error).message}finally{loading=false}}
function tasks(rows:Work[]){return rows.filter(row=>(workflowStatus.value==='all'||row.status===workflowStatus.value)&&[row.id,row.sku,row.correlation_id,row.location,row.origin,row.destination].join(' ').toLowerCase().includes(workSearch.value.toLowerCase()))}
function waiting(reference:string){return snapshot.value?.commands.some(c=>c.command.reference===reference&&c.status==='pending')}
async function send(actionName?:string,fields:Record<string,unknown>={}){
  busy.value=true;error.value=''
  try{
    if(!pending.value){
      if(!actionName)return
      const latest=await props.api('status'),current=latest.run
      if(current.id!==props.run.id||current.epoch!==props.run.epoch)throw new Error('The run changed. Refresh warehouse records before submitting.')
      const margin=props.quantum*2+(current.mode==='standalone'?Number(current.speed??1):0)
      pending.value={key:crypto.randomUUID(),body:{action:actionName,run_id:current.id,epoch:current.epoch,due_at:Math.max(current.granted,current.requested)+margin,...fields}}
    }
    const command=await props.api('warehouse/commands',pending.value.body,pending.value.key)
    notice.value='Command '+command.id+' queued. Its outcome appears below.';pending.value=null;await refresh()
  }catch(e){
    error.value=(e as Error).message
    const code=(e as Error&{httpStatus?:number}).httpStatus
    if(code&&code>=400&&code<500)pending.value=null
  }finally{busy.value=false}
}
function create(){return send(action.value,{sku:sku.value,location:location.value,quantity:Number(quantity.value),correlation_id:correlation.value,...(action.value==='reserve'?{purpose:purpose.value}:{})})}
onMounted(()=>{void refresh();timer=setInterval(refresh,1500)})
onUnmounted(()=>{disposed=true;if(timer)clearInterval(timer)})
</script>
<template>
  <div class="warehouse">
    <p v-if="loadError" role="alert" class="error">Warehouse refresh failed: {{loadError}}. Displayed records may be stale.</p>
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <div v-if="pending&&!busy" class="retry"><p>The outcome is unconfirmed. Retry with the saved command identity.</p><button data-retry @click="send()">Retry command</button><button @click="pending=null;error=''">Discard saved request</button></div>
    <p v-if="notice" role="status" class="muted">{{notice}}</p>
    <template v-if="snapshot">
      <section class="inventory-board">
        <div class="section-heading"><div><p class="app-label">Warehouse / current run</p><h2>Inventory by location</h2></div><label class="search">Search inventory<input type="search" v-model="search" placeholder="SKU or location"></label></div>
        <div class="capacity-strip"><div v-for="place in snapshot.locations" :key="place.code"><span>{{place.code}}</span><strong>{{place.used}} / {{place.capacity}}</strong><meter :value="place.used" :max="place.capacity" :aria-label="place.code+' capacity'" /></div></div>
        <div class="table-scroll"><table data-inventory><thead><tr><th>Location</th><th>SKU</th><th>On hand</th><th>Reserved</th><th>Available</th></tr></thead><tbody><tr v-for="stock in filtered" :key="stock.sku+stock.location"><td>{{stock.location}}</td><td>{{stock.sku}} <span class="muted">{{stock.kind}}</span></td><td>{{stock.on_hand}}</td><td>{{stock.reserved}}</td><td><strong>{{stock.available}}</strong></td></tr><tr v-if="!filtered.length"><td colspan="5">No inventory matches this search.</td></tr></tbody></table></div>
      </section>
      <section v-if="canWrite"><h2>Receive or allocate goods</h2><form class="warehouse-form" @submit.prevent="create"><label>Action<select v-model="action"><option value="expect">Plan receipt</option><option value="reserve">Reserve stock</option></select></label><label>SKU<select v-model="sku"><option v-for="product in products" :key="product">{{product}}</option></select></label><label>Location<select v-model="location"><option v-for="place in snapshot.locations" :key="place.code">{{place.code}}</option></select></label><label>Quantity<input type="number" v-model="quantity" min="1" max="10000" required></label><label v-if="action==='reserve'">Purpose<select v-model="purpose"><option value="customer">Customer order</option><option value="production">Production batch</option></select></label><label class="correlation">Order / batch correlation ID<input v-model="correlation" required pattern="[0-9a-fA-F-]{36}" aria-describedby="correlation-help"></label><button class="primary" :disabled="busy||!!pending||!active">{{action==='expect'?'Plan receipt':'Reserve stock'}}</button></form><p id="correlation-help" class="muted">Use a UUID to follow the order or batch through receipt, allocation and shipment. Actions settle in simulation time.</p><p v-if="!active" class="error">This run is {{run.state}}. An operator must start a new run before accepting work.</p></section>
      <section class="task-filters"><h2>Warehouse work</h2><div class="buttons"><label>Search work<input type="search" v-model="workSearch" placeholder="SKU, record or correlation"></label><label>Workflow status<select v-model="workflowStatus"><option value="all">All statuses</option><option v-for="state in ['expected','received','reserved','picked','released','issued','transferred','in_transit']" :key="state">{{state}}</option></select></label></div></section>
      <section><h2>Receipt list</h2><div class="table-scroll"><table><thead><tr><th>Receipt / correlation</th><th>Goods</th><th>Location</th><th>Quantity</th><th>Status / action</th></tr></thead><tbody><tr v-for="receipt in tasks(snapshot.receipts)" :key="receipt.id"><td><code>{{receipt.id}}</code><small>{{receipt.correlation_id}}</small></td><td>{{receipt.sku}}</td><td>{{receipt.location}}</td><td>{{receipt.quantity}}</td><td>{{receipt.status}} <button v-if="canWrite&&receipt.status==='expected'" data-receive :disabled="busy||!!pending||!active||waiting(receipt.id)" @click="send('receive',{reference:receipt.id})">Receive</button></td></tr><tr v-if="!tasks(snapshot.receipts).length"><td colspan="5">No receipts planned for this run.</td></tr></tbody></table></div></section>
      <section><h2>Reservations and pick list</h2><div class="table-scroll"><table><thead><tr><th>Reservation / correlation</th><th>Goods / location</th><th>Quantity</th><th>Purpose</th><th>Status / action</th></tr></thead><tbody><tr v-for="reservation in tasks(snapshot.reservations)" :key="reservation.id"><td><code>{{reservation.id}}</code><small>{{reservation.correlation_id}}</small></td><td>{{reservation.sku}} / {{reservation.location}}</td><td>{{reservation.quantity}}</td><td>{{reservation.purpose}}</td><td>{{reservation.status}}<div v-if="canWrite" class="row-actions"><template v-if="reservation.status==='reserved'"><button :disabled="busy||!!pending||!active||waiting(reservation.id)" @click="send(reservation.purpose==='production'?'issue':'pick',{reference:reservation.id})">{{reservation.purpose==='production'?'Issue materials':'Pick'}}</button><button :disabled="busy||!!pending||!active||waiting(reservation.id)" @click="send('release',{reference:reservation.id})">Release</button></template><template v-if="reservation.status==='picked'"><label>Destination<select v-model="destinations[reservation.id]"><option v-for="place in snapshot.locations.filter(p=>p.code!==reservation.location)" :key="place.code">{{place.code}}</option></select></label><button :disabled="busy||!!pending||!active||waiting(reservation.id)||!destinations[reservation.id]" @click="send('transfer',{reference:reservation.id,destination:destinations[reservation.id]})">Transfer</button><small>Picked stock remains reserved until departure.</small></template></div></td></tr><tr v-if="!tasks(snapshot.reservations).length"><td colspan="5">No reservations or picks for this run.</td></tr></tbody></table></div></section>
      <section><h2>Transfers</h2><p class="muted">In-transit goods enter destination inventory only after a confirmed receipt.</p><div class="table-scroll"><table><thead><tr><th>Transfer / correlation</th><th>Goods</th><th>Route</th><th>Quantity</th><th>Status / action</th></tr></thead><tbody><tr v-for="transfer in tasks(snapshot.transfers)" :key="transfer.id"><td><code>{{transfer.id}}</code><small>{{transfer.correlation_id}}</small></td><td>{{transfer.sku}}</td><td>{{transfer.origin}} → {{transfer.destination}}</td><td>{{transfer.quantity}}</td><td>{{transfer.status}} <button v-if="canWrite&&transfer.status==='in_transit'" :disabled="busy||!!pending||!active||waiting(transfer.id)" @click="send('arrive',{reference:transfer.id})">Confirm arrival</button></td></tr><tr v-if="!tasks(snapshot.transfers).length"><td colspan="5">No transfers for this run.</td></tr></tbody></table></div></section>
      <section><h2>Command progress</h2><div class="table-scroll"><table><thead><tr><th>Command</th><th>Action</th><th>Due (s)</th><th>Outcome</th><th>Reason</th></tr></thead><tbody><tr v-for="command in snapshot.commands" :key="command.id"><td><code>{{command.id}}</code></td><td>{{command.command.action}}</td><td>{{command.due_at}}</td><td>{{command.job_status==='dead'?'failed':command.status}}</td><td>{{command.error||''}}</td></tr><tr v-if="!snapshot.commands.length"><td colspan="5">No warehouse commands submitted.</td></tr></tbody></table></div></section>
      <section><h2>Movement history</h2><div class="table-scroll"><table><thead><tr><th>Time (s)</th><th>Action</th><th>Location / SKU</th><th>Quantity</th><th>On-hand change</th><th>Reserved change</th><th>Correlation</th></tr></thead><tbody><tr v-for="move in snapshot.movements" :key="move.id"><td>{{move.simulation_time}}</td><td>{{move.action}}</td><td>{{move.location}} / {{move.sku}}</td><td>{{move.quantity}}</td><td>{{move.on_hand_delta}}</td><td>{{move.reserved_delta}}</td><td><code>{{move.correlation_id}}</code></td></tr><tr v-if="!snapshot.movements.length"><td colspan="7">No stock movements committed for this run.</td></tr></tbody></table></div></section>
    </template>
    <section v-else-if="!loadError"><p>Loading warehouse records…</p></section>
  </div>
</template>
