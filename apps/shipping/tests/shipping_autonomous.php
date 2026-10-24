<?php
declare(strict_types=1);
require __DIR__.'/shipping.php';
$first=null;
for($step=0;$step<10;$step++){
 $db->transaction(function($u)use($shipping){$shipping->seed($u,$u->run());});
 $before=count($shipping->snapshot()['commands']);$db->transaction(function($u)use($shipping){$shipping->seed($u,$u->run());});shippingCheck(count($shipping->snapshot()['commands'])===$before,'seed replay schedules no duplicate provider or employee action');
 shippingDrain();$orders=$shipping->snapshot()['orders'];$first??=$orders[0]['id'];
 if($shipping->order($first)['status']==='delivered')break;
}
$o=$shipping->order($first);shippingCheck($o['autonomous']&&$o['status']==='delivered'&&$o['shipment']['confirmation_id']!==null,'seeded autonomous customer completes confirmed delivery without other departments');
$replica=new Shipping\Fulfilment($db,$s);shippingCheck($replica->order($first)['shipment']['id']===$o['shipment']['id'],'restarted domain service observes same autonomous shipment');
echo "Shipping autonomous provider checks passed\n";
