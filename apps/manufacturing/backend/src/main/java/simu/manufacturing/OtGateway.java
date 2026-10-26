package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import static simu.manufacturing.Store.*;
/** One controller lease owns this client. Network calls never hold a business transaction. */
final class OtGateway {
 final Store store;final Object runId,epoch,session;
 final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
 final String base,token;long observed;
 OtGateway(Store store,UUID owner){this.store=store;var cell=Ot.acquire(store,owner);runId=cell.get("run_id");epoch=cell.get("epoch");session=cell.get("session_id");base=store.settings.get("OT_EQUIPMENT_URL","").replaceAll("/+$","");token=store.settings.get("OT_EQUIPMENT_TOKEN","");}
 HttpRequest.Builder request(String path){return HttpRequest.newBuilder(URI.create(base+path)).timeout(Duration.ofSeconds(15)).header("Authorization","Bearer "+token).header("Content-Type","application/json");}
 boolean settle()throws Exception{
  try{
   var op=Ot.next(store);
   if(op!=null){var body=json(op.get("request"));if(!body.path("epoch").asText().equals(epoch.toString()))return false;
    var response=client.send(request("/v1/commands").POST(HttpRequest.BodyPublishers.ofString(Json.write(body))).build(),HttpResponse.BodyHandlers.ofString());
    if(response.statusCode()==200)Ot.acknowledge(store,uuid(op.get("id")),Json.parse(response.body()));
    else if(response.statusCode()==422)Ot.rejected(store,uuid(op.get("id")),Json.parse(response.body()).path("detail").asText("Equipment rejected command"));
    else if(response.statusCode()==409)throw new Conflict("OT equipment requires reconciliation: "+Json.parse(response.body()).path("detail").asText());
    else if(response.statusCode()==503)throw new java.io.IOException("OT equipment unavailable");
    else throw new Conflict("OT equipment protocol/authentication failed: "+response.statusCode());
    return true;
   }
   if(System.nanoTime()-observed>1_000_000_000L){observe();observed=System.nanoTime();}
   return true;
  }catch(java.io.IOException error){failure("PLC observation disconnected".equals(error.getMessage())?"PLC connection unavailable; equipment gateway responding":"OT equipment gateway unavailable; PLC state unknown; awaiting the same durable operation");Thread.sleep(250);return false;}
  catch(Conflict error){if(!store.run().get("epoch").equals(epoch))return false;throw error;}
 }
 void failure(String reason){store.tx(c->{var run=current(c);if(run.get("id").equals(runId)&&run.get("epoch").equals(epoch))OtInsights.sourceLost(c,run,reason);return null;});}
 void observe()throws Exception{
  var reply=client.send(request("/v1/status").GET().build(),HttpResponse.BodyHandlers.ofString());if(reply.statusCode()!=200)throw new java.io.IOException("Equipment observation unavailable");var result=Json.parse(reply.body());
  if(result.path("recovery_required").asBoolean())throw new Conflict("OT equipment restarted or lost its PLC state; controlled recovery required");if(!result.path("connected").asBoolean())throw new java.io.IOException("PLC observation disconnected");var scope=result.path("scope");if(!result.path("version").asText().equals("1.0")||!scope.path("run_id").asText().equals(runId.toString())||!scope.path("epoch").asText().equals(epoch.toString())||!scope.path("session_id").asText().equals(session.toString()))throw new Conflict("Equipment observation scope mismatch");
  store.tx(c->{var run=current(c);if(!run.get("id").equals(runId)||!run.get("epoch").equals(epoch))return null;var cell=one(c,"SELECT * FROM ot_cells WHERE run_id=?",runId);if(!cell.get("session_id").equals(session)||Policy.time(result.get("simulation_time"))!=number(cell,"settled"))throw new Conflict("Unsettled equipment observation");OtInsights.sourceRestored(c,run);sql(c,"UPDATE ot_cells SET telemetry=?::jsonb,observed_at=clock_timestamp(),error=NULL WHERE run_id=?",Json.write(result),runId);return null;});
 }
}
