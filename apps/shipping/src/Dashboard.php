<?php
declare(strict_types=1);
namespace Shipping;
use Livewire\Component;
use Livewire\Attributes\Locked;
final class Dashboard extends Component
{
    public string $dueAt='1',$quantity='1',$confirmation='',$speed='1',$error='';
    #[Locked] public string $idempotencyKey='';
    #[Locked] public array $auditRows=[];
    public function boot():void {$this->identity();}
    private function identity():array {$identity=app(Settings::class)->sessionPrincipal(session('shipping.identity'));abort_unless($identity,401);abort_unless(in_array('status:read',$identity['scopes'],true),403);return $identity;}
    public function mount():void {$value=app(Ledger::class)->status();$this->dueAt=(string)(max($value['run']['granted'],$value['run']['requested'])+app(Settings::class)->quantum);$this->speed=(string)$value['run']['speed'];$this->idempotencyKey=Rules::uuid4();}
    public function updated(string $name):void {if(in_array($name,['dueAt','quantity'],true))$this->idempotencyKey=Rules::uuid4();}
    private function command(string $scope,string $action,callable $handler):void {
        $identity=$this->identity();$ledger=app(Ledger::class);$audit=['actor'=>$identity['username'],'role'=>$identity['role'],'request_id'=>Rules::uuid4(),'action'=>$action,'idempotency_key'=>$scope==='jobs:write'?$this->idempotencyKey:'','peer'=>request()->ip()??''];$status=0;$this->error='';
        try{$audit['run_id']=$ledger->scope();if(!in_array($scope,$identity['scopes'],true)){$status=403;throw new \RuntimeException('This identity cannot perform the requested action');}$handler($ledger,$audit);}
        catch(Validation $e){$status=422;$this->error=$e->getMessage();}catch(Conflict $e){$status=409;$this->error=$e->getMessage();}catch(\PDOException){$status=503;$this->error='Database unavailable; retry the same command';}catch(\Throwable $e){$status=$status?:500;$this->error=$status===403?$e->getMessage():'Unable to process command';}
        finally{if($status&&isset($audit['run_id']))try{$ledger->rejected($audit,$status);}catch(\Throwable){error_log('Web command audit unavailable request_id='.$audit['request_id']);}}
    }
    public function schedule():void {$this->command('jobs:write','POST /api/jobs',function($ledger,$audit){if(!preg_match('/^[1-9]\d{0,4}$/D',$this->quantity)||!is_numeric($this->dueAt))throw new Validation('A numeric due time and whole item quantity are required');$job=Rules::job(['due_at'=>(float)$this->dueAt,'quantity'=>(int)$this->quantity]);$ledger->schedule($this->idempotencyKey,$job['due_at'],$job['quantity'],$audit);$this->idempotencyKey=Rules::uuid4();});}
    public function control(mixed $action):void {$this->command('runs:control','POST /api/control/'.(is_string($action)?$action:'invalid'),function($ledger,$audit)use($action){$action=Rules::text($action);$body=[];if($action==='reset')$body=['confirm_run_id'=>$this->confirmation];if($action==='speed'){if(!preg_match('/^\d+$/D',$this->speed))throw new Validation('Integer speed required');$body=['speed'=>(int)$this->speed];}$ledger->control($action,$body,$audit);if($action==='reset')$this->confirmation='';});}
    public function loadAudit():void {$this->command('audit:read','GET /api/audit',function($ledger){$this->auditRows=$ledger->auditEvents();});}
    public function render():\Illuminate\Contracts\View\View {$identity=$this->identity();$status=null;$unavailable='';try{$status=app(Ledger::class)->status();$status['simulation_time']=(new Scenario($status['run']['scenario']))->instant($status['run']['granted'])->format('Y-m-d\TH:i:sP');}catch(\PDOException){$unavailable='Database unavailable; waiting for status';}return view('dashboard',['status'=>$status,'identity'=>$identity,'providers'=>app(Settings::class)->providers,'quantum'=>app(Settings::class)->quantum,'operator'=>in_array('runs:control',$identity['scopes'],true),'canSchedule'=>in_array('jobs:write',$identity['scopes'],true),'unavailable'=>$unavailable]);}
}
