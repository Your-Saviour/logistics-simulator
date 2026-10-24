package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class StoreTest {
 static Store store;static Settings settings;
 @BeforeAll static void setup(){settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test"));store=new Store(settings);store.migrate();}
 @BeforeEach void newRun(){var r=store.run();store.control("reset",1,r.get("id").toString(),null,null);}
 @Test void scheduleReplayConflictAndAuditAreAtomic(){
  var context=new Store.Audit("employee","employee",UUID.randomUUID(),"POST /api/jobs","key","test",null);
  var key=UUID.randomUUID().toString();var job=store.schedule(key,100,2,context,null);
  assertNotNull(job);assertEquals(job.get("id"),store.schedule(key,100,2,context,null).get("id"));
  assertThrows(Store.Conflict.class,()->store.schedule(key,100,3,context,null));
  assertTrue(store.audit().stream().anyMatch(a->a.get("target_id").equals(job.get("id"))));
 }
 @Test void noEffectsBeforeGrantDuplicateDeliveryAndResetFencing(){
  var job=store.schedule(UUID.randomUUID().toString(),1,4,null,null);var id=UUID.fromString(job.get("id").toString());
  assertEquals("waiting",store.execute(id));
  var run=store.run();store.grant(1,run.get("epoch"),null);store.heartbeat("controller","");
  assertEquals("completed",store.execute(id));assertEquals("duplicate",store.execute(id));
  assertEquals(4L,((Number)store.status().get("effects")).longValue());
  store.control("reset",1,run.get("id").toString(),null,null);
  assertEquals("fenced",store.execute(id));
 }
 @Test void powerDeferralAndOutstandingBarrierAreDurable(){
  var run=store.run();double due=((Number)run.get("granted")).doubleValue()+1;
  var job=store.schedule(UUID.randomUUID().toString(),due,1,null,null);var id=UUID.fromString(job.get("id").toString());
  store.grant(due,run.get("epoch"),"External power unavailable; sample work deferred");
  store.heartbeat("controller","");assertEquals("waiting",store.execute(id));
  assertTrue(store.prepare(due+1,run.get("epoch")));store.grant(due+1,run.get("epoch"),null);
  assertFalse(store.prepare(due+2,run.get("epoch")));assertEquals("completed",store.execute(id));
 }
}
