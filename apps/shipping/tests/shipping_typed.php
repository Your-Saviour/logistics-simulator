<?php
declare(strict_types=1);
require __DIR__.'/shipping.php';
use Shipping\{Fulfilment,Ledger,Rules};
$settings=clone $s;$settings->providers=['orders'=>'synthetic','goods'=>'helics','carrier'=>'helics'];$settings->federationId='typed-test';$settings->peers=['goods'=>[['source'=>'storage','endpoint'=>'storage/events'],['source'=>'manufacturing','endpoint'=>'manufacturing/events']],'carrier'=>['source'=>'logistics','endpoint'=>'logistics/events']];
$shipping=new Fulfilment($db,$settings);$ledger=new Ledger($db,$settings);$seen=[];$shortage=false;
function typedEnvelope(array $o,array $i,array $payload,string $type,float $due,int $version=1):array {global $ledger;$r=$ledger->status()['run'];$owner=str_starts_with($type,'logistics.')?'logistics':'storage';return ['schema_version'=>'1.0','type'=>$type,'event_id'=>Rules::uuid5($i['id'],$type),'federation_id'=>'typed-test','run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$o['correlation_id'],'causation_id'=>$i['id'],'aggregate_id'=>$payload['id']??$i['id'],'aggregate_version'=>$version,'source'=>$owner,'destination'=>'shipping','boundary'=>$owner==='logistics'?'carrier':'goods','effective_time'=>$due,'quantity_unit'=>'item','payload'=>$payload];}
function typedUntil(string $target,string $id):void {global $db,$ledger,$shipping,$seen,$shortage;
 for($n=0;$n<100;$n++){
  $r=$ledger->status()['run'];$o=null;try{$o=$shipping->order($id);}catch(Shipping\Conflict){}
  if($o&&$o['status']===$target)return;
  if($o)foreach($o['intents'] as $i){if($i['state']!=='pending'||isset($seen[$i['id']]))continue;$seen[$i['id']]=true;$line=null;foreach($o['lines'] as $l)if($l['id']===$i['line_id'])$line=$l;
   $p=['id'=>Rules::uuid5($i['id'],'peer-record'),'run_id'=>$r['id'],'correlation_id'=>$o['correlation_id'],'sku'=>$line['sku'],'quantity'=>$line['quantity'],'version'=>1];$type='';$version=1;
   switch($i['kind']){
    case 'reserve':
     if(!$shortage){$shortage=true;$p=['action'=>'reserve','reason'=>'Insufficient available stock; complete quantities required','request'=>['action'=>'reserve','sku'=>$line['sku'],'quantity'=>$line['quantity']]];$type='storage.command.rejected.v1';}
     else{$p+=['location'=>'FINISHED-A','purpose'=>'customer','status'=>'reserved'];$type='storage.reserve.completed.v1';}break;
    case 'produce':$p+=['location'=>'FINISHED-A','status'=>'received'];$type='storage.receive.completed.v1';break;
    case 'pick':$p['id']=$line['reservation_id'];$p['version']=2;$version=2;$p+=['location'=>'FINISHED-A','purpose'=>'customer','status'=>'picked'];$type='storage.pick.completed.v1';break;
    case 'transfer':$p+=['reservation_id'=>$line['reservation_id'],'origin'=>'FINISHED-A','destination'=>'DISPATCH','status'=>'in_transit'];$type='storage.transfer.completed.v1';break;
    case 'receive':$p['id']=$line['transfer_id'];$p['version']=2;$version=2;$p+=['reservation_id'=>$line['reservation_id'],'origin'=>'FINISHED-A','destination'=>'DISPATCH','status'=>'received'];$type='storage.arrive.completed.v1';break;
    case 'dispatch':case 'deliver':
     $dispatch=$i;if($i['kind']==='deliver')foreach($o['intents'] as $candidate)if($candidate['kind']==='dispatch'&&$candidate['line_id']===$line['id'])$dispatch=$candidate;
     $p['id']=Rules::uuid5($dispatch['id'],'journey');$p['epoch']=$r['epoch'];$p['external_reference']=$dispatch['id'];$p['route']='DISPATCH-CUSTOMER';$p['origin']='DISPATCH';$p['destination']=$o['destination'];$p['journey_seconds']=5;$p['vehicle']='VAN-1';$p['provider']=true;$p['planned_eta']=9999;$p['departed_at']=1;$p['arrived_at']=$i['kind']==='deliver'?2:null;$p['unloaded_at']=$i['kind']==='deliver'?3:null;$p['received_at']=$i['kind']==='deliver'?4:null;$p['status']=$i['kind']==='deliver'?'received':'in_transit';$p['custody']=$i['kind']==='deliver'?'destination':'vehicle';$type=$i['kind']==='deliver'?'logistics.receive.completed.v1':'logistics.depart.completed.v1';break;
    default:throw new RuntimeException('Unhandled fixture intent '.$i['kind']);
   }
   $e=typedEnvelope($o,$i,$p,$type,$r['granted']+1,$version);shippingCheck($shipping->ingest($e,$e['source'].'/events')==='accepted','typed '.$type.' staged');shippingCheck($shipping->ingest($e,$e['source'].'/events')==='duplicate','typed fact redelivery deduplicates');
  }
  // Fixture transport has accepted each durable publication. This is not native IO.
  $db->transaction(fn($u)=>$u->execute('UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=? AND sent_at IS NULL',[$r['id']]));
  $jobs=$db->transaction(fn($u)=>$u->query("SELECT * FROM jobs WHERE run_id=? AND status='pending' ORDER BY due_at,id",[$r['id']]));if(!$jobs)throw new RuntimeException('Typed lifecycle stalled at '.($o['status']??'missing'));
  $time=max($r['granted'],(float)$jobs[0]['due_at']);if($time>$r['granted']){shippingCheck($ledger->prepare($time,$r['epoch']),'typed output/job barrier settled');$ledger->grant($time,$r['epoch']);}$ledger->heartbeat('controller');foreach($jobs as $j)if($j['due_at']<=$time)$ledger->execute($j['id']);
 }
 throw new RuntimeException('Typed lifecycle failed to reach '.$target);
}
$create=shippingSubmit(['action'=>'create','customer'=>'TYPED','destination'=>'CUSTOMER-A','lines'=>[['sku'=>'PRODUCT','quantity'=>3],['sku'=>'WIDGET','quantity'=>2]]]);typedUntil('new',$create['id']);
shippingSubmit(['action'=>'fulfil','reference'=>$create['id']]);typedUntil('ready',$create['id']);
$o=$shipping->order($create['id']);shippingCheck(array_sum(array_column($o['lines'],'received'))===5,'typed warehouse facts authorize complete physical receipt');
shippingSubmit(['action'=>'pack','reference'=>$create['id']]);typedUntil('packed',$create['id']);
shippingSubmit(['action'=>'dispatch','reference'=>$create['id']]);typedUntil('in_transit',$create['id']);shippingCheck($shipping->order($create['id'])['shipment']['confirmation_id']===null,'departure and ETA never confirm delivery');
typedUntil('delivered',$create['id']);$o=$shipping->order($create['id']);shippingCheck(count(array_filter($o['intents'],fn($i)=>$i['kind']==='deliver'&&$i['state']==='completed'))===2,'every carrier line requires destination confirmation');
echo "Typed stock/production/carrier lifecycle passed (PHP with controlled wire fixtures; not native IO)\n";
