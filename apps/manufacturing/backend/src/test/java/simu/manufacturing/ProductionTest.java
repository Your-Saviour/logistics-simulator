package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.mock.web.MockHttpServletRequest;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class ProductionTest {
 Store store;Api api;
 @BeforeEach void setup(){var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","APP_IDENTITIES","[{\"username\":\"employee\",\"password\":\"test\",\"role\":\"employee\"}]"));store=new Store(settings);store.migrate();store.control("reset",1,store.run().get("id").toString(),null,Scenario.normalize(Json.parse("{}")));api=new Api(settings,store);store.heartbeat("controller","");}
 @AfterEach void close(){store.pool.close();}
 JsonNode get(){var r=new MockHttpServletRequest("GET","/api/production");r.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("employee:test".getBytes()));var reply=api.handle(r,null);assertEquals(200,reply.getStatusCode().value(),reply.getBody());return Json.parse(reply.getBody());}
 JsonNode post(String key,Map<String,Object> data,int expected){var run=store.run();var body=new LinkedHashMap<String,Object>(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"due_at",Store.number(run,"requested")+2));body.putAll(data);var r=new MockHttpServletRequest("POST","/api/production/commands");r.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("employee:test".getBytes()));r.addHeader("Idempotency-Key",key);var reply=api.handle(r,Json.write(body));assertEquals(expected,reply.getStatusCode().value(),reply.getBody());return Json.parse(reply.getBody());}
 JsonNode command(Map<String,Object> body){return post(UUID.randomUUID().toString(),body,200);}
 void advance(double t){store.grant(t,store.run().get("epoch"),null);for(int i=0;i<10;i++)for(var j:(List<Map<String,Object>>)store.status().get("jobs"))store.execute(Store.uuid(j.get("id")));}
 UUID create(int quantity){var c=command(Map.of("action","create","product","PRODUCT","line","LINE-1","quantity",quantity));advance(Store.number(store.run(),"requested")+2);return UUID.fromString(c.path("id").asText());}
 JsonNode order(UUID id){for(var o:get().path("orders"))if(o.path("id").asText().equals(id.toString()))return o;throw new AssertionError("order missing");}
 @Test void shortagesHoldDurationAndExactlyOnceOutput(){
  UUID id=create(4);command(Map.of("action","release","reference",id));advance(4);advance(5);
  assertEquals("ready",order(id).path("status").asText());assertTrue(order(id).path("blocked_reason").asText().contains("COMPONENT"));
  command(Map.of("action","hold","reference",id));advance(7);
  command(Map.of("action","supply","sku","COMPONENT","quantity",8));advance(9);assertEquals("held",order(id).path("status").asText());
  command(Map.of("action","release","reference",id));advance(11);advance(12);assertEquals("running",order(id).path("status").asText());
  assertEquals(0,get().path("materials").get(0).path("quantity").asInt());double finish=order(id).path("finish_due").asDouble();
  advance(finish-1);assertEquals("running",order(id).path("status").asText());advance(finish);assertEquals("completed",order(id).path("status").asText());assertEquals(4,order(id).path("output_quantity").asInt());
  advance(finish+1);assertEquals(3,get().path("movements").size());
 }
 @Test void finiteLineCapacityAndRestartRedelivery()throws Exception{
  command(Map.of("action","supply","sku","COMPONENT","quantity",20));advance(2);UUID a=create(4),b=create(4);
  command(Map.of("action","release","reference",a));command(Map.of("action","release","reference",b));advance(8);advance(9);
  assertEquals(1,java.util.stream.Stream.of(order(a),order(b)).filter(o->o.path("status").asText().equals("running")).count());
  assertEquals(12,get().path("materials").get(0).path("quantity").asInt());
  try(var executor=java.util.concurrent.Executors.newFixedThreadPool(4)){var tasks=new ArrayList<java.util.concurrent.Future<?>>();for(var job:(List<Map<String,Object>>)store.status().get("jobs"))for(int i=0;i<4;i++)tasks.add(executor.submit(()->store.execute(Store.uuid(job.get("id")))));for(var task:tasks)task.get();}
  assertEquals(12,get().path("materials").get(0).path("quantity").asInt());
  var settings=store.settings;store.pool.close();store=new Store(settings);store.migrate();api=new Api(settings,store);advance(40);advance(41);advance(80);assertEquals("completed",order(a).path("status").asText());assertEquals("completed",order(b).path("status").asText());
 }
 @Test void strictValidationReplayAndEpochFencing(){
  get();assertEquals(422,post("bad",Map.of("action","create","product","PRODUCT","line","LINE-1","quantity",true),422).has("detail")?422:0);
  var body=Map.<String,Object>of("action","create","product","PRODUCT","line","LINE-1","quantity",1,"due_at",2);var first=post("same",body,200);advance(2);assertEquals(first.path("id"),post("same",body,200).path("id"));post("same",Map.of("action","create","product","PRODUCT","line","LINE-1","quantity",2,"due_at",2),409);
  var old=store.run();store.control("reset",1,old.get("id").toString(),null,null);post("stale",Map.of("action","supply","sku","COMPONENT","quantity",1,"run_id",old.get("id"),"epoch",old.get("epoch")),409);
  assertTrue(store.audit().stream().anyMatch(a->a.get("actor").equals("employee")&&a.get("outcome").equals("accepted")));
 }

 @Test void seededProvidersCreateRealProduction(){store.seed();advance(30);assertTrue(get().path("orders").size()>0);assertTrue(get().path("materials").get(0).path("quantity").asInt()>0);store.seed();advance(32);advance(33);advance(60);assertTrue(java.util.stream.StreamSupport.stream(get().path("orders").spliterator(),false).anyMatch(o->o.path("status").asText().equals("completed")));}
 @Test void scrapAndPowerCannotDuplicateOrFinishEarly(){
  var scenario=Scenario.normalize(Json.parse("{\"manufacturing\":{\"products\":[{\"sku\":\"PRODUCT\",\"bom\":{\"COMPONENT\":2},\"duration_seconds\":20,\"scrap_percent\":25}],\"lines\":[{\"code\":\"LINE-1\",\"capacity\":1,\"products\":[\"PRODUCT\"]}]}}"));
  store.control("reset",1,store.run().get("id").toString(),null,scenario);command(Map.of("action","supply","sku","COMPONENT","quantity",8));advance(2);UUID id=create(4);command(Map.of("action","release","reference",id));advance(6);advance(7);double finish=order(id).path("finish_due").asDouble();
  store.grant(finish,store.run().get("epoch"),"Power unavailable");for(var j:(List<Map<String,Object>>)store.status().get("jobs"))store.execute(Store.uuid(j.get("id")));assertEquals("running",order(id).path("status").asText());advance(finish+1);assertEquals(3,order(id).path("output_quantity").asInt());assertEquals(1,order(id).path("scrap_quantity").asInt());
 }
 @Test void employeeCannotStartOrFinishOrControlRun(){post("start",Map.of("action","start","reference",UUID.randomUUID()),422);var r=new MockHttpServletRequest("POST","/api/control/hold");r.addHeader("Authorization","Basic "+Base64.getEncoder().encodeToString("employee:test".getBytes()));assertEquals(403,api.handle(r,"{}").getStatusCode().value());}
 @Test void issuedStorageMaterialIsDeduplicatedByAggregate(){
  UUID aggregate=UUID.randomUUID();var run=store.run();var event=(com.fasterxml.jackson.databind.node.ObjectNode)Json.M.valueToTree(Map.of("type","storage.issue.completed.v1","federation_id","factory-test","run_id",run.get("id"),"epoch",run.get("epoch"),"correlation_id",UUID.randomUUID(),"causation_id",UUID.randomUUID(),"aggregate_id",aggregate,"aggregate_version",2,"source","storage","destination","manufacturing"));
  event.put("event_id",UUID.randomUUID().toString());event.put("schema_version","1.0");event.put("boundary","materials");event.put("effective_time",2);event.put("quantity_unit","item");event.set("payload",Json.M.valueToTree(Map.of("id",aggregate,"run_id",run.get("id"),"correlation_id",event.path("correlation_id").asText(),"sku","COMPONENT","location","RAW-A","quantity",8,"purpose","production","status","issued","version",2)));
  var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","FEDERATION_ID","factory-test","CLOCK_MODE","helics","BOUNDARY_PROVIDERS","{\"materials\":\"helics\",\"demand\":\"synthetic\",\"power\":\"synthetic\"}","HELICS_PEERS","{\"materials\":{\"source\":\"storage\",\"endpoint\":\"storage/events\"}}"));
  // A connected peer is configured explicitly; no real native handle is used by SQL ingress.
  try(var ingressPool=new PoolClose(new Store(settings))){Store ingress=ingressPool.store;
   var reservation=(com.fasterxml.jackson.databind.node.ObjectNode)event.deepCopy();reservation.put("event_id",UUID.randomUUID().toString());reservation.put("type","storage.reserve.completed.v1");reservation.put("aggregate_version",1);((com.fasterxml.jackson.databind.node.ObjectNode)reservation.path("payload")).put("status","reserved").put("version",1);
   assertEquals("observed",ingress.ingest(reservation,"storage/events"));assertEquals(0,get().path("materials").get(0).path("quantity").asInt());
   assertEquals("accepted",ingress.ingest(event,"storage/events"));assertEquals("duplicate",ingress.ingest(event,"storage/events"));event.put("event_id",UUID.randomUUID().toString());assertThrows(Store.Conflict.class,()->ingress.ingest(event,"storage/events"));}
  advance(2);assertEquals(8,get().path("materials").get(0).path("quantity").asInt());
 }
 record PoolClose(Store store) implements AutoCloseable {public void close(){store.pool.close();}}

 @Test void acceptedProductionAuditFailureRollsBackTheEntireCommand(){
  var run=store.run();store.tx(c->{Store.sql(c,"CREATE OR REPLACE FUNCTION production_audit_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.actor='abort-production' THEN RAISE EXCEPTION 'test audit failure'; END IF; RETURN NEW; END $$");Store.sql(c,"CREATE TRIGGER production_audit_failure BEFORE INSERT ON command_audit FOR EACH ROW EXECUTE FUNCTION production_audit_failure()");return null;});
  try {var b=Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"due_at",2,"action","supply","sku","COMPONENT","quantity",2));assertThrows(Store.Unavailable.class,()->Production.command(store,"audit-rollback",b,new Store.Audit("abort-production","employee",UUID.randomUUID(),"production:supply","audit-rollback","test",run.get("id"))));assertNull(store.tx(c->Store.one(c,"SELECT id FROM jobs WHERE run_id=? AND idempotency_key='audit-rollback'",run.get("id"))));}
  finally {store.tx(c->{Store.sql(c,"DROP TRIGGER production_audit_failure ON command_audit");Store.sql(c,"DROP FUNCTION production_audit_failure()");return null;});}
 }
 @Test void invalidConfigurationAndAllScrapRespectAccounting(){
  assertThrows(IllegalArgumentException.class,()->Scenario.normalize(Json.parse("{\"manufacturing\":{\"products\":[],\"lines\":[]}}")));
  var cfg=Production.config(null).deepCopy();((com.fasterxml.jackson.databind.node.ObjectNode)cfg.path("products").get(0)).put("scrap_percent",100);
  var scenario=(com.fasterxml.jackson.databind.node.ObjectNode)Scenario.normalize(Json.parse("{}"));scenario.set("manufacturing",cfg);store.control("reset",1,store.run().get("id").toString(),null,scenario);
  command(Map.of("action","supply","sku","COMPONENT","quantity",4));advance(2);UUID id=create(2);command(Map.of("action","release","reference",id));advance(6);advance(7);advance(30);assertEquals(0,order(id).path("output_quantity").asInt());assertEquals(2,order(id).path("scrap_quantity").asInt());assertEquals(0L,((Number)store.status().get("pending_boundary_outputs")).longValue());
 }

 @Test void jobKeysCannotBeReusedAcrossCommandTypes(){store.schedule("cross-kind",2,1,null,null);post("cross-kind",Map.of("action","supply","sku","COMPONENT","quantity",1,"due_at",2),409);}
 @Test void employeeHoldWinsOverQueuedAutomaticRelease(){
  store.seed();advance(30);UUID id=UUID.fromString(get().path("orders").get(0).path("id").asText());var hold=post("hold-provider",Map.of("action","hold","reference",id,"due_at",31),200);store.seed();store.grant(31,store.run().get("epoch"),null);assertEquals("completed",store.execute(UUID.fromString(hold.path("id").asText())));advance(31);advance(32);assertEquals("held",order(id).path("status").asText());
 }

 @Test void workOrdersExposeQueuedThenReadyBeforeStart(){UUID id=create(1);assertEquals("queued",order(id).path("status").asText());command(Map.of("action","release","reference",id));advance(4);assertEquals("ready",order(id).path("status").asText());}
 @Test void pumpAssemblyPresetProvidesSeededFiniteResources(){var preset=new Settings(Map.of("APP_PASSWORD","test","SCENARIO_PRESET","pump-assembly"));var cfg=Production.config(preset.scenario.get("manufacturing"));assertEquals("PUMP",cfg.path("products").get(0).path("sku").asText());assertEquals(3,cfg.path("products").get(0).path("bom").size());assertEquals(2,cfg.path("lines").get(0).path("capacity").asInt());}
 @Test void batchCompletionPublishesGoodAndScrapAccountingOnce()throws Exception{
  command(Map.of("action","supply","sku","COMPONENT","quantity",4));advance(2);UUID id=create(2);command(Map.of("action","release","reference",id));advance(6);advance(7);advance(30);
  assertEquals(1,get().path("events").size());assertFalse(store.prepare(31,store.run().get("epoch")));var event=get().path("events").get(0).path("envelope");assertEquals("manufacturing.batch.completed.v1",event.path("type").asText());assertEquals(2,event.path("payload").path("output_quantity").asInt());assertEquals(0,event.path("payload").path("scrap_quantity").asInt());assertEquals(id.toString(),event.path("correlation_id").asText());
  try(var broker=new Messaging(System.getenv("MANUFACTURING_TEST_AMQP"))){broker.relay(store);broker.relay(store);int count=0;com.rabbitmq.client.GetResponse delivery;while((delivery=broker.channel.basicGet("production.events.v1",true))!=null){var body=Json.parse(new String(delivery.getBody(),java.nio.charset.StandardCharsets.UTF_8));if(body.path("event_id").asText().equals(event.path("event_id").asText()))count++;}assertEquals(1,count);}
  advance(31);assertEquals(1,get().path("events").size());assertTrue(store.prepare(32,store.run().get("epoch")));
 }

 @Test void prerequisiteDeferralRemainsDispatchableAtTheNextGrant(){
  UUID id=create(1);command(Map.of("action","release","reference",id));advance(4);store.grant(5,store.run().get("epoch"),null);
  var runId=store.run().get("id");var start=store.tx(c->Store.one(c,"SELECT j.* FROM jobs j JOIN production_commands p ON p.id=j.id WHERE p.run_id=? AND p.command->>'action'='start'",runId));
  var out=store.dispatchable().stream().filter(o->o.get("job_id").equals(start.get("id"))).findFirst().orElseThrow();store.published(out.get("id"));assertEquals("waiting",store.execute(Store.uuid(start.get("id"))));store.published(out.get("id"));store.grant(6,store.run().get("epoch"),null);
  assertTrue(store.dispatchable().stream().anyMatch(o->o.get("job_id").equals(start.get("id"))),"A new simulation-time attempt must not inherit the broker-confirm resend delay");
 }
 @Test void resetArchivesCompletionFactsAndFencesTheirPublication(){
  command(Map.of("action","supply","sku","COMPONENT","quantity",2));advance(2);UUID id=create(1);command(Map.of("action","release","reference",id));advance(6);advance(7);advance(30);assertEquals(1,get().path("events").size());var old=store.run();store.control("reset",1,old.get("id").toString(),null,null);assertEquals(0,Production.pendingEvents(store).size());assertEquals(1L,((Number)store.tx(c->Store.one(c,"SELECT count(*) n FROM production_events WHERE run_id=? AND sent_at IS NULL",old.get("id"))).get("n")).longValue());
 }
}
