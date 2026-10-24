<?php
declare(strict_types=1);
namespace Shipping;
use PhpAmqpLib\Connection\AMQPStreamConnection;
use PhpAmqpLib\Connection\AMQPSSLConnection;
use PhpAmqpLib\Channel\AMQPChannel;
use PhpAmqpLib\Message\AMQPMessage;
use PhpAmqpLib\Wire\AMQPTable;
final class Broker
{
    public const QUEUE='sample.jobs.v1',DEAD_QUEUE='sample.jobs.dead.v1';
    private AMQPStreamConnection $connection;
    private AMQPChannel $channel;
    private bool $confirmed=false,$returned=false,$nacked=false;
    public function __construct(Settings $settings){$p=parse_url($settings->amqpUrl);if(!$p||!in_array($p['scheme']??null,['amqp','amqps'],true)||!isset($p['host']))throw new Validation('AMQP URL required');$host=$p['host'];$port=$p['port']??($p['scheme']==='amqps'?5671:5672);$user=rawurldecode($p['user']??'guest');$password=rawurldecode($p['pass']??'guest');$vhost=rawurldecode(substr($p['path']??'/',1));if($vhost==='')$vhost='/';
        $this->connection=$p['scheme']==='amqps'?new AMQPSSLConnection($host,$port,$user,$password,$vhost,['verify_peer'=>true,'verify_peer_name'=>true],['heartbeat'=>10,'connection_timeout'=>3,'read_write_timeout'=>25,'channel_rpc_timeout'=>5]):new AMQPStreamConnection($host,$port,$user,$password,$vhost,false,'AMQPLAIN',null,'en_US',3,25,null,false,10,5);
        $c=$this->channel=$this->connection->channel();$c->exchange_declare('sample.dead.v1','direct',false,true,false);$c->queue_declare(self::DEAD_QUEUE,false,true,false,false);$c->queue_bind(self::DEAD_QUEUE,'sample.dead.v1','dead');$c->queue_declare(self::QUEUE,false,true,false,false,false,new AMQPTable(['x-dead-letter-exchange'=>'sample.dead.v1','x-dead-letter-routing-key'=>'dead']));$c->basic_qos(0,1,false);$c->confirm_select();
        $c->set_ack_handler(function(AMQPMessage $message):void{$this->confirmed=true;});$c->set_nack_handler(function(AMQPMessage $message):void{$this->nacked=true;});$c->set_return_listener(function():void{$this->returned=true;});
    }
    public function publish(string $eventId,array $body,string $route=self::QUEUE):void {$this->publishRaw($eventId,json_encode($body,JSON_THROW_ON_ERROR),$route);}
    public function publishRaw(string $eventId,string $body,string $route=self::QUEUE):void {$this->confirmed=$this->returned=$this->nacked=false;$message=new AMQPMessage($body,['delivery_mode'=>AMQPMessage::DELIVERY_MODE_PERSISTENT,'content_type'=>'application/json','message_id'=>$eventId]);$this->channel->basic_publish($message,'',$route,true);$this->channel->wait_for_pending_acks_returns(5);if(!$this->confirmed||$this->returned||$this->nacked)throw new \RuntimeException('Mandatory publication was returned, negatively acknowledged or unconfirmed');}
    public function get(string $queue=self::QUEUE):?AMQPMessage {return $this->channel->basic_get($queue,false);}
    public function ack(int $tag):void {$this->channel->basic_ack($tag,false);}
    public function reject(int $tag):void {$this->channel->basic_nack($tag,false,false);}
    public function close():void {try{$this->channel->close();}finally{$this->connection->close();}}
    public static function ready(Settings $settings):bool {try{$broker=new self($settings);$broker->close();return true;}catch(\Throwable){return false;}}
}
