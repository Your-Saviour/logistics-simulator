<?php
declare(strict_types=1);
namespace Shipping;
final class Fulfilment
{
    public function __construct(private readonly Database $db,private readonly Settings $settings){}
    public function prepare(string $key,array $fields,string $actor):array {
        $key=Rules::uuid($key);$fields=ShippingRules::command([...$fields,'due_at'=>0.0]);unset($fields['due_at']);
        return $this->db->transaction(function($u)use($key,$fields,$actor){$r=$u->run();if($fields['run_id']!==$r['id']||$fields['epoch']!==$r['epoch'])throw new Conflict('Shipping form belongs to another run/epoch');
            $old=$u->query('SELECT * FROM shipping_prepared_commands WHERE operation_key=?',[$key])[0]??null;
            if($old&&($old['actor']!==$actor||$old['fields']!=$fields))throw new Conflict('Prepared operation identity/body mismatch');
            if($old&&($u->query('SELECT 1 FROM jobs WHERE run_id=? AND idempotency_key=?',[$r['id'],$key])||$old['body']['due_at']>=max($r['granted'],$r['requested'])+$this->settings->quantum))return $old['body'];
            if(!in_array($r['state'],['running','held'],true))throw new Conflict('Cannot prepare a new command in a terminal run');
            $body=[...$fields,'due_at'=>max($r['granted'],$r['requested'])+2*$this->settings->quantum+$r['speed']];
            if($old)$u->execute('UPDATE shipping_prepared_commands SET body=? WHERE operation_key=?',[$body,$key]);
            else $u->execute('INSERT INTO shipping_prepared_commands(operation_key,run_id,actor,fields,body) VALUES (?,?,?,?,?)',[$key,$r['id'],$actor,$fields,$body]);return $body;
        });
    }
    public function submit(string $key,array $body,?array $audit=null):array {
        $body=ShippingRules::command($body);
        if(strlen($key)<1||strlen($key)>128)throw new Validation('Idempotency-Key length must be 1..128');
        foreach(['shipping:','synthetic:','boundary:','synthetic-sample:'] as $prefix)if(str_starts_with($key,$prefix))throw new Conflict('Reserved idempotency namespace');
        return $this->db->transaction(function($u)use($key,$body,$audit){$r=$u->run();return $this->schedule($u,$r,$key,$body,$audit);});
    }
    public function schedule(Unit $u,array $r,string $key,array $body,?array $audit=null,bool $internal=false):array {
        if($body['run_id']!==$r['id']||$body['epoch']!==$r['epoch'])throw new Conflict('Shipping command belongs to another run/epoch');
        $old=$u->query('SELECT c.*,j.due_at FROM shipping_commands c JOIN jobs j USING(id) WHERE c.run_id=? AND j.idempotency_key=?',[$r['id'],$key])[0]??null;
        if($old){if($old['body']!=$body)throw new Conflict('Idempotency key already used with different command');Ledger::audit($u,$r['id'],$audit,'accepted',200,$old['id']);return $old;}
        if($u->query('SELECT 1 FROM jobs WHERE run_id=? AND idempotency_key=?',[$r['id'],$key]))throw new Conflict('Idempotency key belongs to another command');
        if(!in_array($r['state'],['running','held'],true)||$body['due_at']<($internal?$r['granted']:max($r['granted'],$r['requested'])+$this->settings->quantum))throw new Conflict('Schedule beyond granted/requested time in an active run');
        $id=Rules::uuid4();$u->execute('INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (?,?,?,?,?,?,?)',[$id,$r['id'],$r['epoch'],$key,$body['due_at'],$body['due_at'],['shipping'=>$body]]);
        $row=$u->one('INSERT INTO shipping_commands(id,run_id,body) VALUES (?,?,?) RETURNING *',[$id,$r['id'],$body]);Ledger::audit($u,$r['id'],$audit,'accepted',200,$id);return [...$row,'due_at'=>$body['due_at']];
    }
    // Keep the run and its complete durable domain history behind the same writer lock.
    public function projection():array {return $this->db->transaction(function($u){
        $run=$u->run();$orders=[];
        foreach($u->query('SELECT id FROM shipping_orders WHERE run_id=? ORDER BY id',[$run['id']]) as $order)$orders[]=$this->record($u,$run,$order['id']);
        $snapshot=['run_id'=>$run['id'],'epoch'=>$run['epoch'],'orders'=>$orders,'handling'=>HandlingUnits::snapshot($u,$run),
            'shipments'=>$u->query('SELECT s.* FROM shipping_shipments s JOIN shipping_orders o ON o.id=s.order_id WHERE o.run_id=? ORDER BY s.id',[$run['id']]),
            'commands'=>$u->query('SELECT c.*,j.due_at,j.status AS job_status,j.attempts FROM shipping_commands c JOIN jobs j USING(id) WHERE c.run_id=? ORDER BY j.created_at,c.id',[$run['id']])];
        $events=$u->query('SELECT h.*,o.correlation_id FROM shipping_history h JOIN shipping_orders o ON o.id=h.order_id WHERE h.run_id=? ORDER BY h.sequence',[$run['id']]);
        foreach($events as &$event){$event['id']='shipping:history:'.$event['sequence'];$event['kind']='history';}unset($event);
        foreach($snapshot['handling']['movements'] as $movement){$movement['id']='shipping:unit-movement:'.$movement['id'];$movement['kind']='unit_movement';$events[]=$movement;}
        $value=['version'=>1,'source'=>'shipping','effects'=>(int)$u->one('SELECT COALESCE(sum(quantity),0) AS n FROM effects WHERE run_id=?',[$run['id']])['n'],'run'=>$run,'snapshot'=>$snapshot,'events'=>$events];
        $value['health']=['heartbeats'=>$u->query("SELECT role,seen_at,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats ORDER BY role"),
            'pending_jobs'=>(int)$u->one("SELECT count(*) AS n FROM jobs WHERE run_id=? AND status IN ('pending','queued')",[$run['id']])['n'],
            'dead_letters'=>(int)$u->one("SELECT count(*) AS n FROM jobs WHERE run_id=? AND status='dead'",[$run['id']])['n'],'broker'=>null,'ready'=>null];
        $value['cursor']=hash('sha256',json_encode($value,JSON_THROW_ON_ERROR|JSON_PRESERVE_ZERO_FRACTION));return $value;
    });}
    public function snapshot():array {return $this->db->transaction(function($u){$r=$u->run();$orders=[];foreach($u->query('SELECT id FROM shipping_orders WHERE run_id=? ORDER BY created_at DESC,id LIMIT 200',[$r['id']]) as $o)$orders[]=$this->record($u,$r,$o['id']);return ['run_id'=>$r['id'],'epoch'=>$r['epoch'],'orders'=>$orders,'handling'=>HandlingUnits::snapshot($u,$r),'shipments'=>$u->query('SELECT s.* FROM shipping_shipments s JOIN shipping_orders o ON o.id=s.order_id WHERE o.run_id=?',[$r['id']]),'commands'=>$u->query('SELECT c.*,j.due_at,j.status AS job_status,j.attempts FROM shipping_commands c JOIN jobs j USING(id) WHERE c.run_id=? ORDER BY j.created_at DESC,c.id DESC LIMIT 200',[$r['id']])];});}
    public static function canCancel(array $order):bool {return in_array($order['status'],['new','awaiting_stock','awaiting_receipt','shortage','cancelling','blocked'],true)&&isset($order['intents'])&&!array_filter($order['intents'],fn($intent)=>in_array($intent['kind'],['pick','transfer','receive','dispatch'],true));}
    public function order(string $id):array {$id=Rules::uuid($id);return $this->db->transaction(fn($u)=>$this->record($u,$u->run(),$id));}
    private function record(Unit $u,array $r,string $id):array {$o=$u->query('SELECT * FROM shipping_orders WHERE id=? AND run_id=?',[$id,$r['id']])[0]??throw new Conflict('Order does not exist in this run');$o['lines']=$u->query('SELECT * FROM shipping_lines WHERE order_id=? ORDER BY sku',[$id]);$o['shipment']=$u->query('SELECT * FROM shipping_shipments WHERE order_id=?',[$id])[0]??null;$o['history']=$u->query('SELECT * FROM shipping_history WHERE order_id=? ORDER BY sequence',[$id]);$o['intents']=$u->query('SELECT * FROM shipping_intents WHERE order_id=? ORDER BY id',[$id]);return $o;}
    private function history(Unit $u,array $r,string $order,string $event,array $detail=[]):void {$u->execute('INSERT INTO shipping_history(run_id,order_id,event,simulation_time,detail) VALUES (?,?,?,?,?)',[$r['id'],$order,$event,$r['granted'],(object)$detail]);}
    private function state(Unit $u,string $order,string $state):void {$u->execute('UPDATE shipping_orders SET status=?,version=version+1 WHERE id=?',[$state,$order]);}
    private function intent(Unit $u,array $r,array $o,string $kind,?array $line=null):string {
        if($kind==='release'&&$line&&HandlingUnits::releaseLocal($u,$r,$line)){$this->history($u,$r,$o['id'],'released_local_units',['line_id'=>$line['id']]);return $line['id'];}
        $id=Rules::uuid4();$owner=in_array($kind,['dispatch','deliver'],true)?'logistics':($kind==='produce'?'manufacturing':'storage');
        $request=['intent_id'=>$id,'order_id'=>$o['id'],'correlation_id'=>$o['correlation_id'],'destination'=>$o['destination'],'kind'=>$kind];
        if($line)$request+=$line;
        $u->execute('INSERT INTO shipping_intents(id,run_id,order_id,line_id,kind,owner,request) VALUES (?,?,?,?,?,?,?)',[$id,$r['id'],$o['id'],$line['id']??null,$kind,$owner,$request]);
        $boundary=in_array($kind,['dispatch','deliver'],true)?'carrier':'goods';
        if($this->settings->providers[$boundary]==='helics'&&in_array($kind,['receive','deliver'],true)){
            $this->history($u,$r,$o['id'],$kind.'_awaiting_confirmation',['intent_id'=>$id]);return $id;
        }
        if($this->settings->providers[$boundary]==='synthetic'){
            $result=match($kind){'reserve'=>!($line['replenished']??false)&&$line['quantity']>1+Rules::quantity((new Scenario($r['scenario']))->seed,'shipping','stock',0)%2?'shortage':'reserved','produce'=>'produced','pick'=>'picked','transfer'=>'transferred','receive'=>'received','release'=>'released','dispatch'=>'departed','deliver'=>'delivered'};
            $fact=['intent_id'=>$id,'owner'=>$owner,'result'=>$result,'reference'=>$kind==='deliver'?($u->one('SELECT id FROM shipping_shipments WHERE order_id=?',[$o['id']])['id']):$o['id'],'destination'=>$o['destination']];
            if($line)$fact+=['sku'=>$line['sku'],'quantity'=>$line['quantity']];
            if($line&&$kind==='reserve'&&$result==='reserved')$fact['units']=HandlingUnits::planSynthetic($u,$r,$line);
            if($line&&$kind==='receive')$fact['units']=HandlingUnits::planned($u,$line);
            $this->schedule($u,$r,'shipping:fact:'.$id,['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>$r['granted']+$this->settings->quantum,'action'=>'fact','fact'=>$fact],null,true);
        }else{
            $e=['schema_version'=>'1.0','type'=>'shipping.'.$kind.'.requested.v1','event_id'=>$id,'federation_id'=>$this->settings->federationId,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$o['correlation_id'],'causation_id'=>$o['id'],'aggregate_id'=>$o['id'],'aggregate_version'=>$o['version'],'source'=>'shipping','destination'=>$owner,'boundary'=>$owner==='storage'?'requests':($owner==='manufacturing'?'demand':'transport'),'effective_time'=>$r['granted']+$this->settings->quantum,'quantity_unit'=>'item','payload'=>$request];
            if($kind==='transfer')$line['unit_destinations']=GoodsPlans::destinations($u,$line);
            if($kind==='dispatch')$line['unit_manifest']=array_map(fn($unit)=>['id'=>$unit['id'],'quantity'=>$unit['quantity']],HandlingUnits::requireLine($u,$r,$line));
            $e=ShippingBoundary::output($e,$kind,$o,$line);
            $u->execute('INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (?,?,?)',[$id,$r['id'],$e]);
        }
        $this->history($u,$r,$o['id'],$kind.'_requested',['intent_id'=>$id,'provider'=>$this->settings->providers[$boundary]]);return $id;
    }
    public function execute(Unit $u,array $r,array $job):bool {
        $b=$job['payload']['shipping'];$id=$job['id'];$u->execute('SAVEPOINT shipping_effect');
        try{
            if($b['action']==='wire'&&str_starts_with($b['envelope']['type'],'handling.')){
                $e=$b['envelope'];if($e['payload']['source']==='shipping')HandlingHandoffs::source($u,$r,$this->settings,$e['payload'],$e['correlation_id'],$id);else HandlingHandoffs::receive($u,$r,$this->settings,$e['payload'],$e['correlation_id'],$id);$b=['action'=>'noop'];
            }elseif($b['action']==='wire')$b=$this->decodeWire($u,$r,$b['envelope']);
            if($b['action']==='noop'){}
            elseif($b['action']==='goods_admit'){$o=$this->record($u,$r,$b['reference']);if(!$o['cancel_requested']&&in_array($o['status'],['awaiting_stock','awaiting_receipt'],true)){ $reason=GoodsPlans::admit($u,$r,$o);if($reason!==null){$this->state($u,$o['id'],'blocked');$this->history($u,$r,$o['id'],'goods_admission_blocked',['reason'=>$reason]);}else{foreach($o['lines'] as $line)if($line['received']!==$line['quantity']&&!$u->query("SELECT 1 FROM shipping_intents WHERE order_id=? AND line_id=? AND kind='pick'",[$o['id'],$line['id']]))$this->intent($u,$r,$o,'pick',$line);}}}
            elseif($b['action']==='intake'){HandlingUnits::intake($u,$r,$id,$b['sku'],$b['units']);}
            elseif($b['action']==='create'){
                $u->execute('INSERT INTO shipping_orders(id,run_id,customer,destination,correlation_id,autonomous) VALUES (?,?,?,?,?,?)',[$id,$r['id'],$b['customer'],$b['destination'],$b['correlation_id']??$id,str_starts_with($job['idempotency_key'],'synthetic:')]);
                foreach($b['lines'] as $line)$u->execute('INSERT INTO shipping_lines(id,order_id,sku,quantity) VALUES (?,?,?,?)',[Rules::uuid5($id,$line['sku']),$id,$line['sku'],$line['quantity']]);$this->history($u,$r,$id,'created',['customer'=>$b['customer']]);
            }elseif($b['action']==='supply'){
                $i=$u->one('SELECT * FROM shipping_intents WHERE id=? AND run_id=?',[$b['intent_id'],$r['id']]);if($i['state']==='pending'){$u->execute("UPDATE shipping_intents SET state='completed',response=?,fact_id=? WHERE id=?",[$b['detail'],$id,$i['id']]);$o=$this->record($u,$r,$i['order_id']);$line=$u->one('SELECT * FROM shipping_lines WHERE id=?',[$i['line_id']]);$line['replenished']=true;$u->execute('UPDATE shipping_lines SET replenished=true WHERE id=?',[$line['id']]);$this->history($u,$r,$o['id'],'production_stock_received',$b['detail']);if($o['cancel_requested'])$this->cancelled($u,$r,$o['id']);else $this->intent($u,$r,$o,'reserve',$line);}
            }elseif($b['action']==='progress'){
                if($b['event']==='logistics.assign.completed.v1'){$o=$this->record($u,$r,$b['order_id']);if($o['status']==='awaiting_carrier'){$line=$u->one('SELECT * FROM shipping_lines WHERE id=? AND order_id=?',[$b['detail']['line_id'],$o['id']]);HandlingHandoffs::offerLine($u,$r,$this->settings,$line,$o['shipment']['id'],$o['correlation_id'],$b['detail']['unit_destinations']);}}
                $this->history($u,$r,$b['order_id'],$b['event'],$b['detail']);
            }elseif($b['action']==='fact'){$this->applyFact($u,$r,ShippingRules::fact($b['fact']),$id);}
            else{$o=$this->record($u,$r,$b['reference']);switch($b['action']){
                case 'fulfil':if($o['status']!=='new')throw new Conflict('Only new orders can request fulfilment');$this->state($u,$o['id'],'awaiting_stock');foreach($o['lines'] as $line){$units=HandlingUnits::reserveLocal($u,$r,$line);if($units!==null)$this->history($u,$r,$o['id'],'whole_units_allocated',['line_id'=>$line['id'],'unit_ids'=>$units]);else $this->intent($u,$r,$o,'reserve',$line);}if(!$u->query('SELECT 1 FROM shipping_lines WHERE order_id=? AND received<>quantity',[$o['id']]))$this->state($u,$o['id'],'ready');break;
                case 'pack':if($o['status']!=='ready'||array_filter($o['lines'],fn($l)=>$l['received']!==$l['quantity']))throw new Conflict('Packing requires every physical line received');foreach($o['lines'] as $line)HandlingUnits::requireLine($u,$r,$line);$this->state($u,$o['id'],'packed');break;
                case 'dispatch':if($o['status']!=='packed')throw new Conflict('Dispatch requires packed goods');foreach($o['lines'] as $line){$units=HandlingUnits::requireLine($u,$r,$line);if($this->settings->providers['carrier']==='helics'&&count($units)>8)throw new Conflict('Carrier accepts at most eight whole units per line; a compatible manifest is required');}$u->execute('INSERT INTO shipping_shipments(id,order_id) VALUES (?,?)',[$id,$o['id']]);$this->state($u,$o['id'],'awaiting_carrier');foreach($o['lines'] as $line)$this->intent($u,$r,$o,'dispatch',$line);break;
                case 'cancel':
                    if(!self::canCancel($o))throw new Conflict('Irreversible fulfilment has begun; cancellation is unsafe');
                    $u->execute('UPDATE shipping_orders SET cancel_requested=true WHERE id=?',[$o['id']]);$this->state($u,$o['id'],'cancelling');foreach($o['lines'] as $line)if($line['reserved']>0&&!$u->query("SELECT 1 FROM shipping_intents WHERE order_id=? AND line_id=? AND kind='release'",[$o['id'],$line['id']]))$this->intent($u,$r,$o,'release',$line);$this->cancelled($u,$r,$o['id']);break;
                default:throw new Validation('Unknown shipping action');
            }$this->history($u,$r,$o['id'],$b['action'],['command_id'=>$id]);}
            $u->execute("UPDATE shipping_commands SET outcome='completed',completed_at=? WHERE id=?",[$r['granted'],$id]);
        }catch(FleetWait $e){
            // Retain fleet intent and any committed transit stage, defer beyond
            // the current grant so HELICS remains free to request native time.
            $u->execute("UPDATE jobs SET status='pending',due_at=?,error=? WHERE id=?",[$r['granted']+$this->settings->quantum,$e->getMessage(),$id]);
            $u->execute('UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=?',[$id]);$u->execute('RELEASE SAVEPOINT shipping_effect');return false;
        }catch(Conflict|Validation|CustodyCapacity $e){$u->execute('ROLLBACK TO SAVEPOINT shipping_effect');
            $wire=$job['payload']['shipping']['envelope']??null;if(!($e instanceof CustodyCapacity)&&is_array($wire)&&str_starts_with($wire['type']??'','handling.'))CustodyQuarantine::record($u,$r,$wire,$job['payload']['shipping']['custody_endpoint']??'','apply',$e->getMessage(),$id);
            if($e instanceof CustodyCapacity&&$job['payload']['shipping']['action']==='goods_admit'){$u->execute("UPDATE jobs SET due_at=?,error=? WHERE id=?",[$r['granted']+$this->settings->quantum,$e->getMessage(),$id]);$u->execute('UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=?',[$id]);$u->execute('RELEASE SAVEPOINT shipping_effect');return false;}
$u->execute("UPDATE shipping_commands SET outcome='rejected',error=?,completed_at=?,retryable_capacity=? WHERE id=?",[$e->getMessage(),$r['granted'],$e instanceof CustodyCapacity,$id]);}
        $u->execute('RELEASE SAVEPOINT shipping_effect');return true;
    }
    private function cancelled(Unit $u,array $r,string $id):void {if(!$u->query("SELECT 1 FROM shipping_intents WHERE order_id=? AND state='pending'",[$id])&&!$u->query('SELECT 1 FROM shipping_lines WHERE order_id=? AND reserved>0',[$id])){$this->state($u,$id,'cancelled');$this->history($u,$r,$id,'cancelled');}}
    private function applyFact(Unit $u,array $r,array $f,string $event):void {
        $i=$u->query('SELECT * FROM shipping_intents WHERE id=? AND run_id=?',[$f['intent_id'],$r['id']])[0]??throw new Conflict('No matching provider intent');
        if($i['owner']!==$f['owner'])throw new Conflict('Provider does not own this outcome');
        if($i['state']!=='pending'){if($i['response']!=$f)throw new Conflict('Provider outcome conflicts with committed fact');return;}
        $o=$this->record($u,$r,$i['order_id']);$line=null;foreach($o['lines'] as $l)if($l['id']===$i['line_id'])$line=$l;
        $expected=$i['kind']==='deliver'?$o['shipment']['id']:$o['id'];
        if($f['reference']!==$expected||($f['destination']??null)!==$o['destination'])throw new Conflict('Outcome reference/destination mismatch');
        if($line&&(($f['sku']??null)!==$line['sku']||($f['quantity']??null)!==$line['quantity']))throw new Conflict('Outcome must match exact SKU and complete quantity');
        $allowed=match($i['kind']){'reserve'=>['reserved','shortage'],'produce'=>['produced'],'pick'=>['picked'],'transfer'=>['transferred'],'receive'=>['received'],'release'=>['released'],'dispatch'=>['departed'],'deliver'=>['delivered']};
        if($f['result']==='failed'){$u->execute("UPDATE shipping_intents SET state='failed',response=?,fact_id=? WHERE id=?",[$f,$event,$i['id']]);$this->state($u,$o['id'],'blocked');if($i['owner']==='logistics')$u->execute("UPDATE shipping_shipments SET status='blocked' WHERE order_id=?",[$o['id']]);$this->history($u,$r,$o['id'],'provider_rejected',['owner'=>$i['owner'],'intent_id'=>$i['id'],'reason'=>$f['reason']??'Provider declined the operation']);return;}
        if(!in_array($f['result'],$allowed,true))throw new Conflict('Outcome cannot confirm this intent');
        if(Fleet::enabled()&&$this->settings->providers['carrier']==='synthetic'&&in_array($i['kind'],['dispatch','deliver'],true))throw new FleetWait('Coordinated carrier requires native destination custody and physical arrival');
        $u->execute("UPDATE shipping_intents SET state='completed',response=?,fact_id=? WHERE id=?",[$f,$event,$i['id']]);
        $this->history($u,$r,$o['id'],$f['result'],['intent_id'=>$i['id'],'owner'=>$i['owner'],'fact_id'=>$event]);
        switch($f['result']){
            case 'shortage':if(!$o['cancel_requested']){$this->state($u,$o['id'],'shortage');$this->intent($u,$r,$o,'produce',$line);}break;
            case 'produced':$u->execute('UPDATE shipping_lines SET replenished=true WHERE id=?',[$line['id']]);$line['replenished']=true;if(!$o['cancel_requested'])$this->intent($u,$r,$o,'reserve',$line);break;
            case 'reserved':$u->execute('UPDATE shipping_lines SET reserved=quantity,reservation_id=? WHERE id=?',[$f['peer_reference']??$i['id'],$line['id']]);$line['reserved']=$line['quantity'];$line['reservation_id']=$f['peer_reference']??$i['id'];if($o['cancel_requested'])$this->intent($u,$r,$o,'release',$line);elseif(!$u->query('SELECT 1 FROM shipping_lines WHERE order_id=? AND reserved<>quantity',[$o['id']])){$this->state($u,$o['id'],'awaiting_receipt');if($this->settings->providers['goods']==='helics'){$key='shipping:goods-admit:'.$o['id'];if(!$u->query('SELECT 1 FROM jobs WHERE run_id=? AND idempotency_key=?',[$r['id'],$key]))$this->schedule($u,$r,$key,['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>$r['granted']+$this->settings->quantum,'action'=>'goods_admit','reference'=>$o['id']],null,true);}else foreach($this->record($u,$r,$o['id'])['lines'] as $l)if($l['received']!==$l['quantity'])$this->intent($u,$r,$o,'pick',$l);}break;
            case 'picked':$this->intent($u,$r,$o,'transfer',$line);break;
            case 'transferred':$u->execute('UPDATE shipping_lines SET transfer_id=? WHERE id=?',[$f['peer_reference']??$i['id'],$line['id']]);$line['transfer_id']=$f['peer_reference']??$i['id'];$this->intent($u,$r,$o,'receive',$line);break;
            case 'received':$already=$line['received']===$line['quantity'];if($this->settings->providers['goods']==='synthetic')HandlingUnits::receiveSynthetic($u,$r,$event,$line,$f['units']??[],$o['correlation_id']);elseif($already){if(!GoodsPlans::confirmed($u,$r,$line))throw new Conflict('Late source confirmation requires the durable complete custody receipts');}else HandlingUnits::requireLine($u,$r,$line);if(!$already){$u->execute('UPDATE shipping_lines SET received=quantity WHERE id=?',[$line['id']]);if(in_array($o['status'],['awaiting_stock','awaiting_receipt'],true)&&!$u->query('SELECT 1 FROM shipping_lines WHERE order_id=? AND received<>quantity',[$o['id']]))$this->state($u,$o['id'],'ready');}break;
            case 'released':HandlingUnits::releasePlan($u,$line);$u->execute('UPDATE shipping_lines SET reserved=0 WHERE id=?',[$line['id']]);break;
            case 'departed':if($this->settings->providers['carrier']==='synthetic')HandlingUnits::departSynthetic($u,$r,$event,$line,$o['shipment']['id'],$o['correlation_id']);else HandlingUnits::requireDeparture($u,$r,$line,$o['shipment']['id']);$u->execute("UPDATE shipping_shipments SET status=CASE WHEN status='blocked' THEN status ELSE 'in_transit' END,journey_id=? WHERE order_id=?",[$f['peer_reference']??$i['id'],$o['id']]);if($o['status']!=='blocked'&&!$u->query("SELECT 1 FROM shipping_intents WHERE order_id=? AND kind='dispatch' AND state<>'completed'",[$o['id']]))$this->state($u,$o['id'],'in_transit');$this->intent($u,$r,$o,'deliver',$line);break;
            case 'delivered':if(!in_array($o['status'],['in_transit','awaiting_carrier'],true))throw new Conflict('Delivery requires confirmed departure');HandlingUnits::delivered($u,$r,$line,$o['shipment']['id']);if(!$u->query("SELECT 1 FROM shipping_intents WHERE order_id=? AND kind IN ('dispatch','deliver') AND state<>'completed'",[$o['id']])&&(int)$u->one("SELECT count(*) AS n FROM shipping_intents WHERE order_id=? AND kind='deliver' AND state='completed'",[$o['id']])['n']===count($o['lines'])){$u->execute("UPDATE shipping_shipments SET status='delivered',confirmation_id=?,delivered_at=? WHERE order_id=?",[$event,$r['granted'],$o['id']]);$this->state($u,$o['id'],'delivered');}break;
        }
        if($o['cancel_requested'])$this->cancelled($u,$r,$o['id']);
    }
    public function ingest(array $e,string $endpoint):string {
        if(!str_starts_with($e['type']??'','handling.'))return $this->ingestValidated($e,$endpoint);
        ShippingBoundary::header($e);$routes=$this->settings->peers[$e['boundary']]??[];if(isset($routes['source']))$routes=[$routes];$authorized=false;foreach($routes as $route)if(($route['source']??null)===$e['source']&&($route['endpoint']??null)===$endpoint)$authorized=true;
        if(!$authorized||($this->settings->providers[$e['boundary']]??null)!=='helics'||$e['destination']!=='shipping'||$e['federation_id']!==$this->settings->federationId)throw new Conflict('Unconfigured custody peer');
        if($this->db->transaction(fn($u)=>CustodyQuarantine::seen($u,$u->run(),$e)))return 'quarantined';
        try{$result=$this->ingestValidated($e,$endpoint);if($result!=='fenced')return $result;$this->db->transaction(fn($u)=>CustodyQuarantine::record($u,$u->run(),$e,$endpoint,'ingest','Custody run or epoch mismatch'));}
        catch(Conflict|Validation $error){$this->db->transaction(fn($u)=>CustodyQuarantine::record($u,$u->run(),$e,$endpoint,'ingest',$error->getMessage()));}return 'quarantined';
    }
    private function ingestValidated(array $e,string $endpoint):string {
        ShippingBoundary::validate($e);
        $routes=$this->settings->peers[$e['boundary']]??[];if(isset($routes['source']))$routes=[$routes];
        $authorized=false;foreach($routes as $route)if(($route['source']??null)===$e['source']&&($route['endpoint']??null)===$endpoint)$authorized=true;
        if(!$authorized||($this->settings->providers[$e['boundary']]??null)!=='helics'||$e['destination']!=='shipping'||$e['federation_id']!==$this->settings->federationId)throw new Conflict('Boundary owner/routing mismatch');
        return $this->db->transaction(function($u)use($e,$endpoint){$r=$u->run();if($e['run_id']!==$r['id']||$e['epoch']!==$r['epoch'])return 'fenced';
            $old=$u->query('SELECT envelope FROM shipping_incoming_events WHERE event_id=?',[$e['event_id']])[0]??null;if($old){if($old['envelope']!=$e)throw new Conflict('Peer event identity reused with different content');if(str_starts_with($e['type'],'handling.')){
                $retry=$u->query('SELECT c.id FROM shipping_commands c JOIN jobs j USING(id) WHERE c.run_id=? AND j.idempotency_key=? AND c.retryable_capacity',[$r['id'],'boundary:'.$e['event_id']])[0]??null;
                if($retry){$u->execute("UPDATE shipping_commands SET outcome='pending',error=NULL,completed_at=NULL,retryable_capacity=false WHERE id=?",[$retry['id']]);$u->execute("UPDATE jobs SET status='pending',due_at=?,error=NULL,retry_after=clock_timestamp() WHERE id=?",[max($r['granted'],$e['effective_time']),$retry['id']]);$u->execute('UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=?',[$retry['id']]);}
                HandlingHandoffs::replay($u,$r,$e);
            }return 'duplicate';}
            if($e['effective_time']<$r['granted']&&!str_starts_with($e['type'],'handling.'))throw new Conflict('Late fact cannot change committed history');
            if($e['type']==='shipping.order.v1'&&$u->query("SELECT 1 FROM shipping_incoming_events WHERE run_id=? AND envelope->>'source'=? AND envelope->>'aggregate_id'=? AND envelope->>'type'='shipping.order.v1'",[$r['id'],$e['source'],$e['aggregate_id']]))throw new Conflict('Customer aggregate already accepted; replay original event identity');
            $body=$e['type']==='shipping.order.v1'?ShippingRules::command(['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>$e['effective_time'],'action'=>'create',...$e['payload']]):['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>$e['effective_time'],'action'=>'wire','envelope'=>$e];if(str_starts_with($e['type'],'handling.')){$body['due_at']=max($r['granted'],$e['effective_time']);$body['custody_endpoint']=$endpoint;}
            if($e['type']==='shipping.order.v1')$body['correlation_id']=$e['correlation_id'];
            $u->execute('INSERT INTO shipping_incoming_events(event_id,run_id,envelope) VALUES (?,?,?)',[$e['event_id'],$r['id'],$e]);$u->execute('INSERT INTO inbox(event_id,run_id,epoch) VALUES (?,?,?)',[$e['event_id'],$r['id'],$r['epoch']]);
            $this->schedule($u,$r,'boundary:'.$e['event_id'],$body,['actor'=>$e['source'],'role'=>'service','request_id'=>$e['event_id'],'action'=>'boundary:'.$e['type'],'peer'=>'helics'],true);return 'accepted';
        });
    }
    private function decodeWire(Unit $u,array $r,array $e):array {
        $fact=ShippingBoundary::fact($u,$r,$e);
        if(isset($fact['ignore']))return ['action'=>'noop'];
        if(isset($fact['supply']))return ['action'=>'supply','intent_id'=>$fact['intent_id'],'detail'=>$fact['detail']];
        if(isset($fact['progress']))return ['action'=>'progress','order_id'=>$fact['order_id'],'event'=>$fact['event'],'detail'=>$fact['detail']];
        $i=$u->query('SELECT * FROM shipping_intents WHERE id=? AND run_id=?',[$fact['intent_id'],$r['id']])[0]??throw new Conflict('Unknown provider intent');$o=$this->record($u,$r,$i['order_id']);
        if($i['owner']!==$e['source']||$e['correlation_id']!==$o['correlation_id']||($e['type']==='shipping.fact.v1'&&$e['causation_id']!==$i['id']))throw new Conflict('Fact owner or correlation does not match pending intent');
        if($e['type']==='storage.reserve.completed.v1')GoodsPlans::reserve($u,$r,$e,$i);
        return ['action'=>'fact','fact'=>$fact];
    }
    public function seed(Unit $u,array $r):void {
        $scenario=new Scenario($r['scenario']);$slot=(int)ceil((max($r['granted'],$r['requested'])+$this->settings->quantum)/$scenario->interval);$due=$scenario->nextDue(($slot-1)*$scenario->interval,(float)$scenario->interval);$slot=(int)ceil($due/$scenario->interval);
        if($this->settings->providers['orders']==='synthetic')$this->schedule($u,$r,'synthetic:shipping:'.$slot,['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>$due,'action'=>'create','customer'=>'CUSTOMER-'.$slot,'destination'=>'CUSTOMER-A','lines'=>[['sku'=>'PRODUCT','quantity'=>Rules::quantity($scenario->seed,'shipping','orders',$slot)]]],null,true);
        foreach($u->query("SELECT * FROM shipping_orders WHERE run_id=? AND autonomous AND status IN ('new','ready','packed')",[$r['id']]) as $o){$action=match($o['status']){'new'=>'fulfil','ready'=>'pack','packed'=>'dispatch'};if($u->query('SELECT 1 FROM jobs WHERE run_id=? AND idempotency_key=?',[$r['id'],'shipping:auto:'.$o['id'].':'.$action]))continue;$this->schedule($u,$r,'shipping:auto:'.$o['id'].':'.$action,['run_id'=>$r['id'],'epoch'=>$r['epoch'],'due_at'=>max($r['granted'],$r['requested'])+$this->settings->quantum,'action'=>$action,'reference'=>$o['id']],null,true);}
    }
}
