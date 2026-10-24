<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
use Shipping\{Database,Ledger,Settings,Rules,Conflict,Broker,Worker};
$count=0;
function check(bool $ok,string $name):void {global $count;if(!$ok)throw new RuntimeException($name);$count++;echo "PASS $name\n";}
function conflict(callable $action,string $name):void {try{$action();}catch(Conflict){check(true,$name);return;}throw new RuntimeException('Missing conflict: '.$name);}
$settings=new Settings();$db=new Database($settings);$db->migrate();$store=new Ledger($db,$settings);
$a=['actor'=>'operator','role'=>'operator','request_id'=>Rules::uuid4(),'action'=>'test:command','idempotency_key'=>'test','peer'=>'tests'];
$old=$store->status()['run'];$store->control('reset',['confirm_run_id'=>$old['id']],$a);$run=$store->status()['run'];
$job=$store->schedule('test:'.Rules::uuid4(),2.0,7,$a);$id=$job['id'];
check($store->execute($id)==='waiting','no execution before durable grant');
$store->heartbeat('controller');check($store->prepare(2.0,$run['epoch']),'empty completion barrier permits requested time');
$store->grant(1.0,$run['epoch']);check($store->execute($id)==='waiting','earlier grant never authorizes requested time');
conflict(fn()=>$store->grant(3.0,$run['epoch']),'reject grant beyond requested time');
$store->grant(2.0,$run['epoch']);check(!$store->prepare(3.0,$run['epoch']),'due work blocks next request');
$children=[];$folder=sys_get_temp_dir().'/shipping-effects-'.Rules::uuid4();mkdir($folder);
for($n=0;$n<6;$n++){$pid=pcntl_fork();if($pid===-1)throw new RuntimeException('fork failed');if($pid===0){try{file_put_contents($folder.'/'.$n,$store->execute($id));exit(0);}catch(Throwable $e){fwrite(STDERR,$e->getMessage());exit(1);}}$children[]=$pid;}
foreach($children as $pid){pcntl_waitpid($pid,$status);check(pcntl_wexitstatus($status)===0,'concurrent worker process committed');}
$outcomes=[];foreach(glob($folder.'/*') as $path){$outcomes[]=file_get_contents($path);unlink($path);}rmdir($folder);
check(count(array_filter($outcomes,fn($x)=>$x==='completed'))===1,'six concurrent deliveries apply one effect');
check($store->status()['effects']===7,'sample quantity applied exactly once');
check($store->prepare(3.0,$run['epoch']),'completed work unlocks barrier');
$store->control('hold',[],$a);check(!$store->grant(3.0,$run['epoch']),'standalone hold blocks grants');
$store->control('reset',['confirm_run_id'=>$run['id']],$a);check($store->execute($id)==='fenced','old run delivery is fenced after reset');
conflict(fn()=>$store->grant(3.0,$run['epoch']),'stale controller epoch is fenced');
$retry=$store->schedule('retry:'.Rules::uuid4(),2.0,1);
check($store->fail($retry['id'],'domain failure')==='retry','first failure retains durable retry');
check($store->fail($retry['id'],'domain failure')==='retry','second failure retains durable retry');
check($store->fail($retry['id'],'domain failure')==='dead','third failure exhausts bounded retry');
check($store->status()['run']['state']==='failed','retry exhaustion fails the run');
$store->control('reset',['confirm_run_id'=>$store->scope()],$a);$native=$store->status()['run'];$session=Rules::uuid4();
$db->transaction(function($u)use($native,$session){$u->execute("UPDATE runs SET mode='helics' WHERE id=?",[$native['id']]);$u->execute("INSERT INTO shipping_adapter_sessions(run_id,epoch,session_id) VALUES (?,?,?)",[$native['id'],$native['epoch'],$session]);});
check(!$store->prepare(1.0,$native['epoch']),'native initialization blocks requests');
conflict(fn()=>$store->control('finalize',[],$a),'native initialization blocks finalize');
$db->transaction(fn($u)=>$u->execute("UPDATE shipping_adapter_sessions SET native_pending=false,native_state='executing' WHERE session_id=?",[$session]));
check($store->prepare(1.0,$native['epoch']),'settled native session permits intent');
check($db->transaction(fn($u)=>$u->one('SELECT native_pending FROM shipping_adapter_sessions WHERE session_id=?',[$session]))['native_pending']===true,'pending fence commits before adapter HTTP');
conflict(fn()=>$store->control('finalize',[],$a),'native pending request blocks finalize');
$db->transaction(function($u)use($native){$u->execute('DELETE FROM shipping_adapter_sessions WHERE run_id=?',[$native['id']]);$u->execute("UPDATE runs SET mode='standalone',requested=0 WHERE id=?",[$native['id']]);});
$sum=$db->transaction(fn($u)=>$u->one("SELECT checksum FROM schema_migrations WHERE name='001_bootstrap.sql'"))['checksum'];
$db->transaction(fn($u)=>$u->execute("UPDATE schema_migrations SET checksum='edited' WHERE name='001_bootstrap.sql'"));
try{conflict(fn()=>$db->migrate(),'edited applied migration is rejected');}finally{$db->transaction(fn($u)=>$u->execute("UPDATE schema_migrations SET checksum=? WHERE name='001_bootstrap.sql'",[$sum]));}
$broker=new Broker($settings);$returned=false;try{$broker->publish(Rules::uuid4(),['job_id'=>Rules::uuid4()],'missing:'.Rules::uuid4());}catch(RuntimeException){$returned=true;}check($returned,'mandatory return cannot be mistaken for confirmed routing');
$broker->publish(Rules::uuid4(),['job_id'=>$id]);$message=$broker->get();check($message!==null,'confirmed persistent delivery is consumable');
$unavailable=clone $settings;$unavailable->databaseUrl='postgresql://unavailable:bad@127.0.0.1:1/unavailable';
$failed=false;try{Worker::processDelivery(new Ledger(new Database($unavailable),$unavailable),$broker,$message);}catch(PDOException){$failed=true;}
check($failed,'database outage propagates without consuming business retry budget');$broker->close();
$broker=new Broker($settings);$message=$broker->get();check($message!==null&&$message->isRedelivered(),'unacknowledged outage delivery survives reconnect');
Worker::processDelivery($store,$broker,$message);check($broker->get()===null,'fenced delivery is acknowledged after transaction');
foreach(['null','true','[]','[1]','1','"text"','{bad','{"invalid":true}'] as $raw){$broker->publishRaw(Rules::uuid4(),$raw);check(Worker::processDelivery($store,$broker,$broker->get())==='malformed','poison body rejected before business execution: '.$raw);usleep(100000);$dead=$broker->get(Broker::DEAD_QUEUE);check($dead!==null,'poison delivery routed to durable DLQ');$broker->ack($dead->getDeliveryTag());}$broker->close();
echo "$count ledger and AMQP checks passed\n";
