package simu.manufacturing;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class HandlingUnitTest {
 ProductionTest fixture;
 @BeforeEach void setup(){fixture=new ProductionTest();fixture.setup();}
 @AfterEach void close(){fixture.close();}
 @Test void wholeInputsWaitRatherThanSplitAndCompletionPreservesLineageAfterRestart(){
  UUID six=UUID.randomUUID(),four=UUID.randomUUID();
  fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",6,"units",List.of(Map.of("id",six,"quantity",6))));fixture.advance(2);
  UUID batch=fixture.create(2);fixture.command(Map.of("action","release","reference",batch));fixture.advance(6);fixture.advance(7);
  assertEquals("ready",fixture.order(batch).path("status").asText());
  assertTrue(fixture.order(batch).path("blocked_reason").asText().contains("whole"));
  assertEquals(6,fixture.get().path("materials").get(0).path("quantity").asInt());
  fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",4,"units",List.of(Map.of("id",four,"quantity",4))));fixture.advance(9);fixture.advance(10);
  assertEquals("running",fixture.order(batch).path("status").asText());
  var settings=fixture.store.settings;fixture.store.pool.close();fixture.store=new Store(settings);fixture.store.migrate();fixture.api=new Api(settings,fixture.store);
  fixture.advance(fixture.order(batch).path("finish_due").asDouble());
  var handling=fixture.get().path("handling");assertEquals(3,handling.path("units").size());
  var input=java.util.stream.StreamSupport.stream(handling.path("units").spliterator(),false).filter(u->u.path("id").asText().equals(four.toString())).findFirst().orElseThrow();
  assertEquals("consumed",input.path("state").asText());assertTrue(input.path("position").isNull());
  var consumed=java.util.stream.StreamSupport.stream(handling.path("movements").spliterator(),false).filter(m->m.path("unit_id").asText().equals(four.toString())&&m.path("action").asText().equals("consume")).toList();
  assertEquals(1,consumed.size(),"Whole input consumption needs a durable unit history record");
  var consume=consumed.get(0);assertEquals(input.path("barcode"),consume.path("barcode"));assertEquals(batch.toString(),consume.path("references").path("batch_id").asText());
  assertEquals("manufacturing.cell01.input02",consume.path("origin").asText());assertEquals(consume.path("origin"),consume.path("destination"));
  assertEquals(2,consume.path("sequence").asInt());assertEquals(consume.path("sequence"),input.path("last_sequence"));
  var output=java.util.stream.StreamSupport.stream(handling.path("units").spliterator(),false).filter(u->u.path("category").asText().equals("finished")).findFirst().orElseThrow();
  assertNotEquals(four.toString(),output.path("id").asText());assertNotEquals(six.toString(),output.path("id").asText());
  assertEquals("HU-"+output.path("id").asText().replace("-","").toUpperCase(Locale.ROOT),output.path("barcode").asText());
  assertEquals(2,output.path("contents").get(0).path("quantity").asInt());assertTrue(output.path("position").asText().startsWith("manufacturing.cell01.output"));
  assertEquals(1,handling.path("lineage").size());var lineage=handling.path("lineage").get(0);
  assertEquals(batch.toString(),lineage.path("batch_id").asText());assertEquals(four.toString(),lineage.path("input_unit_ids").get(0).asText());assertEquals(output.path("id"),lineage.path("output_unit_ids").get(0));
  var before=handling.deepCopy();fixture.advance(Store.number(fixture.store.run(),"granted")+1);
  assertEquals(before,fixture.get().path("handling"));assertEquals(6,fixture.get().path("materials").get(0).path("quantity").asInt());
  assertEquals(handling.path("units"),Json.M.valueToTree(Projection.read(fixture.store)).path("snapshot").path("handling").path("units"));
 }
 @Test void duplicateSupplyCannotCreateAnotherBarcodeOrChangeContents(){
  UUID unit=UUID.randomUUID();
  fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",4,"units",List.of(Map.of("id",unit,"quantity",4))));fixture.advance(2);
  var second=fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",5,"units",List.of(Map.of("id",unit,"quantity",5))));fixture.advance(4);
  var command=java.util.stream.StreamSupport.stream(fixture.get().path("commands").spliterator(),false).filter(c->c.path("id").equals(second.path("id"))).findFirst().orElseThrow();
  assertEquals("rejected",command.path("status").asText());assertEquals(4,fixture.get().path("materials").get(0).path("quantity").asInt());assertEquals(1,fixture.get().path("handling").path("units").size());
 }
 @Test void explicitLegacyConversionConservesRawMaterialsWithoutInventingMovements(){
  fixture.get();var run=fixture.store.run();fixture.store.tx(c->{Store.sql(c,"UPDATE production_materials SET quantity=6 WHERE run_id=? AND sku='COMPONENT'",run.get("id"));return null;});
  assertEquals(1,fixture.get().path("handling").path("legacy_stock").size());assertEquals(6,fixture.get().path("handling").path("legacy_stock").get(0).path("unplaced_quantity").asInt());
  var body=new LinkedHashMap<String,Object>(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"due_at",2,"action","convert","sku","COMPONENT","quantity",6,"units",List.of(Map.of("id",UUID.randomUUID(),"quantity",2,"position","manufacturing.cell01.input01"),Map.of("id",UUID.randomUUID(),"quantity",4,"position","manufacturing.cell01.input02"))));
  var audit=new Store.Audit("conversion-test","operator",UUID.randomUUID(),"production:convert","legacy-conversion","test",run.get("id"));
  var command=Production.command(fixture.store,"legacy-conversion",Json.M.valueToTree(body),audit);fixture.advance(2);
  var handling=fixture.get().path("handling");assertEquals(2,handling.path("units").size());assertEquals(0,handling.path("movements").size());assertEquals(0,handling.path("legacy_stock").size());assertEquals(6,fixture.get().path("materials").get(0).path("quantity").asInt());
  assertEquals(command.get("id"),Production.command(fixture.store,"legacy-conversion",Json.M.valueToTree(body),audit).get("id"));
  fixture.post("employee-conversion",Map.of("action","convert","sku","COMPONENT","quantity",6,"units",body.get("units")),409);
 }
 @Test void exhaustedUnitVersionDefersProductionWithoutConsumingStock(){
  UUID unit=UUID.randomUUID();fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",2,"units",List.of(Map.of("id",unit,"quantity",2))));fixture.advance(2);
  fixture.store.tx(c->{Store.sql(c,"UPDATE production_handling_units SET version=? WHERE id=?",Integer.MAX_VALUE,unit);return null;});
  UUID batch=fixture.create(1);fixture.command(Map.of("action","release","reference",batch));fixture.advance(6);fixture.advance(7);
  assertEquals("ready",fixture.order(batch).path("status").asText());assertTrue(fixture.order(batch).path("blocked_reason").asText().contains("counter"));
  assertEquals(2,fixture.get().path("materials").get(0).path("quantity").asInt());assertEquals("available",fixture.get().path("handling").path("units").get(0).path("state").asText());
 }
 @Test void exhaustedUnitMovementSequenceDefersWithoutConsumingStock(){
  UUID unit=UUID.randomUUID();fixture.command(Map.of("action","supply","sku","COMPONENT","quantity",2,"units",List.of(Map.of("id",unit,"quantity",2))));fixture.advance(2);
  fixture.store.tx(c->{Store.sql(c,"UPDATE production_handling_units SET last_sequence=? WHERE id=?",Integer.MAX_VALUE,unit);return null;});
  UUID batch=fixture.create(1);fixture.command(Map.of("action","release","reference",batch));fixture.advance(6);fixture.advance(7);
  assertEquals("ready",fixture.order(batch).path("status").asText());assertTrue(fixture.order(batch).path("blocked_reason").asText().contains("counter"));
  assertEquals(2,fixture.get().path("materials").get(0).path("quantity").asInt());assertEquals("available",fixture.get().path("handling").path("units").get(0).path("state").asText());
 }

}
