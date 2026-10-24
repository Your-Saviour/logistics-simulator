package simu.manufacturing;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import java.util.*;
@RestController
final class Api {
 final Settings settings;final Store store;
 Api(Settings settings,Store store){this.settings=settings;this.store=store;}
 static class HttpError extends RuntimeException{final int status;HttpError(int s,String m){super(m);status=s;}}
 @RequestMapping(value="/api/**",produces=MediaType.APPLICATION_JSON_VALUE)
 ResponseEntity<String> handle(HttpServletRequest request,@RequestBody(required=false)String body){
  UUID requestId=UUID.randomUUID();String path=request.getRequestURI();String method=request.getMethod();boolean command=method.equals("POST");int status=200;Object result=null;Store.Audit audit=new Store.Audit("anonymous","anonymous",requestId,method+" "+path,request.getHeader("Idempotency-Key"),request.getRemoteAddr(),null);
  try{
   if(command){var scope=store.run().get("id");audit=new Store.Audit(audit.actor(),audit.role(),requestId,audit.action(),audit.key(),audit.peer(),scope);}
   if(path.equals("/api/health/live")&&method.equals("GET"))result=Map.of("application","manufacturing","alive",true);
   else if(path.equals("/api/health/ready")&&method.equals("GET")){
    var state=store.status();var roles=new HashSet<String>();for(var heartbeat:(List<?>)state.get("heartbeats")){var h=(Map<?,?>)heartbeat;if(Boolean.TRUE.equals(h.get("healthy")))roles.add(h.get("role").toString());}boolean broker=Messaging.ready(settings.amqp);boolean ready=broker&&roles.containsAll(Set.of("worker","controller"))&&!Set.of("failed","stalled").contains(((Map<?,?>)state.get("run")).get("state"));status=ready?200:503;result=Map.of("application","manufacturing","database",true,"broker",broker,"ready",ready);
   }else{
    var account=settings.identify(request.getHeader("Authorization"));if(account==null)throw new HttpError(401,"Invalid username or password");
    audit=new Store.Audit(account.username(),account.role(),requestId,audit.action(),audit.key(),audit.peer(),audit.runId());
    String scope=path.equals("/api/audit")?"audit:read":command&&(path.equals("/api/jobs")||path.equals("/api/production/commands"))?"jobs:write":command&&path.startsWith("/api/control/")?"runs:control":"status:read";
    if(!account.scopes().contains(scope))throw new HttpError(403,"This identity cannot perform the requested action");
    if(method.equals("GET"))result=switch(path){
     case "/api/status"->{var value=store.status();value.put("identity",account.publicValue());value.put("application","manufacturing");value.put("providers",settings.providers);value.put("quantum",settings.quantum);var run=(Map<String,Object>)value.get("run");value.put("simulation_time",Scenario.instant(Store.json(run.get("scenario")),Store.number(run,"granted")).toOffsetDateTime().toString());yield value;}
     case "/api/projection"->Projection.read(store);
     case "/api/production"->Production.snapshot(store);
     case "/api/sources"->List.of();case "/api/audit"->store.audit();default->throw new HttpError(404,"Not found");
    };
    else if(command&&path.equals("/api/production/commands")){result=Production.command(store,request.getHeader("Idempotency-Key"),Json.parse(body==null?"":body),audit);}
    else if(command&&path.equals("/api/jobs")){
     var json=Policy.job(Json.parse(body==null?"":body));String key=request.getHeader("Idempotency-Key");if(key==null||key.isEmpty()||key.length()>128)throw new IllegalArgumentException("Idempotency-Key of 1..128 characters required");if(key.startsWith("production:")||key.startsWith("synthetic:")||key.startsWith("boundary:")||key.startsWith("synthetic-sample:"))throw new Store.Conflict("This idempotency key namespace is reserved for internal providers");result=store.schedule(key,json.get("due_at").doubleValue(),json.get("quantity").intValue(),audit,null);
    }else if(command&&path.startsWith("/api/control/")){
     var json=Json.parse(body==null?"":body);Policy.fields(json,"speed","confirm_run_id","scenario","run_id","epoch");String action=path.substring("/api/control/".length());int speed=json.has("speed")?Policy.integer(json.get("speed"),Integer.MIN_VALUE,Integer.MAX_VALUE):1;String confirm=json.hasNonNull("confirm_run_id")?Policy.uuid(json.get("confirm_run_id")).toString():null;
     if(action.equals("reset")&&confirm==null)throw new Store.Conflict("Reset requires the current run ID as confirmation");if(json.hasNonNull("scenario")&&!action.equals("reset"))throw new Store.Conflict("Scenario changes require a confirmed new run");var scenario=json.hasNonNull("scenario")?Scenario.normalize(json.get("scenario")):null;result=store.controlRequest(action,speed,confirm,audit,scenario,json,json.hasNonNull("run_id")?Policy.uuid(json.get("run_id")).toString():null,json.hasNonNull("epoch")?Policy.uuid(json.get("epoch")).toString():null);
    }else throw new HttpError(404,"Not found");
   }
  }catch(HttpError e){status=e.status;result=Map.of("detail",e.getMessage());}catch(Store.Conflict e){status=409;result=Map.of("detail",e.getMessage());}catch(IllegalArgumentException|java.time.DateTimeException e){status=422;result=Map.of("detail",e.getMessage()==null?"Invalid command":e.getMessage());}catch(Store.Unavailable e){status=503;result=Map.of("detail","Database unavailable; retry with the same idempotency key");}catch(Exception e){status=500;result=Map.of("detail","Internal server error");System.err.println("Manufacturing API error "+requestId+": "+e.getClass().getSimpleName());}
  if(command&&status>=400)try{store.rejected(audit,status);}catch(Store.Unavailable e){System.err.println("Rejected command audit unavailable request_id="+requestId+" status="+status);}
  var response=ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).header("X-Request-ID",requestId.toString());if(status==401)response.header("WWW-Authenticate","Basic realm=\"manufacturing\"");return response.body(Json.write(result));
 }
}
