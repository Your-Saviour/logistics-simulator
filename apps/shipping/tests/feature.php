<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
$app=require __DIR__.'/../bootstrap/app.php';
$kernel=$app->make(Illuminate\Contracts\Http\Kernel::class);
function httpRequest(string $uri,string $method='GET',array $body=[],array $headers=[]):Symfony\Component\HttpFoundation\Response {global $kernel;$request=Illuminate\Http\Request::create($uri,$method,[],[],[],array_merge(['HTTP_ACCEPT'=>'application/json','CONTENT_TYPE'=>'application/json'],$headers),$method==='POST'?json_encode((object)$body):null);$response=$kernel->handle($request);$kernel->terminate($request,$response);return $response;}
$response=httpRequest('/api/health/live');if($response->getStatusCode()!==200)throw new RuntimeException('Public liveness route unavailable');
$response=httpRequest('/api/status');if($response->getStatusCode()!==401)throw new RuntimeException('Unauthenticated status must return401, got '.$response->getStatusCode());
echo "PASS Laravel routes enforce API authentication and leave liveness public\n";
