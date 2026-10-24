package simu.manufacturing;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static simu.manufacturing.Store.*;

@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class OutputCustodyTest {
 ProductionTest fixture;Store ingress;
 @BeforeEach void setup(){fixture=new ProductionTest();fixture.setup();ingress=new Store(new Settings(Map.of("DATABASE_URL",System.getenv("MANUFACTURING_TEST_DATABASE"),"APP_PASSWORD","test","CLOCK_MODE","helics","FEDERATION_ID","output-custody","BOUNDARY_PROVIDERS","{\"materials\":\"helics\",\"demand\":\"synthetic\",\"power\":\"synthetic\"}","HELICS_PEERS","{\"materials\":{\"source\":\"storage\",\"endpoint\":\"storage/events\"}}")));}
 @AfterEach void close(){fixture.store.tx(c->{sql(c,"UPDATE runs SET mode='standalone' WHERE current");return null;});ingress.pool.close();fixture.close();}
 JsonNode finish(){fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",4));fixture.advance(2);var batch=fixture.create(2);fixture.command(Map.of("action","release","reference",batch));fixture.advance(6);fixture.advance(7);fixture.store.tx(c->{sql(c,"UPDATE runs SET mode='helics' WHERE id=?",fixture.store.run().get("id"));return null;});advance(fixture.order(batch).path("finish_due").asDouble());return fixture.get();}
 JsonNode output(JsonNode snapshot){for(var unit:snapshot.path("handling").path("units"))if(unit.path("category").asText().equals("finished"))return unit;throw new AssertionError("missing finished unit");}
 ObjectNode envelope(String stage){return ingress.tx(c->{var row=one(c,"SELECT envelope FROM boundary_outbox WHERE run_id=? AND envelope->>'type'=?",fixture.store.run().get("id"),"handling."+stage+".v1");return row==null?null:(ObjectNode)json(row.get("envelope"));});}
 ObjectNode reply(ObjectNode original,String stage){var e=original.deepCopy();e.put("type","handling."+stage+".v1");e.put("event_id",UUID.randomUUID().toString());e.put("federation_id","output-custody");e.put("source","storage");e.put("destination","manufacturing");e.put("boundary","materials");e.put("effective_time",number(fixture.store.run(),"granted")+1);((ObjectNode)e.path("payload")).put("state",stage);if(stage.equals("received"))((ObjectNode)e.path("payload")).put("receipt_id",UUID.randomUUID().toString());return e;}
 void advance(double t){fixture.store.tx(c->{sql(c,"UPDATE runs SET requested=? WHERE current",t);return null;});fixture.store.grant(t,fixture.store.run().get("epoch"),null);for(var job:(List<Map<String,Object>>)fixture.store.status().get("jobs"))ingress.execute(uuid(job.get("id")));}
 void receive(ObjectNode e){assertEquals("accepted",ingress.ingest(e,"storage/events"));advance(e.path("effective_time").asDouble());var job=ingress.tx(c->one(c,"SELECT id FROM jobs WHERE idempotency_key=?","boundary:"+e.path("event_id").asText()).get("id"));assertEquals("duplicate",ingress.execute(uuid(job)));}
 @Test void finishedOutputRetainsPositionUntilAcceptedThenRetiresOnlyMatchingReceipt(){
  var snapshot=finish();var produced=output(snapshot);var offer=envelope("offered");assertNotNull(offer,"finished production must offer its fresh whole unit instead of a quantity-only receipt");
  assertEquals(Integer.valueOf(0),ingress.tx(c->rows(c,"SELECT id FROM boundary_outbox WHERE run_id=? AND envelope->>'type'='storage.receipt.v1'",fixture.store.run().get("id")).size()));
  assertEquals(produced,offer.path("payload").path("unit"));assertEquals("reserved",produced.path("state").asText());assertEquals("manufacturing.cell01.output01",produced.path("position").asText());assertEquals(1,snapshot.path("handling").path("lineage").size());
  var accepted=reply(offer,"accepted");receive(accepted);var departed=envelope("departed");assertNotNull(departed);var transit=output(fixture.get());assertTrue(transit.path("position").isNull());assertEquals("in_transit",transit.path("state").asText());assertEquals(3,transit.path("version").asInt());assertEquals(2,transit.path("last_sequence").asInt());assertEquals(1,transit.path("custody_generation").asInt());
  var corrupt=reply(departed,"received");((ObjectNode)corrupt.path("payload").path("unit").path("contents").get(0)).put("quantity",3);receive(corrupt);assertEquals("in_transit",output(fixture.get()).path("state").asText());assertEquals(1,fixture.get().path("handling").path("quarantine").size());
  var receipt=reply(departed,"received");receive(receipt);assertEquals("dispatched",output(fixture.get()).path("state").asText());assertNotNull(envelope("acknowledged"));assertEquals("duplicate",ingress.ingest(receipt,"storage/events"));assertEquals(snapshot.path("handling").path("movements").size()+1,fixture.get().path("handling").path("movements").size());
 }
}
