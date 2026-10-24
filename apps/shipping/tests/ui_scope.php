<?php
declare(strict_types=1);
require __DIR__.'/feature.php';
putenv('APP_IDENTITIES=[{"username":"unscoped","password":"private-test","role":"service"}]');
$app->forgetInstance(Shipping\Settings::class);$settings=$app->make(Shipping\Settings::class);$identity=$settings->identify('unscoped','private-test');$session=$app->make('session')->driver();$session->put('shipping.identity',$settings->sessionRecord($identity));$request=Illuminate\Http\Request::create('/');$request->setLaravelSession($session);$app->instance('request',$request);
try{(new Shipping\Dashboard())->boot();throw new RuntimeException('Unscoped service can read private Livewire status');}catch(Symfony\Component\HttpKernel\Exception\HttpException $e){if($e->getStatusCode()!==403)throw $e;echo "PASS unscoped service cannot read Livewire status\n";}
