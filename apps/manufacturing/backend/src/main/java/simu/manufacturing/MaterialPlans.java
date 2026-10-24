package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Receiving expectations reserve endpoints, never inventory or recipe inputs. */
final class MaterialPlans {
 static void manifest(JsonNode event){
  var payload=event.path("payload");var units=payload.path("unit_manifest");if(!event.path("type").asText().equals("storage.reserve.completed.v1")||!payload.path("purpose").asText().equals("production")||!units.isArray()||units.isEmpty()||units.size()>4)throw new IllegalArgumentException("One to four selected production units required");
  var ids=new HashSet<UUID>();int total=0;
  for(var unit:units){
   // Use the receiving wire validator for the same immutable reserved-unit proof.
   // This endpoint is only a structural validation probe; planning chooses the batch cell.
   var h=Json.M.createObjectNode();h.set("id",event.get("aggregate_id"));h.set("run_id",event.get("run_id"));h.set("epoch",event.get("epoch"));h.put("source","storage");h.put("destination_owner","manufacturing");h.set("origin",unit.get("position"));h.put("destination","manufacturing.cell01.input01");h.put("state","offered");h.set("unit",unit);for(var key:List.of("departure_token","receipt_id","reason"))h.putNull(key);
   var probe=(ObjectNode)event.deepCopy();probe.put("type","handling.offered.v1");probe.set("causation_id",event.get("aggregate_id"));probe.set("aggregate_version",unit.get("version"));probe.set("payload",h);Custody.validate(probe);
   if(unit.path("version").asInt()>Integer.MAX_VALUE-3||unit.path("last_sequence").asInt()>Integer.MAX_VALUE-3)throw new Conflict("Selected material counters lack departure, receipt and consumption headroom");
   if(!ids.add(Policy.uuid(unit.get("id")))||!unit.path("contents").get(0).path("sku").equals(payload.path("sku")))throw new Conflict("Selected unit identity or SKU mismatch");total+=unit.path("contents").get(0).path("quantity").asInt();
  }
  if(total!=payload.path("quantity").asInt())throw new Conflict("Selected units must exactly match reserved quantity");
 }
 static String ingest(Store s,JsonNode event,String endpoint){Production.envelope(event);return s.tx(c->{var run=current(c);var peer=s.settings.peers.path("materials");if(!s.settings.providers.path("materials").asText().equals("helics")||!peer.path("source").asText().equals("storage")||!peer.path("endpoint").asText().equals(endpoint)||!event.path("federation_id").asText().equals(s.settings.federation)||!event.path("destination").asText().equals("manufacturing"))throw new Conflict("Unconfigured material assignment peer");
  if(!event.path("run_id").asText().equals(run.get("id").toString())||!event.path("epoch").asText().equals(run.get("epoch").toString()))return "fenced";
  var old=one(c,"SELECT * FROM production_material_plans WHERE event_id=? OR id=?",Policy.uuid(event.get("event_id")),Policy.uuid(event.get("aggregate_id")));if(old!=null){if(!json(old.get("fact")).equals(event))throw new Conflict("Material reservation identity changed");return "duplicate";}
  if(!Set.of("running","held").contains(run.get("state")))throw new Conflict("Inactive material assignment run");if(event.path("effective_time").asDouble()<number(run,"granted"))throw new Conflict("Late material reservation cannot change history");
  UUID job=UUID.randomUUID();sql(c,"INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (?,?,?,?,?,?,?::jsonb)",job,run.get("id"),run.get("epoch"),"boundary:"+event.path("event_id").asText(),event.path("effective_time").asDouble(),event.path("effective_time").asDouble(),Json.write(Map.of("material_reservation",event)));
  sql(c,"INSERT INTO production_commands(id,run_id,command) VALUES (?,?,?::jsonb)",job,run.get("id"),Json.write(Map.of("action","material_reservation","reference",event.path("aggregate_id").asText())));sql(c,"INSERT INTO production_material_plans(id,event_id,run_id,epoch,command_id,fact,status) VALUES (?,?,?,?,?,?::jsonb,'pending')",Policy.uuid(event.get("aggregate_id")),Policy.uuid(event.get("event_id")),run.get("id"),run.get("epoch"),job,Json.write(event));MaterialRequests.noteReservation(c,run,event);return "accepted";
 });}
 static String execute(Store s,Connection c,Map<String,Object> run,Map<String,Object> job)throws SQLException{
  var event=json(job.get("payload")).path("material_reservation");var save=c.setSavepoint();try{plan(s,c,run,job,event);sql(c,"UPDATE production_commands SET status='completed',reason=NULL WHERE id=?",job.get("id"));}
  catch(Custody.Capacity error){c.rollback(save);sql(c,"UPDATE jobs SET due_at=?,error=? WHERE id=?",number(run,"granted")+s.settings.quantum,error.getMessage(),job.get("id"));sql(c,"UPDATE production_material_plans SET reason=? WHERE id=?",error.getMessage(),Policy.uuid(event.get("aggregate_id")));sql(c,"UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=?",job.get("id"));return "waiting";}
  catch(Conflict|IllegalArgumentException error){c.rollback(save);sql(c,"UPDATE production_commands SET status='rejected',reason=? WHERE id=?",error.getMessage(),job.get("id"));sql(c,"UPDATE production_material_plans SET status='rejected',reason=? WHERE id=?",error.getMessage(),Policy.uuid(event.get("aggregate_id")));}
  sql(c,"UPDATE jobs SET status='completed',error=NULL WHERE id=?",job.get("id"));sql(c,"INSERT INTO inbox(event_id,run_id,epoch) VALUES (?,?,?) ON CONFLICT DO NOTHING",Policy.uuid(event.get("event_id")),run.get("id"),run.get("epoch"));return "completed";
 }
 record Requested(JsonNode envelope,Map<String,Object> batch){}
 static Requested requested(Connection c,Map<String,Object> run,JsonNode event)throws SQLException{return MaterialRequests.requested(c,run,event);}
 static void plan(Store s,Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode event)throws SQLException{
  var cfg=Production.ensure(c,run);var context=requested(c,run,event);var batch=context.batch();var requests=MaterialRequests.active(c,run,batch.get("id"));
  var group=new ArrayList<Map<String,Object>>();int footprint=0;
  for(var row:requests){var request=json(row.get("envelope"));var selected=one(c,"SELECT * FROM production_material_plans WHERE run_id=? AND epoch=? AND fact->>'causation_id'=?",run.get("id"),run.get("epoch"),request.path("event_id").asText());if(selected==null)throw new Custody.Capacity("Awaiting selected whole-unit manifests for every material in the batch");if(selected.get("status").equals("rejected"))throw new Conflict("A material manifest for this batch was rejected; reconcile before admission");var fact=json(selected.get("fact"));if(!requested(c,run,fact).batch().get("id").equals(batch.get("id")))throw new Conflict("Material manifests refer to different batches");group.add(selected);footprint+=fact.path("payload").path("unit_manifest").size();}
  String prefix=HandlingUnits.cell(cfg,batch.get("line").toString())+".input";int capacity=0;for(var location:HandlingUnits.CATALOG.path("locations"))if(location.path("id").asText().startsWith(prefix))capacity++;
  if(group.stream().allMatch(r->Set.of("planned","received").contains(r.get("status"))))return;
  int existing=((Number)one(c,"SELECT count(*) n FROM production_handling_units WHERE run_id=? AND epoch=? AND batch_id=? AND category='raw' AND state IN ('available','reserved') AND NOT EXISTS(SELECT 1 FROM production_material_expected e WHERE e.unit_id=production_handling_units.id)",run.get("id"),run.get("epoch"),batch.get("id")).get("n")).intValue();
  if(footprint+existing>capacity)throw new Conflict("Whole recipe selects "+(footprint+existing)+" units but its cell has "+capacity+" input positions; unsupported whole-unit recipe allocation");
  if(group.stream().anyMatch(r->!Set.of("pending","planned","received").contains(r.get("status"))))throw new Conflict("Inconsistent partial batch admission requires reconciliation");
  // All SKU reservations acquire this cell together, under the run lock and
  // the caller's savepoint. A failed group leaves no partial endpoint claims.
  for(var selected:group){if(Set.of("planned","received").contains(selected.get("status")))continue;var fact=json(selected.get("fact"));var destinations=Json.M.createObjectNode();for(var unit:fact.path("payload").path("unit_manifest")){
    UUID id=Policy.uuid(unit.get("id"));if(one(c,"SELECT 1 FROM production_handling_units WHERE id=? UNION ALL SELECT 1 FROM production_material_expected WHERE unit_id=?",id,id)!=null)throw new Conflict("Selected material barcode already known or expected");String position=HandlingUnits.free(c,run,prefix);if(position==null)throw new Custody.Capacity("Whole-batch input capacity unavailable at "+prefix+"; no partial recipe is admitted");
    sql(c,"INSERT INTO production_material_expected VALUES (?,?,?,?,?,?::jsonb,'expected')",id,run.get("id"),run.get("epoch"),selected.get("id"),position,Json.write(unit));destinations.put(id.toString(),position);
   }
   Production.emit(s,c,run,job,"storage.issue.v1",uuid5(uuid(selected.get("id")),"manufacturing-issue"),Policy.uuid(fact.get("correlation_id")),Map.of("reference",selected.get("id").toString(),"unit_destinations",destinations),"storage","requests");
   sql(c,"UPDATE production_material_plans SET status='planned',batch_id=?,unit_destinations=?::jsonb,reason=NULL WHERE id=?",batch.get("id"),Json.write(destinations),selected.get("id"));
  }
 }
 static Object batch(Connection c,Map<String,Object> run,UUID unit)throws SQLException{var row=one(c,"SELECT p.batch_id FROM production_material_expected e JOIN production_material_plans p ON p.id=e.reservation_id WHERE e.unit_id=? AND e.run_id=? AND e.epoch=?",unit,run.get("id"),run.get("epoch"));return row==null?null:row.get("batch_id");}
 static void checkOffer(Connection c,Map<String,Object> run,JsonNode event)throws SQLException{
  var h=event.path("payload");var expected=one(c,"SELECT e.*,p.fact FROM production_material_expected e JOIN production_material_plans p ON p.id=e.reservation_id WHERE e.unit_id=? AND e.run_id=? AND e.epoch=?",Policy.uuid(h.path("unit").get("id")),run.get("id"),run.get("epoch"));
  if(expected!=null&&(!json(expected.get("offered_unit")).equals(h.path("unit"))||!expected.get("destination").toString().equals(h.path("destination").asText())||!json(expected.get("fact")).path("correlation_id").equals(event.path("correlation_id"))))throw new Conflict("Offer changed the reserved whole-unit receiving assignment");
  if(one(c,"SELECT 1 FROM production_material_expected WHERE run_id=? AND epoch=? AND destination=? AND state='expected' AND unit_id<>?",run.get("id"),run.get("epoch"),h.path("destination").asText(),Policy.uuid(h.path("unit").get("id")))!=null)throw new Custody.Capacity("Input endpoint belongs to another expected whole unit");
 }
 static void received(Connection c,Map<String,Object> run,UUID unit)throws SQLException{
  sql(c,"UPDATE production_material_expected SET state='received' WHERE unit_id=? AND run_id=? AND epoch=?",unit,run.get("id"),run.get("epoch"));sql(c,"UPDATE production_material_plans p SET status='received' WHERE p.run_id=? AND p.epoch=? AND p.status='planned' AND NOT EXISTS(SELECT 1 FROM production_material_expected e WHERE e.reservation_id=p.id AND e.state='expected')",run.get("id"),run.get("epoch"));MaterialRequests.received(c,run);
 }
}
