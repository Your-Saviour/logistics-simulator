<?php
declare(strict_types=1);
namespace Shipping;

/** Invoked inside the existing run lock, command transaction and savepoint. */
final class HandlingUnits
{
    private static ?array $locations=null;
    private static function catalog():array {
        if(self::$locations===null){$catalog=json_decode(file_get_contents(__DIR__.'/../handling-facility.json'),true,512,JSON_THROW_ON_ERROR);self::$locations=[];foreach($catalog['locations'] as $location)self::$locations[$location['id']]=$location;}
        return self::$locations;
    }
    public static function manifest(array $units,int $quantity):array {
        if(!array_is_list($units)||count($units)<1||count($units)>256)throw new Validation('Explicit whole-unit manifest of 1..256 units required');
        $seen=[];$total=0;foreach($units as &$unit){if(!is_array($unit))throw new Validation('Unit manifest object required');Rules::fields($unit,['id','quantity']);$unit['id']=Rules::uuid($unit['id']??null);$unit['quantity']=Rules::integer($unit['quantity']??null,1,10000);$unit=['id'=>$unit['id'],'quantity'=>$unit['quantity']];if(isset($seen[$unit['id']]))throw new Validation('Duplicate handling-unit identity');$seen[$unit['id']]=true;$total+=$unit['quantity'];}unset($unit);
        if($total!==$quantity)throw new Validation('Whole-unit contents must exactly match the complete quantity');return $units;
    }
    public static function endpoint(string $id,string $owner,string $category):array {
        $location=self::catalog()[$id]??null;if(!$location||$location['owner']!==$owner||!in_array($category,$location['compatible'],true))throw new Validation('Unknown or incompatible custody endpoint');return $location;
    }
    public static function import(Unit $u,array $r,string $command,array $h,string $correlation):void {
        $source=$h['unit'];$item=$source['contents'][0];
        if($u->query('SELECT 1 FROM shipping_handling_units WHERE run_id=? AND epoch=? AND position=?',[$r['id'],$r['epoch'],$h['destination']]))throw new Conflict('Accepted destination is occupied; preserve source transit for recovery');
        $line=$u->query("SELECT l.* FROM shipping_lines l JOIN shipping_orders o ON o.id=l.order_id JOIN shipping_unit_plans p ON p.line_id=l.id WHERE p.unit_id=? AND p.provider='storage' AND p.state='expected' AND o.run_id=? AND o.correlation_id=?",[$source['id'],$r['id'],$correlation])[0]??null;
        if(!$line)$line=$u->query("SELECT l.* FROM shipping_lines l JOIN shipping_orders o ON o.id=l.order_id JOIN shipping_intents i ON i.line_id=l.id AND i.kind='receive' AND i.state='pending' WHERE o.run_id=? AND o.correlation_id=? AND l.sku=?",[$r['id'],$correlation,$item['sku']])[0]??null;
        if($line){$quantity=$u->one("SELECT COALESCE(sum(h.quantity),0) AS n FROM shipping_handling_units h JOIN shipping_unit_allocations a ON a.unit_id=h.id AND a.active WHERE a.line_id=?",[$line['id']])['n'];if($quantity+$item['quantity']>$line['quantity'])throw new Conflict('Receipt would overfulfil the complete line');}
        $unit=$u->one("INSERT INTO shipping_handling_units(id,barcode,run_id,epoch,sku,quantity,state,position,command_id,version,last_sequence,custody_generation,line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING *",[$source['id'],$source['barcode'],$r['id'],$r['epoch'],$item['sku'],$item['quantity'],$line?'reserved':'available',$h['destination'],$command,$source['version'],$source['last_sequence'],$source['custody_generation'],$line['id']??null]);
        if($line){$u->execute('INSERT INTO shipping_unit_allocations(line_id,unit_id) VALUES (?,?)',[$line['id'],$unit['id']]);$ids=array_values(array_unique([...$line['unit_ids'],$unit['id']]));sort($ids);$u->execute('UPDATE shipping_lines SET unit_ids=? WHERE id=?',[$ids,$line['id']]);}
        self::movement($u,$r,$command,$unit,'receive',$h['origin'],$h['destination'],$correlation);$u->execute("UPDATE shipping_unit_plans SET state='received' WHERE unit_id=? AND provider='storage'",[$source['id']]);
    }
    public static function positions():array {$locations=self::catalog();ksort($locations);$result=[];foreach($locations as $id=>$location)if($location['owner']==='shipping'&&in_array('finished',$location['compatible'],true))$result[]=$id;return $result;}
    public static function freePositions(Unit $u,array $r):array {
        $occupied=array_column($u->query('SELECT position FROM shipping_handling_units WHERE run_id=? AND epoch=? AND position IS NOT NULL',[$r['id'],$r['epoch']]),'position');
        $occupied=[...$occupied,...array_column($u->query("SELECT destination FROM shipping_handling_handoffs WHERE run_id=? AND epoch=? AND state='accepted'",[$r['id'],$r['epoch']]),'destination')];
        $occupied=[...$occupied,...array_column($u->query("SELECT destination FROM shipping_unit_plans WHERE run_id=? AND state='expected' AND destination IS NOT NULL",[$r['id']]),'destination')];
        return array_values(array_diff(self::positions(),$occupied));
    }
    public static function freePosition(Unit $u,array $r):string {return self::freePositions($u,$r)[0]??throw new Conflict('No Shipping staging slot capacity; free a position and retry the receipt');}
    public static function counterRoom(array $unit,bool $movement=false,bool $generation=false):void {
        if($unit['version']>=2147483647||($movement&&$unit['last_sequence']>=2147483647)||($generation&&$unit['custody_generation']>=2147483647))throw new Conflict('Handling-unit counter capacity exhausted; reconcile before further movement');
    }
    private static function movement(Unit $u,array $r,string $command,array $unit,string $action,?string $origin,string $destination,string $correlation,?string $shipment=null):void {
        self::counterRoom($unit,true);$updated=$u->one('UPDATE shipping_handling_units SET last_sequence=last_sequence+1,version=version+1 WHERE id=? RETURNING *',[$unit['id']]);
        $u->execute('INSERT INTO shipping_unit_movements(id,unit_id,barcode,run_id,epoch,command_id,sequence,custody_generation,action,origin,destination,simulation_time,"references",correlation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[Rules::uuid4(),$unit['id'],$unit['barcode'],$r['id'],$r['epoch'],$command,$updated['last_sequence'],$updated['custody_generation'],$action,$origin,$destination,$r['granted'],['transfer_id'=>null,'batch_id'=>null,'shipment_id'=>$shipment],$correlation]);
    }
    public static function intake(Unit $u,array $r,string $command,string $sku,array $manifest,?array $line=null,?string $correlation=null):array {
        $ids=[];foreach($manifest as $entry){if($u->query('SELECT 1 FROM shipping_handling_units WHERE id=?',[$entry['id']]))throw new Conflict('Handling-unit identity already exists; replay the original receipt');$position=self::freePosition($u,$r);
            $unit=$u->one('INSERT INTO shipping_handling_units(id,barcode,run_id,epoch,sku,quantity,state,position,command_id,line_id) VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING *',[$entry['id'],'HU-'.strtoupper(str_replace('-','',$entry['id'])),$r['id'],$r['epoch'],$sku,$entry['quantity'],$line?'reserved':'available',$position,$command,$line['id']??null]);
            if($line)$u->execute('INSERT INTO shipping_unit_allocations(line_id,unit_id) VALUES (?,?)',[$line['id'],$unit['id']]);
            self::movement($u,$r,$command,$unit,'receive',null,$position,$correlation??$command);$ids[]=$unit['id'];
        }return $ids;
    }
    public static function reserveLocal(Unit $u,array $r,array $line):?array {
        $paths=[0=>[]];foreach($u->query("SELECT * FROM shipping_handling_units WHERE run_id=? AND epoch=? AND sku=? AND state='available' ORDER BY id",[$r['id'],$r['epoch'],$line['sku']]) as $unit){foreach($paths as $total=>$ids){$next=$total+$unit['quantity'];if($next<=$line['quantity']&&!isset($paths[$next]))$paths[$next]=[...$ids,$unit['id']];}if(isset($paths[$line['quantity']]))break;}
        $ids=$paths[$line['quantity']]??null;if($ids===null)return null;
        foreach($ids as $id){self::counterRoom($u->one('SELECT * FROM shipping_handling_units WHERE id=?',[$id]));$u->execute("UPDATE shipping_handling_units SET state='reserved',line_id=?,version=version+1 WHERE id=?",[$line['id'],$id]);$u->execute('INSERT INTO shipping_unit_allocations(line_id,unit_id) VALUES (?,?)',[$line['id'],$id]);}
        $u->execute('UPDATE shipping_lines SET reserved=quantity,received=quantity,unit_ids=? WHERE id=?',[$ids,$line['id']]);return $ids;
    }
    public static function planSynthetic(Unit $u,array $r,array $line):array {
        $existing=$u->query("SELECT unit_id AS id,quantity FROM shipping_unit_plans WHERE line_id=? AND state='expected' ORDER BY unit_id",[$line['id']]);if($existing)return $existing;
        // Initial synthetic stock consists of whole one-item units. A replenished
        // order instead receives one newly produced unit of its exact quantity.
        $sizes=($line['replenished']??false)?[$line['quantity']]:array_fill(0,$line['quantity'],1);$manifest=[];
        foreach($sizes as $index=>$quantity){$id=Rules::uuid5($line['id'],'synthetic-unit:'.$index);$u->execute('INSERT INTO shipping_unit_plans(unit_id,run_id,line_id,sku,quantity,provider) VALUES (?,?,?,?,?,?)',[$id,$r['id'],$line['id'],$line['sku'],$quantity,'synthetic']);$manifest[]=['id'=>$id,'quantity'=>$quantity];}
        $u->execute('UPDATE shipping_lines SET unit_ids=? WHERE id=?',[array_column($manifest,'id'),$line['id']]);return $manifest;
    }
    public static function planned(Unit $u,array $line):array {return $u->query("SELECT unit_id AS id,quantity FROM shipping_unit_plans WHERE line_id=? AND state='expected' ORDER BY unit_id",[$line['id']]);}
    public static function receiveSynthetic(Unit $u,array $r,string $command,array $line,array $manifest,string $correlation):void {
        $manifest=self::manifest($manifest,$line['quantity']);$expected=self::planned($u,$line);$sorted=$manifest;usort($sorted,fn($a,$b)=>strcmp($a['id'],$b['id']));if($expected!==$sorted)throw new Conflict('Receipt must preserve the reserved whole-unit manifest');
        self::intake($u,$r,$command,$line['sku'],$manifest,$line,$correlation);$u->execute("UPDATE shipping_unit_plans SET state='received' WHERE line_id=? AND state='expected'",[$line['id']]);
    }
    public static function requireLine(Unit $u,array $r,array $line):array {
        $units=$u->query("SELECT h.* FROM shipping_handling_units h JOIN shipping_unit_allocations a ON a.unit_id=h.id AND a.active WHERE h.run_id=? AND h.epoch=? AND a.line_id=? AND h.line_id=? AND h.state='reserved' AND h.position IS NOT NULL ORDER BY h.id",[$r['id'],$r['epoch'],$line['id'],$line['id']]);
        if(array_sum(array_column($units,'quantity'))!==$line['quantity']||array_filter($units,fn($unit)=>$unit['sku']!==$line['sku']))throw new Conflict('Confirmed whole-unit custody receipt required; quantity-only facts cannot place goods');return $units;
    }
    private static function requireNoPendingDeparture(Unit $u,array $line):void {
        if($u->query("SELECT 1 FROM shipping_handling_departures d JOIN shipping_handling_units h ON h.id=d.unit_id WHERE h.line_id=? AND d.state IN ('offered','departed')",[$line['id']]))throw new Conflict('Pending whole-unit custody offer must settle before release or another departure');
    }
    public static function releaseLocal(Unit $u,array $r,array $line):bool {
        self::requireNoPendingDeparture($u,$line);
        $units=$u->query("SELECT * FROM shipping_handling_units WHERE run_id=? AND line_id=? AND state='reserved'",[$r['id'],$line['id']]);if(!$units)return false;foreach($units as $unit)self::counterRoom($unit);
        $u->execute("UPDATE shipping_handling_units SET state='available',line_id=NULL,version=version+1 WHERE run_id=? AND line_id=? AND state='reserved'",[$r['id'],$line['id']]);$u->execute('UPDATE shipping_unit_allocations SET active=false WHERE line_id=?',[$line['id']]);$u->execute('UPDATE shipping_lines SET reserved=0 WHERE id=?',[$line['id']]);return true;
    }
    public static function releasePlan(Unit $u,array $line):void {
        if($u->query("SELECT 1 FROM shipping_unit_plans p LEFT JOIN shipping_handling_units h ON h.id=p.unit_id LEFT JOIN shipping_handling_handoffs c ON c.unit_id=p.unit_id AND c.state='accepted' WHERE p.line_id=? AND p.provider='storage' AND (h.id IS NOT NULL OR c.id IS NOT NULL)",[$line['id']]))throw new Conflict('Source release cannot reverse accepted or received whole-unit custody');
        $u->execute("DELETE FROM shipping_unit_plans WHERE line_id=? AND provider='storage' AND state='expected'",[$line['id']]);$u->execute("UPDATE shipping_goods_reservations SET state='released',reason=NULL WHERE line_id=?",[$line['id']]);$u->execute("UPDATE shipping_unit_plans SET state='released' WHERE line_id=? AND state='expected'",[$line['id']]);}
    private static function carrierPosition(Unit $u,array $r,int $quantity):string {
        $pending=$u->query("SELECT destination,quantity FROM shipping_handling_units WHERE run_id=? AND epoch=? AND state='in_transit'",[$r['id'],$r['epoch']]);$used=array_column($pending,'destination');$locations=self::catalog();ksort($locations);
        foreach($locations as $id=>$location)if($location['owner']==='logistics'&&str_starts_with($id,'logistics.outbound.truck')&&!in_array($id,$used,true)){
            $prefix=substr($id,0,strrpos($id,'.slot'));$load=0;foreach($pending as $unit)if(str_starts_with($unit['destination'],$prefix.'.slot'))$load+=$unit['quantity'];if($load+$quantity<=10000)return $id;
        }throw new Conflict('Synthetic carrier physical slots or load capacity unavailable; goods remain at Shipping');
    }
    public static function depart(Unit $u,array $r,string $command,array $h,string $correlation):array {
        $unit=$h['unit'];self::counterRoom($unit,true,true);$shipment=$u->query('SELECT s.id FROM shipping_shipments s JOIN shipping_lines l ON l.order_id=s.order_id JOIN shipping_handling_units h ON h.line_id=l.id WHERE h.id=?',[$unit['id']])[0]['id']??null;
        $u->execute("UPDATE shipping_handling_units SET state='in_transit',origin=position,position=NULL,destination=?,handoff_id=?,custody_generation=custody_generation+1,shipment_id=? WHERE id=?",[$h['destination'],$h['id'],$shipment,$unit['id']]);self::movement($u,$r,$command,$unit,'load',$h['origin'],$h['destination'],$correlation,$shipment);
        return self::contract($u->one('SELECT * FROM shipping_handling_units WHERE id=?',[$unit['id']]));
    }
    public static function requireDeparture(Unit $u,array $r,array $line,string $shipment):void {
        $units=$u->query("SELECT h.* FROM shipping_handling_units h JOIN shipping_unit_allocations a ON a.unit_id=h.id AND a.active JOIN shipping_handling_departures d ON d.id=h.handoff_id AND d.unit_id=h.id AND d.state IN ('departed','acknowledged') WHERE h.run_id=? AND h.epoch=? AND a.line_id=? AND h.line_id=? AND h.shipment_id=? AND h.position IS NULL AND h.state IN ('in_transit','dispatched') AND h.custody_generation=(d.departure->'departure_token'->>'custody_generation')::integer",[$r['id'],$r['epoch'],$line['id'],$line['id'],$shipment]);
        if(array_sum(array_column($units,'quantity'))!==$line['quantity']||array_filter($units,fn($unit)=>$unit['sku']!==$line['sku']))throw new Conflict('Carrier must accept whole-unit custody before departure can be confirmed');
    }
    public static function departSynthetic(Unit $u,array $r,string $command,array $line,string $shipment,string $correlation):void {
        self::requireNoPendingDeparture($u,$line);
        foreach(self::requireLine($u,$r,$line) as $unit){self::counterRoom($unit,true,true);$destination=self::carrierPosition($u,$r,$unit['quantity']);$u->execute("UPDATE shipping_handling_units SET state='in_transit',origin=position,position=NULL,destination=?,handoff_id=?,shipment_id=?,custody_generation=custody_generation+1 WHERE id=?",[$destination,Rules::uuid5($shipment,$unit['id']),$shipment,$unit['id']]);self::movement($u,$r,$command,$unit,'load',$unit['position'],$destination,$correlation,$shipment);}
    }
    public static function delivered(Unit $u,array $r,array $line,string $shipment):void {
        $units=$u->query("SELECT * FROM shipping_handling_units WHERE run_id=? AND epoch=? AND line_id=? AND shipment_id=? AND state IN ('in_transit','dispatched')",[$r['id'],$r['epoch'],$line['id'],$shipment]);
        if(array_sum(array_column($units,'quantity'))!==$line['quantity'])throw new Conflict('Carrier receipt must reference the allocated whole units');foreach($units as $unit)self::counterRoom($unit);$u->execute("UPDATE shipping_handling_units SET state='dispatched',position=NULL,version=version+1 WHERE run_id=? AND line_id=? AND shipment_id=?",[$r['id'],$line['id'],$shipment]);$u->execute('UPDATE shipping_unit_allocations SET active=false WHERE line_id=?',[$line['id']]);
    }
    public static function contract(array $unit):array {
        $result=['owner'=>'shipping','contents'=>[['sku'=>$unit['sku'],'quantity'=>$unit['quantity']]]];foreach(['id','barcode','run_id','epoch','version','last_sequence','custody_generation','category','state','position','origin','destination','handoff_id'] as $field)$result[$field]=$unit[$field];return $result;
    }
    public static function snapshot(Unit $u,array $r):array {
        return ['version'=>1,'catalog_version'=>1,'units'=>array_map(self::contract(...),$u->query('SELECT * FROM shipping_handling_units WHERE run_id=? AND epoch=? ORDER BY id',[$r['id'],$r['epoch']])),
            'movements'=>$u->query('SELECT id,unit_id,barcode,run_id,epoch,sequence,custody_generation,action,origin,destination,simulation_time,"references",correlation_id FROM shipping_unit_movements WHERE run_id=? AND epoch=? ORDER BY unit_id,sequence',[$r['id'],$r['epoch']]),
            'goods_reservations'=>$u->query('SELECT * FROM shipping_goods_reservations WHERE run_id=? ORDER BY id',[$r['id']]),'plans'=>$u->query('SELECT * FROM shipping_unit_plans WHERE run_id=? ORDER BY unit_id',[$r['id']]),'handoffs'=>[...array_map(fn($row)=>[...($row['receipt']??$row['acceptance']),'state'=>$row['state']],$u->query('SELECT state,acceptance,receipt FROM shipping_handling_handoffs WHERE run_id=? AND epoch=? ORDER BY id',[$r['id'],$r['epoch']])),...array_map(fn($row)=>$row['acknowledgement']??$row['departure']??$row['offer'],$u->query('SELECT offer,departure,acknowledgement FROM shipping_handling_departures WHERE run_id=? AND epoch=? ORDER BY id',[$r['id'],$r['epoch']]))],'lineage'=>[]];
    }
}
