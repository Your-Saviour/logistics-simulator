package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Durable business attempts. Retries are new intents, never retimed old facts. */
final class MaterialRequests {
 static Map<String,Object> snapshot(Connection c,Map<String,Object> run)throws SQLException{
  var result=new LinkedHashMap<String,Object>();result.put("requests",rows(c,"SELECT * FROM production_material_requests WHERE run_id=? AND epoch=? ORDER BY id",run.get("id"),run.get("epoch")));result.put("attempts",rows(c,"SELECT a.* FROM production_material_attempts a JOIN production_material_requests r ON r.id=a.request_id WHERE r.run_id=? AND r.epoch=? ORDER BY a.request_id,a.generation",run.get("id"),run.get("epoch")));result.put("outcomes",rows(c,"SELECT * FROM production_material_failures WHERE run_id=? AND epoch=? ORDER BY event_id",run.get("id"),run.get("epoch")));result.put("releases",rows(c,"SELECT x.* FROM production_material_releases x JOIN production_material_requests r ON r.id=x.request_id WHERE r.run_id=? AND r.epoch=? ORDER BY x.event_id",run.get("id"),run.get("epoch")));return result;
 }
 static UUID eventId(Object job,String type,Object aggregate){return uuid5(uuid(job),type+":"+aggregate);}
 static void initial(Store s,Connection c,Map<String,Object> run,Map<String,Object> job,Map<String,Object> batch,UUID aggregate,Object payload)throws SQLException{
  if(!run.get("mode").equals("helics"))return;
  Production.emit(s,c,run,job,"storage.request.v1",aggregate,batch.get("correlation_id"),payload,"storage","requests");
  UUID event=eventId(job.get("id"),"storage.request.v1",aggregate);var envelope=one(c,"SELECT envelope FROM boundary_outbox WHERE id=?",event).get("envelope");
  sql(c,"INSERT INTO production_material_requests(id,run_id,epoch,batch_id,release_id,payload,correlation_id,state) VALUES (?,?,?,?,?,?::jsonb,?,'requested')",aggregate,run.get("id"),run.get("epoch"),batch.get("id"),job.get("id"),Json.write(payload),batch.get("correlation_id"));
  sql(c,"INSERT INTO production_material_attempts(event_id,request_id,generation,aggregate_id,envelope,state) VALUES (?,?,0,?,?::jsonb,'requested')",event,aggregate,aggregate,Json.write(envelope));
 }
 static Map<String,Object> attempt(Connection c,Map<String,Object> run,String event)throws SQLException{
  return one(c,"SELECT a.*,r.run_id,r.epoch,r.batch_id,r.payload,r.correlation_id,r.generation active_generation,r.state request_state FROM production_material_attempts a JOIN production_material_requests r ON r.id=a.request_id WHERE a.event_id::text=? AND r.run_id=? AND r.epoch=?",event,run.get("id"),run.get("epoch"));
 }
 static MaterialPlans.Requested requested(Connection c,Map<String,Object> run,JsonNode fact)throws SQLException{
  var a=attempt(c,run,fact.path("causation_id").asText());if(a==null)throw new Conflict("Reservation does not answer a known material attempt");
  if(!a.get("generation").equals(a.get("active_generation"))||!Set.of("requested","reserved","received").contains(a.get("state")))throw new Conflict("Reservation belongs to an obsolete or rejected material attempt");
  var e=json(a.get("envelope"));var p=fact.path("payload");
  if(!e.path("epoch").equals(fact.path("epoch"))||!e.path("federation_id").equals(fact.path("federation_id"))||!e.path("correlation_id").equals(fact.path("correlation_id"))||!e.path("payload").path("sku").equals(p.path("sku"))||!e.path("payload").path("quantity").equals(p.path("quantity"))||!e.path("payload").path("location").equals(p.path("location"))||!p.path("purpose").asText().equals("production"))throw new Conflict("Reservation changed its original material attempt");
  var batch=one(c,"SELECT * FROM production_orders WHERE id=? AND run_id=? AND epoch=?",a.get("batch_id"),run.get("id"),run.get("epoch"));if(batch==null)throw new Conflict("Material attempt batch is not current");return new MaterialPlans.Requested(e,batch);
 }
 static void noteReservation(Connection c,Map<String,Object> run,JsonNode event)throws SQLException{
  try{requested(c,run,event);}catch(Conflict ignored){return;}
  sql(c,"UPDATE production_material_attempts SET state='reserved' WHERE event_id=? AND state='requested'",Policy.uuid(event.get("causation_id")));
  sql(c,"UPDATE production_material_requests r SET state='reserved',reason=NULL FROM production_material_attempts a WHERE a.event_id=? AND a.request_id=r.id AND a.generation=r.generation AND r.state='requested'",Policy.uuid(event.get("causation_id")));
 }
 static List<Map<String,Object>> active(Connection c,Map<String,Object> run,Object batch)throws SQLException{
  var result=rows(c,"SELECT a.envelope,r.state FROM production_material_requests r JOIN production_material_attempts a ON a.request_id=r.id AND a.generation=r.generation WHERE r.run_id=? AND r.epoch=? AND r.batch_id=? ORDER BY r.id",run.get("id"),run.get("epoch"),batch);
  for(var row:result)if(!Set.of("requested","reserved","received").contains(row.get("state")))throw new Custody.Capacity("Material request recovery is "+row.get("state")+"; no partial recipe is admitted");return result;
 }
 static void received(Connection c,Map<String,Object> run)throws SQLException{
  sql(c,"UPDATE production_material_attempts a SET state='received' FROM production_material_plans p WHERE p.run_id=? AND p.epoch=? AND p.status='received' AND p.fact->>'causation_id'=a.event_id::text AND a.state='reserved'",run.get("id"),run.get("epoch"));
  sql(c,"UPDATE production_material_requests r SET state='received',reason=NULL FROM production_material_attempts a WHERE r.run_id=? AND r.epoch=? AND a.request_id=r.id AND a.generation=r.generation AND a.state='received'",run.get("id"),run.get("epoch"));
 }
 static boolean isRelease(Store s,JsonNode e){if(!e.path("type").asText().equals("storage.release.completed.v1"))return false;return s.tx(c->one(c,"SELECT 1 FROM production_material_releases WHERE event_id::text=? UNION ALL SELECT 1 FROM production_material_plans WHERE id::text=?",e.path("causation_id").asText(),e.path("aggregate_id").asText())!=null);}
 static String ingest(Store s,JsonNode e,String endpoint){Production.envelope(e);return s.tx(c->{
  var run=current(c);var peer=s.settings.peers.path("materials");if(!s.settings.providers.path("materials").asText().equals("helics")||!peer.path("source").asText().equals("storage")||!peer.path("endpoint").asText().equals(endpoint)||!e.path("source").asText().equals("storage")||!e.path("destination").asText().equals("manufacturing")||!e.path("federation_id").asText().equals(s.settings.federation))throw new Conflict("Unconfigured material recovery peer");
  UUID event=Policy.uuid(e.get("event_id"));var old=one(c,"SELECT * FROM production_material_failures WHERE event_id=?",event);if(old!=null){if(!json(old.get("envelope")).equals(e))throw new Conflict("Material recovery event identity changed");return "duplicate";}
  String reason=null;if(!e.path("run_id").asText().equals(run.get("id").toString())||!e.path("epoch").asText().equals(run.get("epoch").toString()))reason="Material recovery run or epoch mismatch";else if(!Set.of("running","held").contains(run.get("state")))reason="Inactive material recovery run";else if(e.path("effective_time").asDouble()<number(run,"granted"))reason="Late ordinary material outcome cannot change history";
  if(reason!=null){sql(c,"INSERT INTO production_material_failures VALUES (?,?,?,?::jsonb,NULL,'quarantined',?)",event,run.get("id"),run.get("epoch"),Json.write(e),reason);return "quarantined";}
  UUID id=UUID.randomUUID();sql(c,"INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (?,?,?,?,?,?,?::jsonb)",id,run.get("id"),run.get("epoch"),"boundary:"+event,e.path("effective_time").asDouble(),e.path("effective_time").asDouble(),Json.write(Map.of("material_failure",e)));sql(c,"INSERT INTO production_commands(id,run_id,command) VALUES (?,?,?::jsonb)",id,run.get("id"),Json.write(Map.of("action","material_recovery","event_id",event)));sql(c,"INSERT INTO production_material_failures VALUES (?,?,?,?::jsonb,?,'queued',NULL)",event,run.get("id"),run.get("epoch"),Json.write(e),id);return "accepted";
 });}
 static String execute(Store s,Connection c,Map<String,Object> run,Map<String,Object> job)throws SQLException{
  var e=json(job.get("payload")).path("material_failure");var save=c.setSavepoint();try{if(e.path("type").asText().equals("storage.release.completed.v1"))released(s,c,run,job,e);else rejected(s,c,run,job,e);sql(c,"UPDATE production_material_failures SET state='applied',reason=NULL WHERE event_id=?",Policy.uuid(e.get("event_id")));sql(c,"UPDATE production_commands SET status='completed',reason=NULL WHERE id=?",job.get("id"));}
  catch(Conflict|IllegalArgumentException error){c.rollback(save);sql(c,"UPDATE production_material_failures SET state='quarantined',reason=? WHERE event_id=?",error.getMessage(),Policy.uuid(e.get("event_id")));sql(c,"UPDATE production_commands SET status='rejected',reason=? WHERE id=?",error.getMessage(),job.get("id"));}
  sql(c,"UPDATE jobs SET status='completed',error=NULL WHERE id=?",job.get("id"));sql(c,"INSERT INTO inbox(event_id,run_id,epoch) VALUES (?,?,?) ON CONFLICT DO NOTHING",Policy.uuid(e.get("event_id")),run.get("id"),run.get("epoch"));return "completed";
 }
 static JsonNode original(Connection c,Map<String,Object> run,JsonNode e)throws SQLException{
  var row=one(c,"SELECT envelope FROM boundary_outbox WHERE run_id=? AND envelope->>'event_id'=? LIMIT 1",run.get("id"),e.path("causation_id").asText());if(row==null)throw new Conflict("Unknown material outcome cause");var original=json(row.get("envelope"));
  for(var field:List.of("run_id","epoch","federation_id","correlation_id"))if(!original.path(field).equals(e.path(field)))throw new Conflict("Material outcome scope or correlation changed");return original;
 }
 static void rejected(Store s,Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode e)throws SQLException{
  var original=original(c,run,e);String action=switch(original.path("type").asText()){case "storage.request.v1"->"reserve";case "storage.issue.v1"->"issue";case "storage.release.v1"->"release";default->throw new Conflict("Outcome does not concern a material intent");};
  var expected=(ObjectNode)original.path("payload").deepCopy();expected.put("action",action);expected.set("run_id",original.get("run_id"));expected.set("epoch",original.get("epoch"));expected.set("due_at",original.get("effective_time"));
  if(action.equals("reserve"))expected.set("correlation_id",original.get("correlation_id"));
  if(!original.path("aggregate_id").equals(e.path("aggregate_id"))||e.path("aggregate_version").asInt()!=1||!e.path("payload").path("action").asText().equals(action)||!expected.equals(e.path("payload").path("request")))throw new Conflict("Rejection changed the original material intent");
  if(action.equals("reserve")){
   var a=attempt(c,run,original.path("event_id").asText());if(a==null)throw new Conflict("Unknown material attempt");if(a.get("state").equals("rejected")){if(!json(a.get("outcome")).path("payload").equals(e.path("payload")))throw new Conflict("Rejected attempt outcome changed");return;}
   if(!a.get("state").equals("requested")||!a.get("generation").equals(a.get("active_generation"))||one(c,"SELECT 1 FROM production_material_plans WHERE fact->>'causation_id'=?",original.path("event_id").asText())!=null)throw new Conflict("Rejection contradicts an existing reservation or newer attempt");
   sql(c,"UPDATE production_material_attempts SET state='rejected',outcome=?::jsonb WHERE event_id=?",Json.write(e),a.get("event_id"));schedule(s,c,run,a,e.path("payload").path("reason").asText());return;
  }
  if(action.equals("issue")){beginRelease(s,c,run,job,e,original);return;}
  var release=one(c,"SELECT * FROM production_material_releases WHERE event_id=?",Policy.uuid(original.get("event_id")));if(release==null)throw new Conflict("Unknown recovery release");
  if(release.get("state").equals("released"))throw new Conflict("Release rejection contradicts confirmed source release");
  if(release.get("state").equals("rejected")){if(!json(release.get("outcome")).path("payload").equals(e.path("payload")))throw new Conflict("Release rejection outcome changed");return;}
  var plan=one(c,"SELECT fact FROM production_material_plans WHERE id=?",release.get("reservation_id"));var a=attempt(c,run,json(plan.get("fact")).path("causation_id").asText());
  if(a!=null&&a.get("state").equals("released")&&!json(a.get("outcome")).path("causation_id").asText().equals(release.get("event_id").toString())){sql(c,"UPDATE production_material_releases SET state='rejected',outcome=?::jsonb WHERE event_id=?",Json.write(e),release.get("event_id"));return;}
  if(a==null||!a.get("request_id").equals(release.get("request_id"))||!a.get("generation").equals(a.get("active_generation"))||!Set.of("reserved","received").contains(a.get("state")))throw new Conflict("Release rejection belongs to obsolete material custody");
  sql(c,"UPDATE production_material_releases SET state='rejected',outcome=?::jsonb WHERE event_id=?",Json.write(e),release.get("event_id"));
  if(a.get("state").equals("received"))return;
  boolean accepted=one(c,"SELECT 1 FROM production_custody h JOIN production_material_expected x ON x.unit_id=h.unit_id WHERE x.reservation_id=?",release.get("reservation_id"))!=null;
  sql(c,"UPDATE production_material_requests SET state=?,reason=? WHERE id=?",accepted?"reserved":"blocked",e.path("payload").path("reason").asText(),release.get("request_id"));
 }
 static void schedule(Store s,Connection c,Map<String,Object> run,Map<String,Object> a,String reason)throws SQLException{
  int generation=((Number)a.get("generation")).intValue();if(generation==Integer.MAX_VALUE){sql(c,"UPDATE production_material_requests SET state='blocked',reason='Material attempt counter exhausted' WHERE id=?",a.get("request_id"));return;}
  int quanta=Integer.parseInt(s.settings.get("MATERIAL_RETRY_QUANTA","5"));if(quanta<1||quanta>3600)throw new IllegalArgumentException("Material retry interval must be 1..3600 quanta");
  sql(c,"UPDATE production_material_requests SET state='retry_pending',reason=? WHERE id=?",reason,a.get("request_id"));UUID id=uuid5(uuid(a.get("event_id")),"material-retry");double due=number(run,"granted")+quanta*s.settings.quantum;
  if(one(c,"SELECT 1 FROM jobs WHERE id=?",id)!=null)return;
  sql(c,"INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (?,?,?,?,?,?,?::jsonb)",id,run.get("id"),run.get("epoch"),"production:material-retry:"+a.get("event_id"),due,due,Json.write(Map.of("material_retry",Map.of("request_id",a.get("request_id"),"generation",generation+1))));sql(c,"INSERT INTO production_commands(id,run_id,command) VALUES (?,?,?::jsonb)",id,run.get("id"),Json.write(Map.of("action","material_retry","reference",a.get("request_id"))));
 }
 static String retry(Store s,Connection c,Map<String,Object> run,Map<String,Object> job)throws SQLException{
  var b=json(job.get("payload")).path("material_retry");var r=one(c,"SELECT * FROM production_material_requests WHERE id=? AND run_id=? AND epoch=?",Policy.uuid(b.get("request_id")),run.get("id"),run.get("epoch"));
  if(r!=null&&r.get("state").equals("retry_pending")&&((Number)r.get("generation")).intValue()<Integer.MAX_VALUE&&b.path("generation").asInt()==((Number)r.get("generation")).intValue()+1){
   var batch=one(c,"SELECT status FROM production_orders WHERE id=?",r.get("batch_id"));if(batch==null||!Set.of("ready","held","queued").contains(batch.get("status"))){sql(c,"UPDATE production_material_requests SET state='blocked',reason='Batch no longer awaits this material' WHERE id=?",r.get("id"));}
   else{int generation=b.path("generation").asInt();UUID aggregate=uuid5(uuid(r.get("id")),"attempt:"+generation);Production.emit(s,c,run,job,"storage.request.v1",aggregate,r.get("correlation_id"),json(r.get("payload")),"storage","requests");UUID event=eventId(job.get("id"),"storage.request.v1",aggregate);var e=one(c,"SELECT envelope FROM boundary_outbox WHERE id=?",event).get("envelope");sql(c,"INSERT INTO production_material_attempts(event_id,request_id,generation,aggregate_id,envelope,state) VALUES (?,?,?,?,?::jsonb,'requested')",event,r.get("id"),generation,aggregate,Json.write(e));sql(c,"UPDATE production_material_requests SET state='requested',generation=?,reason=NULL WHERE id=?",generation,r.get("id"));}
  }
  sql(c,"UPDATE production_commands SET status='completed' WHERE id=?",job.get("id"));sql(c,"UPDATE jobs SET status='completed',error=NULL WHERE id=?",job.get("id"));return "completed";
 }
 static void unreceived(Connection c,Object reservation)throws SQLException{
  if(one(c,"SELECT 1 FROM production_material_expected e LEFT JOIN production_custody h ON h.unit_id=e.unit_id WHERE e.reservation_id=? AND (e.state='received' OR h.id IS NOT NULL)",reservation)!=null)throw new Conflict("Material outcome cannot reverse accepted or received custody");
 }
 static void beginRelease(Store s,Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode e,JsonNode issue)throws SQLException{
  UUID reservation=Policy.uuid(issue.path("payload").get("reference"));var plan=one(c,"SELECT * FROM production_material_plans WHERE id=? AND run_id=? AND epoch=?",reservation,run.get("id"),run.get("epoch"));if(plan==null)throw new Conflict("Unknown rejected issue reservation");var a=attempt(c,run,json(plan.get("fact")).path("causation_id").asText());if(a==null)throw new Conflict("Unknown issue material attempt");
  if(one(c,"SELECT 1 FROM production_material_releases WHERE reservation_id=?",reservation)!=null)return;
  if(!a.get("generation").equals(a.get("active_generation"))||!a.get("state").equals("reserved"))throw new Conflict("Issue rejection belongs to an obsolete attempt");unreceived(c,reservation);
  UUID aggregate=uuid5(Policy.uuid(issue.get("event_id")),"release-after-rejection");Production.emit(s,c,run,job,"storage.release.v1",aggregate,Policy.uuid(e.get("correlation_id")),Map.of("reference",reservation.toString()),"storage","requests");UUID id=eventId(job.get("id"),"storage.release.v1",aggregate);var envelope=one(c,"SELECT envelope FROM boundary_outbox WHERE id=?",id).get("envelope");sql(c,"INSERT INTO production_material_releases VALUES (?,?,?,?::jsonb,'requested',NULL)",id,a.get("request_id"),reservation,Json.write(envelope));sql(c,"UPDATE production_material_requests SET state='release_pending',reason=? WHERE id=?",e.path("payload").path("reason").asText(),a.get("request_id"));
 }
 static void released(Store s,Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode e)throws SQLException{
  var release=one(c,"SELECT * FROM production_material_releases WHERE event_id=?",Policy.uuid(e.get("causation_id")));if(release!=null)original(c,run,e);
  Object reservation=release==null?Policy.uuid(e.get("aggregate_id")):release.get("reservation_id");var plan=one(c,"SELECT * FROM production_material_plans WHERE id=? AND run_id=? AND epoch=?",reservation,run.get("id"),run.get("epoch"));if(plan==null)throw new Conflict("Unknown material release proof");
  var before=json(plan.get("fact")).path("payload");var p=e.path("payload");if(!p.path("id").asText().equals(reservation.toString())||!p.path("status").asText().equals("released")||p.path("version").asInt()<=before.path("version").asInt()||!e.path("correlation_id").equals(before.path("correlation_id")))throw new Conflict("Invalid source reservation release proof");for(var key:List.of("sku","location","quantity","purpose","correlation_id","run_id"))if(!p.path(key).equals(before.path(key)))throw new Conflict("Release changed the original reservation");
  var a=attempt(c,run,json(plan.get("fact")).path("causation_id").asText());if(a==null)throw new Conflict("Unknown release material attempt");if(a.get("state").equals("released")){if(!json(a.get("outcome")).path("payload").equals(p))throw new Conflict("Confirmed source release proof changed");return;}
  if(!a.get("generation").equals(a.get("active_generation"))||!a.get("state").equals("reserved"))throw new Conflict("Release belongs to an obsolete material attempt");if(release!=null&&!release.get("state").equals("requested"))throw new Conflict("Release outcome contradicts an earlier rejection");unreceived(c,reservation);
  sql(c,"DELETE FROM production_material_expected WHERE reservation_id=? AND state='expected'",reservation);sql(c,"UPDATE production_material_plans SET status='rejected',reason='Source reservation release confirmed' WHERE id=?",reservation);if(release!=null)sql(c,"UPDATE production_material_releases SET state='released',outcome=?::jsonb WHERE event_id=?",Json.write(e),release.get("event_id"));sql(c,"UPDATE production_material_attempts SET state='released',outcome=?::jsonb WHERE event_id=?",Json.write(e),a.get("event_id"));schedule(s,c,run,a,"Source reservation released; retrying missing material");
 }
}
