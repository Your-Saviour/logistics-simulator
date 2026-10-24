<?php
declare(strict_types=1);
namespace Shipping;

/** Destination custody protocol. All calls run under the native run/command lock. */
final class HandlingHandoffs
{
    public static function validate(array $h):void {
        $required=['id','run_id','epoch','source','destination_owner','origin','destination','state','unit','departure_token','receipt_id','reason'];Rules::fields($h,$required);foreach($required as $field)if(!array_key_exists($field,$h))throw new Validation('Complete custody shape required: '.$field);
        Rules::text($h['origin'],128);Rules::text($h['destination'],128);if($h['reason']!==null&&!is_string($h['reason']))throw new Validation('Custody reason must be text or null');
        foreach(['id','run_id','epoch'] as $field)Rules::uuid($h[$field]??null);
        if(!in_array($h['destination_owner']??null,['storage','manufacturing','logistics','shipping'],true)||!in_array($h['source']??null,['storage','manufacturing','logistics','shipping'],true)||$h['source']===$h['destination_owner']||!in_array($h['state']??null,['offered','accepted','departed','received','acknowledged'],true))throw new Validation('Unsupported destination custody transition');
        $unit=$h['unit']??null;if(!is_array($unit))throw new Validation('Whole-unit custody manifest required');
        $required=['id','barcode','run_id','epoch','contents','category','state','owner','version','custody_generation','last_sequence','position','origin','destination','handoff_id'];Rules::fields($unit,$required);foreach($required as $field)if(!array_key_exists($field,$unit))throw new Validation('Complete custody unit shape required: '.$field);
        Rules::uuid($unit['id']??null);$contents=$unit['contents']??null;
        if(!is_array($contents)||!array_is_list($contents)||count($contents)!==1||!is_array($contents[0]))throw new Validation('Shipping requires one complete SKU per handling unit');
        Rules::fields($contents[0],['sku','quantity']);ShippingRules::code($contents[0]['sku']??null);Rules::integer($contents[0]['quantity']??null,1,10000);
        if(($unit['barcode']??null)!=='HU-'.strtoupper(str_replace('-','',$unit['id']))||($unit['run_id']??null)!==$h['run_id']||($unit['epoch']??null)!==$h['epoch']||($unit['owner']??null)!==$h['source']||($unit['category']??null)!=='finished')throw new Conflict('Custody identity, scope or contents mismatch');
        foreach(['version'=>1,'custody_generation'=>0,'last_sequence'=>0] as $field=>$min)Rules::integer($unit[$field]??null,$min,PHP_INT_MAX);
        HandlingUnits::endpoint($h['origin']??'', $h['source'],'finished');HandlingUnits::endpoint($h['destination']??'',$h['destination_owner'],'finished');
        if(in_array($h['state'],['offered','accepted'],true)){
            if($unit['state']!=='reserved'||$unit['position']!==$h['origin']||($unit['origin']??null)!==null||($unit['destination']??null)!==null||($unit['handoff_id']??null)!==null||($h['departure_token']??null)!==null||($h['receipt_id']??null)!==null)throw new Conflict('Offer must retain reserved source placement');
        }else{
            $token=$h['departure_token']??null;if(!is_array($token))throw new Validation('Durable source departure token required');
            Rules::fields($token,['id','handoff_id','unit_id','run_id','epoch','custody_generation','last_sequence','unit_version']);Rules::uuid($token['id']??null);
            $expected=['handoff_id'=>$h['id'],'unit_id'=>$unit['id'],'run_id'=>$h['run_id'],'epoch'=>$h['epoch'],'custody_generation'=>$unit['custody_generation'],'last_sequence'=>$unit['last_sequence'],'unit_version'=>$unit['version']];
            foreach($expected as $key=>$value)if(($token[$key]??null)!==$value)throw new Conflict('Departure token identity or version mismatch');
            if($unit['state']!=='in_transit'||$unit['position']!==null||$unit['origin']!==$h['origin']||$unit['destination']!==$h['destination']||$unit['handoff_id']!==$h['id']||$unit['custody_generation']<1||$unit['last_sequence']<1)throw new Conflict('Departure requires unplaced source custody');
            if(in_array($h['state'],['received','acknowledged'],true))Rules::uuid($h['receipt_id']??null);
        }
    }
    public static function receive(Unit $u,array $r,Settings $s,array $h,string $correlation,string $command):array {
        self::validate($h);if($h['destination_owner']!=='shipping'||!in_array($h['state'],['offered','departed','acknowledged'],true))throw new Conflict('Not a Shipping destination transition');if($h['run_id']!==$r['id']||$h['epoch']!==$r['epoch'])throw new Conflict('Handoff belongs to another run/epoch; reconcile before reset');
        $old=$u->query('SELECT * FROM shipping_handling_handoffs WHERE id=?',[$h['id']])[0]??null;
        if($old&&$old['correlation_id']!==$correlation)throw new Conflict('Handoff correlation changed');
        if($h['state']==='offered'){
            if($old){if($old['offer']!=$h)throw new Conflict('Handoff identity changed');return $old['acceptance'];}
            if($u->query('SELECT 1 FROM shipping_handling_units WHERE id=?',[$h['unit']['id']]))throw new Conflict('Barcode already known; explicit returning-custody reconciliation required');
            if($u->query("SELECT 1 FROM shipping_handling_handoffs WHERE run_id=? AND epoch=? AND state='accepted' AND unit_id=?",[$r['id'],$r['epoch'],$h['unit']['id']]))throw new Conflict('Whole-unit identity already has an accepted handoff');
            if($u->query("SELECT 1 FROM shipping_handling_handoffs WHERE run_id=? AND epoch=? AND state='accepted' AND destination=?",[$r['id'],$r['epoch'],$h['destination']])||$u->query('SELECT 1 FROM shipping_handling_units WHERE run_id=? AND epoch=? AND position=?',[$r['id'],$r['epoch'],$h['destination']]))throw new CustodyCapacity('Destination capacity unavailable; identical offer can retry after the slot becomes free');
            $accepted=[...$h,'state'=>'accepted'];$u->execute('INSERT INTO shipping_handling_handoffs(id,run_id,epoch,unit_id,destination,correlation_id,state,offer,acceptance,command_id) VALUES (?,?,?,?,?,?,?,?,?,?)',[$h['id'],$r['id'],$r['epoch'],$h['unit']['id'],$h['destination'],$correlation,'accepted',$h,$accepted,$command]);self::publish($u,$r,$s,$accepted,$correlation);return $accepted;
        }
        if(!$old)throw new Conflict('Departure cannot precede durable capacity acceptance');
        $base=$old['offer'];foreach(['id','run_id','epoch','source','destination_owner','origin','destination'] as $field)if($base[$field]!==$h[$field])throw new Conflict('Departure changed accepted handoff');
        $expected=[...$base['unit'],'state'=>'in_transit','position'=>null,'origin'=>$base['origin'],'destination'=>$base['destination'],'handoff_id'=>$base['id'],'custody_generation'=>$base['unit']['custody_generation']+1,'last_sequence'=>$base['unit']['last_sequence']+1,'version'=>$base['unit']['version']+1];
        if($expected!=$h['unit'])throw new Conflict('Departure changed immutable contents or skipped custody sequence');
        if($old['receipt']){
            $received=$old['receipt'];if($h['state']==='acknowledged'&&$h['receipt_id']!==$received['receipt_id'])throw new Conflict('Acknowledgement changed receipt identity');$check=[...$h,'state'=>'received','receipt_id'=>$received['receipt_id']];if($check!=$received)throw new Conflict('Departure proof conflicts with confirmed receipt');
            if($h['state']==='acknowledged'){$u->execute("UPDATE shipping_handling_handoffs SET state='acknowledged' WHERE id=?",[$h['id']]);return [...$received,'state'=>'acknowledged'];}return $received;
        }
        if($h['state']!=='departed')throw new Conflict('Acknowledgement cannot precede receipt');
        // Only this receiver writes its confirmed position. Source placement was
        // already removed in the durable departure represented by this token.
        HandlingUnits::import($u,$r,$command,$h,$correlation);
        $received=[...$h,'state'=>'received','receipt_id'=>Rules::uuid5($h['id'],'shipping-receipt')];$u->execute("UPDATE shipping_handling_handoffs SET state='received',receipt=? WHERE id=?",[$received,$h['id']]);self::publish($u,$r,$s,$received,$correlation);return $received;
    }
    public static function offer(Unit $u,array $r,Settings $s,string $unitId,string $owner,string $destination,string $correlation,string $command):array {
        $id=Rules::uuid5($command,$unitId);$old=$u->query('SELECT offer FROM shipping_handling_departures WHERE id=?',[$id])[0]??null;
        if($old){$offer=$old['offer'];if($offer['destination_owner']!==$owner||$offer['destination']!==$destination)throw new Conflict('Departure command identity changed');return $offer;}
        $unit=$u->one('SELECT * FROM shipping_handling_units WHERE id=? AND run_id=? AND epoch=?',[$unitId,$r['id'],$r['epoch']]);
        if($unit['state']!=='reserved'||$unit['position']===null||$u->query("SELECT 1 FROM shipping_handling_departures WHERE unit_id=? AND state IN ('offered','departed')",[$unitId]))throw new Conflict('Reserved unit has a pending departure or no confirmed placement');
        $h=['id'=>$id,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'source'=>'shipping','destination_owner'=>$owner,'origin'=>$unit['position'],'destination'=>$destination,'state'=>'offered','unit'=>HandlingUnits::contract($unit),'departure_token'=>null,'receipt_id'=>null,'reason'=>null];self::validate($h);
        $u->execute("INSERT INTO shipping_handling_departures(id,run_id,epoch,unit_id,correlation_id,state,offer,command_id) VALUES (?,?,?,?,?,'offered',?,?)",[$id,$r['id'],$r['epoch'],$unitId,$correlation,$h,$command]);self::publish($u,$r,$s,$h,$correlation);return $h;
    }
    public static function source(Unit $u,array $r,Settings $s,array $h,string $correlation,string $command):array {
        self::validate($h);if($h['source']!=='shipping'||!in_array($h['state'],['accepted','received'],true)||$h['run_id']!==$r['id']||$h['epoch']!==$r['epoch'])throw new Conflict('Source custody scope or transition mismatch');
        $row=$u->one('SELECT * FROM shipping_handling_departures WHERE id=? AND run_id=? AND epoch=?',[$h['id'],$r['id'],$r['epoch']]);if($row['correlation_id']!==$correlation)throw new Conflict('Departure correlation changed');
        if($h['state']==='accepted'){
            if([...$h,'state'=>'offered']!=$row['offer'])throw new Conflict('Acceptance changed the offered unit or endpoints');if($row['departure'])return $row['departure'];
            $unit=$u->one('SELECT * FROM shipping_handling_units WHERE id=?',[$h['unit']['id']]);if(HandlingUnits::contract($unit)!=$h['unit'])throw new Conflict('Source unit changed after offer; destination remains reserved for reconciliation');
            $unit=HandlingUnits::depart($u,$r,$command,$h,$correlation);
            $token=['id'=>Rules::uuid5($h['id'],'shipping-departure'),'handoff_id'=>$h['id'],'unit_id'=>$unit['id'],'run_id'=>$r['id'],'epoch'=>$r['epoch'],'custody_generation'=>$unit['custody_generation'],'last_sequence'=>$unit['last_sequence'],'unit_version'=>$unit['version']];
            $departed=[...$h,'state'=>'departed','unit'=>$unit,'departure_token'=>$token];$u->execute("UPDATE shipping_handling_departures SET state='departed',departure=? WHERE id=?",[$departed,$h['id']]);self::publish($u,$r,$s,$departed,$correlation);return $departed;
        }
        if(!$row['departure']||[...$h,'state'=>'departed','receipt_id'=>null]!=$row['departure'])throw new Conflict('Receipt does not prove this exact source departure');
        $ack=[...$h,'state'=>'acknowledged'];if($row['acknowledgement']){if($row['acknowledgement']!=$ack)throw new Conflict('Receipt identity changed after acknowledgement');return $row['acknowledgement'];}
        $unit=$u->one('SELECT * FROM shipping_handling_units WHERE id=?',[$h['unit']['id']]);if($unit['state']!=='in_transit'||$unit['handoff_id']!==$h['id']||$unit['custody_generation']!==$h['departure_token']['custody_generation'])throw new Conflict('Late receipt cannot retire newer source custody');
        $u->execute("UPDATE shipping_handling_units SET state='dispatched',version=version+1 WHERE id=?",[$unit['id']]);$u->execute("UPDATE shipping_handling_departures SET state='acknowledged',acknowledgement=? WHERE id=?",[$ack,$h['id']]);self::publish($u,$r,$s,$ack,$correlation);return $ack;
    }
    /** Republish only unresolved protocol stages, with bounded wall-clock retry. */
    public static function recover(Unit $u,array $r):int {
        $rows=$u->query("WITH pending AS (SELECT id,state FROM shipping_handling_departures WHERE run_id=? AND epoch=? AND state IN ('offered','departed') UNION ALL SELECT id,state FROM shipping_handling_handoffs WHERE run_id=? AND epoch=? AND state IN ('accepted','received')) SELECT DISTINCT b.envelope FROM boundary_outbox b JOIN pending p ON p.id::text=b.envelope->'payload'->>'id' AND p.state=b.envelope->'payload'->>'state' WHERE b.run_id=? AND b.envelope->>'type' LIKE 'handling.%' AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'type' LIKE 'handling.%' AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds'))",[$r['id'],$r['epoch'],$r['id'],$r['epoch'],$r['id']]);
        foreach($rows as $row)$u->execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (?,?,?)',[Rules::uuid4(),$r['id'],$row['envelope']]);return count($rows);
    }
    public static function replay(Unit $u,array $r,array $incoming):void {
        $reply=match($incoming['payload']['state']){'offered'=>'accepted','accepted'=>'departed','departed'=>'received','received'=>'acknowledged',default=>null};if(!$reply)return;
        $event=Rules::uuid5($incoming['payload']['id'],'shipping:'.$reply);
        $rows=$u->query("SELECT envelope FROM boundary_outbox b WHERE b.run_id=? AND b.envelope->>'type' LIKE 'handling.%' AND b.envelope->>'event_id'=? AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'type' LIKE 'handling.%' AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds')) LIMIT 1",[$r['id'],$event]);
        if($rows)$u->execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (?,?,?)',[Rules::uuid4(),$r['id'],$rows[0]['envelope']]);
    }
    private static function publish(Unit $u,array $r,Settings $s,array $h,string $correlation):void {
        $id=Rules::uuid5($h['id'],'shipping:'.$h['state']);$recipient=$h['source']==='shipping'?$h['destination_owner']:$h['source'];
        $e=['schema_version'=>'1.0','type'=>'handling.'.$h['state'].'.v1','event_id'=>$id,'federation_id'=>$s->federationId,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$correlation,'causation_id'=>$h['id'],'aggregate_id'=>$h['id'],'aggregate_version'=>$h['unit']['version'],'source'=>'shipping','destination'=>$recipient,'boundary'=>match($recipient){'logistics'=>'transport','manufacturing'=>'supply',default=>'requests'},'effective_time'=>$r['granted']+$s->quantum,'wall_time'=>(new \DateTimeImmutable('now',new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s.uP'),'quantity_unit'=>'item','payload'=>$h];
        $u->execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING',[$id,$r['id'],$e]);
    }
}
