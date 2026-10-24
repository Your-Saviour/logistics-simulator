<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
use Shipping\{Database,Ledger,Settings,Rules,Fulfilment,Conflict,Validation};
function shippingCheck(bool $ok,string $message):void {if(!$ok)throw new RuntimeException($message);echo "PASS $message\n";}
function shippingReject(callable $fn,string $message):void {try{$fn();}catch(Conflict|Validation|Shipping\CustodyCapacity){shippingCheck(true,$message);return;}throw new RuntimeException('Expected rejection: '.$message);}
$s=new Settings();$db=new Database($s);$db->migrate();$ledger=new Ledger($db,$s);
$a=['actor'=>'employee','role'=>'employee','request_id'=>Rules::uuid4(),'action'=>'test:shipping','peer'=>'test'];
$ledger->control('reset',['confirm_run_id'=>$ledger->scope()],$a);
$shipping=new Fulfilment($db,$s);$r=$ledger->status()['run'];
function shippingSubmit(array $body,?string $key=null):array {global $shipping,$ledger,$a;$r=$ledger->status()['run'];return $shipping->submit($key??Rules::uuid4(),['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>max($r['granted'],$r['requested'])+1,...$body],$a);}
function shippingDrain():void {global $ledger,$db;for($i=0;$i<100;$i++){$r=$ledger->status()['run'];$jobs=$db->transaction(fn($u)=>$u->query("SELECT id,due_at FROM jobs WHERE run_id=? AND status='pending' ORDER BY due_at,id",[$r['id']]));if(!$jobs)return;$time=max($r['granted'],(float)$jobs[0]['due_at']);if($time>$r['granted']){shippingCheck($ledger->prepare($time,$r['epoch']),'settled work permits next domain grant');$ledger->grant($time,$r['epoch']);}$ledger->heartbeat('controller');foreach($jobs as $j)if($j['due_at']<=$time)$ledger->execute($j['id']);}throw new RuntimeException('Domain work failed to settle');}
$key=Rules::uuid4();$create=shippingSubmit(['action'=>'create','customer'=>'ACME','destination'=>'CUSTOMER-A','lines'=>[['sku'=>'PRODUCT','quantity'=>3],['sku'=>'WIDGET','quantity'=>2]]],$key);
shippingCheck($ledger->execute($create['id'])==='waiting','order creation waits for granted time');
shippingDrain();$order=$shipping->snapshot()['orders'][0];$id=$order['id'];
shippingCheck(count($order['lines'])===2&&$order['status']==='new','multiline order is durable');
shippingCheck($shipping->submit($key,$create['body'],$a)['id']===$create['id'],'identical replay returns original command');
shippingReject(fn()=>$shipping->submit($key,[...$create['body'],'customer'=>'OTHER'],$a),'changed idempotent body conflicts');
shippingSubmit(['action'=>'pack','reference'=>$id]);shippingDrain();shippingCheck($shipping->snapshot()['commands'][0]['outcome']==='rejected','packing unreceived goods is a business rejection');
shippingSubmit(['action'=>'fulfil','reference'=>$id]);shippingDrain();$order=$shipping->order($id);
shippingCheck($order['status']==='ready'&&array_sum(array_column($order['lines'],'received'))===5,'standalone stock and production fulfil every line before packing');
shippingCheck(count(array_filter($order['history'],fn($h)=>$h['event']==='shortage'))>0,'shortage and production are visible');
shippingSubmit(['action'=>'pack','reference'=>$id]);shippingDrain();shippingCheck($shipping->order($id)['status']==='packed','received complete order can be packed');
$dispatch=shippingSubmit(['action'=>'dispatch','reference'=>$id]);
$r=$ledger->status()['run'];$ledger->prepare($dispatch['due_at'],$r['epoch']);$ledger->grant($dispatch['due_at'],$r['epoch']);$ledger->heartbeat('controller');$ledger->execute($dispatch['id']);
shippingCheck($shipping->order($id)['status']==='awaiting_carrier','dispatch request alone never confirms delivery');
shippingDrain();$order=$shipping->order($id);shippingCheck($order['status']==='delivered'&&$order['shipment']['confirmation_id']!==null,'explicit correlated carrier outcome confirms delivery');
shippingCheck($ledger->execute($dispatch['id'])==='duplicate','redelivered dispatch does not duplicate shipment');
shippingCheck(count($shipping->snapshot()['shipments'])===1,'one correlated shipment per order');
shippingSubmit(['action'=>'cancel','reference'=>$id]);shippingDrain();shippingCheck($shipping->order($id)['status']==='delivered','irreversible shipment cancellation rejects');
$c=shippingSubmit(['action'=>'create','customer'=>'CANCEL','destination'=>'CUSTOMER-B','lines'=>[['sku'=>'PRODUCT','quantity'=>1]]]);shippingDrain();
shippingSubmit(['action'=>'cancel','reference'=>$c['id']]);shippingDrain();shippingCheck($shipping->order($c['id'])['status']==='cancelled','safe cancellation before fulfilment');
shippingReject(fn()=>shippingSubmit(['action'=>'create','customer'=>'BAD','destination'=>'CUSTOMER','lines'=>[['sku'=>'PRODUCT','quantity'=>true]]]),'boolean line quantity rejects');
shippingReject(fn()=>shippingSubmit(['action'=>'create','customer'=>'BAD','destination'=>'CUSTOMER','lines'=>[['sku'=>'PRODUCT','quantity'=>1],['sku'=>'PRODUCT','quantity'=>2]]]),'duplicate SKU rejects');
$db->transaction(function($u)use($id){$r=$u->run();$u->execute("INSERT INTO shipping_history(run_id,order_id,event,simulation_time,detail) SELECT ?,?,'historical-record',0,'{}'::jsonb FROM generate_series(1,205)",[$r['id'],$id]);});
$projection=$shipping->projection();shippingCheck(count($projection['events'])>205,'projection preserves complete history beyond interactive snapshot limit');
shippingCheck(count(array_unique(array_column($projection['events'],'id')))===count($projection['events']),'projection history ids are unique strings');
shippingCheck($projection['cursor']===$shipping->projection()['cursor'],'unchanged source retains cursor');
$validEvents=array_filter($projection['events'],fn($event)=>is_string($event['id'])&&isset($event['correlation_id'],$event['simulation_time']));shippingCheck(count($validEvents)===count($projection['events']),'projection retains correlation and simulation time');
$pending=shippingSubmit(['action'=>'create','customer'=>'OLD','destination'=>'CUSTOMER','lines'=>[['sku'=>'PRODUCT','quantity'=>1]]]);
$ledger->control('reset',['confirm_run_id'=>$ledger->scope()],$a);shippingCheck($ledger->execute($pending['id'])==='fenced','old domain work is fenced after reset');
shippingReject(fn()=>$shipping->submit(Rules::uuid4(),$pending['body'],$a),'old browser run cannot enter new epoch');
shippingCheck($shipping->snapshot()['orders']===[],'reset isolates shipping state');
shippingCheck($shipping->projection()['events']===[],'projection reset excludes old-run history');
echo "Shipping lifecycle checks passed\n";
