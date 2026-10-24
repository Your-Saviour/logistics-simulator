<?php
declare(strict_types=1);
namespace Shipping;
final class Adapter
{
    private readonly string $session;
    public function __construct(private readonly Ledger $ledger,private readonly Settings $settings,private readonly array $initialRun){$this->session=Rules::uuid4();}
    private function current(Unit $u):array {$r=$u->run();if($r['id']!==$this->initialRun['id']||$r['epoch']!==$this->initialRun['epoch'])throw new Conflict('Stale adapter controller session');return $r;}
    public function begin():void {$this->ledger->db->transaction(function($u){$r=$this->current($u);if($u->query('SELECT 1 FROM shipping_adapter_sessions WHERE run_id=?',[$r['id']]))throw new Conflict('Native session cannot resume from SQL; coordinate a new federation epoch');$u->execute('INSERT INTO shipping_adapter_sessions(run_id,epoch,session_id) VALUES (?,?,?)',[$r['id'],$r['epoch'],$this->session]);});}
    public function command(string $operation,array $payload,?string $key=null):array {
        $key??=Rules::uuid4();$record=$this->ledger->db->transaction(function($u)use($operation,$payload,$key){$this->current($u);$old=$u->query('SELECT * FROM shipping_adapter_operations WHERE session_id=? AND operation_key=?',[$this->session,$key])[0]??null;if($old){if($old['request']['operation']!==$operation)throw new Conflict('Adapter operation key reused for a different operation');return $old;}
            if($operation==='poll')$u->execute("UPDATE shipping_adapter_sessions SET native_pending=true,native_state='polling' WHERE session_id=?",[$this->session]);
            $id=Rules::uuid4();$request=['version'=>'1.0','request_id'=>$id,'run_id'=>$this->initialRun['id'],'epoch'=>$this->initialRun['epoch'],'session_id'=>$this->session,'operation'=>$operation,'payload'=>(object)$payload];return $u->one('INSERT INTO shipping_adapter_operations(request_id,session_id,operation_key,request) VALUES (?,?,?,?) RETURNING *',[$id,$this->session,$key,$request]);
        });
        if($record['response']!==null)return $record['response'];$request=$record['request'];$request['payload']=(object)$request['payload'];$json=json_encode($request,JSON_THROW_ON_ERROR|JSON_PRESERVE_ZERO_FRACTION);
        for($attempt=0;$attempt<3;$attempt++){$curl=curl_init(rtrim($this->settings->adapterUrl,'/').'/v1/commands');curl_setopt_array($curl,[CURLOPT_POST=>true,CURLOPT_POSTFIELDS=>$json,CURLOPT_HTTPHEADER=>['Content-Type: application/json','Authorization: Bearer '.$this->settings->adapterToken],CURLOPT_RETURNTRANSFER=>true,CURLOPT_CONNECTTIMEOUT=>3,CURLOPT_TIMEOUT=>5]);$raw=curl_exec($curl);$status=(int)curl_getinfo($curl,CURLINFO_RESPONSE_CODE);curl_close($curl);
            if($raw===false||$status>=500||$status===0){usleep(200000);continue;}if($status!==200)throw new Conflict('Adapter rejected operation; coordinated recovery may be required');$body=Rules::object($raw);if(($body['version']??null)!=='1.0'||($body['request_id']??null)!==$record['request_id']||!is_array($body['result']??null))throw new Conflict('Adapter response identity/schema mismatch');$result=$body['result'];$this->ledger->db->transaction(function($u)use($record,$result){$this->current($u);$u->execute('UPDATE shipping_adapter_operations SET response=? WHERE request_id=?',[$result,$record['request_id']]);});return $result;
        }throw new Conflict('Adapter lost; native state is ambiguous and a coordinated new epoch is required');
    }
    public function pollSettled(array $poll):void {$this->ledger->db->transaction(function($u)use($poll){$this->current($u);$state=Rules::text($poll['state']??null);if(!is_bool($poll['pending']??null))throw new Validation('Adapter pending flag required');$u->execute('UPDATE shipping_adapter_sessions SET native_pending=?,native_state=? WHERE session_id=?',[$poll['pending']||$state!=='executing',$state,$this->session]);});}
    public function settle(array $r):void {
        $rows=$this->ledger->db->transaction(function($u){$r=$this->current($u);return $u->query('SELECT * FROM boundary_outbox WHERE run_id=? AND sent_at IS NULL ORDER BY id',[$r['id']]);});
        foreach($rows as $row){$sample=$row['envelope'];foreach($this->settings->outputs as $output){$endpoint=Rules::text($output['endpoint']??null);$job=Rules::uuid($sample['job_id']);$envelope=['schema_version'=>'1.0','type'=>'sample.completed.v1','event_id'=>$row['id'],'federation_id'=>$this->settings->federationId,'run_id'=>$r['id'],'epoch'=>$r['epoch'],'correlation_id'=>$job,'causation_id'=>$job,'aggregate_id'=>$job,'aggregate_version'=>1,'source'=>'shipping','destination'=>Rules::text($output['destination']??null),'boundary'=>Rules::text($output['boundary']??null),'effective_time'=>$r['granted']+$this->settings->quantum,'wall_time'=>(new \DateTimeImmutable('now',new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s.uP'),'quantity_unit'=>'item','payload'=>['quantity'=>$sample['quantity']]];$this->command('publish',['endpoint'=>$endpoint,'envelope'=>$envelope],'publish:'.$row['id'].':'.$endpoint);}
            $this->ledger->db->transaction(function($u)use($row){$this->current($u);$u->execute('UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE id=?',[$row['id']]);});
        }
        $effects=$this->ledger->status()['effects'];$this->command('publish_value',['value'=>(float)$effects,'unit'=>'item'],'value:'.$effects);
    }
    public function finalized():void {$this->ledger->db->transaction(function($u){$r=$this->current($u);$u->execute("UPDATE shipping_adapter_sessions SET native_pending=false,native_state='finalized' WHERE session_id=?",[$this->session]);$u->execute("UPDATE runs SET state='finalized' WHERE id=?",[$r['id']]);});}
}
