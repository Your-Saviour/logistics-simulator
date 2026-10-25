package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.sql.*;
import java.time.*;
import java.util.*;
import static simu.manufacturing.Store.*;
/** Manufacturing owns OT admission, grant fences and the business completion transaction. */
final class Ot {
 static boolean enabled(Map<String,Object> run){return "openplc".equals(run.get("ot_mode"));}
 static Map<String,Object> acquire(Store s,UUID owner){return s.tx(c->{var run=current(c);if(!enabled(run))return null;var old=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));if(old!=null){if(!old.get("owner_id").equals(owner))throw new Conflict("OT controller restart requires reconciliation and a new epoch");return old;}if(number(run,"granted")!=0)throw new Conflict("OT initialization requires a fresh epoch at time zero");UUID session=UUID.randomUUID();sql(c,"INSERT INTO ot_cells(run_id,epoch,session_id,owner_id) VALUES (?,?,?,?)",run.get("id"),run.get("epoch"),session,owner);issue(c,run,"initialize","initialize",Map.of(),null);return one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));});}
 static UUID issue(Connection c,Map<String,Object> run,String key,String operation,Object payload,UUID explicit)throws SQLException{
  var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));if(cell==null)throw new Conflict("OT cell is not initialized by the owning controller");UUID id=explicit==null?Store.uuid5(uuid(cell.get("session_id")),key):explicit;
  var request=Map.of("version","1.0","command_id",id,"run_id",run.get("id"),"epoch",run.get("epoch"),"session_id",cell.get("session_id"),"operation",operation,"payload",payload);
  sql(c,"INSERT INTO ot_operations(id,run_id,epoch,session_id,order_id,op_key,operation,request) VALUES (?,?,?,?,?,?,?,?::jsonb) ON CONFLICT(run_id,op_key) DO NOTHING",id,run.get("id"),run.get("epoch"),cell.get("session_id"),cell.get("active_order"),key,operation,Json.write(request));return id;
 }
 /** Admit every interval of an actual grant in its SQL transaction, before Hold can interleave. */
 static void admit(Connection c,Map<String,Object> run,double granted,String blocked)throws SQLException{
  if(!enabled(run)||!run.get("state").equals("running"))return;
  if(granted>65535)throw new Conflict("OT logical sequence exhausted; controlled new epoch required");
  var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=? AND initialized AND NOT finalized",run.get("id"));if(cell==null)return;
  for(long target=((Number)cell.get("settled")).longValue()+1;target<=Math.floor(granted);target++)issue(c,run,"step:"+target,"step",Map.of("simulation_time",target,"power_available",blocked==null),null);
 }
 static boolean outstanding(Connection c,Map<String,Object> run)throws SQLException{
  if(!enabled(run))return false;var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));
  return cell==null||!Boolean.TRUE.equals(cell.get("initialized"))||number(cell,"settled")<Math.floor(number(run,"granted"))||one(c,"SELECT 1 FROM ot_operations WHERE run_id=? AND status='pending' LIMIT 1",run.get("id"))!=null;
 }
 static Map<String,Object> next(Store s){return s.tx(c->{
  var run=current(c);if(!enabled(run))return null;
  var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));if(cell==null)return null;
  var pending=one(c,"SELECT * FROM ot_operations WHERE run_id=? AND epoch=? AND status='pending' ORDER BY ordinal LIMIT 1",run.get("id"),run.get("epoch"));
  if(!Boolean.TRUE.equals(cell.get("initialized")))return pending;
  // Settle already admitted steps even after Hold. Current-grant controls/dispatch must
  // wait until older logical intervals are settled, otherwise they change past physics.
  var admitted=one(c,"SELECT * FROM ot_operations WHERE run_id=? AND epoch=? AND status='pending' AND operation='step' ORDER BY ordinal LIMIT 1",run.get("id"),run.get("epoch"));if(admitted!=null)return admitted;
  long target=((Number)cell.get("settled")).longValue()+1;
  if(target<=Math.floor(number(run,"granted"))){
   if(!run.get("state").equals("running")||Boolean.TRUE.equals(cell.get("finalized")))return pending;
   UUID id=issue(c,run,"step:"+target,"step",Map.of("simulation_time",target,"power_available",run.get("blocked_reason")==null),null);return one(c,"SELECT * FROM ot_operations WHERE id=?",id);
  }
  return pending;
 });}
 static void acknowledge(Store s,UUID id,JsonNode reply){s.tx(c->{var run=current(c);var op=one(c,"SELECT * FROM ot_operations WHERE id=? AND run_id=? AND epoch=?",id,run.get("id"),run.get("epoch"));if(op==null)throw new Conflict("Stale OT operation");if(op.get("response")!=null){if(!json(op.get("response")).equals(reply))throw new Conflict("Conflicting OT response replay");return null;}
  var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));var result=reply.path("result");var scope=result.path("scope");
  if(!reply.path("version").asText().equals("1.0")||!reply.path("command_id").asText().equals(id.toString())||!result.path("initialized").asBoolean()||!scope.path("run_id").asText().equals(run.get("id").toString())||!scope.path("epoch").asText().equals(run.get("epoch").toString())||!scope.path("session_id").asText().equals(cell.get("session_id").toString())||!op.get("session_id").equals(cell.get("session_id")))throw new Conflict("Uncorrelated OT response");
  double time=Policy.time(result.get("simulation_time"));double expected=op.get("operation").equals("step")?json(op.get("request")).path("payload").path("simulation_time").asDouble():number(cell,"settled");if(time!=expected||time>number(run,"granted"))throw new Conflict("OT response exceeds its authorized grant/step");
  var event=result.get("completion");if(event!=null&&!event.isNull())completion(c,run,cell,event,time);
  boolean finalized=op.get("operation").equals("finalize");if(finalized&&!result.path("finalized").asBoolean())throw new Conflict("Equipment did not acknowledge stopped finalisation");
  sql(c,"UPDATE ot_cells SET initialized=true,settled=?,telemetry=?::jsonb,observed_at=clock_timestamp(),error=NULL,finalized=? WHERE run_id=?",(long)time,Json.write(result),finalized||Boolean.TRUE.equals(cell.get("finalized")),run.get("id"));
  sql(c,"UPDATE ot_operations SET response=?::jsonb,status='completed',reason=NULL WHERE id=?",Json.write(reply),id);sql(c,"UPDATE ot_commands SET status='completed',reason=NULL WHERE id=?",id);return null;
 });}
 static void completion(Connection c,Map<String,Object> run,Map<String,Object> cell,JsonNode event,double time)throws SQLException{
  Policy.fields(event,"version","event_id","run_id","epoch","session_id","order_id","correlation_id","simulation_time","quantity","good_quantity","scrap_quantity");
  UUID order=Policy.uuid(event.get("order_id"));var batch=one(c,"SELECT b.*,o.quantity,o.correlation_id,o.product FROM ot_batches b JOIN production_orders o ON o.id=b.order_id WHERE b.order_id=? AND b.run_id=? AND b.epoch=?",order,run.get("id"),run.get("epoch"));if(batch!=null&&Boolean.TRUE.equals(batch.get("committed"))&&event.equals(json(batch.get("completed_event"))))return;if(batch==null||!order.equals(cell.get("active_order")))throw new Conflict("Completion is not for the dispatched OT batch");
  var cfg=Production.ensure(c,run);var product=Production.find(cfg,"products","sku",batch.get("product").toString());int quantity=((Number)batch.get("quantity")).intValue(),scrap=quantity*product.path("scrap_percent").asInt()/100;
  if(!event.path("version").asText().equals("1.0")||!Policy.uuid(event.get("event_id")).equals(Store.uuid5(order,"ot.completed"))||!event.path("run_id").asText().equals(run.get("id").toString())||!event.path("epoch").asText().equals(run.get("epoch").toString())||!event.path("session_id").asText().equals(cell.get("session_id").toString())||!event.path("correlation_id").asText().equals(batch.get("correlation_id").toString())||Policy.integer(event.get("quantity"),1,10000)!=quantity||Policy.integer(event.get("good_quantity"),0,10000)!=quantity-scrap||Policy.integer(event.get("scrap_quantity"),0,10000)!=scrap||Policy.time(event.get("simulation_time"))>time)throw new Conflict("OT completion identity, quantities or time mismatch");
  if(batch.get("completed_event")!=null&&!json(batch.get("completed_event")).equals(event))throw new Conflict("Completion identity changed its durable contents");sql(c,"UPDATE ot_batches SET completed_event=?::jsonb WHERE order_id=? AND completed_event IS NULL",Json.write(event),order);
 }
 static boolean available(Connection c,Map<String,Object> run)throws SQLException{if(!enabled(run))return true;var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=? AND initialized AND NOT finalized AND active_order IS NULL",run.get("id"));return cell!=null;}
 static void dispatch(Connection c,Map<String,Object> run,Map<String,Object> order,JsonNode product)throws SQLException{if(!enabled(run))return;sql(c,"UPDATE ot_cells SET active_order=? WHERE run_id=?",order.get("id"),run.get("id"));sql(c,"INSERT INTO ot_batches(order_id,run_id,epoch) VALUES (?,?,?)",order.get("id"),run.get("id"),run.get("epoch"));int quantity=((Number)order.get("quantity")).intValue();issue(c,run,"dispatch:"+order.get("id"),"dispatch",Map.of("order_id",order.get("id"),"correlation_id",order.get("correlation_id"),"quantity",quantity,"scrap_quantity",quantity*product.path("scrap_percent").asInt()/100,"duration_seconds",product.path("duration_seconds").asInt()),null);}
 static boolean ready(Connection c,Map<String,Object> run,Object order)throws SQLException{return !enabled(run)||one(c,"SELECT 1 FROM ot_batches WHERE order_id=? AND run_id=? AND epoch=? AND completed_event IS NOT NULL AND NOT committed",order,run.get("id"),run.get("epoch"))!=null;}
 static void committed(Connection c,Map<String,Object> run,Object order)throws SQLException{if(!enabled(run))return;sql(c,"UPDATE ot_batches SET committed=true WHERE order_id=?",order);sql(c,"UPDATE ot_cells SET active_order=NULL WHERE run_id=? AND active_order=?",run.get("id"),order);}
 static Map<String,Object> command(Store s,String key,JsonNode body,Audit audit){
  Policy.fields(body,"run_id","epoch","action","fault","active");UUID runId=Policy.uuid(body.get("run_id")),epoch=Policy.uuid(body.get("epoch"));String action=body.path("action").asText();if(!Set.of("start","stop","reset","fault").contains(action))throw new IllegalArgumentException("Unknown OT action");if(action.equals("fault")){if(!Set.of("conveyor_jam","sensor_failure","guard_open","power_loss").contains(body.path("fault").asText())||!body.path("active").isBoolean())throw new IllegalArgumentException("Known fault and boolean active required");}else if(body.has("fault")||body.has("active"))throw new IllegalArgumentException("Fault fields require fault action");
  if(audit==null||!audit.role().equals("operator"))throw new Conflict("OT controls require an attributed operator");if(key==null||key.isBlank()||key.length()>128)throw new IllegalArgumentException("Idempotency-Key of 1..128 characters required");
  return s.tx(c->{var run=current(c);if(!run.get("id").equals(runId)||!run.get("epoch").equals(epoch))throw new Conflict("Stale OT command scope");if(!enabled(run))throw new Conflict("OT is disabled for this run");var old=one(c,"SELECT * FROM ot_commands WHERE run_id=? AND actor=? AND idempotency_key=?",runId,audit.actor(),key);if(old!=null){if(!json(old.get("body")).equals(body))throw new Conflict("OT idempotency key conflicts with prior body");return old;}
   boolean rejected=!Set.of("running","held").contains(run.get("state"))||action.equals("start")&&!run.get("state").equals("running");
   UUID id=Store.uuid5(epoch,"ot.operator:"+audit.actor()+":"+key);var payload=new LinkedHashMap<String,Object>();payload.put("action",action);if(action.equals("fault")){payload.put("fault",body.path("fault").asText());payload.put("active",body.path("active").asBoolean());}issue(c,run,"control:"+id,"control",payload,id);sql(c,"INSERT INTO ot_commands(id,run_id,epoch,actor,idempotency_key,body) VALUES (?,?,?,?,?,?::jsonb)",id,runId,epoch,audit.actor(),key,Json.write(body));if(rejected){String reason="Run state does not admit this OT action";sql(c,"UPDATE ot_operations SET status='rejected',reason=? WHERE id=?",reason,id);sql(c,"UPDATE ot_commands SET status='rejected',reason=? WHERE id=?",reason,id);}s.accepted(c,run,audit,id);return one(c,"SELECT * FROM ot_commands WHERE id=?",id);
  });
 }
 static void rejected(Store s,UUID id,String reason){s.tx(c->{var run=current(c);var op=one(c,"SELECT * FROM ot_operations WHERE id=? AND run_id=? AND epoch=?",id,run.get("id"),run.get("epoch"));if(op==null)throw new Conflict("Stale OT rejection");if(!op.get("operation").equals("control"))throw new Conflict("Equipment rejected durable batch execution: "+reason);sql(c,"UPDATE ot_operations SET status='rejected',reason=? WHERE id=? AND status='pending'",cut(reason,1000),id);sql(c,"UPDATE ot_commands SET status='rejected',reason=? WHERE id=?",cut(reason,1000),id);return null;});}
 static Map<String,Object> snapshot(Store s){return s.tx(c->{var run=current(c);var result=new LinkedHashMap<String,Object>();result.put("mode",run.get("ot_mode"));result.put("configured_mode",s.settings.otMode);result.put("run_id",run.get("id"));result.put("epoch",run.get("epoch"));var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));result.put("cell",cell);result.put("stale",cell==null||cell.get("observed_at")==null||Duration.between(Instant.parse(cell.get("observed_at").toString()),Instant.now()).toSeconds()>15);result.put("batches",rows(c,"SELECT * FROM ot_batches WHERE run_id=? ORDER BY order_id",run.get("id")));result.put("commands",rows(c,"SELECT * FROM ot_commands WHERE run_id=? ORDER BY created_at DESC LIMIT 50",run.get("id")));return result;});}
 static void finalizing(Connection c,Map<String,Object> run)throws SQLException{if(enabled(run))issue(c,run,"finalize","finalize",Map.of(),null);}
 static boolean stopped(Store s){return s.tx(c->{var run=current(c);return !enabled(run)||one(c,"SELECT 1 FROM ot_cells WHERE run_id=? AND finalized",run.get("id"))!=null;});}
 static void finalizeLocal(Store s,Object epoch){s.tx(c->{var run=current(c);if(!run.get("epoch").equals(epoch)||!run.get("mode").equals("standalone")||!run.get("state").equals("finalizing")||Store.outstanding(c,run)||one(c,"SELECT 1 FROM ot_cells WHERE run_id=? AND finalized",run.get("id"))==null)throw new Conflict("OT finalisation is not settled");sql(c,"UPDATE runs SET state='finalized',committed=granted WHERE id=?",run.get("id"));return null;});}

}
