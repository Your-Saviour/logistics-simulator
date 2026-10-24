<?php
declare(strict_types=1);
namespace Shipping;
use Livewire\Component;
use Livewire\Attributes\Locked;
final class OrderDesk extends Component
{
    public string $customer='',$destination='CUSTOMER-A',$search='',$queue='all',$selected='',$error='',$notice='';
    public string $unitSearch='',$selectedUnit='';
    public array $lines=[['sku'=>'PRODUCT','quantity'=>'1']];
    #[Locked] public array $pending=[];
    #[Locked] public string $key='',$runId='',$epoch='';
    public function boot():void {$this->identity();}
    private function identity():array {$p=app(Settings::class)->sessionPrincipal(session('shipping.identity'));abort_unless($p,401);abort_unless(in_array('status:read',$p['scopes'],true),403);return $p;}
    public function mount():void {$this->refreshRun();}
    public function refreshRun():void {$this->identity();$r=app(Ledger::class)->status()['run'];$this->runId=$r['id'];$this->epoch=$r['epoch'];$this->key=Rules::uuid4();$this->pending=[];$this->selected='';$this->unitSearch='';$this->selectedUnit='';}
    public function updated(string $name):void {if(in_array($name,['customer','destination'],true)||str_starts_with($name,'lines.')){$this->pending=[];}}
    public function addLine():void {$this->identity();if(count($this->lines)<100)$this->lines[]=['sku'=>'','quantity'=>'1'];$this->pending=[];}
    public function removeLine(int $index):void {$this->identity();if(count($this->lines)>1&&isset($this->lines[$index])){unset($this->lines[$index]);$this->lines=array_values($this->lines);}$this->pending=[];}
    public function createOrder():void {$this->send('create');}
    public function act(string $action,string $reference):void {$this->send($action,$reference);}
    public function retry():void {if($this->pending)$this->send($this->pending['action'],$this->pending['reference']??null);}
    private function send(string $action,?string $reference=null):void {
        $p=$this->identity();$this->error='';$this->notice='';$ledger=app(Ledger::class);$audit=['actor'=>$p['username'],'role'=>$p['role'],'request_id'=>Rules::uuid4(),'action'=>'POST /api/shipping/commands','idempotency_key'=>$this->key,'peer'=>request()->ip()??''];$status=0;
        try{
            $audit['run_id']=$ledger->scope();if(!in_array('jobs:write',$p['scopes'],true)){$status=403;throw new Conflict('This identity cannot change orders');}
            if($this->pending&&($this->pending['action']!==$action||($this->pending['reference']??null)!==$reference))throw new Conflict('Retry or edit the pending command before starting another action');
            $fields=['run_id'=>$this->runId,'epoch'=>$this->epoch,'action'=>$action];
            if($action==='create'){$lines=[];foreach($this->lines as $line){if(!is_array($line)||!is_string($line['quantity']??null)||!preg_match('/^[1-9]\d{0,4}$/D',$line['quantity']))throw new Validation('Whole line quantities 1..10000 required');$lines[]=['sku'=>$line['sku']??null,'quantity'=>(int)$line['quantity']];}$fields+=['customer'=>$this->customer,'destination'=>$this->destination,'lines'=>$lines];}else $fields['reference']=$reference;
            $canonical=ShippingRules::command([...$fields,'due_at'=>0.0]);unset($canonical['due_at']);
            $operationKey=Rules::uuid5($this->key,json_encode($canonical,JSON_THROW_ON_ERROR));$audit['idempotency_key']=$operationKey;
            $this->pending=app(Fulfilment::class)->prepare($operationKey,$canonical,$p['username']);
            $command=app(Fulfilment::class)->submit($operationKey,$this->pending,$audit);$this->notice='Command accepted: '.$command['id'].'. Follow its outcome below.';$this->pending=[];$this->key=Rules::uuid4();
        }catch(Validation $e){$status=422;$this->error=$e->getMessage();}catch(Conflict $e){$status=$status?:409;$this->error=$e->getMessage();}catch(\PDOException){$status=503;$this->error='Database unavailable. Retry the same command.';}
        finally{if($status&&isset($audit['run_id']))try{$ledger->rejected($audit,$status);}catch(\Throwable){error_log('Shipping web rejection audit unavailable');}}
    }
    public function render():\Illuminate\Contracts\View\View {
        $p=$this->identity();$snapshot=null;$unavailable='';try{$snapshot=app(Fulfilment::class)->snapshot();}catch(\PDOException){$unavailable='Shipping records unavailable. Waiting for database recovery.';}
        $orders=$snapshot['orders']??[];$detail=null;foreach($orders as $o)if($o['id']===$this->selected)$detail=$o;
        $query=strtolower($this->search);$orders=array_values(array_filter($orders,function($o)use($query){$text=strtolower($o['id'].' '.$o['customer'].' '.$o['destination'].' '.implode(' ',array_column($o['lines'],'sku')));return ($query===''||str_contains($text,$query))&&match($this->queue){'packing'=>$o['status']==='ready','dispatch'=>$o['status']==='packed','delivery'=>in_array($o['status'],['awaiting_carrier','in_transit'],true),default=>true};}));
        $handling=$snapshot['handling']??null;$allUnits=$handling['units']??[];$term=strtolower(trim($this->unitSearch));
        $unitRows=array_values(array_filter($allUnits,fn($unit)=>$term===''||str_contains(strtolower(implode(' ',[$unit['id'],$unit['barcode'],$unit['position']??'',$unit['destination']??'',...array_column($unit['contents'],'sku')])),$term)));
        $unitDetail=null;foreach($allUnits as $unit)if($unit['id']===$this->selectedUnit){
            $relatedOrders=[];foreach($snapshot['orders'] as $order)foreach($order['lines'] as $line)if(in_array($unit['id'],$line['unit_ids']??[],true)){$relatedOrders[$order['id']]=['id'=>$order['id'],'customer'=>$order['customer']];}
            $unitDetail=['unit'=>$unit,'movements'=>array_values(array_filter($handling['movements'],fn($move)=>$move['unit_id']===$unit['id'])),'handoffs'=>array_values(array_filter($handling['handoffs'],fn($handoff)=>$handoff['unit']['id']===$unit['id'])),'orders'=>array_values($relatedOrders)];break;
        }
        $unitPromises=array_values(array_filter($handling['handoffs']??[],fn($handoff)=>in_array($handoff['state'],['offered','accepted'],true)));
        return view('orders',['snapshot'=>$snapshot,'orders'=>$orders,'detail'=>$detail,'canWrite'=>in_array('jobs:write',$p['scopes'],true),'unavailable'=>$unavailable,'handling'=>$handling,'unitRows'=>$unitRows,'unitDetail'=>$unitDetail,'unitPromises'=>$unitPromises]);
    }
}
