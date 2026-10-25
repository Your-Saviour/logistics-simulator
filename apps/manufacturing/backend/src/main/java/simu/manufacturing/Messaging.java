package simu.manufacturing;
import com.rabbitmq.client.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** The SQL outbox remains authoritative until publisher confirms and mandatory routing succeed. */
final class Messaging implements AutoCloseable {
 static final String QUEUE="sample.jobs.v1";
 final Connection connection;
 final Channel channel;
 final AtomicBoolean returned=new AtomicBoolean();
 Messaging(String url)throws Exception{
  var factory=new ConnectionFactory();factory.setUri(url);factory.setConnectionTimeout(3000);factory.setHandshakeTimeout(5000);factory.setRequestedHeartbeat(30);factory.setAutomaticRecoveryEnabled(false);connection=factory.newConnection("manufacturing");channel=connection.createChannel();
  channel.exchangeDeclare("sample.dead.v1","direct",true);channel.queueDeclare("sample.jobs.dead.v1",true,false,false,null);channel.queueBind("sample.jobs.dead.v1","sample.dead.v1","dead");
  channel.queueDeclare("production.events.v1",true,false,false,null);
  channel.queueDeclare(QUEUE,true,false,false,Map.of("x-dead-letter-exchange","sample.dead.v1","x-dead-letter-routing-key","dead"));channel.basicQos(1);channel.confirmSelect();channel.addReturnListener(r->returned.set(true));
 }
 void publish(String destination,String body,String id)throws Exception{
  returned.set(false);channel.basicPublish("",destination,true,new AMQP.BasicProperties.Builder().deliveryMode(2).contentType("application/json").messageId(id).build(),body.getBytes(java.nio.charset.StandardCharsets.UTF_8));channel.waitForConfirmsOrDie(5000);if(returned.get())throw new IllegalStateException("Mandatory message was unroutable");
 }
 void relay(Store store)throws Exception{for(var event:Production.pendingEvents(store)){publish("production.events.v1",Json.write(event.get("envelope")),event.get("id").toString());Production.eventPublished(store,event.get("id"));}for(var row:store.dispatchable()){publish(QUEUE,Json.write(Map.of("job_id",row.get("job_id"))),row.get("id").toString());store.published(row.get("id"));}}
 boolean consume(Store store)throws Exception{
  var delivery=channel.basicGet(QUEUE,false);if(delivery==null)return false;long tag=delivery.getEnvelope().getDeliveryTag();UUID id;
  try{var body=Json.parse(new String(delivery.getBody(),java.nio.charset.StandardCharsets.UTF_8));Policy.fields(body,"job_id");id=Policy.uuid(body.get("job_id"));}
  catch(IllegalArgumentException e){channel.basicNack(tag,false,false);return true;}
  String result;
  try{result=store.execute(id);}catch(Store.Unavailable e){throw e;}catch(Exception e){result=store.fail(id,e);}
  if(result.equals("dead"))channel.basicNack(tag,false,false);else channel.basicAck(tag,false);return true;
 }
 static boolean ready(String url){try(var m=new Messaging(url)){return true;}catch(Exception e){return false;}}
 @Override public void close()throws Exception{try{if(channel.isOpen())channel.close();}finally{connection.close();}}
 static void worker(Store store,Settings settings){while(!Thread.currentThread().isInterrupted())try(var m=new Messaging(settings.amqp)){while(!Thread.currentThread().isInterrupted()){Fleet.relay(store);m.relay(store);boolean received=m.consume(store);store.heartbeat("worker","");if(!received)Thread.sleep(150);}}catch(Exception e){System.err.println("Manufacturing worker dependency unavailable; SQL work retained: "+e.getClass().getSimpleName());try{Thread.sleep(2000);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}}}
}
