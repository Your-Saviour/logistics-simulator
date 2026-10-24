package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.mock.web.MockHttpServletRequest;
import java.util.*;
import java.nio.charset.StandardCharsets;
import static org.junit.jupiter.api.Assertions.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class ApiTest {
 Store store;Api api;
 @BeforeEach void setup(){var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","secret","APP_IDENTITIES","[{\"username\":\"employee\",\"password\":\"employee\",\"role\":\"employee\"},{\"username\":\"service\",\"password\":\"service\",\"role\":\"service\",\"scopes\":[\"status:read\"]}]"));store=new Store(settings);store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);api=new Api(settings,store);}
 @AfterEach void close(){store.pool.close();}
 org.springframework.http.ResponseEntity<String> request(String method,String path,String user,String body,String key){var r=new MockHttpServletRequest(method,path);if(user!=null)r.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString((user+":"+(user.equals("operator")?"secret":user)).getBytes(StandardCharsets.UTF_8)));if(key!=null)r.addHeader("Idempotency-Key",key);return api.handle(r,body);}
 @Test void projectionRequiresStatusReadAndKeepsCompleteHistory(){
  assertEquals(401,request("GET","/api/projection",null,null,null).getStatusCode().value());
  var response=request("GET","/api/projection","service",null,null);
  assertEquals(200,response.getStatusCode().value());
  var first=Json.parse(response.getBody());assertEquals(1,first.path("version").asInt());assertEquals("manufacturing",first.path("source").asText());assertEquals(0,first.path("effects").asInt(-1));
  assertEquals(first.path("cursor"),Json.parse(request("GET","/api/projection","service",null,null).getBody()).path("cursor"));
  assertEquals(0L,((Number)store.tx(c->Store.one(c,"SELECT count(*) n FROM production_config WHERE run_id=?",UUID.fromString(first.path("run").path("id").asText()))).get("n")).longValue(),"projection must not initialize business records");
  var job=store.schedule(UUID.randomUUID().toString(),1,1,null,null);var run=store.run();
  var correlation=UUID.randomUUID();
  store.tx(c->{Store.sql(c,"UPDATE jobs SET boundary_input=?::jsonb WHERE id=?",Json.write(Map.of("correlation_id",correlation)),job.get("id"));Store.sql(c,"INSERT INTO production_history(run_id,job_id,action,simulation_time,detail) SELECT ?,?,'test-record',0,'{}'::jsonb FROM generate_series(1,205)",run.get("id"),job.get("id"));return null;});
  var full=Json.parse(request("GET","/api/projection","service",null,null).getBody());assertEquals(205,full.path("events").size());assertEquals(correlation.toString(),full.path("events").get(0).path("correlation_id").asText());assertNotEquals(first.path("cursor"),full.path("cursor"));
  assertEquals(205,full.path("events").findValuesAsText("id").stream().distinct().count());assertTrue(full.path("events").get(0).has("simulation_time"));
  store.control("reset",1,run.get("id").toString(),null,null);
  assertEquals(0,Json.parse(request("GET","/api/projection","service",null,null).getBody()).path("events").size());
 }
 @Test void controlsRejectStaleRunAndEpochBeforeMutation(){
  var run=store.run();
  assertEquals(409,request("POST","/api/control/hold","operator",Json.write(Map.of("run_id",UUID.randomUUID(),"epoch",run.get("epoch"))),null).getStatusCode().value());
  assertEquals(409,request("POST","/api/control/speed","operator",Json.write(Map.of("run_id",run.get("id"),"epoch",UUID.randomUUID(),"speed",60)),null).getStatusCode().value());
  assertEquals("running",store.run().get("state"));assertEquals(1,store.run().get("speed"));
  assertEquals(200,request("POST","/api/control/hold","operator",Json.write(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"))),null).getStatusCode().value());
 }
 @Test void keyedHoldReplayDoesNotOverrideInterveningResume(){
  var key=UUID.randomUUID().toString();var first=request("POST","/api/control/hold","operator","{}",key);assertEquals(200,first.getStatusCode().value());
  assertEquals(200,request("POST","/api/control/resume","operator","{}",null).getStatusCode().value());
  var replay=request("POST","/api/control/hold","operator","{}",key);assertEquals(200,replay.getStatusCode().value());
  assertEquals("running",store.run().get("state"));assertEquals(Json.parse(first.getBody()),Json.parse(replay.getBody()));
  assertEquals(409,request("POST","/api/control/resume","operator","{}",key).getStatusCode().value());
  assertEquals(409,request("POST","/api/control/hold","operator","{\"speed\":1}",key).getStatusCode().value());
 }
 @Test void projectionInfrastructureUsesSafeDurableCounts(){
  var run=store.run();var first=store.schedule(UUID.randomUUID().toString(),1,1,null,null);var dead=store.schedule(UUID.randomUUID().toString(),2,1,null,null);
  store.tx(c->{Store.sql(c,"UPDATE jobs SET status='dead' WHERE id=?",dead.get("id"));Store.sql(c,"INSERT INTO heartbeats(role,detail) VALUES ('worker','postgres://secret:password@db') ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp(),detail=EXCLUDED.detail");return null;});
  var health=Json.parse(request("GET","/api/projection","service",null,null).getBody()).path("health");
  assertEquals(1,health.path("pending_jobs").asInt(-1));assertEquals(1,health.path("dead_letters").asInt(-1));assertTrue(health.path("heartbeats").isArray());assertFalse(health.toString().contains("password"));
 }
 @Test void strictCommandsReplayConflictsAndRejectedActorAudit(){
  var key=UUID.randomUUID().toString();var accepted=request("POST","/api/jobs","employee","{\"due_at\":2,\"quantity\":3}",key);assertEquals(200,accepted.getStatusCode().value());
  assertEquals(accepted.getBody(),request("POST","/api/jobs","employee","{\"due_at\":2,\"quantity\":3}",key).getBody());
  assertEquals(409,request("POST","/api/jobs","employee","{\"due_at\":2,\"quantity\":4}",key).getStatusCode().value());
  assertEquals(422,request("POST","/api/jobs","employee","{\"due_at\":2,\"quantity\":true}","invalid").getStatusCode().value());
  assertTrue(store.audit().stream().anyMatch(a->a.get("actor").equals("employee")&&a.get("outcome").equals("rejected")&&a.get("status_code").equals(422)));
 }
 @Test void independentEmployeeAndServiceRolesHaveNoOperatorRights(){
  assertEquals(401,request("GET","/api/status",null,null,null).getStatusCode().value());
  assertEquals(403,request("POST","/api/control/hold","employee","{}",null).getStatusCode().value());
  assertEquals(403,request("POST","/api/jobs","service","{\"due_at\":2,\"quantity\":1}","service-key").getStatusCode().value());
  assertEquals(403,request("GET","/api/audit","service",null,null).getStatusCode().value());
  assertEquals(200,request("GET","/api/status","service",null,null).getStatusCode().value());
 }
 @Test void acceptedAuditFailureRollsBackBusinessCommand(){
  store.tx(c->{Store.sql(c,"CREATE OR REPLACE FUNCTION manufacturing_test_audit_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.actor='abort-atomic' THEN RAISE EXCEPTION 'test audit failure'; END IF; RETURN NEW; END $$");Store.sql(c,"CREATE TRIGGER manufacturing_test_audit_fail BEFORE INSERT ON command_audit FOR EACH ROW EXECUTE FUNCTION manufacturing_test_audit_fail()");return null;});
  var key=UUID.randomUUID().toString();try{
   assertThrows(Store.Unavailable.class,()->store.schedule(key,5,2,new Store.Audit("abort-atomic","employee",UUID.randomUUID(),"POST /api/jobs",key,"test",null),null));
   assertNull(store.tx(c->Store.one(c,"SELECT id FROM jobs WHERE idempotency_key=?",key)));
  }finally{store.tx(c->{Store.sql(c,"DROP TRIGGER manufacturing_test_audit_fail ON command_audit");Store.sql(c,"DROP FUNCTION manufacturing_test_audit_fail()");return null;});}
 }
 @Test void concurrentDuplicateDeliveriesHaveOneEffect()throws Exception{
  var run=store.run();var job=store.schedule(UUID.randomUUID().toString(),1,7,null,null);store.grant(1,run.get("epoch"),null);store.heartbeat("controller","");UUID id=Store.uuid(job.get("id"));
  try(var executor=java.util.concurrent.Executors.newFixedThreadPool(4)){var tasks=new ArrayList<java.util.concurrent.Future<String>>();for(int i=0;i<8;i++)tasks.add(executor.submit(()->store.execute(id)));var results=new ArrayList<String>();for(var task:tasks)results.add(task.get());assertEquals(1,results.stream().filter("completed"::equals).count());assertEquals(7,results.stream().filter("duplicate"::equals).count());}
  assertEquals(7L,((Number)store.status().get("effects")).longValue());
 }
}
