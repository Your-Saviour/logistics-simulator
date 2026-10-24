<?php
declare(strict_types=1);
require __DIR__.'/shipping_typed.php';
use Shipping\{ShippingBoundary,Rules};
$o=$shipping->order($create['id']);$line=$o['lines'][0];$r=$ledger->status()['run'];$intents=[];foreach($o['intents'] as $i)if($i['line_id']===$line['id'])$intents[$i['kind']]=$i;
$p=['id'=>$line['reservation_id'],'run_id'=>$r['id'],'correlation_id'=>$o['correlation_id'],'sku'=>$line['sku'],'location'=>'FINISHED-A','quantity'=>$line['quantity'],'purpose'=>'customer','status'=>'picked','version'=>2];
$wrong=[...$p,'id'=>Rules::uuid4()];$e=typedEnvelope($o,$intents['pick'],$wrong,'storage.pick.completed.v1',$r['granted']+1,2);shippingReject(fn()=>$db->transaction(fn($u)=>ShippingBoundary::fact($u,$r,$e)),'pick cannot confirm a different reservation');
$e=typedEnvelope($o,$intents['release']??$intents['pick'],[...$wrong,'status'=>'released'],'storage.release.completed.v1',$r['granted']+1,2);
// A real release intent is covered in cancellation tests; transfer/arrival use the completed physical records.
$p=['id'=>$line['transfer_id'],'run_id'=>$r['id'],'correlation_id'=>$o['correlation_id'],'sku'=>$line['sku'],'quantity'=>$line['quantity'],'reservation_id'=>Rules::uuid4(),'origin'=>'FINISHED-A','destination'=>'DISPATCH','status'=>'in_transit','version'=>1];
$e=typedEnvelope($o,$intents['transfer'],$p,'storage.transfer.completed.v1',$r['granted']+1);shippingReject(fn()=>$db->transaction(fn($u)=>ShippingBoundary::fact($u,$r,$e)),'transfer cannot substitute another reservation');
$p['reservation_id']=$line['reservation_id'];$p['destination']='WRONG-DESTINATION';$p['status']='received';$p['version']=2;$e=typedEnvelope($o,$intents['receive'],$p,'storage.arrive.completed.v1',$r['granted']+1,2);shippingReject(fn()=>$db->transaction(fn($u)=>ShippingBoundary::fact($u,$r,$e)),'goods at another physical destination cannot authorize packing');
$dispatch=$intents['dispatch'];$p=['id'=>Rules::uuid4(),'run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$o['correlation_id'],'external_reference'=>$dispatch['id'],'sku'=>$line['sku'],'quantity'=>$line['quantity'],'destination'=>$o['destination'],'status'=>'received','custody'=>'destination','version'=>7];$e=typedEnvelope($o,$intents['deliver'],$p,'logistics.receive.completed.v1',$r['granted']+1,7);shippingReject(fn()=>$db->transaction(fn($u)=>ShippingBoundary::fact($u,$r,$e)),'delivery must refer to the confirmed departure journey');
echo "Shipping physical peer identity checks passed\n";
