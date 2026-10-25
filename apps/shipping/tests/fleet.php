<?php
declare(strict_types=1);
require __DIR__.'/run.php';
$request=['id'=>'job','unit_id'=>'unit','run_id'=>'fleet','epoch'=>'epoch','source_run_id'=>'source','source_epoch'=>'source-epoch','origin'=>'a','destination'=>'b','custody_generation'=>2];
$body=[...$request,'job_id'=>'job','kind'=>'arrival','route_version'=>1,'robot_id'=>'robot','effective_time'=>12];unset($body['id']);
check(!Shipping\Fleet::fact($request,$body,'arrival',11),'future arrival cannot create receipt');
check(Shipping\Fleet::fact($request,$body,'arrival',12),'eligible committed arrival permits receipt');
$body['epoch']='stale';check(!Shipping\Fleet::fact($request,$body,'arrival',20),'stale fleet proof is fenced');

require __DIR__.'/shipping.php';
putenv('FLEET_MODE=coordinated');putenv('FLEET_RUN_ID=11111111-1111-4111-8111-111111111111');putenv('FLEET_EPOCH=22222222-2222-4222-8222-222222222222');putenv('FLEET_URL=http://127.0.0.1:1');putenv('FLEET_TOKEN=private');putenv('FLEET_TIME_OFFSET=0');
$r=$ledger->status()['run'];$id=Shipping\Rules::uuid4();$h=['id'=>Shipping\Rules::uuid4(),'run_id'=>$r['id'],'epoch'=>$r['epoch'],'source'=>'shipping','origin'=>'shipping.outbound.dock01','destination'=>'logistics.outbound.truck01.slot01','unit'=>['id'=>$id,'custody_generation'=>0]];
$request=Shipping\Fleet::request($r,$h,true);
$db->transaction(function($u)use($r,$request){try{Shipping\Fleet::gate($u,$r,$request,'pickup_ready');throw new RuntimeException('Unavailable fleet allowed departure');}catch(Shipping\FleetWait){}});
$rows=$db->transaction(fn($u)=>$u->query('SELECT * FROM shipping_fleet_jobs WHERE id=?',[$request['id']]));check(count($rows)===1&&$rows[0]['departure']===null,'fleet request commits before source departure');
Shipping\Fleet::relay($db);$rows=$db->transaction(fn($u)=>$u->query('SELECT * FROM shipping_fleet_jobs WHERE id=?',[$request['id']]));check($rows[0]['error']!==null&&!$rows[0]['admitted'],'fleet outage preserves durable unsent intent');
$body=$request;unset($body['id']);$body=[...$body,'job_id'=>$request['id'],'kind'=>'pickup_ready','route_version'=>1,'robot_id'=>Shipping\Rules::uuid4(),'effective_time'=>$r['granted']];$snapshot=['events'=>[['job_id'=>$request['id'],'kind'=>'pickup_ready','body'=>$body]]];
$db->transaction(function($u)use($r,$request,$snapshot){$u->execute('UPDATE shipping_fleet_jobs SET snapshot=? WHERE id=?',[$snapshot,$request['id']]);Shipping\Fleet::gate($u,$r,$request,'pickup_ready');Shipping\Fleet::proof($u,$r,$request,'departure');});
$proof=$db->transaction(fn($u)=>$u->one('SELECT departure FROM shipping_fleet_jobs WHERE id=?',[$request['id']]))['departure'];check($proof['effective_time']==$r['granted']&&$proof['source_run_id']===$r['id'],'departure proof freezes actual native time and native scope');
$next=[...$r,'granted'=>$r['granted']+1];$db->transaction(fn($u)=>Shipping\Fleet::proof($u,$next,$request,'departure'));check($db->transaction(fn($u)=>$u->one('SELECT departure FROM shipping_fleet_jobs WHERE id=?',[$request['id']]))['departure']===$proof,'lost departure response cannot recompute proof time');

