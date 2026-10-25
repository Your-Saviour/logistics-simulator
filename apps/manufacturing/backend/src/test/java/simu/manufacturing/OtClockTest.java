package simu.manufacturing;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
@EnabledIfEnvironmentVariable(named="MANUFACTURING_TEST_DATABASE",matches=".+")
class OtClockTest {
 final OtTest fixture=new OtTest();Store store;
 @BeforeEach void setup(){fixture.setup();store=fixture.store;fixture.acquire();fixture.acknowledge(fixture.next());}
 @AfterEach void cleanup(){store.tx(c->{Store.sql(c,"UPDATE runs SET mode='standalone' WHERE current");return null;});fixture.cleanup();}
 @Test void requestedTimeDoesNotAuthorizeEquipmentAndEarlierGrantsBoundSteps(){
  var run=store.run();UUID session=UUID.randomUUID();store.tx(c->{Store.sql(c,"UPDATE runs SET mode='helics' WHERE id=?",run.get("id"));Store.sql(c,"INSERT INTO manufacturing_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (?,?,?,false,'executing')",run.get("id"),run.get("epoch"),session);return null;});
  assertTrue(store.prepare(10,run.get("epoch")));assertNull(fixture.next(),"A delayed native grant cannot cause future equipment I/O");
  store.grant(3,run.get("epoch"),null);
  for(int time=1;time<=3;time++){var step=fixture.next();assertEquals(time,Store.json(step.get("request")).path("payload").path("simulation_time").asInt());fixture.acknowledge(step);}
  assertNull(fixture.next(),"The pending request at 10 cannot authorize step 4 after an earlier grant at 3");
 }
 @Test void futureEquipmentReplyCannotAdvanceTheWatermark(){
  var run=store.run();store.grant(1,run.get("epoch"),null);var op=fixture.next();var request=Store.json(op.get("request"));var response=Json.M.valueToTree(Map.of("version","1.0","command_id",op.get("id"),"result",Map.of("initialized",true,"simulation_time",2,"scope",Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"session_id",request.path("session_id").asText()))));
  assertThrows(Store.Conflict.class,()->Ot.acknowledge(store,Store.uuid(op.get("id")),response));assertEquals(0,Store.json(Ot.snapshot(store).get("cell")).path("settled").asInt());
 }
}
