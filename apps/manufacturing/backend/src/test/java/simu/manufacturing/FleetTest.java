package simu.manufacturing;
import org.junit.jupiter.api.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
class FleetTest {
 @Test void coordinatedModeRequiresExplicitFleetScopeAndCredentials(){assertThrows(IllegalArgumentException.class,()->new Settings(Map.of("APP_PASSWORD","test","FLEET_MODE","coordinated")));}
 @Test void invalidClockOffsetFailsClosed(){for(String value:List.of("NaN","Infinity","-1"))assertThrows(IllegalArgumentException.class,()->new Settings(Map.of("APP_PASSWORD","test","FLEET_TIME_OFFSET",value)));}
 @Test void unknownFleetModeCannotSilentlyDisableTransport(){assertThrows(IllegalArgumentException.class,()->new Settings(Map.of("APP_PASSWORD","test","FLEET_MODE","coordnated")));}
 @Test void arrivalRequiresExactScopeAndNativeGrantAtOrAfterPhysicalTime(){
  var env=new HashMap<String,String>();env.put("APP_PASSWORD","test");env.put("FLEET_MODE","coordinated");env.put("FLEET_URL","http://fleet:8000");env.put("FLEET_TOKEN","secret");env.put("FLEET_RUN_ID",UUID.randomUUID().toString());env.put("FLEET_EPOCH",UUID.randomUUID().toString());var settings=new Settings(env);
  var run=Map.<String,Object>of("id",UUID.randomUUID(),"epoch",UUID.randomUUID(),"granted",10.0);var h=Json.M.createObjectNode();h.put("id",UUID.randomUUID().toString());h.put("run_id",run.get("id").toString());h.put("epoch",run.get("epoch").toString());h.put("source","storage");h.put("origin","storage.raw.r01.b01.l01");h.put("destination","manufacturing.cell01.input01");h.set("unit",Json.M.valueToTree(Map.of("id",UUID.randomUUID().toString(),"custody_generation",1)));
  var request=(com.fasterxml.jackson.databind.node.ObjectNode)Fleet.request(settings,run,h,1);request.put("producer","storage");var body=request.deepCopy();body.remove("id");body.put("job_id",Fleet.id(h,1).toString());body.put("robot_id",UUID.randomUUID().toString());body.put("kind","arrival");body.put("route_version",1);body.put("effective_time",11);var snapshot=Json.M.createObjectNode();snapshot.set("request",request);snapshot.set("fleet_scope",Json.M.valueToTree(Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"offset",0)));snapshot.set("events",Json.M.valueToTree(List.of(Map.of("kind","arrival","body",body))));
  assertFalse(Fleet.eligible(settings,run,h,1,"arrival",snapshot));env.put("FLEET_TIME_OFFSET","1");((com.fasterxml.jackson.databind.node.ObjectNode)snapshot.path("fleet_scope")).put("offset",1);assertTrue(Fleet.eligible(new Settings(env),run,h,1,"arrival",snapshot));((com.fasterxml.jackson.databind.node.ObjectNode)snapshot.path("fleet_scope")).put("offset",0);body.put("effective_time",10);snapshot.set("events",Json.M.valueToTree(List.of(Map.of("kind","arrival","body",body))));assertTrue(Fleet.eligible(settings,run,h,1,"arrival",snapshot));body.put("epoch",UUID.randomUUID().toString());snapshot.set("events",Json.M.valueToTree(List.of(Map.of("kind","arrival","body",body))));assertFalse(Fleet.eligible(settings,run,h,1,"arrival",snapshot));
 }
}