// Real receiver custody needs both the durable source token and physical arrival.
$r=$ledger->status()['run'];$remote=Shipping\Rules::uuid4();$handoff=Shipping\Rules::uuid4();$correlation=Shipping\Rules::uuid4();
$unit=['id'=>$remote,'barcode'=>'HU-'.strtoupper(str_replace('-','',$remote)),'run_id'=>$r['id'],'epoch'=>$r['epoch'],'contents'=>[['sku'=>'FLEETRECV','quantity'=>1]],'category'=>'finished','state'=>'reserved','owner'=>'storage','version'=>1,'custody_generation'=>0,'last_sequence'=>0,'position'=>'storage.dispatch.dock01','origin'=>null,'destination'=>null,'handoff_id'=>null];
$offer=['id'=>$handoff,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'source'=>'storage','destination_owner'=>'shipping','origin'=>$unit['position'],'destination'=>'shipping.outbound.dock01','state'=>'offered','unit'=>$unit,'departure_token'=>null,'receipt_id'=>null,'reason'=>null];
$command=shippingSubmit(['action'=>'intake','sku'=>'UNUSED','quantity'=>1,'units'=>[['id'=>Shipping\Rules::uuid4(),'quantity'=>1]]])['id'];
$db->transaction(fn($u)=>Shipping\HandlingHandoffs::receive($u,$r,$s,$offer,$correlation,$command));
$departed=[...$offer,'state'=>'departed','unit'=>[...$unit,'state'=>'in_transit','position'=>null,'origin'=>$offer['origin'],'destination'=>$offer['destination'],'handoff_id'=>$handoff,'custody_generation'=>1,'version'=>2,'last_sequence'=>1],'departure_token'=>['id'=>Shipping\Rules::uuid4(),'handoff_id'=>$handoff,'unit_id'=>$remote,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'custody_generation'=>1,'last_sequence'=>1,'unit_version'=>2]];
$db->transaction(function($u)use($r,$s,$departed,$correlation,$command){try{Shipping\HandlingHandoffs::receive($u,$r,$s,$departed,$correlation,$command);throw new RuntimeException('Source token alone created receipt');}catch(Shipping\FleetWait){}});
check(!$db->transaction(fn($u)=>$u->query('SELECT id FROM shipping_handling_units WHERE id=?',[$remote])),'source departure alone cannot place coordinated receiver stock');
$request=Shipping\Fleet::request($r,$departed,false);$body=$request;unset($body['id']);$body=[...$body,'job_id'=>$request['id'],'kind'=>'arrival','route_version'=>1,'robot_id'=>Shipping\Rules::uuid4(),'effective_time'=>$r['granted']+2];
$snapshot=['events'=>[['job_id'=>$request['id'],'kind'=>'arrival','body'=>$body]]];$db->transaction(fn($u)=>$u->execute('UPDATE shipping_fleet_jobs SET snapshot=? WHERE id=?',[$snapshot,$request['id']]));
$db->transaction(function($u)use($r,$s,$departed,$correlation,$command){try{Shipping\HandlingHandoffs::receive($u,$r,$s,$departed,$correlation,$command);throw new RuntimeException('Future arrival created receipt');}catch(Shipping\FleetWait){}});
check(!$db->transaction(fn($u)=>$u->query('SELECT id FROM shipping_handling_units WHERE id=?',[$remote])),'future fleet arrival cannot place coordinated receiver stock');
putenv('FLEET_TIME_OFFSET=2');$db->transaction(fn($u)=>Shipping\Fleet::gate($u,$r,$request,'arrival',true));check(true,'matching common-origin offset makes arrival eligible');putenv('FLEET_TIME_OFFSET=0');
$eligible=[...$r,'granted'=>$r['granted']+2];$db->transaction(fn($u)=>$u->execute('UPDATE runs SET granted=?,requested=? WHERE id=?',[$eligible['granted'],$eligible['granted'],$r['id']]));$received=$db->transaction(fn($u)=>Shipping\HandlingHandoffs::receive($u,$eligible,$s,$departed,$correlation,$command));
check($received['state']==='received'&&count($db->transaction(fn($u)=>$u->query('SELECT id FROM shipping_handling_units WHERE id=?',[$remote])))===1,'eligible arrival and custody token commit exactly one receiver unit');
check($db->transaction(fn($u)=>$u->one('SELECT receipt FROM shipping_fleet_jobs WHERE id=?',[$request['id']]))['receipt']['effective_time']==$eligible['granted'],'receiver proof commits at its eligible native time');
$db->transaction(fn($u)=>$u->execute('UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=?',[$r['id']]));shippingDrain();
shippingSubmit(['action'=>'intake','sku'=>'FLEETITEM','quantity'=>1,'units'=>[['id'=>Shipping\Rules::uuid4(),'quantity'=>1]]]);shippingDrain();
$order=shippingSubmit(['action'=>'create','customer'=>'FLEET','destination'=>'CUSTOMER-A','lines'=>[['sku'=>'FLEETITEM','quantity'=>1]]]);shippingDrain();
shippingSubmit(['action'=>'fulfil','reference'=>$order['id']]);shippingDrain();shippingSubmit(['action'=>'pack','reference'=>$order['id']]);shippingDrain();
$dispatch=shippingSubmit(['action'=>'dispatch','reference'=>$order['id']]);$r=$ledger->status()['run'];check($ledger->prepare($dispatch['due_at'],$r['epoch']),'coordinated dispatch can request native time');$ledger->grant($dispatch['due_at'],$r['epoch']);$ledger->heartbeat('controller');$ledger->execute($dispatch['id']);
$fact=$db->transaction(fn($u)=>$u->one("SELECT id,due_at FROM jobs WHERE run_id=? AND status='pending' ORDER BY due_at,id LIMIT 1",[$r['id']]));check($ledger->prepare($fact['due_at'],$r['epoch']),'synthetic carrier fact can receive native grant');$ledger->grant($fact['due_at'],$r['epoch']);$ledger->heartbeat('controller');check($ledger->execute($fact['id'])==='waiting','coordinated synthetic carrier requires native Logistics custody');
$waiting=$db->transaction(fn($u)=>$u->one('SELECT due_at,error FROM jobs WHERE id=?',[$fact['id']]));check($waiting['due_at']>$fact['due_at']&&str_contains($waiting['error'],'native destination custody'),'unsupported synthetic carrier has actionable deferred wait');
check($ledger->prepare($waiting['due_at'],$r['epoch']),'fleet wait permits the next native time request');
putenv('FLEET_MODE');putenv('FLEET_RUN_ID');putenv('FLEET_EPOCH');putenv('FLEET_URL');putenv('FLEET_TOKEN');putenv('FLEET_TIME_OFFSET');
