<?php
declare(strict_types=1);
require __DIR__.'/feature.php';
set_exception_handler(function(Throwable $e){fwrite(STDERR,(string)$e);exit(1);});
use Shipping\{Settings,OrderDesk,Ledger,Fulfilment,Rules,Database};
$s=$app->make(Settings::class);$db=$app->make(Database::class);$db->migrate();$l=$app->make(Ledger::class);$a=['actor'=>'operator','role'=>'operator','request_id'=>Rules::uuid4(),'action'=>'test:replay','peer'=>'test'];$l->control('reset',['confirm_run_id'=>$l->scope()],$a);
$session=$app->make('session')->driver();$session->put('shipping.identity',$s->sessionRecord($s->identify('employee','employee-smoke')));$request=Illuminate\Http\Request::create('/');$request->setLaravelSession($session);$app->instance('request',$request);
$snapshot=new OrderDesk();$snapshot->boot();$snapshot->mount();
$first=clone $snapshot;$first->customer='RESPONSE-LOST';$first->updated('customer');$first->createOrder();if($first->error)throw new RuntimeException($first->error);
$db->transaction(fn($u)=>$u->execute('UPDATE runs SET requested=requested+5 WHERE current'));
$retry=clone $snapshot;$retry->customer='RESPONSE-LOST';$retry->updated('customer');$retry->createOrder();if($retry->error)throw new RuntimeException('Original browser snapshot replay failed: '.$retry->error);
$commands=$app->make(Fulfilment::class)->snapshot()['commands'];if(count($commands)!==1||$first->notice!==$retry->notice)throw new RuntimeException('Lost response duplicated command or changed its identity/body');
echo "PASS original Livewire snapshot replays committed command after lost response and advancing watermarks\n";
