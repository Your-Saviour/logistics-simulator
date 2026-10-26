package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Bounded observations and diagnostics. Synthetic signals never drive PLC or business state. */
final class OtInsights {
 static final Set<String> PROFILES=Set.of("normal","noise","drift","stuck","dropout");
 static final Set<String> FAULTS=Set.of("conveyor_jam","sensor_failure","guard_open","power_loss");
 static Map<String,Object> signals(JsonNode model,double time,String profile,int seed,double start){
  double elapsed=Math.max(0,time-start);boolean enabled=model.path("enabled").asBoolean();
  // Deliberately simple synthetic model, not a physical thermal simulation.
  double temperature=enabled?35+Math.min(30,model.path("progress_seconds").asDouble()*.2):25;
  double current=enabled?4.5:.2;
  var rng=new Random(((long)seed<<32)^Double.doubleToLongBits(time));
  if(profile.equals("noise")){temperature+=(rng.nextDouble()-.5)*4;current+=(rng.nextDouble()-.5)*.4;}
  if(profile.equals("drift")){temperature+=Math.min(20,elapsed*.05);current+=Math.min(2,elapsed*.005);}
  if(profile.equals("stuck")){temperature=35;current=4.5;}
  boolean dropout=profile.equals("dropout")&&((long)elapsed%10)<3;
  var values=new LinkedHashMap<String,Object>();values.put("motor_temperature",dropout?null:Math.round(temperature*100)/100.0);values.put("motor_current",dropout?null:Math.round(current*100)/100.0);
  values.put("quality",dropout?"missing":profile.equals("normal")?"synthetic":"degraded");values.put("profile",profile);return values;
 }
 static List<Map<String,Object>> devices(){return List.of(
  Map.of("id","assembly.motor.temperature","name","Motor temperature","signal","motor_temperature","unit","°C","range","23–85","source","Synthetic model v1","protocol","derived","synthetic",true),
  Map.of("id","assembly.motor.current","name","Motor current","signal","motor_current","unit","A","range","0–8","source","Synthetic model v1","protocol","derived","synthetic",true));}
 static void record(Connection c,Map<String,Object> run,UUID operation,Object order,JsonNode telemetry)throws SQLException{
  double time=telemetry.path("simulation_time").asDouble();
  var scenario=one(c,"SELECT * FROM ot_sensor_scenarios WHERE run_id=? AND epoch=? AND started_simulation_time<=? AND (stopped_simulation_time IS NULL OR stopped_simulation_time>?) ORDER BY started_at DESC LIMIT 1",run.get("id"),run.get("epoch"),time,time);
  String profile=scenario==null||!PROFILES.contains(scenario.get("profile").toString())?"normal":scenario.get("profile").toString();int seed=scenario==null?0:((Number)scenario.get("seed")).intValue();double start=scenario==null?0:number(scenario,"started_simulation_time");
  int inserted=sql(c,"INSERT INTO ot_observations(operation_id,run_id,epoch,order_id,simulation_time,telemetry,signals,scenario_id,continuity) VALUES (?,?,?,?,?,?::jsonb,?::jsonb,?,?) ON CONFLICT(operation_id) DO NOTHING",operation,run.get("id"),run.get("epoch"),order,time,Json.write(telemetry),Json.write(signals(telemetry.path("cell"),time,profile,seed,start)),scenario==null?null:scenario.get("id"),one(c,"SELECT continuity FROM ot_cells WHERE run_id=?",run.get("id")).get("continuity"));
  if(inserted==0)return;
  sql(c,"DELETE FROM ot_observations WHERE run_id=? AND id NOT IN (SELECT id FROM ot_observations WHERE run_id=? ORDER BY id DESC LIMIT 600)",run.get("id"),run.get("id"));
  var sources=new HashSet<String>();telemetry.path("cell").path("faults").forEach(f->sources.add(f.asText()));
  if(telemetry.path("cell").has("power_available")&&!telemetry.path("cell").path("power_available").asBoolean())sources.add("external_power_unavailable");
  if(sources.isEmpty()&&telemetry.path("cell").path("latched").asBoolean())sources.add("reset_required");
  for(var alarm:rows(c,"SELECT * FROM ot_alarms WHERE run_id=? AND epoch=? AND active",run.get("id"),run.get("epoch"))){
   if(sources.contains(alarm.get("source").toString()))sql(c,"UPDATE ot_alarms SET last_at=clock_timestamp() WHERE id=?",alarm.get("id"));
   else sql(c,"UPDATE ot_alarms SET active=false,cleared_at=clock_timestamp(),last_at=clock_timestamp() WHERE id=?",alarm.get("id"));
  }
  for(String source:sources)sql(c,"INSERT INTO ot_alarms(id,run_id,epoch,source,severity,impact,order_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT(run_id,epoch,source) WHERE active DO NOTHING",UUID.randomUUID(),run.get("id"),run.get("epoch"),source,source.equals("reset_required")?"warning":"critical","Production inhibited. Restore condition, reset latch, then explicitly Start.",order);
  sql(c,"DELETE FROM ot_alarms WHERE run_id=? AND NOT active AND id NOT IN (SELECT id FROM ot_alarms WHERE run_id=? ORDER BY first_at DESC LIMIT 200)",run.get("id"),run.get("id"));
 }
 static Map<String,Object> snapshot(Store s){return s.tx(c->{var run=current(c);var result=new LinkedHashMap<String,Object>();result.put("run_id",run.get("id"));result.put("epoch",run.get("epoch"));result.put("source_events",rows(c,"SELECT * FROM ot_source_events WHERE run_id=? AND epoch=? ORDER BY id DESC LIMIT 200",run.get("id"),run.get("epoch")));result.put("devices",devices());result.put("profiles",PROFILES.stream().sorted().toList());result.put("observations",rows(c,"SELECT * FROM (SELECT * FROM ot_observations WHERE run_id=? AND epoch=? ORDER BY id DESC LIMIT 600) latest ORDER BY id",run.get("id"),run.get("epoch")));result.put("alarms",rows(c,"SELECT * FROM ot_alarms WHERE run_id=? AND epoch=? ORDER BY active DESC,first_at DESC LIMIT 200",run.get("id"),run.get("epoch")));result.put("scenarios",rows(c,"SELECT * FROM ot_sensor_scenarios WHERE run_id=? AND epoch=? ORDER BY started_at DESC LIMIT 50",run.get("id"),run.get("epoch")));result.put("events",rows(c,"SELECT * FROM ot_insight_receipts WHERE run_id=? AND epoch=? ORDER BY created_at DESC LIMIT 200",run.get("id"),run.get("epoch")));return result;});}
 static void sourceEvent(Connection c,Map<String,Object> run,String kind,String detail)throws SQLException{
  sql(c,"INSERT INTO ot_source_events(run_id,epoch,kind,detail,simulation_time) VALUES (?,?,?,?,?)",run.get("id"),run.get("epoch"),kind,cut(detail,1000),run.get("granted"));
  sql(c,"DELETE FROM ot_source_events WHERE run_id=? AND id NOT IN (SELECT id FROM ot_source_events WHERE run_id=? ORDER BY id DESC LIMIT 200)",run.get("id"),run.get("id"));
 }
 static void sourceLost(Connection c,Map<String,Object> run,String reason)throws SQLException{
  var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",run.get("id"));if(cell==null)return;
  if(cell.get("error")==null){sourceEvent(c,run,"disconnected",reason);sql(c,"UPDATE ot_cells SET continuity=continuity+1 WHERE run_id=?",run.get("id"));}
  sql(c,"UPDATE ot_cells SET error=? WHERE run_id=?",cut(reason,1000),run.get("id"));
 }
 static void sourceRestored(Connection c,Map<String,Object> run)throws SQLException{
  var cell=one(c,"SELECT error FROM ot_cells WHERE run_id=?",run.get("id"));if(cell!=null&&cell.get("error")!=null)sourceEvent(c,run,"reconnected","Confirmed equipment feedback restored");
 }
 static void fault(Connection c,Map<String,Object> run,UUID id,String key,Audit audit,String fault,boolean active)throws SQLException{
  var body=Map.of("run_id",run.get("id"),"epoch",run.get("epoch"),"action","fault","fault",fault,"active",active);
  Ot.issue(c,run,"control:"+id,"control",Map.of("action","fault","fault",fault,"active",active),id);
  sql(c,"INSERT INTO ot_commands(id,run_id,epoch,actor,idempotency_key,body) VALUES (?,?,?,?,?,?::jsonb)",id,run.get("id"),run.get("epoch"),audit.actor(),"scenario:"+key,Json.write(body));
 }
 static Map<String,Object> control(Store s,String key,JsonNode body,Audit audit){
  Policy.fields(body,"run_id","epoch","action","alarm_id","profile","seed");UUID runId=Policy.uuid(body.get("run_id")),epoch=Policy.uuid(body.get("epoch"));String action=body.path("action").asText();
  if(!Set.of("alarm_ack","scenario_start","scenario_stop").contains(action))throw new IllegalArgumentException("Unknown insight action");
  if(audit==null||!audit.role().equals("operator"))throw new Conflict("Attributed operator required");if(key==null||key.isBlank()||key.length()>128)throw new IllegalArgumentException("Idempotency-Key of 1..128 characters required");
  if(action.equals("scenario_start")){if(!PROFILES.contains(body.path("profile").asText())&&!FAULTS.contains(body.path("profile").asText()))throw new IllegalArgumentException("Known sensor profile required");Policy.integer(body.get("seed"),0,Integer.MAX_VALUE);}
  return s.tx(c->{var run=current(c);if(!runId.equals(run.get("id"))||!epoch.equals(run.get("epoch")))throw new Conflict("Stale insight scope");
   var old=one(c,"SELECT * FROM ot_insight_receipts WHERE run_id=? AND actor=? AND idempotency_key=?",runId,audit.actor(),key);if(old!=null){if(!json(old.get("body")).equals(body))throw new Conflict("Insight idempotency conflict");return old;}
   if(!Ot.enabled(run))throw new Conflict("OT is disabled");
   UUID id=Store.uuid5(epoch,"ot.insight:"+audit.actor()+":"+key);
   if(action.equals("alarm_ack")){UUID alarm=Policy.uuid(body.get("alarm_id"));if(one(c,"SELECT * FROM ot_alarms WHERE id=? AND run_id=? AND epoch=?",alarm,runId,epoch)==null)throw new Conflict("Alarm not in current scope");sql(c,"UPDATE ot_alarms SET acknowledged_at=COALESCE(acknowledged_at,clock_timestamp()),acknowledged_by=COALESCE(acknowledged_by,?) WHERE id=?",audit.actor(),alarm);}
   else {
    if(!Set.of("running","held").contains(run.get("state")))throw new Conflict("Scenarios require a running or held run");
    if(action.equals("scenario_start")){if(one(c,"SELECT id FROM ot_sensor_scenarios WHERE run_id=? AND epoch=? AND stopped_at IS NULL",runId,epoch)!=null)throw new Conflict("Stop the active scenario first");sql(c,"INSERT INTO ot_sensor_scenarios(id,run_id,epoch,profile,seed,started_simulation_time,actor) VALUES (?,?,?,?,?,?,?)",id,runId,epoch,body.path("profile").asText(),body.path("seed").asInt(),run.get("granted"),audit.actor());String fault=body.path("profile").asText();if(FAULTS.contains(fault))fault(c,run,id,key,audit,fault,true);}
    else {var active=one(c,"SELECT * FROM ot_sensor_scenarios WHERE run_id=? AND epoch=? AND stopped_at IS NULL",runId,epoch);if(active!=null&&FAULTS.contains(active.get("profile").toString()))fault(c,run,id,key,audit,active.get("profile").toString(),false);sql(c,"UPDATE ot_sensor_scenarios SET stopped_at=clock_timestamp(),stopped_simulation_time=? WHERE run_id=? AND epoch=? AND stopped_at IS NULL",run.get("granted"),runId,epoch);}
   }
   sql(c,"INSERT INTO ot_insight_receipts(id,run_id,epoch,actor,idempotency_key,body) VALUES (?,?,?,?,?,?::jsonb)",id,runId,epoch,audit.actor(),key,Json.write(body));s.accepted(c,run,audit,id);return one(c,"SELECT * FROM ot_insight_receipts WHERE id=?",id);
  });
 }
}
