<?php
declare(strict_types=1);
namespace Shipping;

/** Reservation facts promise exact units and slots; departure proofs create custody. */
final class GoodsPlans
{
    private static function observations(Unit $u,string $id):array {return $u->query("SELECT g.state,manifest.value AS unit FROM shipping_goods_reservations g CROSS JOIN LATERAL jsonb_array_elements(g.fact->'payload'->'unit_manifest') manifest(value) WHERE manifest.value->>'id'=?",[$id]);}
    public static function reserve(Unit $u,array $r,array $e,array $intent):void {
        $p=$e['payload'];$old=$u->query('SELECT * FROM shipping_goods_reservations WHERE id=?',[$p['id']])[0]??null;
        if($old){if($old['fact']!=$e)throw new Conflict('Reserved goods manifest changed');return;}
        $line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$intent['line_id']]);$units=$p['unit_manifest']??null;
        if(!is_array($units)||!array_is_list($units)||count($units)<1||count($units)>8||($p['purpose']??null)!=='customer'||($p['status']??null)!=='reserved'||($p['location']??null)!==Settings::env('SHIPPING_STOCK_LOCATION','FINISHED-A'))throw new Conflict('Native reservation requires one to eight canonical whole finished units');
        $seen=[];$total=0;
        foreach($units as $n=>$unit){
            if(!is_array($unit))throw new Validation('Canonical source unit required');$id=Rules::uuid($unit['id']??null);if(isset($seen[$id])||$u->query('SELECT 1 FROM shipping_unit_plans WHERE unit_id=? UNION ALL SELECT 1 FROM shipping_handling_units WHERE id=?',[$id,$id]))throw new Conflict('Reserved barcode already assigned or known');$seen[$id]=true;
            foreach(self::observations($u,$id) as $known){if($known['state']!=='released')throw new Conflict('Barcode already promised by another reserved manifest');foreach(['id','barcode','contents','category','run_id','epoch','owner'] as $field)if($known['unit'][$field]!=$unit[$field])throw new Conflict('Released reservation cannot change immutable unit identity or contents');if($unit['version']<=$known['unit']['version']||$unit['last_sequence']<$known['unit']['last_sequence']||$unit['custody_generation']!==$known['unit']['custody_generation'])throw new Conflict('Replacement reservation must continue the released source unit counters');}
            $h=['id'=>$p['id'],'run_id'=>$r['id'],'epoch'=>$r['epoch'],'source'=>'storage','destination_owner'=>'shipping','origin'=>$unit['position']??null,'destination'=>'shipping.outbound.dock01','state'=>'offered','unit'=>$unit,'departure_token'=>null,'receipt_id'=>null,'reason'=>null];HandlingHandoffs::validate($h);
            if($unit['owner']!=='storage'||$unit['run_id']!==$r['id']||$unit['epoch']!==$r['epoch']||$unit['contents'][0]['sku']!==$line['sku']||$unit['version']>2147483644||$unit['last_sequence']>2147483644||$unit['custody_generation']>2147483646)throw new Conflict('Selected goods differ from the line or lack pick/departure/receipt headroom');$total+=$unit['contents'][0]['quantity'];
        }
        if($total!==$line['quantity']||$p['quantity']!==$line['quantity'])throw new Conflict('Reserved units must exactly equal the complete line');
        $u->execute('INSERT INTO shipping_goods_reservations(id,run_id,epoch,line_id,fact) VALUES (?,?,?,?,?)',[$p['id'],$r['id'],$r['epoch'],$line['id'],$e]);
        $ids=array_keys($seen);sort($ids);$u->execute('UPDATE shipping_lines SET unit_ids=? WHERE id=?',[$ids,$line['id']]);
    }
    public static function admit(Unit $u,array $r,array $order):?string {
        $group=$u->query("SELECT g.*,l.sku,l.quantity FROM shipping_goods_reservations g JOIN shipping_lines l ON l.id=g.line_id WHERE l.order_id=? AND l.received<>l.quantity ORDER BY g.line_id",[$order['id']]);
        $missing=$u->query('SELECT l.id FROM shipping_lines l LEFT JOIN shipping_goods_reservations g ON g.line_id=l.id WHERE l.order_id=? AND l.received<>l.quantity AND g.id IS NULL',[$order['id']]);if($missing)throw new Conflict('Every external line requires a canonical reserved unit manifest before admission');
        if($group&&!array_filter($group,fn($g)=>$g['state']!=='admitted'))return null;
        $count=0;foreach($group as $g)$count+=count($g['fact']['payload']['unit_manifest']);$owned=(int)$u->one('SELECT count(*) n FROM shipping_unit_allocations a JOIN shipping_lines l ON l.id=a.line_id WHERE l.order_id=? AND a.active',[$order['id']])['n'];
        if($count+$owned>count(HandlingUnits::positions())){ $reason='Whole order requires '.($count+$owned).' unit positions; fixed Shipping capacity is '.count(HandlingUnits::positions());$u->execute("UPDATE shipping_goods_reservations SET state='blocked',reason=? WHERE line_id IN (SELECT id FROM shipping_lines WHERE order_id=?)",[$reason,$order['id']]);return $reason;}
        $available=HandlingUnits::freePositions($u,$r);if(count($available)<$count)throw new CustodyCapacity('Shipping receiving capacity unavailable for the whole order; no partial slots were claimed');$next=0;
        foreach($group as $g){foreach($g['fact']['payload']['unit_manifest'] as $unit)$u->execute('INSERT INTO shipping_unit_plans(unit_id,run_id,line_id,sku,quantity,provider,reservation_id,source_manifest,destination) VALUES (?,?,?,?,?,?,?,?,?)',[$unit['id'],$r['id'],$g['line_id'],$g['sku'],$unit['contents'][0]['quantity'],'storage',$g['id'],$unit,$available[$next++]]);$u->execute("UPDATE shipping_goods_reservations SET state='admitted',reason=NULL WHERE id=?",[$g['id']]);}return null;
    }
    public static function confirmed(Unit $u,array $r,array $line):bool {
        $proof=$u->one("SELECT COALESCE(sum(p.quantity),0) quantity,count(*) FILTER(WHERE p.state<>'received' OR NOT EXISTS(SELECT 1 FROM shipping_handling_handoffs h WHERE h.unit_id=p.unit_id AND h.run_id=p.run_id AND h.epoch=? AND h.state IN ('received','acknowledged') AND h.receipt IS NOT NULL AND h.destination=p.destination AND h.offer->>'source'='storage' AND h.correlation_id=(SELECT o.correlation_id FROM shipping_orders o JOIN shipping_lines l ON l.order_id=o.id WHERE l.id=p.line_id))) missing FROM shipping_unit_plans p WHERE p.run_id=? AND p.line_id=? AND p.provider='storage'",[$r['epoch'],$r['id'],$line['id']]);return $proof['quantity']===$line['quantity']&&$proof['missing']===0;
    }
    public static function received(Unit $u,array $r,string $unitId):void {
        $line=$u->query("SELECT l.* FROM shipping_lines l JOIN shipping_unit_plans p ON p.line_id=l.id WHERE p.unit_id=? AND p.provider='storage' AND p.run_id=?",[$unitId,$r['id']])[0]??null;if(!$line||$line['received']===$line['quantity']||!self::confirmed($u,$r,$line))return;
        $u->execute('UPDATE shipping_lines SET received=quantity WHERE id=?',[$line['id']]);$order=$u->one('SELECT * FROM shipping_orders WHERE id=?',[$line['order_id']]);$u->execute('INSERT INTO shipping_history(run_id,order_id,event,simulation_time,detail) VALUES (?,?,?,?,?)',[$r['id'],$order['id'],'whole_goods_received',$r['granted'],['line_id'=>$line['id'],'unit_ids'=>$line['unit_ids']]]);
        if(!$order['cancel_requested']&&in_array($order['status'],['awaiting_stock','awaiting_receipt'],true)&&!$u->query('SELECT 1 FROM shipping_lines WHERE order_id=? AND received<>quantity',[$order['id']]))$u->execute("UPDATE shipping_orders SET status='ready',version=version+1 WHERE id=?",[$order['id']]);
    }
    public static function destinations(Unit $u,array $line):array {
        $plans=$u->query("SELECT * FROM shipping_unit_plans WHERE line_id=? AND provider='storage' AND state='expected' ORDER BY unit_id",[$line['id']]);if(!$plans||array_sum(array_column($plans,'quantity'))!==$line['quantity'])throw new Conflict('Native transfer requires the exact reserved whole-unit receiving plan');$map=[];foreach($plans as $p){if(!$p['destination'])throw new Conflict('Native transfer lacks a receiving endpoint');$map[$p['unit_id']]=$p['destination'];}return $map;
    }
    public static function checkOffer(Unit $u,array $r,array $h,string $correlation):void {
        $plan=$u->query("SELECT p.*,o.correlation_id FROM shipping_unit_plans p JOIN shipping_lines l ON l.id=p.line_id JOIN shipping_orders o ON o.id=l.order_id WHERE p.unit_id=? AND p.run_id=? AND p.provider='storage'",[$h['unit']['id'],$r['id']])[0]??null;
        if(!$plan){foreach(self::observations($u,$h['unit']['id']) as $known)if($known['state']!=='released')throw new Conflict('Reserved barcode must wait for whole-order endpoint admission');if($u->query("SELECT 1 FROM shipping_orders o JOIN shipping_intents i ON i.order_id=o.id WHERE o.run_id=? AND o.correlation_id=? AND i.owner='storage' AND i.state='pending'",[$r['id'],$correlation]))throw new Conflict('Unplanned barcode cannot fulfil this Shipping order');return;}
        if($plan['state']!=='expected'||$plan['correlation_id']!==$correlation||$plan['destination']!==$h['destination'])throw new Conflict('Goods offer changed its reservation or receiving endpoint');$expected=$plan['source_manifest'];$expected['version']++;$expected['last_sequence']++;$expected['position']=$h['origin'];
        if(!str_starts_with($h['origin'],'storage.outbound.dock')||$expected!=$h['unit'])throw new Conflict('Goods offer differs from the canonical picked reservation');
    }
}
