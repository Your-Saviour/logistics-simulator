package simu.manufacturing;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Full replacement read model. The current run lock also guards every domain writer. */
final class Projection {
 static Map<String,Object> read(Store store){return store.tx(c->{
  var run=current(c);var id=run.get("id");var snapshot=new LinkedHashMap<String,Object>();
  var config=one(c,"SELECT config FROM production_config WHERE run_id=?",id);
  snapshot.put("config",config==null?Production.config(json(run.get("scenario")).get("manufacturing")):config.get("config"));
  snapshot.put("orders",rows(c,"SELECT * FROM production_orders WHERE run_id=? ORDER BY id",id));
  snapshot.put("material_assignments",rows(c,"SELECT * FROM production_material_plans WHERE run_id=? AND epoch=? ORDER BY id",id,run.get("epoch")));
  snapshot.put("expected_material_units",rows(c,"SELECT * FROM production_material_expected WHERE run_id=? AND epoch=? ORDER BY unit_id",id,run.get("epoch")));
  snapshot.put("materials",rows(c,"SELECT * FROM production_materials WHERE run_id=? ORDER BY sku",id));
  snapshot.put("commands",rows(c,"SELECT p.*,j.due_at,j.status job_status,j.attempts,j.boundary_input FROM production_commands p JOIN jobs j ON p.id=j.id WHERE p.run_id=? ORDER BY j.created_at,p.id",id));
  var history=rows(c,"SELECT h.*,COALESCE(o.correlation_id::text,j.boundary_input->>'correlation_id') AS correlation_id FROM production_history h JOIN jobs j ON j.id=h.job_id LEFT JOIN production_orders o ON o.id=h.order_id WHERE h.run_id=? ORDER BY h.id",id);
  var movements=rows(c,"SELECT m.*,COALESCE(o.correlation_id::text,j.boundary_input->>'correlation_id') AS correlation_id FROM production_movements m JOIN jobs j ON j.id=m.job_id LEFT JOIN production_orders o ON o.id=m.order_id WHERE m.run_id=? ORDER BY m.id",id);
  var facts=rows(c,"SELECT * FROM production_events WHERE run_id=? ORDER BY id",id);
  snapshot.put("handling",HandlingUnits.snapshot(c,run));snapshot.put("history",history);snapshot.put("movements",movements);snapshot.put("events",facts);
  var events=new ArrayList<Map<String,Object>>();
  for(var h:history)events.add(event("history",h));
  for(var m:movements)events.add(event("movement",m));
  for(var f:facts){var e=event("fact",f);e.remove("sent_at");var envelope=json(f.get("envelope"));if(envelope.hasNonNull("correlation_id"))e.put("correlation_id",envelope.get("correlation_id").asText());if(envelope.hasNonNull("simulation_time"))e.put("simulation_time",envelope.get("simulation_time").doubleValue());else if(envelope.hasNonNull("effective_time"))e.put("simulation_time",envelope.get("effective_time").doubleValue());else if(envelope.hasNonNull("time"))e.put("simulation_time",envelope.get("time").doubleValue());events.add(e);}
  for(var movement:rows(c,"SELECT * FROM production_unit_movements WHERE run_id=? AND epoch=? ORDER BY unit_id,sequence",id,run.get("epoch")))events.add(event("unit-movement",movement));
  for(var lineage:rows(c,"SELECT payload FROM production_unit_lineage WHERE run_id=? AND epoch=? ORDER BY id",id,run.get("epoch"))){Map<String,Object> record=Json.M.convertValue(json(lineage.get("payload")),Map.class);events.add(event("lineage",record));}
  var value=new LinkedHashMap<String,Object>();value.put("version",1);value.put("source","manufacturing");value.put("effects",one(c,"SELECT COALESCE(sum(quantity),0) n FROM effects WHERE run_id=?",id).get("n"));value.put("run",run);value.put("snapshot",snapshot);value.put("events",events);
  var health=new LinkedHashMap<String,Object>();health.put("heartbeats",rows(c,"SELECT role,seen_at,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats ORDER BY role"));
  health.put("pending_jobs",one(c,"SELECT count(*) n FROM jobs WHERE run_id=? AND status IN ('pending','queued')",id).get("n"));health.put("dead_letters",one(c,"SELECT count(*) n FROM jobs WHERE run_id=? AND status='dead'",id).get("n"));health.put("broker",null);health.put("ready",null);value.put("health",health);
  value.put("cursor",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Json.write(value).getBytes(StandardCharsets.UTF_8))));return value;
 });}
 static Map<String,Object> event(String kind,Map<String,Object> row){var e=new LinkedHashMap<>(row);e.put("id","manufacturing:"+kind+":"+row.get("id"));e.putIfAbsent("kind",kind);if(e.get("correlation_id")==null)e.remove("correlation_id");return e;}
}
