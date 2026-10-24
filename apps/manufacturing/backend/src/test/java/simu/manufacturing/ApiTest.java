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
