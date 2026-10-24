package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.junit.jupiter.api.Assertions.*;
import com.sun.net.httpserver.HttpServer;
import java.net.*;
import java.util.*;
import java.util.concurrent.atomic.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class AdapterTest {
 @Test void lostReplyRetriesPersistedOperationAndSessionCannotBeRecreated()throws Exception{
  var attempts=new AtomicInteger();var bodies=new ArrayList<String>();var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
  server.createContext("/v1/commands",exchange->{assertEquals("Bearer test-token",exchange.getRequestHeaders().getFirst("Authorization"));String body=new String(exchange.getRequestBody().readAllBytes());bodies.add(body);var json=Json.parse(body);int code=attempts.incrementAndGet()==1?503:200;byte[] response=Json.write(Map.of("version","1.0","request_id",json.path("request_id").asText(),"result",Map.of("state","initializing"))).getBytes();exchange.sendResponseHeaders(code,response.length);exchange.getResponseBody().write(response);exchange.close();});server.start();
  Store store=null;try{
   var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","HELICS_ADAPTER_URL","http://127.0.0.1:"+server.getAddress().getPort(),"HELICS_ADAPTER_TOKEN","test-token"));store=new Store(settings);store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);var run=store.run();var adapter=new Adapter(store,settings,run);UUID request=UUID.randomUUID();assertEquals("initializing",adapter.call(request,"initialize",Map.of()).path("state").asText());assertEquals(2,attempts.get());assertEquals(bodies.get(0),bodies.get(1));assertEquals("initializing",adapter.call(request,"initialize",Map.of()).path("state").asText());assertEquals(2,attempts.get());assertThrows(Store.Conflict.class,()->adapter.call(request,"poll",Map.of()));Store target=store;assertThrows(Store.Conflict.class,()->new Adapter(target,settings,run));
   assertNotNull(store.tx(c->Store.one(c,"SELECT response FROM manufacturing_adapter_operations WHERE request_id=?",request)).get("response"));
  }finally{server.stop(0);if(store!=null)store.pool.close();}
 }
 @Test void earlierGrantCannotAuthorizeRequestedFutureWorkAndStaleEpochCannotAdvance(){
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test"));var store=new Store(settings);try{store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);var run=store.run();UUID id=Store.uuid(store.schedule(UUID.randomUUID().toString(),5,2,null,null).get("id"));assertTrue(store.prepare(10,run.get("epoch")));store.grant(3,run.get("epoch"),null);store.heartbeat("controller","");assertEquals("waiting",store.execute(id));assertEquals(0L,((Number)store.status().get("effects")).longValue());assertThrows(Store.Conflict.class,()->store.grant(5,UUID.randomUUID(),null));assertFalse(store.prepare(5,UUID.randomUUID()));}finally{store.pool.close();}
 }
}
