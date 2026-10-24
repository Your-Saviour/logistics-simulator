package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import com.zaxxer.hikari.*;
import org.springframework.core.io.ClassPathResource;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.time.*;
import java.util.*;

/** PostgreSQL row locks are the transition authority; lock order: schema gate, run, job/outbox. */
final class Store {
 record Audit(String actor,String role,UUID requestId,String action,String key,String peer,Object runId){}
 static class Conflict extends RuntimeException {Conflict(String m){super(m);}}
 static class Unavailable extends RuntimeException {Unavailable(Throwable e){super(e);}}
 interface Work<T>{T apply(Connection c)throws Exception;}
 final Settings settings;
 final HikariDataSource pool;
 Store(Settings s){
  settings=s;var config=new HikariConfig();
  if(s.database.startsWith("jdbc:"))config.setJdbcUrl(s.database);
  else{var uri=URI.create(s.database);String host=uri.getHost().contains(":")?"["+uri.getHost()+"]":uri.getHost();
   config.setJdbcUrl("jdbc:postgresql://"+host+":"+(uri.getPort()<0?5432:uri.getPort())+uri.getRawPath()+(uri.getRawQuery()==null?"":"?"+uri.getRawQuery()));
   if(uri.getRawUserInfo()!=null){var pair=uri.getRawUserInfo().split(":",2);config.setUsername(URLDecoder.decode(pair[0],StandardCharsets.UTF_8));if(pair.length>1)config.setPassword(URLDecoder.decode(pair[1],StandardCharsets.UTF_8));}
  }
  config.setMaximumPoolSize(8);config.setConnectionTimeout(5000);config.setInitializationFailTimeout(-1);pool=new HikariDataSource(config);
 }
 Connection connect()throws SQLException{return pool.getConnection();}
 <T>T tx(Work<T> work){try(var c=connect()){c.setAutoCommit(false);try{sql(c,"SELECT pg_advisory_xact_lock_shared(8192103)");T result=work.apply(c);c.commit();return result;}catch(Exception e){c.rollback();if(e instanceof RuntimeException r)throw r;throw new Unavailable(e);}}catch(SQLException e){throw new Unavailable(e);}}
 static int sql(Connection c,String statement,Object...args)throws SQLException{try(var p=c.prepareStatement(statement)){bind(p,args);boolean result=p.execute();return result?0:p.getUpdateCount();}}
 static void bind(PreparedStatement p,Object[] args)throws SQLException{for(int i=0;i<args.length;i++)p.setObject(i+1,args[i]);}
 static List<Map<String,Object>> rows(Connection c,String q,Object...args)throws SQLException{
  try(var p=c.prepareStatement(q)){bind(p,args);try(var rs=p.executeQuery()){var values=new ArrayList<Map<String,Object>>();var md=rs.getMetaData();while(rs.next()){var row=new LinkedHashMap<String,Object>();for(int i=1;i<=md.getColumnCount();i++){
   Object v=rs.getObject(i);if(v instanceof java.sql.Timestamp t)v=t.toInstant().toString();else if(v!=null&&v.getClass().getName().equals("org.postgresql.util.PGobject"))v=Json.parse(v.toString());
   row.put(md.getColumnLabel(i),v);
  }values.add(row);}return values;}}
 }
 static Map<String,Object> one(Connection c,String q,Object...args)throws SQLException{var r=rows(c,q,args);return r.isEmpty()?null:r.getFirst();}
 static double number(Map<String,Object> r,String k){return ((Number)r.get(k)).doubleValue();}
 static JsonNode json(Object v){return v instanceof JsonNode n?n:Json.M.valueToTree(v);}
 static UUID uuid(Object v){return v instanceof UUID u?u:UUID.fromString(v.toString());}
 static Map<String,Object> current(Connection c)throws SQLException{
  for(int i=0;i<10;i++){var run=one(c,"SELECT * FROM runs WHERE current FOR UPDATE");if(run!=null)return run;}
  throw new Conflict("Current run changed repeatedly; retry the command");
 }
 void migrate(){
  try(var c=connect()){c.setAutoCommit(false);try{
   sql(c,"SELECT pg_advisory_xact_lock(8192101)");sql(c,"SELECT pg_advisory_xact_lock(8192103)");
   sql(c,"CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())");
   var index=new ClassPathResource("migrations/index.txt");
   var resources=new String(index.getInputStream().readAllBytes(),StandardCharsets.UTF_8).lines().filter(n->!n.isBlank()).sorted().map(n->new ClassPathResource("migrations/"+n)).toList();
   for(var resource:resources){String source=new String(resource.getInputStream().readAllBytes(),StandardCharsets.UTF_8);String checksum=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(source.getBytes(StandardCharsets.UTF_8)));var old=one(c,"SELECT checksum FROM schema_migrations WHERE name=?",resource.getFilename());
    if(old!=null){if(!old.get("checksum").equals(checksum))throw new Conflict("Applied migration was edited: "+resource.getFilename());}
    else{sql(c,source);sql(c,"INSERT INTO schema_migrations(name,checksum) VALUES (?,?)",resource.getFilename(),checksum);}
   }
   var run=one(c,"SELECT * FROM runs WHERE current FOR UPDATE");
   if(run==null){if(settings.mode.equals("helics")&&(settings.run.isEmpty()||settings.epoch.isEmpty()))throw new Conflict("Federation owner must supply run and epoch IDs");sql(c,"INSERT INTO runs(id,epoch,mode,scenario) VALUES (?,?,?,?::jsonb)",settings.run.isEmpty()?UUID.randomUUID():UUID.fromString(settings.run),settings.epoch.isEmpty()?UUID.randomUUID():UUID.fromString(settings.epoch),settings.mode,Json.write(settings.scenario));run=current(c);}
   if(json(run.get("scenario")).isEmpty()){sql(c,"UPDATE runs SET scenario=?::jsonb WHERE id=?",Json.write(settings.scenario),run.get("id"));}
   if(!run.get("mode").equals(settings.mode))throw new Conflict("Persisted run mode differs; use a fresh deployment database");
   if(settings.mode.equals("helics")&&(!run.get("id").toString().equals(settings.run)||!run.get("epoch").toString().equals(settings.epoch)))throw new Conflict("Persisted federation identity differs; archive and use a fresh database");
   c.commit();
  }catch(Exception e){c.rollback();if(e instanceof RuntimeException r)throw r;throw new Unavailable(e);}}
  catch(SQLException e){throw new Unavailable(e);}
 }
 Map<String,Object> run(){return tx(Store::current);}
 Map<String,Object> status(){return tx(this::status);}
 Map<String,Object> status(Connection c)throws SQLException{var run=current(c);var result=new LinkedHashMap<String,Object>();result.put("run",run);result.put("jobs",rows(c,"SELECT * FROM jobs WHERE run_id=? ORDER BY created_at DESC LIMIT 100",run.get("id")));result.put("effects",one(c,"SELECT COALESCE(sum(quantity),0) n FROM effects WHERE run_id=?",run.get("id")).get("n"));result.put("heartbeats",rows(c,"SELECT role,seen_at,detail,seen_at>clock_timestamp()-interval '15 seconds' healthy FROM heartbeats"));result.put("pending_boundary_outputs",one(c,"SELECT count(*) n FROM boundary_outbox WHERE run_id=? AND sent_at IS NULL",run.get("id")).get("n"));return result;}

 void accepted(Connection c,Map<String,Object> run,Audit a,Object target)throws SQLException{audit(c,run.get("id"),a,"accepted",200,target);}
 void audit(Connection c,Object run,Audit a,String outcome,int status,Object target)throws SQLException{if(a==null)return;sql(c,"INSERT INTO command_audit(id,run_id,actor,role,request_id,action,outcome,status_code,idempotency_key,peer,target_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",UUID.randomUUID(),run,a.actor,a.role,a.requestId,cut(a.action,256),outcome,status,cut(a.key,128),cut(a.peer,128),target);}
 static String cut(String v,int n){return v==null?"":v.substring(0,Math.min(n,v.length()));}
 void rejected(Audit a,int status){tx(c->{audit(c,a.runId==null?current(c).get("id"):a.runId,a,"rejected",status,null);return null;});}
 List<Map<String,Object>> audit(){return tx(c->rows(c,"SELECT * FROM command_audit ORDER BY recorded_at DESC,id DESC LIMIT 100"));}
 Map<String,Object> schedule(String key,double due,int quantity,Audit audit,Object boundary){
  if(key==null||key.isEmpty()||key.length()>128||!Double.isFinite(due)||due<0||quantity<1||quantity>10000)throw new Conflict("Valid idempotency key, quantity and finite time required");
  return tx(c->{var run=current(c);JsonNode payload=Json.M.valueToTree(Map.of("quantity",quantity));JsonNode input=boundary==null?null:json(boundary);
   if(input!=null&&(!input.path("run_id").asText().equals(run.get("id").toString())||!input.path("epoch").asText().equals(run.get("epoch").toString())))throw new Conflict("Seeded input belongs to a different run or epoch");
   var old=one(c,"SELECT * FROM jobs WHERE run_id=? AND idempotency_key=?",run.get("id"),key);
   if(old!=null){if(number(old,"original_due_at")!=due||!old.get("payload").equals(payload)||!Objects.equals(old.get("boundary_input"),input))throw new Conflict("Idempotency key already used with a different command");accepted(c,run,audit,old.get("id"));return old;}
   if(!Set.of("running","held").contains(run.get("state"))||due<Math.max(number(run,"granted"),number(run,"requested"))+settings.quantum)throw new Conflict("Schedule at least one quantum beyond granted/requested time in an active run");
   var job=one(c,"INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload,boundary_input) VALUES (?,?,?,?,?,?,?::jsonb,?::jsonb) RETURNING *",UUID.randomUUID(),run.get("id"),run.get("epoch"),key,due,due,Json.write(payload),input==null?null:Json.write(input));accepted(c,run,audit,job.get("id"));return job;
  });
 }
 String execute(UUID id){return tx(c->{var run=current(c);var job=one(c,"SELECT *,retry_after<=clock_timestamp() retry_ready FROM jobs WHERE id=? FOR UPDATE",id);
  if(job==null||!job.get("run_id").equals(run.get("id"))||!job.get("epoch").equals(run.get("epoch")))return "fenced";
  if(job.get("status").equals("completed"))return "duplicate";if(job.get("status").equals("dead"))return "dead";
  if(!run.get("state").equals("running")||number(job,"due_at")>number(run,"granted")||!Boolean.TRUE.equals(job.get("retry_ready"))||one(c,"SELECT 1 FROM heartbeats WHERE role='controller' AND seen_at>clock_timestamp()-interval '15 seconds'")==null)return "waiting";
  if(json(job.get("payload")).has("material_reservation"))return MaterialPlans.execute(this,c,run,job);
  if(json(job.get("payload")).has("custody"))return Custody.execute(this,c,run,job);
  if(json(job.get("payload")).path("production").asBoolean())return Production.execute(this,c,run,job);
  sql(c,"INSERT INTO inbox(event_id,run_id,epoch) VALUES (?,?,?) ON CONFLICT DO NOTHING",id,run.get("id"),run.get("epoch"));
  int quantity=json(job.get("payload")).get("quantity").intValue();sql(c,"INSERT INTO effects(job_id,run_id,quantity) VALUES (?,?,?)",id,run.get("id"),quantity);sql(c,"UPDATE jobs SET status='completed',error=NULL WHERE id=?",id);
  if(run.get("mode").equals("helics")&&!job.get("idempotency_key").toString().startsWith("boundary:"))sql(c,"INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (?,?,?::jsonb)",UUID.randomUUID(),run.get("id"),Json.write(Map.of("job_id",id,"quantity",quantity,"time",run.get("granted"))));return "completed";
 });}
 String fail(UUID id,Exception error){return tx(c->{var run=current(c);var job=one(c,"SELECT * FROM jobs WHERE id=? FOR UPDATE",id);if(job==null||!job.get("run_id").equals(run.get("id"))||!job.get("epoch").equals(run.get("epoch")))return "fenced";if(Set.of("completed","dead").contains(job.get("status")))return job.get("status").toString();int attempts=((Number)job.get("attempts")).intValue()+1;sql(c,"UPDATE jobs SET attempts=?,status=?,error=?,retry_after=clock_timestamp()+interval '2 seconds' WHERE id=?",attempts,attempts>=3?"dead":"pending",cut(error.toString(),1000),id);if(attempts>=3)sql(c,"UPDATE runs SET state='failed',error='Job retry limit exceeded' WHERE id=?",run.get("id"));return attempts>=3?"dead":"retry";});}
 List<Map<String,Object>> dispatchable(){return tx(c->{var run=current(c);if(!run.get("state").equals("running"))return List.of();for(var job:rows(c,"SELECT id FROM jobs WHERE run_id=? AND epoch=? AND due_at<=? AND status IN ('pending','queued') AND retry_after<=clock_timestamp()",run.get("id"),run.get("epoch"),run.get("granted")))sql(c,"INSERT INTO outbox(id,job_id,run_id) VALUES (?,?,?) ON CONFLICT(job_id) DO NOTHING",UUID.randomUUID(),job.get("id"),run.get("id"));return rows(c,"SELECT o.id,o.job_id FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.run_id=? AND j.epoch=? AND j.status IN ('pending','queued') AND j.retry_after<=clock_timestamp() AND o.retry_after<=clock_timestamp()",run.get("id"),run.get("epoch"));});}
 void published(Object id){tx(c->{current(c);sql(c,"UPDATE outbox o SET sent_at=clock_timestamp(),retry_after=CASE WHEN EXISTS(SELECT 1 FROM jobs j JOIN runs r ON r.id=j.run_id WHERE j.id=o.job_id AND j.due_at>r.granted) THEN clock_timestamp() ELSE clock_timestamp()+interval '5 seconds' END WHERE o.id=?",id);return null;});}
 void heartbeat(String role,String detail){tx(c->{sql(c,"INSERT INTO heartbeats(role,detail) VALUES (?,?) ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp(),detail=EXCLUDED.detail",role,detail);return null;});}
 void grant(double granted,Object epoch,String blocked){tx(c->{var run=current(c);if(!run.get("epoch").equals(epoch))throw new Conflict("Stale controller epoch");if(Set.of("failed","stalled","finalizing","finalized").contains(run.get("state"))||run.get("mode").equals("standalone")&&run.get("state").equals("held"))return null;if(!Double.isFinite(granted)||granted<number(run,"granted")||run.get("mode").equals("helics")&&granted>number(run,"requested"))throw new Conflict("Grant must be finite, monotonic and within the native requested target");sql(c,"UPDATE runs SET granted=?,requested=GREATEST(requested,?),anchor=clock_timestamp(),blocked_reason=? WHERE id=?",granted,granted,blocked,run.get("id"));if(blocked!=null)sql(c,"UPDATE jobs SET due_at=? WHERE run_id=? AND epoch=? AND status IN ('pending','queued') AND due_at<=?",granted+settings.quantum,run.get("id"),run.get("epoch"),granted);sql(c,"INSERT INTO heartbeats(role) VALUES ('controller') ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp()");return null;});}
 static boolean outstanding(Connection c,Map<String,Object> run)throws SQLException{return Boolean.TRUE.equals(one(c,"SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=? AND due_at<=? AND status NOT IN ('completed','fenced')) OR EXISTS(SELECT 1 FROM boundary_outbox WHERE run_id=? AND sent_at IS NULL) OR EXISTS(SELECT 1 FROM production_events WHERE run_id=? AND sent_at IS NULL) busy",run.get("id"),run.get("granted"),run.get("id"),run.get("id")).get("busy"));}
 boolean prepare(double target,Object epoch){return tx(c->{var run=current(c);if(!run.get("epoch").equals(epoch)||!run.get("state").equals("running")||outstanding(c,run))return false;if(!Double.isFinite(target)||target<=number(run,"granted"))throw new Conflict("Next request must advance time");if(run.get("mode").equals("helics")&&sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=true,native_state='requesting' WHERE run_id=? AND epoch=? AND NOT native_pending AND native_state='executing'",run.get("id"),run.get("epoch"))!=1)return false;sql(c,"UPDATE runs SET committed=granted,requested=? WHERE id=?",target,run.get("id"));return true;});}

 boolean beginPoll(Object epoch,UUID session){return tx(c->{var run=current(c);if(!run.get("epoch").equals(epoch))throw new Conflict("Stale controller epoch");if(!Set.of("running","held").contains(run.get("state")))return false;if(sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=true,native_state='polling' WHERE run_id=? AND epoch=? AND session_id=?",run.get("id"),epoch,session)!=1)throw new Conflict("Native session unavailable");return true;});}
 void nativeSettled(Object epoch,UUID session){tx(c->{var run=current(c);if(!run.get("epoch").equals(epoch))throw new Conflict("Stale controller epoch");if(sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=false,native_state='executing' WHERE run_id=? AND epoch=? AND session_id=?",run.get("id"),epoch,session)!=1)throw new Conflict("Native session unavailable");return null;});}
 void nativeFinalized(Object runId,Object epoch,UUID session){tx(c->{var run=current(c);if(!run.get("id").equals(runId)||!run.get("epoch").equals(epoch))throw new Conflict("Stale native finalization session");if(!run.get("state").equals("finalizing"))throw new Conflict("Run is not awaiting native finalization");if(outstanding(c,run))throw new Conflict("Native finalization still has outstanding work");if(sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=false,native_state='finalized' WHERE run_id=? AND epoch=? AND session_id=? AND native_pending AND native_state='finalizing'",runId,epoch,session)!=1)throw new Conflict("Native finalization session unavailable");sql(c,"UPDATE runs SET state='finalized',committed=granted WHERE id=? AND epoch=?",runId,epoch);return null;});}
 Map<String,Object> control(String action,int speed,String expected,Audit a,Object scenario,String... preconditions){return controlRequest(action,speed,expected,a,scenario,null,preconditions);}
 Map<String,Object> controlRequest(String action,int speed,String expected,Audit a,Object scenario,JsonNode body,String... preconditions){
  return tx(c->{var run=current(c);if(preconditions.length>0&&preconditions[0]!=null&&!run.get("id").toString().equals(preconditions[0])||preconditions.length>1&&preconditions[1]!=null&&!run.get("epoch").toString().equals(preconditions[1]))throw new Conflict("Control belongs to a different run or epoch");
   String key=body!=null&&a!=null&&a.key()!=null&&!a.key().isEmpty()&&Set.of("hold","resume").contains(action)?a.key():null;
   if(key!=null){if(key.length()>128)throw new IllegalArgumentException("Idempotency-Key length must be 1..128");var old=one(c,"SELECT action,request,response FROM control_receipts WHERE run_id=? AND actor=? AND idempotency_key=?",run.get("id"),a.actor(),key);if(old!=null){if(!action.equals(old.get("action"))||!body.equals(json(old.get("request"))))throw new Conflict("Idempotency key already used with a different control");accepted(c,run,a,null);return Json.M.convertValue(old.get("response"),new com.fasterxml.jackson.core.type.TypeReference<Map<String,Object>>(){});}}
   switch(action){
   case "reset"->{if(expected==null||!run.get("id").toString().equals(expected))throw new Conflict("Reset confirmation does not match the current run");if(run.get("mode").equals("helics"))throw new Conflict("Finalize federation and allocate new run/epoch; live reset forbidden");var next=Scenario.normalize(scenario==null?json(run.get("scenario")):json(scenario));sql(c,"UPDATE runs SET current=false WHERE id=?",run.get("id"));sql(c,"INSERT INTO runs(id,epoch,mode,scenario) VALUES (?,?,?,?::jsonb)",UUID.randomUUID(),UUID.randomUUID(),settings.mode,Json.write(next));}
   case "hold","resume"->{if(!Set.of("running","held").contains(run.get("state")))throw new Conflict("Cannot resume failed, stalled or finalized run");sql(c,"UPDATE runs SET state=?,anchor=clock_timestamp() WHERE id=?",action.equals("hold")?"held":"running",run.get("id"));}
   case "speed"->{if(!run.get("mode").equals("standalone")||!Set.of(1,5,20,60).contains(speed))throw new Conflict("Only standalone speeds 1, 5, 20, 60 are supported");sql(c,"UPDATE runs SET speed=?,anchor=clock_timestamp() WHERE id=?",speed,run.get("id"));}
   case "finalize"->{if(run.get("mode").equals("helics")&&one(c,"SELECT 1 FROM manufacturing_adapter_sessions WHERE run_id=? AND epoch=? AND NOT native_pending AND native_state='executing'",run.get("id"),run.get("epoch"))==null)throw new Conflict("Native initialization, time request or receive processing is unsettled");if(outstanding(c,run))throw new Conflict("Hold and settle current-time work before finalizing");if(run.get("mode").equals("helics")){sql(c,"UPDATE manufacturing_adapter_sessions SET native_pending=true,native_state='finalizing' WHERE run_id=? AND epoch=?",run.get("id"),run.get("epoch"));sql(c,"UPDATE runs SET state='finalizing' WHERE id=?",run.get("id"));}else sql(c,"UPDATE runs SET state='finalized' WHERE id=?",run.get("id"));}
   default->throw new Conflict("Unknown control");
  }accepted(c,run,a,null);var response=status(c);if(key!=null)sql(c,"INSERT INTO control_receipts(run_id,actor,idempotency_key,action,request,response) VALUES (?,?,?,?,?::jsonb,?::jsonb)",run.get("id"),a.actor(),key,action,Json.write(body),Json.write(response));return response;});
 }
 void stall(String reason,Object epoch){tx(c->{if(!Boolean.TRUE.equals(one(c,"SELECT pg_try_advisory_xact_lock(8192102) held").get("held")))return null;var run=current(c);if(!run.get("epoch").equals(epoch)||Set.of("failed","stalled","finalized").contains(run.get("state")))return null;sql(c,"UPDATE runs SET state='stalled',error=? WHERE id=?",cut(reason,1000),run.get("id"));return null;});}
 String ingest(JsonNode event,String endpoint){if(!event.path("type").asText("sample.completed.v1").equals("sample.completed.v1"))return Production.ingest(this,event,endpoint);Policy.envelope(event);return tx(c->{var run=current(c);if(!run.get("id").toString().equals(event.path("run_id").asText())||!run.get("epoch").toString().equals(event.path("epoch").asText()))return "fenced";var peer=settings.peers.path(event.path("boundary").asText());if(!peer.path("source").asText().equals(event.path("source").asText())||!peer.path("endpoint").asText().equals(endpoint)||!event.path("destination").asText().equals("manufacturing")||!event.path("federation_id").asText().equals(settings.federation))throw new Conflict("Boundary owner/routing mismatch");var id=Policy.uuid(event.get("event_id"));if(one(c,"SELECT 1 FROM inbox WHERE event_id=?",id)!=null)return "duplicate";double due=event.path("effective_time").doubleValue();if(due<number(run,"granted"))throw new Conflict("Late event cannot change committed history");sql(c,"INSERT INTO inbox(event_id,run_id,epoch) VALUES (?,?,?)",id,run.get("id"),run.get("epoch"));sql(c,"INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (?,?,?,?,?,?,?::jsonb)",UUID.randomUUID(),run.get("id"),run.get("epoch"),"boundary:"+id,run.get("blocked_reason")==null?due:Math.max(due,number(run,"granted")+settings.quantum),due,Json.write(event.get("payload")));return "accepted";});}
 void seed(){Production.seed(this);}
 static UUID uuid5(UUID ns,String name){try{var bytes=java.nio.ByteBuffer.allocate(16).putLong(ns.getMostSignificantBits()).putLong(ns.getLeastSignificantBits()).array();var d=MessageDigest.getInstance("SHA-1");d.update(bytes);byte[] h=d.digest(name.getBytes(StandardCharsets.UTF_8));h[6]=(byte)((h[6]&15)|80);h[8]=(byte)((h[8]&63)|128);var b=java.nio.ByteBuffer.wrap(h);return new UUID(b.getLong(),b.getLong());}catch(Exception e){throw new IllegalStateException(e);}}
}
