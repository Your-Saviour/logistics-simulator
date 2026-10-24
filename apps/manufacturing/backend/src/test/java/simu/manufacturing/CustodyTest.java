package simu.manufacturing;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static simu.manufacturing.Store.*;

@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class CustodyTest {
 ProductionTest fixture; Store ingress;
 @BeforeEach void setup(){fixture=new ProductionTest();fixture.setup();fixture.get();var settings=new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","FEDERATION_ID","factory-custody","CLOCK_MODE","helics","BOUNDARY_PROVIDERS","{\"materials\":\"helics\",\"demand\":\"synthetic\",\"power\":\"synthetic\"}","HELICS_PEERS","{\"materials\":{\"source\":\"storage\",\"endpoint\":\"storage/events\"}}"));ingress=new Store(settings);}
 @AfterEach void close(){if(ingress!=null)ingress.pool.close();if(fixture!=null)fixture.close();}
 ObjectNode wire(ObjectNode handoff){var run=fixture.store.run();var e=Json.M.createObjectNode();e.put("schema_version","1.0");e.put("type","handling."+handoff.path("state").asText()+".v1");e.put("event_id",UUID.randomUUID().toString());e.put("federation_id","factory-custody");e.put("run_id",run.get("id").toString());e.put("epoch",run.get("epoch").toString());e.put("correlation_id",run.get("id").toString());e.put("causation_id",handoff.path("id").asText());e.put("aggregate_id",handoff.path("id").asText());e.put("aggregate_version",handoff.path("unit").path("version").asInt());e.put("source","storage");e.put("destination","manufacturing");e.put("boundary","materials");e.put("effective_time",number(run,"granted")+1);e.put("wall_time","2026-10-25T00:00:00Z");e.put("quantity_unit","item");e.set("payload",handoff);return e;}
 void execute(ObjectNode event){fixture.store.tx(c->{sql(c,"UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE run_id=?",fixture.store.run().get("id"));return null;});fixture.store.grant(event.path("effective_time").asDouble(),fixture.store.run().get("epoch"),null);var id=ingress.tx(c->uuid(one(c,"SELECT id FROM jobs WHERE idempotency_key=?","boundary:"+event.path("event_id").asText()).get("id")));assertEquals("completed",ingress.execute(id));}
 ObjectNode offer(){
  var run=fixture.store.run();UUID id=UUID.randomUUID(),handoff=UUID.randomUUID();var unit=Json.M.createObjectNode();unit.put("id",id.toString());unit.put("barcode","HU-"+id.toString().replace("-","").toUpperCase(Locale.ROOT));unit.put("run_id",run.get("id").toString());unit.put("epoch",run.get("epoch").toString());unit.set("contents",Json.M.valueToTree(List.of(Map.of("sku","COMPONENT","quantity",2))));unit.put("category","raw");unit.put("state","reserved");unit.put("owner","storage");unit.put("version",1);unit.put("custody_generation",0);unit.put("last_sequence",1);unit.put("position","storage.raw.r01.b01.l01");for(var key:List.of("origin","destination","handoff_id"))unit.putNull(key);
  var h=Json.M.createObjectNode();h.put("id",handoff.toString());h.put("run_id",run.get("id").toString());h.put("epoch",run.get("epoch").toString());h.put("source","storage");h.put("destination_owner","manufacturing");h.put("origin",unit.path("position").asText());h.put("destination","manufacturing.cell01.input01");h.put("state","offered");h.set("unit",unit);for(var key:List.of("departure_token","receipt_id","reason"))h.putNull(key);
  return h;
 }
 @Test void acceptsCapacityWithoutStockAndImportsOnlyMatchingDeparture(){
  var h=offer();var unit=(ObjectNode)h.path("unit");UUID id=Policy.uuid(unit.get("id")),handoff=Policy.uuid(h.get("id"));var run=fixture.store.run();
  var offer=wire(h);assertThrows(RuntimeException.class,()->ingress.ingest(offer,"intruder/events"));assertEquals("accepted",ingress.ingest(offer,"storage/events"));execute(offer);
  assertEquals(0,fixture.get().path("handling").path("units").size());assertEquals(0,fixture.get().path("materials").get(0).path("quantity").asInt());assertEquals(1,fixture.get().path("handling").path("handoffs").size());
  var departed=h.deepCopy();departed.put("state","departed");var transit=unit.deepCopy();transit.put("state","in_transit");transit.putNull("position");transit.put("origin",h.path("origin").asText());transit.put("destination",h.path("destination").asText());transit.put("handoff_id",handoff.toString());transit.put("version",2);transit.put("last_sequence",2);transit.put("custody_generation",1);departed.set("unit",transit);departed.set("departure_token",Json.M.valueToTree(Map.of("id",UUID.randomUUID(),"handoff_id",handoff,"unit_id",id,"run_id",run.get("id"),"epoch",run.get("epoch"),"custody_generation",1,"last_sequence",2,"unit_version",2)));
  var event=wire(departed);assertEquals("accepted",ingress.ingest(event,"storage/events"));execute(event);var snapshot=fixture.get();var received=snapshot.path("handling").path("units").get(0);assertEquals(id.toString(),received.path("id").asText());assertEquals("manufacturing.cell01.input01",received.path("position").asText());assertEquals(3,received.path("last_sequence").asInt());assertEquals(1,received.path("custody_generation").asInt());assertEquals(2,snapshot.path("materials").get(0).path("quantity").asInt());assertEquals("duplicate",ingress.ingest(event,"storage/events"));assertEquals(1,fixture.get().path("handling").path("movements").size());
  var corrupt=departed.deepCopy();((ObjectNode)corrupt.path("unit").path("contents").get(0)).put("quantity",3);var bad=wire(corrupt);assertEquals("accepted",ingress.ingest(bad,"storage/events"));execute(bad);assertEquals(2,fixture.get().path("materials").get(0).path("quantity").asInt());
  var ack=(ObjectNode)fixture.get().path("handling").path("handoffs").get(0).deepCopy();ack.put("state","acknowledged");var acknowledgement=wire(ack);assertEquals("accepted",ingress.ingest(acknowledgement,"storage/events"));execute(acknowledgement);assertEquals("acknowledged",fixture.get().path("handling").path("handoffs").get(0).path("state").asText());assertEquals(2,fixture.get().path("materials").get(0).path("quantity").asInt());

 }
 @Test void reservedInputsExcludeLocalSupplyAndDuplicateOffersReplayStableAcceptance(){
  var first=wire(offer());assertEquals("accepted",ingress.ingest(first,"storage/events"));execute(first);
  fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",2));fixture.advance(number(fixture.store.run(),"granted")+2);
  assertEquals("manufacturing.cell01.input02",fixture.get().path("handling").path("units").get(0).path("position").asText());
  var competing=wire(offer());assertEquals("accepted",ingress.ingest(competing,"storage/events"));execute(competing);
  assertEquals(1,fixture.get().path("handling").path("handoffs").size());
  assertEquals(Boolean.TRUE,ingress.tx(c->Boolean.TRUE.equals(one(c,"SELECT retryable_capacity FROM production_commands WHERE id=(SELECT command_id FROM production_custody_events WHERE event_id=?)",Policy.uuid(competing.get("event_id"))).get("retryable_capacity"))));
  var original=ingress.tx(c->json(one(c,"SELECT envelope FROM boundary_outbox WHERE envelope->>'type'='handling.accepted.v1' AND run_id=? LIMIT 1",fixture.store.run().get("id")).get("envelope")));
  ingress.tx(c->{sql(c,"UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=?",fixture.store.run().get("id"));return null;});
  assertEquals("duplicate",ingress.ingest(first,"storage/events"));
  assertEquals(original,ingress.tx(c->json(one(c,"SELECT envelope FROM boundary_outbox WHERE sent_at IS NULL AND run_id=?",fixture.store.run().get("id")).get("envelope"))));
  var changed=first.deepCopy();((ObjectNode)changed.path("payload")).put("reason","changed");assertEquals("quarantined",ingress.ingest(changed,"storage/events"));
 }

 @Test void legacyConversionCannotOccupyAnAcceptedIncomingEndpoint(){
  var event=wire(offer());assertEquals("accepted",ingress.ingest(event,"storage/events"));execute(event);var run=fixture.store.run();
  fixture.store.tx(c->{sql(c,"UPDATE production_materials SET quantity=2 WHERE run_id=? AND sku='COMPONENT'",run.get("id"));return null;});
  var body=Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"due_at",number(run,"granted")+2,"action","convert","sku","COMPONENT","quantity",2,"units",List.of(Map.of("id",UUID.randomUUID(),"quantity",2,"position","manufacturing.cell01.input01"))));
  var command=Production.command(fixture.store,"promised-conversion",body,new Store.Audit("promised-conversion","operator",UUID.randomUUID(),"production:convert","promised-conversion","test",run.get("id")));fixture.advance(number(run,"granted")+2);
  var status=fixture.store.tx(c->one(c,"SELECT status FROM production_commands WHERE id=?",command.get("id"))).get("status");assertEquals("rejected",status);assertEquals(0,fixture.get().path("handling").path("units").size());
 }

 @Test void recoveryRetriesUnacknowledgedEvidenceOncePerWindowWithoutChangingEnvelope(){
  var event=wire(offer());assertEquals("accepted",ingress.ingest(event,"storage/events"));execute(event);var run=fixture.store.run();
  var original=ingress.tx(c->json(one(c,"SELECT envelope FROM boundary_outbox WHERE run_id=?",run.get("id")).get("envelope")));
  ingress.tx(c->{sql(c,"UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=?",run.get("id"));return null;});
  assertEquals(Integer.valueOf(1),ingress.tx(c->Custody.recover(c,current(c))));assertEquals(Integer.valueOf(0),ingress.tx(c->Custody.recover(c,current(c))));
  assertEquals(original,ingress.tx(c->json(one(c,"SELECT envelope FROM boundary_outbox WHERE run_id=? AND sent_at IS NULL",run.get("id")).get("envelope"))));
 }

 @Test void staleAndChangedCustodyFramesAreDurableQuarantineWithoutStock(){
  var stale=wire(offer());String epoch=UUID.randomUUID().toString();stale.put("epoch",epoch);((ObjectNode)stale.path("payload")).put("epoch",epoch);((ObjectNode)stale.path("payload").path("unit")).put("epoch",epoch);
  assertEquals("quarantined",ingress.ingest(stale,"storage/events"));assertEquals("quarantined",ingress.ingest(stale,"storage/events"));assertEquals(1,fixture.get().path("handling").path("quarantine").size());assertEquals(0,fixture.get().path("handling").path("units").size());
  var accepted=wire(offer());assertEquals("accepted",ingress.ingest(accepted,"storage/events"));execute(accepted);var changed=accepted.deepCopy();changed.put("correlation_id",UUID.randomUUID().toString());assertEquals("quarantined",ingress.ingest(changed,"storage/events"));assertEquals(2,fixture.get().path("handling").path("quarantine").size());assertEquals(1,fixture.get().path("handling").path("handoffs").size());assertEquals(0,fixture.get().path("materials").get(0).path("quantity").asInt());
 }

}
