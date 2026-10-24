package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
final class Adapter {
 final Store store;final Settings settings;final UUID session;final Object runId,epoch;
 final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
 Adapter(Store store,Settings settings,Map<String,Object> run){
  this.store=store;this.settings=settings;runId=run.get("id");epoch=run.get("epoch");
  if(settings.get("HELICS_ADAPTER_URL","").isEmpty()||settings.get("HELICS_ADAPTER_TOKEN","").isEmpty())throw new Store.Conflict("Connected mode requires authenticated department adapter");
  session=store.tx(c->{var active=Store.current(c);if(!active.get("epoch").equals(epoch))throw new Store.Conflict("Stale controller epoch");if(Store.one(c,"SELECT 1 FROM manufacturing_adapter_sessions WHERE run_id=? AND epoch=?",runId,epoch)!=null)throw new Store.Conflict("Adapter/native session restart requires coordinated new epoch");var id=UUID.randomUUID();Store.sql(c,"INSERT INTO manufacturing_adapter_sessions(run_id,epoch,session_id) VALUES (?,?,?)",runId,epoch,id);return id;});
 }
 JsonNode call(String operation,Object payload)throws Exception{return call(UUID.randomUUID(),operation,payload);}
 JsonNode call(UUID id,String operation,Object payload)throws Exception{
  var body=Map.of("version","1.0","request_id",id,"run_id",runId,"epoch",epoch,"session_id",session,"operation",operation,"payload",payload);String request=Json.write(body);
  JsonNode previous=store.tx(c->{var active=Store.current(c);if(!active.get("epoch").equals(epoch))throw new Store.Conflict("Stale controller epoch");var old=Store.one(c,"SELECT * FROM manufacturing_adapter_operations WHERE request_id=?",id);if(old!=null){if(!old.get("request").equals(Json.parse(request)))throw new Store.Conflict("Conflicting adapter operation replay");return old.get("response")==null?null:Store.json(old.get("response"));}Store.sql(c,"INSERT INTO manufacturing_adapter_operations(request_id,run_id,epoch,session_id,operation,request) VALUES (?,?,?,?,?,?::jsonb)",id,runId,epoch,session,operation,request);return null;});
  if(previous!=null)return previous;
  Exception failure=null;
  for(int attempt=0;attempt<3;attempt++)try{
   var http=HttpRequest.newBuilder(URI.create(settings.get("HELICS_ADAPTER_URL","")+"/v1/commands")).timeout(Duration.ofSeconds(5)).header("Authorization","Bearer "+settings.get("HELICS_ADAPTER_TOKEN","")).header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(request)).build();
   var reply=client.send(http,HttpResponse.BodyHandlers.ofString());if(reply.statusCode()==503)throw new java.io.IOException("Adapter unavailable");if(reply.statusCode()!=200)throw new Store.Conflict("Adapter rejected operation: "+reply.statusCode());var response=Json.parse(reply.body());if(!response.path("version").asText().equals("1.0")||!response.path("request_id").asText().equals(id.toString())||!response.path("result").isObject())throw new Store.Conflict("Invalid adapter response");var result=response.get("result");store.tx(c->{var active=Store.current(c);if(!active.get("epoch").equals(epoch))throw new Store.Conflict("Stale controller epoch");Store.sql(c,"UPDATE manufacturing_adapter_operations SET response=?::jsonb WHERE request_id=?",Json.write(result),id);return null;});return result;
  }catch(java.io.IOException e){failure=e;Thread.sleep(250);}throw failure;
 }
}
