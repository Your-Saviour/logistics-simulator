package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static simu.manufacturing.Store.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class FleetNativeTest {
 @Test void snapshotCacheRejectsMismatchedAuthenticatedNativeMapping(){
  var fixture=new ProductionTest();fixture.setup();Store coordinated=null;try{
   var env=new HashMap<>(fixture.store.settings.env);env.putAll(new FleetScopeTest().settings.env);coordinated=new Store(new Settings(env));var store=coordinated;var run=store.run();var id=UUID.randomUUID();store.tx(c->{Fleet.track(c,run,id,null);return null;});var row=store.tx(c->one(c,"SELECT * FROM production_fleet_jobs WHERE id=?",id));var snapshot=Json.M.createObjectNode();snapshot.set("fleet_scope",Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",UUID.randomUUID(),"offset",1)));
   assertThrows(Store.Conflict.class,()->Fleet.mark(store,row,"snapshot",snapshot));assertNull(store.tx(c->one(c,"SELECT snapshot FROM production_fleet_jobs WHERE id=?",id).get("snapshot")));
   ((ObjectNode)snapshot.path("fleet_scope")).put("epoch",run.get("epoch").toString());Fleet.mark(store,row,"snapshot",snapshot);assertEquals(snapshot,store.tx(c->json(one(c,"SELECT snapshot FROM production_fleet_jobs WHERE id=?",id).get("snapshot"))));
  }finally{if(coordinated!=null)coordinated.pool.close();fixture.close();}
 }

 @Test void outputWaitPersistsOneRequestAndDefersBeyondGrantUntilPhysicalPickup(){
  var f=new OutputCustodyTest();f.setup();try{
   f.finish();var env=new HashMap<>(f.ingress.settings.env);env.put("FLEET_MODE","coordinated");env.put("FLEET_URL","http://unavailable.invalid");env.put("FLEET_TOKEN","private");env.put("FLEET_RUN_ID",UUID.randomUUID().toString());env.put("FLEET_EPOCH",UUID.randomUUID().toString());f.ingress.pool.close();f.ingress=new Store(new Settings(env));
   var accepted=f.reply(f.envelope("offered"),"accepted");assertEquals("accepted",f.ingress.ingest(accepted,"storage/events"));f.advance(accepted.path("effective_time").asDouble());
   var job=f.ingress.tx(c->one(c,"SELECT * FROM jobs WHERE idempotency_key=?","boundary:"+accepted.path("event_id").asText()));assertEquals("Awaiting coordinated fleet physical proof",job.get("error"));assertTrue(number(job,"due_at")>number(f.ingress.run(),"granted"));assertEquals("reserved",f.output(f.fixture.get()).path("state").asText());
   var intent=f.ingress.tx(c->one(c,"SELECT * FROM production_fleet_jobs WHERE run_id=?",f.ingress.run().get("id")));var original=json(intent.get("request"));assertEquals("manufacturing",original.path("producer").asText());assertEquals(1,original.path("custody_generation").asInt());
   f.advance(number(job,"due_at"));assertEquals(original,f.ingress.tx(c->json(one(c,"SELECT request FROM production_fleet_jobs WHERE run_id=?",f.ingress.run().get("id")).get("request"))));
   var snapshot=Json.M.createObjectNode();snapshot.set("request",original);snapshot.set("fleet_scope",Json.M.valueToTree(Map.of("run_id",f.ingress.run().get("id"),"epoch",f.ingress.run().get("epoch"),"offset",0)));var body=(ObjectNode)original.deepCopy();body.remove("id");body.put("job_id",intent.get("id").toString());body.put("robot_id",UUID.randomUUID().toString());body.put("kind","pickup_ready");body.put("route_version",1);body.put("effective_time",number(f.ingress.run(),"granted")+2);snapshot.set("events",Json.M.valueToTree(List.of(Map.of("kind","pickup_ready","body",body))));
   f.ingress.tx(c->{sql(c,"UPDATE production_fleet_jobs SET snapshot=?::jsonb WHERE id=?",Json.write(snapshot),intent.get("id"));return null;});f.advance(number(f.ingress.run(),"granted")+1);assertNull(f.envelope("departed"));f.advance(number(f.ingress.run(),"granted")+1);assertNotNull(f.envelope("departed"));assertEquals("in_transit",f.output(f.fixture.get()).path("state").asText());assertNotNull(f.ingress.tx(c->one(c,"SELECT departure FROM production_fleet_jobs WHERE run_id=?",f.ingress.run().get("id")).get("departure")));
  }finally{f.close();}
 }
}
