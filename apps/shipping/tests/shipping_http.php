<?php
declare(strict_types=1);
require __DIR__.'/feature.php';
set_exception_handler(function(Throwable $e){fwrite(STDERR,(string)$e);exit(1);});
use Shipping\{Database,Ledger,Settings,Rules};
$s=new Settings();$db=new Database($s);$db->migrate();$l=new Ledger($db,$s);$r=$l->status()['run'];
$auth=['HTTP_AUTHORIZATION'=>'Basic '.base64_encode('employee:employee-smoke')];
$body=['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>max($r['granted'],$r['requested'])+10,'action'=>'create','customer'=>'HTTP CUSTOMER','destination'=>'CUSTOMER-A','lines'=>[['sku'=>'PRODUCT','quantity'=>2]]];
$response=httpRequest('/api/shipping','GET',[],$auth);if($response->getStatusCode()!==200)throw new RuntimeException('Employee shipping read unavailable: '.$response->getStatusCode());
$response=httpRequest('/api/shipping/commands','POST',$body,$auth+['HTTP_IDEMPOTENCY_KEY'=>'http:'.Rules::uuid4()]);if($response->getStatusCode()!==200)throw new RuntimeException('Employee shipping command unavailable: '.$response->getContent());
$command=json_decode($response->getContent(),true);if(($command['outcome']??null)!=='pending')throw new RuntimeException('Expected asynchronous acceptance');
$response=httpRequest('/api/shipping/commands','POST',$body,['HTTP_AUTHORIZATION'=>'Basic '.base64_encode('observer:observer-smoke'),'HTTP_IDEMPOTENCY_KEY'=>'denied']);if($response->getStatusCode()!==403)throw new RuntimeException('Read-only identity mutated order');
$response=httpRequest('/api/shipping/commands','POST',[...$body,'action'=>'fact'], $auth+['HTTP_IDEMPOTENCY_KEY'=>'forged']);if($response->getStatusCode()!==422)throw new RuntimeException('Employee forged provider outcome');
echo "PASS shipping HTTP employee commands, asynchronous outcomes and forged provider rejection\n";
