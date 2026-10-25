package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class OtTest {
 Store store;
 Map<String,String> environment(){return Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","APP_IDENTITIES","[{\"username\":\"employee\",\"password\":\"test\",\"role\":\"employee\"}]","OT_MODE","openplc","OT_EQUIPMENT_URL","http://equipment:8010","OT_EQUIPMENT_TOKEN","test-equipment-token");}
 @BeforeEach void setup(){store=new Store(new Settings(environment()));store.migrate();store.control("reset",1,store.run().get("id").toString(),null,null);store.heartbeat("controller","");}
 @AfterEach void cleanup(){if(store!=null){var disabled=new Store(new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test")));try{disabled.control("reset",1,store.run().get("id").toString(),null,null);}finally{disabled.pool.close();store.pool.close();}}}
 Map<String,Object> acquire(){return Ot.acquire(store,UUID.randomUUID());}
 Map<String,Object> next(){return Ot.next(store);}
 void acknowledge(Map<String,Object> op){var request=Store.json(op.get("request"));var payload=request.path("payload");var result=new LinkedHashMap<String,Object>();result.put("initialized",true);result.put("scope",Map.of("run_id",request.path("run_id").asText(),"epoch",request.path("epoch").asText(),"session_id",request.path("session_id").asText()));result.put("simulation_time",request.path("operation").asText().equals("step")?payload.path("simulation_time").asInt():store.tx(c->Store.one(c,"SELECT settled FROM ot_cells WHERE run_id=?",request.path("run_id").asText().isEmpty()?null:UUID.fromString(request.path("run_id").asText()))).get("settled"));result.put("sequence",1);result.put("cell",Map.of("completed",false));Ot.acknowledge(store,Store.uuid(op.get("id")),Json.M.valueToTree(Map.of("version","1.0","command_id",op.get("id"),"result",result)));}
 @Test void configuredModeRequiresExplicitEndpointTokenAndWholeQuantum(){
  var env=new HashMap<>(environment());env.put("OT_MODE","unknown");assertThrows(IllegalArgumentException.class,()->new Settings(env));
  env.put("OT_MODE","openplc");env.put("OT_EQUIPMENT_TOKEN","");assertThrows(IllegalArgumentException.class,()->new Settings(env));
  env.put("OT_EQUIPMENT_TOKEN","test-equipment-token");env.put("HANDOFF_QUANTUM","1.5");assertThrows(IllegalArgumentException.class,()->new Settings(env));
 }
 @Test void unadmittedGrantBlocksPreparationAndHeldRunCannotAdmitSteps(){
  acquire();acknowledge(next());var epoch=store.run().get("epoch");store.grant(1,epoch,null);
  assertFalse(store.prepare(2,epoch),"The grant itself must create the equipment barrier before a step intent exists");
  store.control("hold",1,null,null,null);assertNull(next(),"Hold must prevent new equipment step admission");
  store.control("resume",1,null,null,null);var step=next();assertEquals(1,Store.json(step.get("request")).path("payload").path("simulation_time").asInt());acknowledge(step);
  assertTrue(store.prepare(2,epoch));
 }
 @Test void admittedStepMaySettleAfterHoldAndDuplicateReplyIsStable(){
  acquire();acknowledge(next());store.grant(1,store.run().get("epoch"),null);var step=next();store.control("hold",1,null,null,null);acknowledge(step);acknowledge(step);assertNull(next());
 }
 @Test void secondOwnerAndStaleEpochCannotTakeOver(){
  acquire();assertThrows(Store.Conflict.class,()->Ot.acquire(store,UUID.randomUUID()));var old=next();store.control("reset",1,store.run().get("id").toString(),null,null);assertThrows(Store.Conflict.class,()->acknowledge(old));
 }
 @Test void operatorCommandReplaysAndFencesScope(){
  acquire();acknowledge(next());var run=store.run();var body=Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","stop"));var audit=new Store.Audit("operator","operator",UUID.randomUUID(),"ot:stop","same","test",run.get("id"));
  var first=Ot.command(store,"same",body,audit);assertEquals(first.get("id"),Ot.command(store,"same",body,audit).get("id"));
  var changed=Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","start"));assertThrows(Store.Conflict.class,()->Ot.command(store,"same",changed,audit));
  store.control("reset",1,run.get("id").toString(),null,null);assertThrows(Store.Conflict.class,()->Ot.command(store,"new",body,audit));
 }
 @Test void publicOtApiRequiresOperatorControlScope(){
  acquire();acknowledge(next());var api=new Api(store.settings,store);var run=store.run();var body=Json.write(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","stop"));
  var request=new org.springframework.mock.web.MockHttpServletRequest("POST","/api/ot/commands");request.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("operator:test".getBytes()));request.addHeader("Idempotency-Key","api-stop");
  assertEquals(200,api.handle(request,body).getStatusCode().value());
  var denied=new org.springframework.mock.web.MockHttpServletRequest("POST","/api/ot/commands");denied.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("employee:test".getBytes()));denied.addHeader("Idempotency-Key","denied");assertEquals(403,api.handle(denied,body).getStatusCode().value());
  var read=new org.springframework.mock.web.MockHttpServletRequest("GET","/api/ot");read.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("operator:test".getBytes()));assertEquals(200,api.handle(read,null).getStatusCode().value());
 }

 @Test void commandsAtANewGrantDoNotChangeEarlierCatchupSteps(){
  acquire();acknowledge(next());store.grant(2,store.run().get("epoch"),null);var run=store.run();var body=Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","stop"));Ot.command(store,"at-two",body,new Store.Audit("operator","operator",UUID.randomUUID(),"ot:stop","at-two","test",run.get("id")));
  var first=next();assertEquals("step",first.get("operation"),"Current-grant controls must not affect earlier equipment catchup");acknowledge(first);var second=next();assertEquals("step",second.get("operation"));acknowledge(second);var control=next();assertEquals("control",control.get("operation"));acknowledge(control);
 }

}
