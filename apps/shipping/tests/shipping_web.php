<?php
declare(strict_types=1);
require __DIR__.'/feature.php';
set_exception_handler(function(Throwable $e){fwrite(STDERR,(string)$e);exit(1);});
use Shipping\{Settings,OrderDesk,Ledger};
$s=$app->make(Settings::class);$session=$app->make('session')->driver();$session->put('shipping.identity',$s->sessionRecord($s->identify('employee','employee-smoke')));$request=Illuminate\Http\Request::create('/');$request->setLaravelSession($session);$app->instance('request',$request);
$desk=new OrderDesk();$desk->boot();$desk->mount();$desk->customer='WEB CUSTOMER';$desk->lines=[['sku'=>'PRODUCT','quantity'=>'3'],['sku'=>'WIDGET','quantity'=>'1']];$desk->createOrder();if($desk->error!==''||!str_contains($desk->notice,'Command accepted'))throw new RuntimeException('Employee order form: '.$desk->error);
$desk->act('fact',Shipping\Rules::uuid4());if($desk->error!=='Unknown shipping action')throw new RuntimeException('Forged Livewire provider action accepted');
$desk->render()->with(get_object_vars($desk))->render();
$session->put('shipping.identity',$s->sessionRecord($s->identify('observer','observer-smoke')));$desk=new OrderDesk();$desk->boot();$desk->mount();$desk->customer='DENIED';$desk->createOrder();if($desk->error!=='This identity cannot change orders')throw new RuntimeException('Read-only Livewire identity mutated shipping');
echo "PASS shipping Livewire order entry, view rendering and server-side command authorization\n";
