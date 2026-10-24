<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
$app=require __DIR__.'/../bootstrap/app.php';
$kernel=$app->make(Illuminate\Contracts\Http\Kernel::class);
function httpRequest(string $uri,string $method='GET',array $body=[],array $headers=[]):Symfony\Component\HttpFoundation\Response {global $kernel;$request=Illuminate\Http\Request::create($uri,$method,[],[],[],array_merge(['HTTP_ACCEPT'=>'application/json','CONTENT_TYPE'=>'application/json'],$headers),$method==='POST'?json_encode((object)$body):null);$response=$kernel->handle($request);$kernel->terminate($request,$response);return $response;}
$response=httpRequest('/api/health/live');if($response->getStatusCode()!==200)throw new RuntimeException('Public liveness route unavailable');
set_exception_handler(function(Throwable $error){fwrite(STDERR,(string)$error);exit(1);});
$response=httpRequest('/api/status');if($response->getStatusCode()!==401)throw new RuntimeException('Unauthenticated status must return401, got '.$response->getStatusCode());
echo "PASS Laravel routes enforce API authentication and leave liveness public\n";

$response=httpRequest('/api/projection');if($response->getStatusCode()!==401)throw new RuntimeException('Projection requires authentication');
$response=httpRequest('/api/projection','GET',[],['HTTP_AUTHORIZATION'=>'Basic '.base64_encode('observer:observer-smoke')]);
if($response->getStatusCode()!==200)throw new RuntimeException('Status reader projection expected 200, got '.$response->getStatusCode());
$value=json_decode($response->getContent(),true);if(!isset($value['effects'])||$value['effects']<0||$value['version']!==1||$value['source']!=='shipping'||!is_array($value['events'])||!is_array($value['snapshot']))throw new RuntimeException('Projection contract missing');
echo "PASS authenticated status reader source projection\n";

$ledger=$app->make(Shipping\Ledger::class);$run=$ledger->status()['run'];
foreach(['hold','resume','speed','reset','finalize'] as $action)foreach(['run_id','epoch'] as $field){
 $body=['run_id'=>$run['id'],'epoch'=>$run['epoch'],'confirm_run_id'=>$run['id']];$body[$field]=Shipping\Rules::uuid4();
 $response=httpRequest('/api/control/'.$action,'POST',$body,['HTTP_AUTHORIZATION'=>'Basic '.base64_encode('operator:shipping-smoke')]);
 if($response->getStatusCode()!==409)throw new RuntimeException('Stale control precondition must conflict: '.$action.' '.$field.' '.$response->getStatusCode());
}
if($ledger->status()['run']['id']!==$run['id'])throw new RuntimeException('Stale control reset run');
echo "PASS controls fence stale run and epoch before mutation\n";

$key=Shipping\Rules::uuid4();$auth=['HTTP_AUTHORIZATION'=>'Basic '.base64_encode('operator:shipping-smoke')];
$first=httpRequest('/api/control/hold','POST',[],$auth+['HTTP_IDEMPOTENCY_KEY'=>$key]);if($first->getStatusCode()!==200)throw new RuntimeException('Keyed hold failed');
httpRequest('/api/control/resume','POST',[],$auth);
$retry=httpRequest('/api/control/hold','POST',[],$auth+['HTTP_IDEMPOTENCY_KEY'=>$key]);
if($ledger->status()['run']['state']!=='running'||json_decode($retry->getContent(),true)!=json_decode($first->getContent(),true))throw new RuntimeException('Keyed retry overwrote another actor resume or lost original response');
foreach([['resume',[]],['hold',['speed'=>1]]] as [$action,$body])if(httpRequest('/api/control/'.$action,'POST',$body,$auth+['HTTP_IDEMPOTENCY_KEY'=>$key])->getStatusCode()!==409)throw new RuntimeException('Control key accepted changed action/body');
$projection=json_decode(httpRequest('/api/projection','GET',[],$auth)->getContent(),true);if(!isset($projection['health']['pending_jobs'],$projection['health']['dead_letters'],$projection['health']['heartbeats']))throw new RuntimeException('Infrastructure missing');
echo "PASS lost-response control receipt and safe projection infrastructure\n";
