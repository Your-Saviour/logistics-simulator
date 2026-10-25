package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class FleetScopeTest {
 final Settings settings=new Settings(Map.of("APP_PASSWORD","test","FLEET_MODE","coordinated","FLEET_URL","http://fleet:8000","FLEET_TOKEN","secret","FLEET_RUN_ID",UUID.randomUUID().toString(),"FLEET_EPOCH",UUID.randomUUID().toString(),"FLEET_TIME_OFFSET","1"));
 final Map<String,Object> run=Map.of("id",UUID.randomUUID(),"epoch",UUID.randomUUID(),"granted",10.0);
 final ObjectNode handoff=handoff();
 ObjectNode handoff(){var h=Json.M.createObjectNode();h.put("id",UUID.randomUUID().toString());h.put("run_id",run.get("id").toString());h.put("epoch",run.get("epoch").toString());h.put("source","manufacturing");h.put("origin","manufacturing.cell01.output01");h.put("destination","storage.finished_receipt.dock01");h.set("unit",Json.M.valueToTree(Map.of("id",UUID.randomUUID().toString(),"custody_generation",1)));return h;}
 ObjectNode snapshot(String kind){var request=Fleet.request(settings,run,handoff,1);var body=(ObjectNode)request.deepCopy();body.remove("id");body.put("job_id",Fleet.id(handoff,1).toString());body.put("kind",kind);body.put("robot_id","robot-01");body.put("route_version",1);body.put("effective_time",11);var value=Json.M.createObjectNode();value.set("request",request);value.set("fleet_scope",Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"offset",1)));value.set("events",Json.M.valueToTree(List.of(Map.of("kind",kind,"body",body))));return value;}
 boolean eligible(String kind,JsonNode value){return Fleet.eligible(settings,run,handoff,1,kind,value);}
 @Test void matchingNativeScopeAndOffsetAllowsReportedRobotIdentity(){for(String kind:List.of("pickup_ready","arrival"))assertTrue(eligible(kind,snapshot(kind)));}
 @Test void missingOrWrongNativeScopeCannotAuthorizeFuturePhysicalFacts(){for(String kind:List.of("pickup_ready","arrival")){
  var missing=snapshot(kind);missing.remove("fleet_scope");assertFalse(eligible(kind,missing),kind+" missing fleet_scope");
 }}
 @Test void wrongNativeRunOrEpochCannotAuthorizePhysicalFacts(){for(String kind:List.of("pickup_ready","arrival")){
  for(String key:List.of("run_id","epoch")){var value=snapshot(kind);((ObjectNode)value.path("fleet_scope")).put(key,UUID.randomUUID().toString());assertFalse(eligible(kind,value),kind+" mismatched "+key);}
 }}
 @Test void mismatchedOrMalformedOffsetCannotAuthorizeFuturePhysicalFacts(){for(String kind:List.of("pickup_ready","arrival")){
  for(JsonNode offset:List.of(Json.M.valueToTree(0),Json.M.valueToTree(2),Json.M.valueToTree(-1),Json.M.valueToTree(Double.NaN),Json.M.valueToTree(Double.POSITIVE_INFINITY),Json.M.valueToTree(true),Json.M.valueToTree("1"),Json.M.nullNode())){var value=snapshot(kind);((ObjectNode)value.path("fleet_scope")).set("offset",offset);assertFalse(eligible(kind,value),kind+" invalid scope offset "+offset);}
 }}
 @Test void malformedPhysicalTimesNeverAuthorizePickupOrArrival(){for(String kind:List.of("pickup_ready","arrival"))for(JsonNode time:List.of(Json.M.valueToTree(-1),Json.M.valueToTree(Double.NaN),Json.M.valueToTree(Double.POSITIVE_INFINITY),Json.M.valueToTree(Double.NEGATIVE_INFINITY),Json.M.valueToTree(true),Json.M.valueToTree("0"),Json.M.nullNode())){var value=snapshot(kind);((ObjectNode)value.path("events").get(0).path("body")).set("effective_time",time);assertFalse(eligible(kind,value),kind+" malformed effective_time "+time);}}
}
