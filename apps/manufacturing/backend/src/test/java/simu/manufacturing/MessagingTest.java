package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_AMQP",matches=".+")
class MessagingTest {
 final String url=System.getenv("MANUFACTURING_TEST_AMQP");
 @Test void mandatoryRoutingFailureDoesNotCountAsConfirmedDelivery()throws Exception{try(var messaging=new Messaging(url)){assertThrows(IllegalStateException.class,()->messaging.publish("manufacturing-does-not-exist", "{}",UUID.randomUUID().toString()));}}
 @Test void malformedDeliveryIsDeadLetteredAfterManualNack()throws Exception{
  try(var m=new Messaging(url)){
   m.channel.queuePurge(Messaging.QUEUE);m.channel.queuePurge("sample.jobs.dead.v1");m.publish(Messaging.QUEUE,"{\"job_id\":\"invalid\"}",UUID.randomUUID().toString());assertTrue(m.consume(null));
   com.rabbitmq.client.GetResponse dead=null;for(int i=0;i<30&&dead==null;i++){dead=m.channel.basicGet("sample.jobs.dead.v1",true);if(dead==null)Thread.sleep(50);}assertNotNull(dead);
  }
 }
 @Test void databaseOutageLeavesDeliveryUnacknowledged()throws Exception{
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test"));var store=new Store(settings);store.pool.close();
  try(var m=new Messaging(url)){m.channel.queuePurge(Messaging.QUEUE);m.publish(Messaging.QUEUE,Json.write(Map.of("job_id",UUID.randomUUID())),UUID.randomUUID().toString());assertThrows(Store.Unavailable.class,()->m.consume(store));}
  try(var m=new Messaging(url)){var recovered=m.channel.basicGet(Messaging.QUEUE,false);assertNotNull(recovered);assertTrue(recovered.getEnvelope().isRedeliver());m.channel.basicAck(recovered.getEnvelope().getDeliveryTag(),false);}
 }
}
