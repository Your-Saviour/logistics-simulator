package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Durable native transport intents and proofs. Network work runs only after commit. */
final class Fleet {
 static final HttpClient CLIENT=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
 static boolean enabled(Settings s){return s.get("FLEET_MODE","disabled").equals("coordinated");}
 static UUID id(JsonNode h,int generation){return uuid5(Policy.uuid(h.path("unit").get("id")),"fleet:"+h.path("id").asText()+":"+generation);}
 static JsonNode request(Settings s,Map<String,Object> run,JsonNode h,int generation){var b=Json.M.createObjectNode();b.put("version",1);b.put("id",id(h,generation).toString());b.put("run_id",s.get("FLEET_RUN_ID",""));b.put("epoch",s.get("FLEET_EPOCH",""));b.put("producer","manufacturing");b.put("source_run_id",run.get("id").toString());b.put("source_epoch",run.get("epoch").toString());b.set("unit_id",h.path("unit").get("id"));b.set("origin",h.get("origin"));b.set("destination",h.get("destination"));b.put("custody_generation",generation);b.put("effective_time",number(run,"granted"));return b;}
 static void track(Connection c,Map<String,Object> run,UUID id,JsonNode request)throws SQLException{sql(c,"INSERT INTO production_fleet_jobs(id,run_id,epoch,request) VALUES (?,?,?,?::jsonb) ON CONFLICT(id) DO NOTHING",id,run.get("id"),run.get("epoch"),request==null?null:Json.write(request));var row=one(c,"SELECT * FROM production_fleet_jobs WHERE id=?",id);if(!row.get("run_id").equals(run.get("id"))||!row.get("epoch").equals(run.get("epoch")))throw new Conflict("Fleet identity belongs to another native scope");}
 static boolean ready(Store s,Connection c,Map<String,Object> run,JsonNode h,String kind)throws SQLException{
  if(!enabled(s.settings))return true;int generation=h.path("unit").path("custody_generation").asInt()+(kind.equals("pickup_ready")?1:0);UUID id=id(h,generation);track(c,run,id,kind.equals("pickup_ready")?request(s.settings,run,h,generation):null);var row=one(c,"SELECT * FROM production_fleet_jobs WHERE id=?",id);if(row.get("snapshot")==null)return false;return eligible(s.settings,run,h,generation,kind,json(row.get("snapshot")));
 }
 static boolean finiteNonnegative(JsonNode value){return value.isNumber()&&Double.isFinite(value.asDouble())&&value.asDouble()>=0;}
 static boolean scopeMatches(Settings s,Map<String,Object> run,JsonNode snapshot){
  var scope=snapshot.path("fleet_scope");var offset=scope.path("offset");
  return scope.isObject()&&scope.path("run_id").isTextual()&&scope.path("run_id").asText().equals(run.get("id").toString())&&scope.path("epoch").isTextual()&&scope.path("epoch").asText().equals(run.get("epoch").toString())&&finiteNonnegative(offset)&&offset.asDouble()==Double.parseDouble(s.get("FLEET_TIME_OFFSET","0"));
 }
 static boolean eligible(Settings s,Map<String,Object> run,JsonNode h,int generation,String kind,JsonNode snapshot){
  if(!scopeMatches(s,run,snapshot))return false;
  var request=snapshot.path("request");if(!finiteNonnegative(request.path("effective_time"))||!request.path("id").asText().equals(id(h,generation).toString())||!request.path("run_id").asText().equals(s.get("FLEET_RUN_ID",""))||!request.path("epoch").asText().equals(s.get("FLEET_EPOCH",""))||!request.path("unit_id").equals(h.path("unit").path("id"))||!request.path("origin").equals(h.path("origin"))||!request.path("destination").equals(h.path("destination"))||request.path("custody_generation").asInt()!=generation||!request.path("producer").asText().equals(h.path("source").asText())||!request.path("source_run_id").equals(h.path("run_id"))||!request.path("source_epoch").equals(h.path("epoch")))return false;
  for(var e:snapshot.path("events")){var b=e.path("body");if(!e.path("kind").asText().equals(kind)||!b.path("kind").asText().equals(kind)||!b.path("job_id").asText().equals(id(h,generation).toString())||b.path("route_version").asInt()!=1||!b.path("robot_id").isTextual()||b.path("robot_id").asText().isBlank())continue;boolean same=true;for(String key:List.of("run_id","epoch","producer","source_run_id","source_epoch","unit_id","origin","destination","custody_generation"))same&=b.path(key).equals(request.path(key));if(same&&finiteNonnegative(b.path("effective_time"))&&b.path("effective_time").asDouble()<=number(run,"granted")+Double.parseDouble(s.get("FLEET_TIME_OFFSET","0")))return true;}return false;
 }
 static void proof(Store s,Connection c,Map<String,Object> run,JsonNode h,String kind)throws SQLException{
  if(!enabled(s.settings))return;int generation=h.path("unit").path("custody_generation").asInt();UUID id=id(h,generation);track(c,run,id,null);var b=Json.M.createObjectNode();b.put("job_id",id.toString());b.set("unit_id",h.path("unit").get("id"));b.put("run_id",s.settings.get("FLEET_RUN_ID",""));b.put("epoch",s.settings.get("FLEET_EPOCH",""));b.put("source_run_id",run.get("id").toString());b.put("source_epoch",run.get("epoch").toString());b.put("custody_generation",generation);b.set("endpoint",h.get(kind.equals("departure")?"origin":"destination"));b.put("effective_time",number(run,"granted"));sql(c,"UPDATE production_fleet_jobs SET "+kind+"=COALESCE("+kind+",?::jsonb) WHERE id=?",Json.write(b),id);
 }
 static String defer(Store s,Connection c,Map<String,Object> run,Map<String,Object> job)throws SQLException{sql(c,"UPDATE jobs SET due_at=?,error='Awaiting coordinated fleet physical proof' WHERE id=?",number(run,"granted")+s.settings.quantum,job.get("id"));sql(c,"UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=?",job.get("id"));return "waiting";}
 static JsonNode http(Settings s,String method,String path,Object body)throws Exception{var b=HttpRequest.newBuilder(URI.create(s.get("FLEET_URL","").replaceAll("/$","")+path)).timeout(Duration.ofSeconds(2)).header("Authorization","Bearer "+s.get("FLEET_TOKEN","")).header("Content-Type","application/json");if(method.equals("GET"))b.GET();else b.POST(HttpRequest.BodyPublishers.ofString(Json.write(body)));var response=CLIENT.send(b.build(),HttpResponse.BodyHandlers.ofString());if(response.statusCode()<200||response.statusCode()>=300)throw new IllegalStateException("Fleet HTTP "+response.statusCode());return Json.parse(response.body());}
 static void relay(Store s){if(!enabled(s.settings))return;var pending=s.tx(c->{var run=current(c);return rows(c,"SELECT f.* FROM production_fleet_jobs f WHERE f.run_id=? AND f.epoch=? ORDER BY polled_at,id LIMIT 1",run.get("id"),run.get("epoch"));});for(var row:pending)try{
   String path="/v1/jobs/"+row.get("id");if(row.get("request")!=null&&!Boolean.TRUE.equals(row.get("admitted"))){http(s.settings,"POST","/v1/jobs",row.get("request"));mark(s,row,"admitted",null);}
   for(String kind:List.of("departure","receipt"))if(row.get(kind)!=null&&!Boolean.TRUE.equals(row.get(kind+"_sent"))){http(s.settings,"POST",path+"/proofs/"+kind,row.get(kind));mark(s,row,kind+"_sent",null);}
   var snapshot=http(s.settings,"GET",path,null);mark(s,row,"snapshot",snapshot);
  }catch(Exception error){s.tx(c->{var run=current(c);if(run.get("id").equals(row.get("run_id"))&&run.get("epoch").equals(row.get("epoch")))sql(c,"UPDATE production_fleet_jobs SET error=?,polled_at=clock_timestamp() WHERE id=?",cut(error.toString(),256),row.get("id"));return null;});}}
 static void mark(Store s,Map<String,Object> row,String field,JsonNode snapshot){s.tx(c->{var run=current(c);if(run.get("id").equals(row.get("run_id"))&&run.get("epoch").equals(row.get("epoch"))){if(snapshot!=null&&!scopeMatches(s.settings,run,snapshot))throw new Conflict("Fleet response native run/epoch/offset mapping does not match current scope");if(snapshot==null)sql(c,"UPDATE production_fleet_jobs SET "+field+"=true,error=NULL WHERE id=?",row.get("id"));else sql(c,"UPDATE production_fleet_jobs SET snapshot=?::jsonb,error=NULL,polled_at=clock_timestamp() WHERE id=?",Json.write(snapshot),row.get("id"));}return null;});}
}
