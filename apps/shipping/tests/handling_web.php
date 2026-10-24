<?php
declare(strict_types=1);
require __DIR__.'/shipping.php';
require __DIR__.'/feature.php';

$id=Shipping\Rules::uuid4();shippingSubmit(['action'=>'intake','sku'=>'PRODUCT','quantity'=>6,'units'=>[['id'=>$id,'quantity'=>6]]]);shippingDrain();
$before=$shipping->snapshot()['handling']['units'];$barcode='HU-'.strtoupper(str_replace('-','',$id));
$settings=$app->make(Shipping\Settings::class);$session=$app->make('session')->driver();$session->put('shipping.identity',$settings->sessionRecord($settings->identify('observer','observer-smoke')));
$request=Illuminate\Http\Request::create('/');$request->setLaravelSession($session);$app->instance('request',$request);
$desk=new Shipping\OrderDesk();$desk->boot();$desk->mount();$desk->unitSearch=strtolower($barcode);$desk->selectedUnit=$id;
$html=$desk->render()->with(get_object_vars($desk))->render();
shippingCheck(str_contains($html,'data-unit-detail')&&str_contains($html,$barcode)&&str_contains($html,'PRODUCT')&&str_contains($html,'6 items'),'Shipping observer inspects actual immutable barcode contents');
shippingCheck(str_contains($html,$before[0]['position'])&&str_contains($html,'Movement history'),'Shipping unit detail retains exact placement and native history');
shippingCheck(!str_contains($html,'wire:submit="createOrder"')&&$shipping->snapshot()['handling']['units']===$before,'Read-only unit inspection cannot change order or stock state');
$desk->unitSearch='NO-SUCH-BARCODE';$html=$desk->render()->with(get_object_vars($desk))->render();shippingCheck(str_contains($html,'No handling units match'),'Shipping barcode lookup has an explicit no-match state');
$desk->refreshRun();shippingCheck($desk->selectedUnit===''&&$desk->unitSearch==='','Refreshing scope clears handling-unit selection and search');
echo "Shipping handling-unit web inspection passed\n";
