<?php
declare(strict_types=1);
namespace Shipping;
final class ShippingBoundary
{
    public static function header(array $e):void {
        Rules::fields($e,['schema_version','type','event_id','federation_id','run_id','epoch','correlation_id','causation_id','aggregate_id','aggregate_version','source','destination','boundary','effective_time','wall_time','quantity_unit','payload']);
        foreach(['event_id','run_id','epoch','correlation_id','causation_id','aggregate_id'] as $key)Rules::uuid($e[$key]??null);
        foreach(['federation_id','source','destination','boundary'] as $key)Rules::text($e[$key]??null,128);
        if(($e['schema_version']??null)!=='1.0'||($e['quantity_unit']??null)!=='item'||Rules::number($e['effective_time']??null)<0)throw new Validation('Invalid shipping envelope metadata');Rules::integer($e['aggregate_version']??null,1,PHP_INT_MAX);
        Rules::text($e['type']??null,128);
    }
    public static function validate(array $e):void {
        self::header($e);
        if(!is_array($e['payload']??null))throw new Validation('Payload required');
        if(str_starts_with($e['type'],'handling.')){
            $h=$e['payload'];HandlingHandoffs::validate($h);$sourceSide=$h['source']==='shipping';$peer=$sourceSide?$h['destination_owner']:$h['source'];
            if($e['source']!==$peer||$e['destination']!=='shipping'||$e['boundary']!==($peer==='logistics'?'carrier':'goods')||$e['type']!=='handling.'.$h['state'].'.v1'||$e['run_id']!==$h['run_id']||$e['epoch']!==$h['epoch']||$e['aggregate_id']!==$h['id']||$e['causation_id']!==$h['id']||$e['aggregate_version']!==$h['unit']['version']||!in_array($h['state'],$sourceSide?['accepted','received']:['offered','departed','acknowledged'],true))throw new Conflict('Custody envelope owner, scope or identity mismatch');
        }elseif($e['type']==='shipping.order.v1'){
            Rules::fields($e['payload'],['customer','destination','lines']);
            if($e['boundary']!=='orders'||$e['source']!=='external-orders'||$e['aggregate_version']!==1)throw new Conflict('Customer order owner/version mismatch');
            ShippingRules::command(['run_id'=>$e['run_id'],'epoch'=>$e['epoch'],'due_at'=>$e['effective_time'],'action'=>'create',...$e['payload']]);
        }elseif($e['type']==='shipping.fact.v1'){
            $f=ShippingRules::fact($e['payload']);$expected=$f['result']==='failed'?$f['owner']:(in_array($f['result'],['departed','delivered'],true)?'logistics':($f['result']==='produced'?'manufacturing':'storage'));if(!in_array($expected,['storage','manufacturing','logistics'],true))throw new Conflict('Unknown provider owner');
            if($e['source']!==$expected||$f['owner']!==$e['source']||$e['boundary']!==($expected==='logistics'?'carrier':'goods')||$e['causation_id']!==$f['intent_id']||$e['aggregate_id']!==$f['reference'])throw new Conflict('Provider cannot assert this outcome');
        }elseif(str_starts_with($e['type'],'storage.')&&$e['source']==='storage'&&$e['boundary']==='goods'){
            if(!in_array($e['type'],['storage.expect.completed.v1','storage.issue.completed.v1','storage.reserve.completed.v1','storage.pick.completed.v1','storage.transfer.completed.v1','storage.arrive.completed.v1','storage.release.completed.v1','storage.command.rejected.v1','storage.receive.completed.v1'],true))throw new Validation('Unsupported storage outcome');
        }elseif(str_starts_with($e['type'],'logistics.')&&$e['source']==='logistics'&&$e['boundary']==='carrier'){
            if(!in_array($e['type'],['logistics.request.completed.v1','logistics.assign.completed.v1','logistics.load.completed.v1','logistics.depart.completed.v1','logistics.arrive.completed.v1','logistics.unload.completed.v1','logistics.receive.completed.v1'],true))throw new Validation('Unsupported carrier outcome');
        }else throw new Validation('Unsupported shipping boundary event');
    }
    public static function output(array $e,string $kind,array $order,?array $line):array {
        $e['aggregate_id']=$e['event_id'];$e['aggregate_version']=1;$e['wall_time']=(new \DateTimeImmutable('now',new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s.uP');
        if($kind==='reserve'){$e['type']='storage.request.v1';$e['payload']=['sku'=>$line['sku'],'location'=>Settings::env('SHIPPING_STOCK_LOCATION','FINISHED-A'),'quantity'=>$line['quantity'],'purpose'=>'customer'];}
        elseif(in_array($kind,['pick','release'],true)){$e['type']='storage.'.$kind.'.v1';$e['payload']=['reference'=>$line['reservation_id']];}
        elseif($kind==='transfer'){$e['type']='storage.transfer.v1';$e['payload']=['reference'=>$line['reservation_id'],'destination'=>Settings::env('SHIPPING_STOCK_DESTINATION','DISPATCH'),'unit_destinations'=>$line['unit_destinations']];}
        elseif($kind==='produce'){$e['type']='manufacturing.demand.v1';$e['payload']=['product'=>$line['sku'],'line'=>Settings::env('SHIPPING_PRODUCTION_LINE','LINE-1'),'quantity'=>$line['quantity']];}
        elseif($kind==='dispatch'){$e['type']='logistics.request.v1';$e['payload']=['route'=>Settings::env('SHIPPING_CARRIER_ROUTE','DISPATCH-CUSTOMER'),'sku'=>$line['sku'],'quantity'=>$line['quantity'],'external_reference'=>$e['event_id'],'customer_destination'=>$order['destination'],'unit_ids'=>$line['unit_ids'],'unit_manifest'=>$line['unit_manifest']];}
        return $e;
    }
    public static function fact(Unit $u,array $r,array $e):array {
        if($e['type']==='shipping.fact.v1')return $e['payload'];
        $p=$e['payload'];$type=$e['type'];$id=null;$result=null;
        if(str_starts_with($type,'storage.')){
            if($type==='storage.command.rejected.v1'){
                Rules::fields($p,['action','reason','request']);Rules::text($p['reason']??null,1000);
                $i=$u->query('SELECT * FROM shipping_intents WHERE id=? AND run_id=?',[$e['causation_id'],$r['id']])[0]??null;if(!$i)return ['ignore'=>true];
                if($e['aggregate_id']!==$i['id']||($p['request']['action']??null)!==($i['kind']==='reserve'?'reserve':($i['kind']==='transfer'?'transfer':$i['kind'])))throw new Conflict('Rejected stock command identity mismatch');
                $line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$i['line_id']]);$o=$u->one('SELECT * FROM shipping_orders WHERE id=?',[$i['order_id']]);
                if($e['correlation_id']!==$o['correlation_id'])throw new Conflict('Rejected stock command correlation mismatch');
                return ['intent_id'=>$i['id'],'owner'=>'storage','result'=>$i['kind']==='reserve'&&str_contains($p['reason'],'Insufficient available stock')?'shortage':'failed','reference'=>$o['id'],'destination'=>$o['destination'],'sku'=>$line['sku'],'quantity'=>$line['quantity'],'reason'=>$p['reason']];
            }
            if(($p['run_id']??null)!==$r['id']||($p['id']??null)!==$e['aggregate_id']||($p['correlation_id']??null)!==$e['correlation_id']||($p['version']??null)!==$e['aggregate_version'])throw new Conflict('Stock fact metadata mismatch');
            Rules::uuid($p['id']);ShippingRules::code($p['sku']??null);Rules::integer($p['quantity']??null,1,10000);
            if($type==='storage.receive.completed.v1'){
                if(($p['status']??null)!=='received')throw new Conflict('Supply must be physically received');
                $i=$u->query("SELECT i.* FROM shipping_intents i JOIN shipping_orders o ON o.id=i.order_id JOIN shipping_lines l ON l.id=i.line_id WHERE i.run_id=? AND i.kind='produce' AND i.state='pending' AND o.correlation_id=? AND l.sku=?",[$r['id'],$e['correlation_id'],$p['sku']])[0]??null;
                if(!$i)return ['ignore'=>true];return ['supply'=>true,'intent_id'=>$i['id'],'order_id'=>$i['order_id'],'line_id'=>$i['line_id'],'detail'=>['owner'=>'storage','fact_id'=>$e['event_id'],'quantity'=>$p['quantity']]];
            }
            if(in_array($type,['storage.expect.completed.v1','storage.issue.completed.v1'],true))return ['ignore'=>true];

            $kinds=['storage.reserve.completed.v1'=>['reserve','reserved'],'storage.pick.completed.v1'=>['pick','picked'],'storage.transfer.completed.v1'=>['transfer','transferred'],'storage.arrive.completed.v1'=>['receive','received'],'storage.release.completed.v1'=>['release','released']];
            if(!isset($kinds[$type]))throw new Conflict('Storage outcome has no matching shipping transition');
            [$kind,$result]=$kinds[$type];
            if($kind==='receive')$matches=$u->query("SELECT i.* FROM shipping_intents i JOIN shipping_lines l ON l.id=i.line_id WHERE i.run_id=? AND i.kind='receive' AND l.transfer_id=?",[$r['id'],$p['id']??'']);
            else $matches=$u->query('SELECT * FROM shipping_intents WHERE id=? AND run_id=? AND kind=?',[$e['causation_id'],$r['id'],$kind]);
            $i=$matches[0]??null;if(!$i)return ['ignore'=>true];$id=$i['id'];
            $line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$i['line_id']]);
            if(in_array($kind,['pick','release'],true)&&$p['id']!==$line['reservation_id'])throw new Conflict('Stock outcome changed the reservation identity');
            if(in_array($kind,['transfer','receive'],true)&&(($p['reservation_id']??null)!==$line['reservation_id']||($p['origin']??null)!==Settings::env('SHIPPING_STOCK_LOCATION','FINISHED-A')||($p['destination']??null)!==Settings::env('SHIPPING_STOCK_DESTINATION','DISPATCH')))throw new Conflict('Stock movement reference or physical destination mismatch');
            if($kind==='receive'&&$p['id']!==$line['transfer_id'])throw new Conflict('Arrival changed the physical transfer identity');

