<?php
declare(strict_types=1);
require __DIR__.'/shipping.php';
use Shipping\{Fulfilment,Ledger,Rules};
$settings=clone $s;$settings->providers=['orders'=>'synthetic','goods'=>'helics','carrier'=>'helics'];$settings->federationId='typed-test';$settings->peers=['goods'=>[['source'=>'storage','endpoint'=>'storage/events'],['source'=>'manufacturing','endpoint'=>'manufacturing/events']],'carrier'=>['source'=>'logistics','endpoint'=>'logistics/events']];
$shipping=new Fulfilment($db,$settings);$ledger=new Ledger($db,$settings);$seen=[];$shortage=false;
function typedEnvelope(array $o,array $i,array $payload,string $type,float $due,int $version=1):array {global $ledger;$r=$ledger->status()['run'];$owner=str_starts_with($type,'logistics.')?'logistics':'storage';return ['schema_version'=>'1.0','type'=>$type,'event_id'=>Rules::uuid5($i['id'],$type),'federation_id'=>'typed-test','run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$o['correlation_id'],'causation_id'=>$i['id'],'aggregate_id'=>$payload['id']??$i['id'],'aggregate_version'=>$version,'source'=>$owner,'destination'=>'shipping','boundary'=>$owner==='logistics'?'carrier':'goods','effective_time'=>$due,'quantity_unit'=>'item','payload'=>$payload];}
// Controlled peer fixture: these native calls stand in for the external
// source/receiver handshake. They are not evidence of connected native IO.
function typedReceiveHandoff(array $o,array $line,array $intent):void {global $db,$ledger,$settings;
 $db->transaction(function($u)use($o,$line,$intent,$settings){$r=$u->run();$plan=$u->one("SELECT * FROM shipping_unit_plans WHERE line_id=? AND provider='storage' AND state='expected'",[$line['id']]);$unit=$plan['source_manifest'];$id=$unit['id'];$handoff=Rules::uuid5($intent['id'],'handoff');$destination=$plan['destination'];$unit['position']='storage.outbound.dock01';$unit['version']++;$unit['last_sequence']++;
  $h=['id'=>$handoff,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'source'=>'storage','destination_owner'=>'shipping','origin'=>$unit['position'],'destination'=>$destination,'state'=>'offered','unit'=>$unit,'departure_token'=>null,'receipt_id'=>null,'reason'=>null];
  Shipping\HandlingHandoffs::receive($u,$r,$settings,$h,$o['correlation_id'],$o['id']);
  $transit=[...$unit,'state'=>'in_transit','position'=>null,'origin'=>$h['origin'],'destination'=>$destination,'handoff_id'=>$handoff,'custody_generation'=>$unit['custody_generation']+1,'last_sequence'=>$unit['last_sequence']+1,'version'=>$unit['version']+1];
  $h=[...$h,'state'=>'departed','unit'=>$transit,'departure_token'=>['id'=>Rules::uuid5($handoff,'token'),'handoff_id'=>$handoff,'unit_id'=>$id,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'custody_generation'=>$transit['custody_generation'],'last_sequence'=>$transit['last_sequence'],'unit_version'=>$transit['version']]];
  Shipping\HandlingHandoffs::receive($u,$r,$settings,$h,$o['correlation_id'],$o['id']);
 });
}
function typedCarrierHandoff(array $o,array $intent):void {global $db,$settings;
 $db->transaction(function($u)use($o,$intent,$settings){$r=$u->run();$line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$intent['line_id']]);
  foreach(Shipping\HandlingUnits::requireLine($u,$r,$line) as $unit){$used=array_column($u->query("SELECT offer->>'destination' AS destination FROM shipping_handling_departures WHERE run_id=?",[$r['id']]),'destination');$destination=null;for($n=1;$n<=32;$n++){$candidate=sprintf('logistics.outbound.truck%02d.slot%02d',intdiv($n-1,8)+1,($n-1)%8+1);if(!in_array($candidate,$used,true)){$destination=$candidate;break;}}if(!$destination)throw new RuntimeException('Fixture carrier slots full');
   $h=Shipping\HandlingHandoffs::offer($u,$r,$settings,$unit['id'],'logistics',$destination,$o['correlation_id'],$o['shipment']['id']);Shipping\HandlingHandoffs::source($u,$r,$settings,[...$h,'state'=>'accepted'],$o['correlation_id'],$o['shipment']['id']);
  }
 });
}
function typedUntil(string $target,string $id):void {global $db,$ledger,$shipping,$seen,$shortage;
 for($n=0;$n<100;$n++){
  $r=$ledger->status()['run'];$o=null;try{$o=$shipping->order($id);}catch(Shipping\Conflict){}
  if($o&&$o['status']===$target)return;
  if($o)foreach($o['intents'] as $i){if($i['state']!=='pending'||isset($seen[$i['id']]))continue;$seen[$i['id']]=true;$line=null;foreach($o['lines'] as $l)if($l['id']===$i['line_id'])$line=$l;
   $p=['id'=>Rules::uuid5($i['id'],'peer-record'),'run_id'=>$r['id'],'correlation_id'=>$o['correlation_id'],'sku'=>$line['sku'],'quantity'=>$line['quantity'],'version'=>1];$type='';$version=1;
   switch($i['kind']){
    case 'reserve':
     if(!$shortage){$shortage=true;$p=['action'=>'reserve','reason'=>'Insufficient available stock; complete quantities required','request'=>['action'=>'reserve','sku'=>$line['sku'],'quantity'=>$line['quantity']]];$type='storage.command.rejected.v1';}
     else{$unitId=Rules::uuid5($line['id'],'canonical-stock');$unit=['id'=>$unitId,'barcode'=>'HU-'.strtoupper(str_replace('-','',$unitId)),'run_id'=>$r['id'],'epoch'=>$r['epoch'],'contents'=>[['sku'=>$line['sku'],'quantity'=>$line['quantity']]],'category'=>'finished','state'=>'reserved','owner'=>'storage','version'=>3,'custody_generation'=>0,'last_sequence'=>1,'position'=>'storage.finished.r01.b01.l01','origin'=>null,'destination'=>null,'handoff_id'=>null];$p+=['location'=>'FINISHED-A','purpose'=>'customer','status'=>'reserved','unit_manifest'=>[$unit]];$type='storage.reserve.completed.v1';}break;
    case 'produce':$p+=['location'=>'FINISHED-A','status'=>'received'];$type='storage.receive.completed.v1';break;
    case 'pick':$p['id']=$line['reservation_id'];$p['version']=2;$version=2;$p+=['location'=>'FINISHED-A','purpose'=>'customer','status'=>'picked'];$type='storage.pick.completed.v1';break;
    case 'transfer':$p+=['reservation_id'=>$line['reservation_id'],'origin'=>'FINISHED-A','destination'=>'DISPATCH','destination_owner'=>'shipping','status'=>'in_transit'];$type='storage.transfer.completed.v1';break;
    case 'receive':typedReceiveHandoff($o,$line,$i);$p['id']=$line['transfer_id'];$p['version']=2;$version=2;$p+=['reservation_id'=>$line['reservation_id'],'origin'=>'FINISHED-A','destination'=>'DISPATCH','destination_owner'=>'shipping','status'=>'received'];$type='storage.arrive.completed.v1';break;
    case 'dispatch':case 'deliver':
     if($i['kind']==='dispatch')typedCarrierHandoff($o,$i);
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
$o=$shipping->order($create['id']);shippingCheck(array_sum(array_column($o['lines'],'received'))===5,'typed warehouse facts require separately confirmed whole-unit custody');
shippingSubmit(['action'=>'pack','reference'=>$create['id']]);typedUntil('packed',$create['id']);
shippingSubmit(['action'=>'dispatch','reference'=>$create['id']]);typedUntil('in_transit',$create['id']);shippingCheck($shipping->order($create['id'])['shipment']['confirmation_id']===null,'departure and ETA never confirm delivery');
typedUntil('delivered',$create['id']);$o=$shipping->order($create['id']);shippingCheck(count(array_filter($o['intents'],fn($i)=>$i['kind']==='deliver'&&$i['state']==='completed'))===2,'every carrier line requires destination confirmation');
echo "Typed stock/production/carrier lifecycle passed (PHP with controlled wire fixtures; not native IO)\n";
