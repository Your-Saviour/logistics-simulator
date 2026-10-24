package simu.manufacturing;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static simu.manufacturing.Store.*;

@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class MaterialRecoveryTest {
 MaterialPlanningTest fixture;
 @BeforeEach void setup(){fixture=new MaterialPlanningTest();fixture.setup();}
 @AfterEach void close(){if(fixture!=null)fixture.close();}
 Store store(){return fixture.store();}
 ObjectNode failed(JsonNode original,String action){var e=(ObjectNode)original.deepCopy();e.put("type","storage.command.rejected.v1");e.put("event_id",UUID.randomUUID().toString());e.set("causation_id",original.get("event_id"));e.put("source","storage");e.put("destination","manufacturing");e.put("boundary","materials");e.put("effective_time",number(store().run(),"granted")+1);e.put("wall_time","2026-10-25T00:00:00Z");var body=(ObjectNode)original.path("payload").deepCopy();body.put("action",action);body.set("run_id",original.get("run_id"));body.set("epoch",original.get("epoch"));body.set("due_at",original.get("effective_time"));if(action.equals("reserve"))body.set("correlation_id",original.get("correlation_id"));var p=e.putObject("payload");p.put("action",action);p.put("reason","Insufficient available stock; complete quantities required");p.set("request",body);return e;}
 @Test void rejectedReservationRetriesAsANewIntentWithoutChangingTheRecipeQuantity(){
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var original=fixture.release(batch);var failure=failed(original,"reserve");fixture.execute(failure);
  assertEquals("running",store().run().get("state"));assertEquals(0,fixture.peer.fixture.get().path("handling").path("units").size());
  var retry=store().tx(c->one(c,"SELECT j.* FROM jobs j JOIN production_commands p USING(id) WHERE j.run_id=? AND p.command->>'action'='material_retry'",store().run().get("id")));assertNotNull(retry);
  assertEquals("duplicate",store().ingest(failure,"storage/events"));fixture.clock(number(retry,"due_at"));assertEquals("completed",store().execute(uuid(retry.get("id"))));
  var requests=store().tx(c->rows(c,"SELECT envelope FROM boundary_outbox WHERE run_id=? AND envelope->>'type'='storage.request.v1' ORDER BY (envelope->>'effective_time')::double precision",store().run().get("id")));assertEquals(2,requests.size());var next=json(requests.get(1).get("envelope"));assertNotEquals(original.path("event_id"),next.path("event_id"));assertNotEquals(original.path("aggregate_id"),next.path("aggregate_id"));assertEquals(original.path("payload"),next.path("payload"));assertTrue(next.path("effective_time").asDouble()>number(store().run(),"granted"));
  var reservation=fixture.reserved(next,fixture.units("COMPONENT",2));fixture.execute(reservation);assertEquals(1,fixture.issueCount(),"obsolete rejected attempt must not block admission");
 }
 JsonNode output(String type){return store().tx(c->json(one(c,"SELECT envelope FROM boundary_outbox WHERE run_id=? AND envelope->>'type'=? ORDER BY (envelope->>'effective_time')::double precision DESC LIMIT 1",store().run().get("id"),type).get("envelope")));}
 @Test void rejectedIssueReleasesSourceReservationBeforeRetryingAndFreesOnlyUnreceivedPromises(){
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var request=fixture.release(batch);var units=fixture.units("COMPONENT",2);var reservation=fixture.reserved(request,units);fixture.execute(reservation);var issue=output("storage.issue.v1");fixture.execute(failed(issue,"issue"));
  assertEquals(2,store().tx(c->rows(c,"SELECT unit_id FROM production_material_expected WHERE run_id=?",store().run().get("id"))).size());assertEquals(0,store().tx(c->rows(c,"SELECT id FROM production_commands WHERE run_id=? AND command->>'action'='material_retry'",store().run().get("id"))).size());
  var release=output("storage.release.v1");var proof=reservation.deepCopy();proof.put("type","storage.release.completed.v1");proof.put("event_id",UUID.randomUUID().toString());proof.set("causation_id",release.get("event_id"));proof.put("effective_time",number(store().run(),"granted")+1);proof.put("aggregate_version",2);((ObjectNode)proof.path("payload")).put("status","released").put("version",2).remove("unit_manifest");fixture.execute(proof);
  assertEquals(0,store().tx(c->rows(c,"SELECT unit_id FROM production_material_expected WHERE run_id=?",store().run().get("id"))).size());var retry=store().tx(c->one(c,"SELECT j.* FROM jobs j JOIN production_commands p USING(id) WHERE j.run_id=? AND p.command->>'action'='material_retry'",store().run().get("id")));fixture.clock(number(retry,"due_at"));assertEquals("completed",store().execute(uuid(retry.get("id"))));
  for(var unit:units)unit.put("version",unit.path("version").asInt()+2);fixture.execute(fixture.reserved(output("storage.request.v1"),units));assertEquals(2,fixture.issueCount());
  var late=failed(release,"release");fixture.execute(late);assertEquals("quarantined",store().tx(c->one(c,"SELECT state FROM production_material_failures WHERE event_id=?",Policy.uuid(late.get("event_id")))).get("state"));assertEquals("reserved",store().tx(c->one(c,"SELECT state FROM production_material_requests WHERE id=?",Policy.uuid(request.get("aggregate_id")))).get("state"));
 }
 @Test void retryingOneSkuPreservesAnotherSkusExistingReservation(){
  fixture.twoMaterials(2);UUID batch=fixture.peer.fixture.create(1);fixture.connected();var requests=fixture.requests(fixture.release(batch));var kept=fixture.reserved(requests.get(0),fixture.units("COMPONENT",2));fixture.execute(kept,"waiting");var failure=failed(requests.get(1),"reserve");fixture.execute(failure);
  var retry=store().tx(c->one(c,"SELECT j.* FROM jobs j JOIN production_commands p USING(id) WHERE j.run_id=? AND p.command->>'action'='material_retry'",store().run().get("id")));fixture.clock(number(retry,"due_at"));assertEquals("completed",store().execute(uuid(retry.get("id"))));fixture.execute(fixture.reserved(output("storage.request.v1"),fixture.units("OTHER",2)));assertEquals(2,fixture.issueCount());
  assertEquals(1,store().tx(c->rows(c,"SELECT id FROM boundary_outbox WHERE run_id=? AND envelope->>'type'='storage.request.v1' AND envelope->'payload'->>'sku'='COMPONENT'",store().run().get("id"))).size());
  fixture.execute(failed(requests.get(1),"reserve"));assertEquals(1,store().tx(c->rows(c,"SELECT id FROM production_commands WHERE run_id=? AND command->>'action'='material_retry'",store().run().get("id"))).size());
 }
 @Test void sourceOperatorReleaseSupersedesOldIssueWithoutBlockingItsReplacement(){
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var request=fixture.release(batch);var reservation=fixture.reserved(request,fixture.units("COMPONENT",2));fixture.execute(reservation);var issue=output("storage.issue.v1");fixture.execute(failed(issue,"issue"));var recoveryRelease=output("storage.release.v1");
  var proof=reservation.deepCopy();proof.put("type","storage.release.completed.v1");proof.put("event_id",UUID.randomUUID().toString());proof.put("causation_id",UUID.randomUUID().toString());proof.put("effective_time",number(store().run(),"granted")+1);proof.put("aggregate_version",2);((ObjectNode)proof.path("payload")).put("status","released").put("version",2).remove("unit_manifest");fixture.execute(proof);
  fixture.execute(failed(recoveryRelease,"release"));assertEquals("retry_pending",store().tx(c->one(c,"SELECT state FROM production_material_requests WHERE id=?",Policy.uuid(request.get("aggregate_id")))).get("state"));assertEquals(0,store().tx(c->rows(c,"SELECT unit_id FROM production_material_expected WHERE run_id=?",store().run().get("id"))).size());
 }
 @Test void unknownAndStaleOutcomesRemainInspectableWithoutCreatingRetryWork(){
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var request=fixture.release(batch);var unknown=failed(request,"reserve");unknown.put("causation_id",UUID.randomUUID().toString());fixture.execute(unknown);assertEquals("quarantined",store().tx(c->one(c,"SELECT state FROM production_material_failures WHERE event_id=?",Policy.uuid(unknown.get("event_id")))).get("state"));
  var stale=failed(request,"reserve");stale.put("epoch",UUID.randomUUID().toString());assertEquals("quarantined",store().ingest(stale,"storage/events"));assertEquals(0,store().tx(c->rows(c,"SELECT id FROM production_commands WHERE run_id=? AND command->>'action'='material_retry'",store().run().get("id"))).size());assertEquals(2,fixture.peer.fixture.get().path("material_recovery").path("outcomes").size());
 }
 @Test void priorReleaseOutboxCanBackfillLogicalAttemptsWithoutChangingItsEnvelope()throws Exception{
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var request=fixture.release(batch);String migration=new String(getClass().getResourceAsStream("/migrations/012_material_request_recovery.sql").readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);String backfill=migration.substring(migration.indexOf("INSERT INTO production_material_requests"));backfill=backfill.replace("production_material_requests","upgrade_material_requests").replace("production_material_attempts","upgrade_material_attempts");final String sqlText=backfill;
  store().tx(c->{try(var statement=c.createStatement()){statement.execute("CREATE TEMP TABLE upgrade_material_requests (LIKE production_material_requests INCLUDING ALL); CREATE TEMP TABLE upgrade_material_attempts (LIKE production_material_attempts INCLUDING ALL)");statement.execute(sqlText);}var restored=one(c,"SELECT r.batch_id,a.envelope FROM upgrade_material_requests r JOIN upgrade_material_attempts a ON a.request_id=r.id WHERE r.id=?",Policy.uuid(request.get("aggregate_id")));assertEquals(batch,restored.get("batch_id"));assertEquals(request,json(restored.get("envelope")));return null;});
 }
 @Test void contradictoryIssueRejectionCannotReverseDurableCapacityAcceptance(){
  UUID batch=fixture.peer.fixture.create(1);fixture.connected();var request=fixture.release(batch);var units=fixture.units("COMPONENT",2);var reservation=fixture.reserved(request,units);fixture.execute(reservation);var issue=output("storage.issue.v1");var h=fixture.peer.offer();h.set("unit",units[0]);h.set("origin",units[0].get("position"));h.set("destination",issue.path("payload").path("unit_destinations").get(units[0].path("id").asText()));var offer=fixture.peer.wire(h);offer.set("correlation_id",request.get("correlation_id"));fixture.execute(offer);
  var rejection=failed(issue,"issue");fixture.execute(rejection);assertEquals("quarantined",store().tx(c->one(c,"SELECT state FROM production_material_failures WHERE event_id=?",Policy.uuid(rejection.get("event_id")))).get("state"));assertEquals(0,store().tx(c->rows(c,"SELECT event_id FROM production_material_releases WHERE request_id=?",Policy.uuid(request.get("aggregate_id")))).size());assertEquals(2,store().tx(c->rows(c,"SELECT unit_id FROM production_material_expected WHERE run_id=?",store().run().get("id"))).size());
 }
}
