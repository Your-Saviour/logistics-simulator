package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class NativeBarrierTest {
 Store store;
 @BeforeEach void setup(){var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test"));store=new Store(settings);store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);store.tx(c->{var r=Store.current(c);Store.sql(c,"UPDATE runs SET mode='helics' WHERE id=?",r.get("id"));return null;});}
 @AfterEach void restore(){if(store!=null){store.tx(c->{var r=Store.current(c);Store.sql(c,"UPDATE runs SET mode='standalone' WHERE id=?",r.get("id"));return null;});store.pool.close();}}
 @Test void connectedFinalizeRejectsUninitializedNativeSession(){assertThrows(Store.Conflict.class,()->store.control("finalize",1,null,null,null));}
 @Test void preparedRequestAndEarlierGrantKeepFinalizeBlockedUntilInputsSettle(){
  var run=store.run();store.tx(c->{Store.sql(c,"INSERT INTO manufacturing_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (?,?,?,false,'executing')",run.get("id"),run.get("epoch"),UUID.randomUUID());return null;});
  assertTrue(store.prepare(5,run.get("epoch")));store.grant(2,run.get("epoch"),null);store.control("hold",1,null,null,null);
  assertThrows(Store.Conflict.class,()->store.control("finalize",1,null,null,null));
  store.tx(c->{Store.sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=false,native_state='executing' WHERE run_id=? AND epoch=?",run.get("id"),run.get("epoch"));return null;});
  UUID session=Store.uuid(store.tx(c->Store.one(c,"SELECT session_id FROM manufacturing_adapter_sessions WHERE run_id=?",run.get("id"))).get("session_id"));
  assertTrue(store.beginPoll(run.get("epoch"),session));assertThrows(Store.Conflict.class,()->store.control("finalize",1,null,null,null));store.nativeSettled(run.get("epoch"),session);
  assertEquals("finalizing",((Map<?,?>)store.control("finalize",1,null,null,null).get("run")).get("state"));
 }
 @Test void connectedFinalizeRemainsPendingUntilNativeAcknowledgement(){
  var run=store.run();store.tx(c->{Store.sql(c,"INSERT INTO manufacturing_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (?,?,?,false,'executing')",run.get("id"),run.get("epoch"),UUID.randomUUID());return null;});
  var requested=store.control("finalize",1,null,null,null);assertEquals("finalizing",((Map<?,?>)requested.get("run")).get("state"));
  store.stall("Native finalize unavailable",run.get("epoch"));assertEquals("stalled",store.run().get("state"));
 }
 @Test void nativeGrantCannotExceedRequestedWatermark(){
  var run=store.run();store.tx(c->{Store.sql(c,"INSERT INTO manufacturing_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (?,?,?,false,'executing')",run.get("id"),run.get("epoch"),UUID.randomUUID());return null;});
  assertTrue(store.prepare(5,run.get("epoch")));assertThrows(Store.Conflict.class,()->store.grant(6,run.get("epoch"),null));assertEquals(0,Store.number(store.run(),"granted"));
 }
}
