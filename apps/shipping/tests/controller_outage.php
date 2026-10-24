<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
use Shipping\{Settings,Database,Ledger,Rules};
$db=new Database(new Settings());$db->migrate();$store=new Ledger($db,new Settings());$audit=['actor'=>'operator','role'=>'operator','request_id'=>Rules::uuid4(),'action'=>'test:controller-recovery'];$store->control('reset',['confirm_run_id'=>$store->scope()],$audit);$run=$store->status()['run'];
$process=proc_open([PHP_BINARY,__DIR__.'/controller_fixture.php'],[0=>['file','/dev/null','r'],1=>['file','/dev/null','a'],2=>['file','/dev/null','a']],$pipes);if(!is_resource($process))throw new RuntimeException('Controller fixture did not start');
try{$pid=null;for($n=0;$n<100;$n++){$pid=$db->transaction(fn($u)=>$u->query("SELECT pid FROM pg_locks WHERE locktype='advisory' AND objid=8192102 AND granted")[0]['pid']??null);if($pid!==null)break;usleep(50000);}if($pid===null)throw new RuntimeException('Controller did not acquire lease');
    // Terminate only this disposable controller's own DB session, while the
    // server remains available. This catches a transient outage falsely stalling
    // the run when the subsequent stall-write connection happens to succeed.
    $db->transaction(fn($u)=>$u->one('SELECT pg_terminate_backend(?) AS terminated',[$pid]));
    for($n=0;$n<100;$n++){if(!proc_get_status($process)['running'])break;usleep(50000);}$after=$store->status()['run'];if($after['id']!==$run['id']||$after['epoch']!==$run['epoch']||$after['state']!=='running')throw new RuntimeException('Standalone controller DB loss changed recoverable run to '.$after['state']);echo "PASS standalone controller DB connection loss retains active run/epoch for restart\n";
}finally{if(proc_get_status($process)['running'])proc_terminate($process);proc_close($process);}
