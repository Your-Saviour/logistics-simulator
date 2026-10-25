package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.*;
import java.util.*;
final class Controller {
 final Store store;final Settings settings;
 Controller(Store store,Settings settings){this.store=store;this.settings=settings;}
 boolean grantLocal(double target,Object epoch){
  try{store.grant(target,epoch,null);return true;}
  catch(Store.Conflict error){if(!store.run().get("epoch").equals(epoch))return false;throw error;}
 }
 void run(){
  boolean connected=settings.mode.equals("helics");
  while(!Thread.currentThread().isInterrupted()){
   Object epoch=null;boolean owned=false;Connection lease=null;Adapter adapter=null;Exception failure=null;OtGateway ot=null;UUID otOwner=UUID.randomUUID();
   try{
    lease=store.connect();lease.setAutoCommit(true);
    if(!Boolean.TRUE.equals(Store.one(lease,"SELECT pg_try_advisory_lock(8192102) held").get("held")))throw new Store.Conflict("Another controller owns manufacturing");
    owned=true;
    var run=store.run();epoch=run.get("epoch");
    if(connected&&Set.of("failed","stalled","finalized").contains(run.get("state")))throw new Store.Conflict("Run requires recovery");
    if(connected){
     if(Store.number(run,"granted")!=0||Store.number(run,"requested")!=0||Store.number(run,"committed")!=0)throw new Store.Conflict("Live federation restart requires coordinated new run/epoch");
     var required=new HashSet<String>();settings.providers.fields().forEachRemaining(e->{if(e.getValue().asText().equals("helics"))required.add(e.getKey());});
     var configured=new HashSet<String>();settings.peers.fieldNames().forEachRemaining(configured::add);
     if(!required.equals(configured)||settings.federation.isEmpty()||!settings.outputs.isArray()||settings.outputs.isEmpty())throw new Store.Conflict("Connected mode requires explicit peer routes, outputs and federation identity");
     adapter=new Adapter(store,settings,run);adapter.call("initialize",Map.of());
    }
    if(Ot.enabled(run)&&!Set.of("failed","stalled","finalized").contains(run.get("state")))ot=new OtGateway(store,otOwner);
    boolean initialized=!connected,pending=connected;long waitingSince=System.nanoTime();
    double timeout=Double.parseDouble(settings.get("HELICS_TIMEOUT_SECONDS","60"));
    while(!Thread.currentThread().isInterrupted()){
     Store.one(lease,"SELECT 1");run=store.run();
     if(!run.get("epoch").equals(epoch)&&connected)throw new Store.Conflict("Controller epoch changed");
     if(!connected)epoch=run.get("epoch");
     if(!connected&&Ot.enabled(run)&&!Set.of("failed","stalled","finalized").contains(run.get("state"))&&(ot==null||!ot.epoch.equals(epoch)))ot=new OtGateway(store,otOwner);
     if(!Ot.enabled(run))ot=null;
     if(Set.of("failed","stalled","finalized").contains(run.get("state"))){
      if(!connected){store.heartbeat("controller","");Thread.sleep(100);continue;}
      break;
     }
     if(run.get("state").equals("finalizing")){if(finish(ot,adapter,epoch)){if(connected)break;continue;}Thread.sleep(100);continue;}
     store.heartbeat("controller","");
     if(adapter!=null){
      if(pending&&(System.nanoTime()-waitingSince)/1e9>timeout)throw new Store.Conflict("HELICS initialization/grant timed out; federation recovery required");
      if(!store.beginPoll(epoch,adapter.session))continue;
      var snapshot=adapter.call("poll",Map.of());String state=snapshot.path("state").asText();
      if(Set.of("stalled","failed","finalized").contains(state))throw new Store.Conflict("Native adapter no longer executing: "+state);
      initialized=state.equals("executing");pending=!initialized||snapshot.path("pending").asBoolean();
      if(initialized&&!pending){
       double granted=Policy.time(snapshot.get("granted"));if(granted>1e20)throw new Store.Conflict("Federation ended unexpectedly");
       String blocked=null;
       if(settings.providers.path("power").asText().equals("helics")){
        String target=settings.peers.path("power").path("value_target").asText("external-power/available_power_kw");
        var value=snapshot.path("values").path(target);double power=value.isNumber()?value.doubleValue():0;
        if(!(power>0&&power<1e12))blocked="External power unavailable; production deferred";
       }
       store.grant(granted,epoch,blocked);
       var ids=new ArrayList<String>();
       for(var input:snapshot.path("messages")){var event=input.path("envelope");store.ingest(event,input.path("source").asText());ids.add(event.path("event_id").asText());}
       if(!ids.isEmpty())adapter.call("receive_ack",Map.of("event_ids",ids));
       store.nativeSettled(epoch,adapter.session);
       publish(adapter);run=store.run();
      }
     }
     if(run.get("state").equals("finalizing")){if(finish(ot,adapter,epoch)){if(connected)break;continue;}Thread.sleep(100);continue;}
     if(ot!=null){ot.settle();run=store.run();}
     if(connected&&run.get("state").equals("finalized"))break;
     if(!initialized||run.get("state").equals("held")){Thread.sleep(100);continue;}
     if(settings.get("AUTONOMOUS_PRODUCTION",settings.get("AUTONOMOUS_SAMPLE","true")).equalsIgnoreCase("true"))store.seed();
     double target=Store.number(run,"granted")+settings.quantum;
     if(adapter!=null&&!pending){
      if(store.prepare(target,epoch)){adapter.call("request_time",Map.of("target",target,"committed",run.get("granted"),"pending_work",0,"pending_outputs",0));pending=true;waitingSince=System.nanoTime();}
     }else if(adapter==null){
      double elapsed=Duration.between(Instant.parse(run.get("anchor").toString()),Instant.now()).toNanos()/1e9;
      if(elapsed*Store.number(run,"speed")>=settings.quantum&&store.prepare(target,epoch))grantLocal(target,epoch);
     }
     Thread.sleep(50);
    }
   }catch(Exception error){failure=error;}
   finally{releaseLease(lease,owned);}
   if(failure==null){
    if(connected&&Thread.currentThread().isInterrupted())failure=new InterruptedException("Connected controller interrupted");
    else return;
   }
   boolean interrupted=failure instanceof InterruptedException||Thread.currentThread().isInterrupted();
   if(interrupted&&!connected){Thread.currentThread().interrupt();return;}
   if(!connected&&(failure instanceof SQLException||failure instanceof Store.Unavailable)){
    // SQL remains the local clock. Losing the session lease never changes its run.
    System.err.println("Manufacturing local controller database unavailable; reacquiring lease");
    try{Thread.sleep(250);}catch(InterruptedException stopped){Thread.currentThread().interrupt();return;}
    continue;
   }
   System.err.println("Manufacturing controller stopped: "+failure.getMessage());
   // A connected participant cannot replace a lost native session in this epoch.
   if(interrupted)Thread.interrupted();
   try{if(owned&&epoch!=null)store.stall(failure.toString(),epoch);}
   catch(Exception unavailable){System.err.println("Controller stall persistence unavailable");}
   finally{if(interrupted)Thread.currentThread().interrupt();}
   return;
  }
 }
 boolean finish(OtGateway ot,Adapter adapter,Object epoch)throws Exception{
  if(ot!=null){if(!ot.settle()||!Ot.stopped(store))return false;}
  if(adapter!=null)finalizeNative(adapter);else Ot.finalizeLocal(store,epoch);return true;
 }
 void finalizeNative(Adapter adapter)throws Exception{
  if(adapter==null)throw new Store.Conflict("Native finalization requires the owning adapter session");
  UUID operation=Store.uuid5(adapter.session,"finalize");
  var reply=adapter.call(operation,"finalize",Map.of());
  if(!reply.path("state").asText().equals("finalized"))throw new Store.Conflict("Adapter did not acknowledge native finalization");
  store.nativeFinalized(adapter.runId,adapter.epoch,adapter.session);
 }
 private static void releaseLease(Connection lease,boolean owned){
  if(lease==null)return;
  try{if(owned)Store.one(lease,"SELECT pg_advisory_unlock(8192102)");}
  catch(Exception unavailable){/* A dead connection has already lost its server lease. */}
  finally{try{lease.close();}catch(SQLException unavailable){System.err.println("Controller lease close unavailable");}}
 }
 void publish(Adapter adapter)throws Exception{
  var run=store.run();var outputs=store.tx(c->{var active=Store.current(c);Custody.recover(c,active);OutputCustody.recover(c,active);return Store.rows(c,"SELECT * FROM boundary_outbox WHERE run_id=? AND sent_at IS NULL ORDER BY id",active.get("id"));});
  for(var row:outputs){JsonNode sample=Store.json(row.get("envelope"));
   if(sample.has("type")){boolean routed=false;for(var output:settings.outputs)if(output.path("destination").asText().equals(sample.path("destination").asText())&&output.path("boundary").asText().equals(sample.path("boundary").asText()))routed=true;if(!routed)throw new Store.Conflict("No HELICS route for committed production output");}
   for(var output:settings.outputs){
    if(sample.has("type")){if(!output.path("destination").asText().equals(sample.path("destination").asText())||!output.path("boundary").asText().equals(sample.path("boundary").asText()))continue;UUID operation=Store.uuid5(Store.uuid(row.get("id")),"publish:"+output.path("endpoint").asText());adapter.call(operation,"publish",Map.of("endpoint",output.path("endpoint").asText(),"envelope",sample));continue;}
    // Operation and envelope identities remain stable across lost HTTP replies.
    String route=output.path("endpoint").asText();UUID operation=Store.uuid5(Store.uuid(row.get("id")),"publish:"+route);
    var envelope=new LinkedHashMap<String,Object>();envelope.put("schema_version","1.0");envelope.put("type","sample.completed.v1");envelope.put("event_id",row.get("id"));envelope.put("federation_id",settings.federation);envelope.put("run_id",run.get("id"));envelope.put("epoch",run.get("epoch"));for(String key:List.of("correlation_id","causation_id","aggregate_id"))envelope.put(key,sample.path("job_id").asText());envelope.put("aggregate_version",1);envelope.put("source","manufacturing");envelope.put("destination",output.path("destination").asText());envelope.put("boundary",output.path("boundary").asText());envelope.put("effective_time",Store.number(run,"granted")+settings.quantum);envelope.put("quantity_unit","item");envelope.put("payload",Map.of("quantity",sample.path("quantity").asInt()));
    adapter.call(operation,"publish",Map.of("endpoint",route,"envelope",envelope));
   }
   store.tx(c->{var active=Store.current(c);if(!active.get("epoch").equals(run.get("epoch")))throw new Store.Conflict("Stale controller epoch");Store.sql(c,"UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE id=? AND run_id=?",row.get("id"),run.get("id"));return null;});
  }
  adapter.call("publish_value",Map.of("value",store.status().get("effects"),"unit","item"));
 }
}