            if(($p['run_id']??null)!==$r['id']||($p['id']??null)!==$e['aggregate_id']||($p['correlation_id']??null)!==$e['correlation_id']||($p['version']??null)!==$e['aggregate_version'])throw new Conflict('Stock fact metadata mismatch');
            $expected=match($kind){'reserve'=>'reserved','pick'=>'picked','transfer'=>'in_transit','receive'=>'received','release'=>'released'};
            if(($p['status']??null)!==$expected)throw new Conflict('Stock fact has wrong physical state');
        }elseif(str_starts_with($type,'logistics.')){
            $dispatch=$u->query("SELECT * FROM shipping_intents WHERE id=? AND run_id=? AND kind='dispatch'",[$p['external_reference']??'',$r['id']])[0]??null;if(!$dispatch)return ['ignore'=>true];
            $line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$dispatch['line_id']]);$order=$u->one('SELECT * FROM shipping_orders WHERE id=?',[$dispatch['order_id']]);if(($p['sku']??null)!==$line['sku']||($p['quantity']??null)!==$line['quantity']||($p['customer_destination']??$p['destination']??null)!==$order['destination'])throw new Conflict('Carrier cargo or destination mismatch');
            if(($p['id']??null)!==$e['aggregate_id']||($p['run_id']??null)!==$r['id']||($p['epoch']??null)!==$r['epoch']||($p['correlation_id']??null)!==$e['correlation_id']||($p['version']??null)!==$e['aggregate_version'])throw new Conflict('Carrier fact metadata mismatch');
            if($type==='logistics.depart.completed.v1'&&($p['status']??null)==='in_transit'){$i=$dispatch;$result='departed';}
            elseif($type==='logistics.receive.completed.v1'&&($p['status']??null)==='received'&&($p['custody']??null)==='destination'){if(($dispatch['response']['peer_reference']??null)!==($p['id']??null))throw new Conflict('Carrier receipt changed the confirmed journey');$i=$u->query("SELECT * FROM shipping_intents WHERE order_id=? AND line_id=? AND kind='deliver'",[$dispatch['order_id'],$dispatch['line_id']])[0]??throw new Conflict('Carrier receipt preceded confirmed departure');$result='delivered';}
            else {
                $state=['logistics.request.completed.v1'=>'requested','logistics.assign.completed.v1'=>'assigned','logistics.load.completed.v1'=>'loaded','logistics.arrive.completed.v1'=>'arrived','logistics.unload.completed.v1'=>'unloaded'][$type]??null;
                if(!$state||($p['status']??null)!==$state)throw new Conflict('Carrier state differs from event type');
                if($state==='assigned'){$ids=$p['unit_ids']??[];$expected=$line['unit_ids'];if(!is_array($ids)||!array_is_list($ids))throw new Conflict('Assigned carrier requires exact whole-unit identities');sort($ids);sort($expected);if($ids!==$expected||!$ids)throw new Conflict('Assigned carrier changed the whole-unit manifest');$destinations=$p['unit_destinations']??[];if(!is_array($destinations))throw new Conflict('Assigned carrier requires exact receiving endpoints');$keys=array_keys($destinations);sort($keys);if($keys!==$expected)throw new Conflict('Assigned receiving endpoints differ from the whole manifest');foreach($destinations as $endpoint){if(!is_string($endpoint)||!str_starts_with($endpoint,'logistics.outbound.staging'))throw new Conflict('Carrier receiving endpoint must be a fixed staging position');HandlingUnits::endpoint($endpoint,'logistics','finished');}if(count(array_unique($destinations))!==count($destinations))throw new Conflict('Assigned units cannot share a receiving endpoint');}
                return ['progress'=>true,'order_id'=>$dispatch['order_id'],'event'=>$type,'detail'=>['owner'=>'logistics','fact_id'=>$e['event_id'],'status'=>$state,'line_id'=>$line['id'],'dispatch_id'=>$dispatch['id'],'unit_destinations'=>$p['unit_destinations']??[]]];
            }
            $id=$i['id'];
        }else throw new Conflict('Unsupported peer fact');
        $order=$u->one('SELECT * FROM shipping_orders WHERE id=?',[$i['order_id']]);$reference=$result==='delivered'?$u->one('SELECT id FROM shipping_shipments WHERE order_id=?',[$order['id']])['id']:$order['id'];
        return ShippingRules::fact(['intent_id'=>$id,'owner'=>$e['source'],'result'=>$result,'reference'=>$reference,'destination'=>$order['destination'],'sku'=>$p['sku'],'quantity'=>$p['quantity'],'peer_reference'=>$p['id']]);
    }
}
