package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class OtInsightsTest {
 OtTest fixture=new OtTest();Store store;
 @BeforeEach void setup(){fixture.setup();store=fixture.store;fixture.acquire();fixture.acknowledge(fixture.next());}
 @AfterEach void cleanup(){fixture.cleanup();}
 Map<String,Object> control(String action,Map<String,Object> extra,String key){var run=store.run();var body=new LinkedHashMap<String,Object>(extra);body.put("run_id",run.get("id"));body.put("epoch",run.get("epoch"));body.put("action",action);return OtInsights.control(store,key,Json.M.valueToTree(body),new Store.Audit("operator","operator",UUID.randomUUID(),"ot:insight",key,"test",run.get("id")));}
 @Test void acknowledgedHistoryIsScopedAndDuplicateDoesNotAddSample(){
  assertEquals(1,((List<?>)OtInsights.snapshot(store).get("observations")).size());
  store.grant(1,store.run().get("epoch"),null);var step=fixture.next();fixture.acknowledge(step);fixture.acknowledge(step);
  assertEquals(2,((List<?>)OtInsights.snapshot(store).get("observations")).size());
  store.control("reset",1,store.run().get("id").toString(),null,null);assertTrue(((List<?>)OtInsights.snapshot(store).get("observations")).isEmpty());
 }
 @Test void scenariosReplayExactlyAndStopDoesNotChangeEquipment(){
  var first=control("scenario_start",Map.of("profile","noise","seed",42),"noise");assertEquals(first,control("scenario_start",Map.of("profile","noise","seed",42),"noise"));
  assertThrows(Store.Conflict.class,()->control("scenario_start",Map.of("profile","drift","seed",42),"noise"));
  assertThrows(Store.Conflict.class,()->control("scenario_start",Map.of("profile","drift","seed",42),"another"));
  var model=Json.M.valueToTree(Map.of("enabled",true));assertEquals(OtInsights.signals(model,10,"noise",42,0),OtInsights.signals(model,10,"noise",42,0));
  assertNotEquals(OtInsights.signals(model,10,"noise",42,0),OtInsights.signals(model,10,"noise",43,0));
  assertNull(OtInsights.signals(model,10,"dropout",42,0).get("motor_temperature"));
  control("scenario_stop",Map.of(),"stop");assertNull(fixture.next());
 }
 @Test void alarmAcknowledgementNeverClearsUnsafeCondition(){
  store.tx(c->{var run=Store.current(c);OtInsights.record(c,run,UUID.randomUUID(),null,Json.M.valueToTree(Map.of("simulation_time",0,"cell",Map.of("faults",List.of("guard_open"),"latched",true))));return null;});
  var alarms=(List<Map<String,Object>>)OtInsights.snapshot(store).get("alarms");assertEquals(1,alarms.size());var alarm=alarms.get(0);
  control("alarm_ack",Map.of("alarm_id",alarm.get("id")),"ack");
  var ack=(Map<?,?>)((List<?>)OtInsights.snapshot(store).get("alarms")).get(0);assertEquals(true,ack.get("active"));assertEquals("operator",ack.get("acknowledged_by"));assertNull(fixture.next());
  store.tx(c->{OtInsights.record(c,Store.current(c),UUID.randomUUID(),null,Json.M.valueToTree(Map.of("simulation_time",0,"cell",Map.of("faults",List.of()))));return null;});
  assertEquals(false,((Map<?,?>)((List<?>)OtInsights.snapshot(store).get("alarms")).get(0)).get("active"));
 }
 @Test void retentionAndAuthorizationAreEnforced(){
  store.tx(c->{var run=Store.current(c);for(int n=0;n<605;n++)OtInsights.record(c,run,UUID.randomUUID(),null,Json.M.valueToTree(Map.of("simulation_time",n,"cell",Map.of())));return null;});
  assertEquals(600,((List<?>)OtInsights.snapshot(store).get("observations")).size());
  var api=new Api(store.settings,store);var request=new org.springframework.mock.web.MockHttpServletRequest("POST","/api/ot/insights");request.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("employee:test".getBytes()));assertEquals(403,api.handle(request,"{}").getStatusCode().value());
 }
 @Test void physicalFaultScenarioUsesDurableGatewayAndStopOnlyRestoresCondition(){
  control("scenario_start",Map.of("profile","guard_open","seed",7),"guard-scenario");
  var inject=fixture.next();assertEquals("control",inject.get("operation"));
  var payload=Store.json(inject.get("request")).path("payload");assertEquals("fault",payload.path("action").asText());assertEquals("guard_open",payload.path("fault").asText());assertTrue(payload.path("active").asBoolean());
  fixture.acknowledge(inject);control("scenario_stop",Map.of(),"restore");
  var restore=fixture.next();assertEquals("fault",Store.json(restore.get("request")).path("payload").path("action").asText());assertFalse(Store.json(restore.get("request")).path("payload").path("active").asBoolean());
 }
 @Test void lateCatchupSamplesUseTheScenarioIntervalRatherThanCurrentActiveScenario(){
  store.grant(3,store.run().get("epoch"),null);
  control("scenario_start",Map.of("profile","noise","seed",7),"noise-at-three");
  fixture.acknowledge(fixture.next());
  var samples=(List<Map<String,Object>>)OtInsights.snapshot(store).get("observations");
  assertEquals("normal",Store.json(samples.getLast().get("signals")).path("profile").asText());
  fixture.acknowledge(fixture.next());fixture.acknowledge(fixture.next());
  store.grant(4,store.run().get("epoch"),null);control("scenario_stop",Map.of(),"stop-at-four");fixture.acknowledge(fixture.next());
  samples=(List<Map<String,Object>>)OtInsights.snapshot(store).get("observations");assertEquals("normal",Store.json(samples.getLast().get("signals")).path("profile").asText());
 }

 @Test void routineOperatorCannotInjectFaultsThroughEitherGatewayInterface(){
  var env=new HashMap<>(fixture.environment());env.put("APP_IDENTITIES","[{\"username\":\"routine\",\"password\":\"test\",\"role\":\"operator\",\"scopes\":[\"status:read\",\"runs:control\"]}]");
  var restricted=new Store(new Settings(env));try{var api=new Api(restricted.settings,restricted);var run=store.run();
   var body=new LinkedHashMap<String,Object>(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","fault","fault","guard_open","active",true));
   for(String path:List.of("/api/ot/commands","/api/ot/tags")){
    var request=new org.springframework.mock.web.MockHttpServletRequest("POST",path);request.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("routine:test".getBytes()));request.addHeader("Idempotency-Key","restricted");
    Object input=body;if(path.endsWith("tags")){var tagBody=new LinkedHashMap<>(body);tagBody.put("command_id",UUID.randomUUID());input=List.of(Map.of("id","command","value",Json.write(tagBody)));}
    assertEquals(403,api.handle(request,Json.write(input)).getStatusCode().value(),path);
   }
  }finally{restricted.pool.close();}
 }

 @Test void sourceLossPersistsContinuityBreakWithoutAdvancingEquipment(){
  var run=store.run();store.tx(c->{OtInsights.sourceLost(c,run,"PLC disconnected");OtInsights.sourceLost(c,run,"PLC disconnected");return null;});
  assertNull(fixture.next());store.grant(1,run.get("epoch"),null);fixture.acknowledge(fixture.next());
  var samples=(List<Map<String,Object>>)OtInsights.snapshot(store).get("observations");assertNotEquals(samples.getFirst().get("continuity"),samples.getLast().get("continuity"));
  assertEquals(2,((List<?>)OtInsights.snapshot(store).get("source_events")).size());
 }

}
