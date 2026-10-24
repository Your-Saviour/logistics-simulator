package simu.manufacturing;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class PolicyTest {
 @Test void quantityRejectsCoercionAndUnknownFields() {
  for(String body: new String[]{"{\"due_at\":1,\"quantity\":true}","{\"due_at\":1,\"quantity\":\"2\"}","{\"due_at\":1,\"quantity\":1.0}","{\"due_at\":1,\"quantity\":0}","{\"due_at\":1,\"quantity\":10001}","{\"due_at\":1,\"quantity\":1,\"extra\":0}"})
   assertThrows(IllegalArgumentException.class,()->Policy.job(Json.parse(body)),body);
 }
 @Test void finiteTimeAndValidQuantityArePreserved() {
  assertEquals(2,Policy.job(Json.parse("{\"due_at\":3.5,\"quantity\":2}")).get("quantity").intValue());
  assertThrows(IllegalArgumentException.class,()->Policy.job(Json.parse("{\"due_at\":-1,\"quantity\":2}")));
  assertThrows(IllegalArgumentException.class,()->Policy.job(Json.parse("{\"due_at\":1e999,\"quantity\":2}")));
 }
 @Test void serviceDoesNotInheritOperatorOrEmployeePermissions() {
  assertFalse(Policy.scopes("service").contains("jobs:write"));
  assertFalse(Policy.scopes("employee").contains("runs:control"));
  assertTrue(Policy.scopes("operator").contains("audit:read"));
 }
 @Test void businessCalendarUsesElapsedUtcSecondsAcrossDst() {
  var scenario=Json.parse("{\"start_at\":\"2026-10-02T16:59:30+09:30\"}");
  assertEquals(223230,Scenario.nextDue(scenario,0,60));
  assertEquals("Australia/Adelaide",Scenario.normalize(scenario).get("time_zone").asText());
 }
 @Test void commandJsonRejectsTrailingDocumentsAndGarbage(){
  assertThrows(IllegalArgumentException.class,()->Json.parse("{\"due_at\":1,\"quantity\":2} {}"));
  assertThrows(IllegalArgumentException.class,()->Json.parse("{} trailing"));
 }
}
