<?php
declare(strict_types=1);
namespace Shipping;
use PhpAmqpLib\Message\AMQPMessage;
final class Worker
{
    public static function processDelivery(Ledger $ledger,Broker $broker,AMQPMessage $message):string {
        try{$body=Rules::object($message->getBody());Rules::fields($body,['job_id']);$id=Rules::uuid($body['job_id']??null);}catch(Validation){$broker->reject($message->getDeliveryTag());return 'malformed';}
        try{$result=$ledger->execute($id);}catch(\PDOException $error){throw $error;}catch(\Throwable $error){$result=$ledger->fail($id,$error->getMessage());}
        // The store has committed before this manual consumer acknowledgement.
        if($result==='dead')$broker->reject($message->getDeliveryTag());else $broker->ack($message->getDeliveryTag());return $result;
    }
    public static function run(Ledger $ledger,Settings $settings):void {$stop=false;pcntl_async_signals(true);pcntl_signal(SIGTERM,function()use(&$stop){$stop=true;});pcntl_signal(SIGINT,function()use(&$stop){$stop=true;});while(!$stop){$broker=null;try{$broker=new Broker($settings);while(!$stop){foreach($ledger->dispatchable() as $row){$broker->publish($row['id'],['job_id'=>$row['job_id']]);$ledger->published($row['id']);}$message=$broker->get();if($message)self::processDelivery($ledger,$broker,$message);else $ledger->relayFleet();$ledger->heartbeat('worker');usleep(100000);}}catch(\Throwable $error){fwrite(STDERR,'Worker dependency unavailable; durable work retained ('.get_class($error).")\n");if(!$stop)usleep(2000000);}finally{if($broker)try{$broker->close();}catch(\Throwable){}}}}
}
