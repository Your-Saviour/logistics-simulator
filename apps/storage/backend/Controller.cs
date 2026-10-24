using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
using Npgsql;
namespace Storage;
internal sealed class NativeFinalizationPending : Exception { }
public sealed class Adapter(Ledger ledger,Settings settings,JsonObject run)
{
    readonly HttpClient http=new() { BaseAddress=new Uri(settings.AdapterUrl.TrimEnd('/')+"/"),Timeout=TimeSpan.FromSeconds(5) };
    readonly Guid session=Guid.NewGuid();
    public void Begin() { ledger.Db.Transaction(u=> { var r=u.Run(); if(Ledger.Id(r)!=Ledger.Id(run)||Ledger.Id(r,"epoch")!=Ledger.Id(run,"epoch")) throw new Conflict("Stale adapter owner"); if(u.Query("SELECT 1 FROM storage_adapter_sessions WHERE run_id=@p0",Ledger.Id(r)).Count>0) throw new Conflict("Native session cannot resume; coordinate a new federation epoch"); u.Exec("INSERT INTO storage_adapter_sessions(run_id,epoch,session_id) VALUES (@p0,@p1,@p2)",Ledger.Id(r),Ledger.Id(r,"epoch"),session); return true; }); }
    public async Task<JsonObject> Command(string operation,JsonObject payload,string? key=null) {
        key??=Guid.NewGuid().ToString(); var record=ledger.Db.Transaction(u=> { var r=u.Run(); if(Ledger.Id(r)!=Ledger.Id(run)||Ledger.Id(r,"epoch")!=Ledger.Id(run,"epoch")) throw new Conflict("Stale controller session");
            if((r["state"]!.ToString() is "finalizing" or "finalized") && operation!="finalize") throw new NativeFinalizationPending();
            var old=u.Query("SELECT * FROM storage_adapter_operations WHERE session_id=@p0 AND operation_key=@p1",session,key).FirstOrDefault(); if(old is not null) return old;
            if(operation=="poll") u.Exec("UPDATE storage_adapter_sessions SET native_pending=true,native_state='polling' WHERE session_id=@p0",session);
            var id=Guid.NewGuid(); var command=new JsonObject {["version"]="1.0",["request_id"]=id.ToString(),["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["session_id"]=session.ToString(),["operation"]=operation,["payload"]=payload.DeepClone()};
            return u.One("INSERT INTO storage_adapter_operations(request_id,session_id,operation_key,request) VALUES (@p0,@p1,@p2,@p3) RETURNING *",id,session,key,command);
        });
        if(record["response"] is JsonObject done) return done;
        Exception? failure=null;
        for(int attempt=0;attempt<3;attempt++) { try { using var request=new HttpRequestMessage(HttpMethod.Post,"v1/commands") { Content=new StringContent(record["request"]!.ToJsonString(),Encoding.UTF8,"application/json") }; request.Headers.Authorization=new AuthenticationHeaderValue("Bearer",settings.AdapterToken);
                using var response=await http.SendAsync(request); if(!response.IsSuccessStatusCode) { if((int)response.StatusCode<500) throw new Conflict("Adapter rejected operation: "+await response.Content.ReadAsStringAsync()); throw new HttpRequestException("Adapter unavailable"); }
                var body=JsonNode.Parse(await response.Content.ReadAsStringAsync())!.AsObject(); if(body["version"]?.ToString()!="1.0"||body["request_id"]?.ToString()!=record["request_id"]!.ToString()) throw new Conflict("Adapter response identity mismatch"); var result=body["result"]!.AsObject();
                ledger.Db.Transaction(u=> { u.Run(); u.Exec("UPDATE storage_adapter_operations SET response=@p0 WHERE request_id=@p1",result,Ledger.Id(record,"request_id")); return true; }); return result;
            } catch(Exception e) when(e is HttpRequestException or TaskCanceledException) { failure=e; await Task.Delay(200); }
        } throw new Conflict("Adapter lost; new coordinated epoch required: "+failure?.Message);
    }
    public void PollSettled(JsonObject poll) {
        // Grant and inbox transactions, followed by native receive acknowledgement,
        // have completed before this barrier can be cleared. A failed poll/ACK
        // leaves the pre-send intent pending and rejects concurrent finalization.
        ledger.Db.Transaction(u=> { var r=u.Run(); if(Ledger.Id(r)!=Ledger.Id(run)||Ledger.Id(r,"epoch")!=Ledger.Id(run,"epoch")) throw new Conflict("Stale native poll session");
            var state=Rules.Text(poll["state"]); var pending=poll["pending"]?.GetValue<bool>()??true;
            u.Exec("UPDATE storage_adapter_sessions SET native_pending=@p0,native_state=@p1 WHERE session_id=@p2",pending||state!="executing",state,session); return true;
        });
    }
    public void CompleteFinalization() {
        ledger.Db.Transaction(u=> {
            var r=u.Run();
            if(Ledger.Id(r)!=Ledger.Id(run)||Ledger.Id(r,"epoch")!=Ledger.Id(run,"epoch")||r["state"]!.ToString()!="finalizing") throw new Conflict("Stale native finalization acknowledgement");
            if(u.Query("SELECT 1 FROM storage_adapter_sessions WHERE run_id=@p0 AND epoch=@p1 AND session_id=@p2 AND native_pending AND native_state='finalizing'",Ledger.Id(r),Ledger.Id(r,"epoch"),session).Count==0) throw new Conflict("Native finalization session is no longer current");
            u.Exec("UPDATE storage_adapter_sessions SET native_pending=false,native_state='finalized' WHERE run_id=@p0 AND epoch=@p1 AND session_id=@p2",Ledger.Id(r),Ledger.Id(r,"epoch"),session);
            u.Exec("UPDATE runs SET state='finalized' WHERE id=@p0 AND epoch=@p1",Ledger.Id(r),Ledger.Id(r,"epoch"));
            return true;
        });
    }
    public async Task Settle(JsonObject current) {
        var rows=ledger.Db.Transaction(u=> { var r=u.Run(); return u.Query("SELECT * FROM boundary_outbox WHERE run_id=@p0 AND sent_at IS NULL ORDER BY id",Ledger.Id(r)); });
        foreach(var row in rows) { var sample=row["envelope"]!.AsObject(); foreach(var output in settings.Outputs) {
                var destination=Rules.Text(output!["destination"]); var boundary=Rules.Text(output["boundary"]); var endpoint=Rules.Text(output["endpoint"]); var eventId=Ledger.Id(row); var job=Rules.Text(sample["job_id"]);
                var envelope=new JsonObject {["schema_version"]="1.0",["type"]="sample.completed.v1",["event_id"]=eventId.ToString(),["federation_id"]=settings.Federation,["run_id"]=current["id"]!.DeepClone(),["epoch"]=current["epoch"]!.DeepClone(),["correlation_id"]=job,["causation_id"]=job,["aggregate_id"]=job,["aggregate_version"]=1,["source"]="storage",["destination"]=destination,["boundary"]=boundary,["effective_time"]=Ledger.Num(current,"granted")+settings.Quantum,["wall_time"]=DateTimeOffset.UtcNow.ToString("O"),["quantity_unit"]="item",["payload"]=new JsonObject {["quantity"]=sample["quantity"]!.DeepClone()} };
                await Command("publish",new JsonObject {["endpoint"]=endpoint,["envelope"]=envelope},$"publish:{eventId}:{endpoint}");
            }
            ledger.Db.Transaction(u=> { var r=u.Run(); if(Ledger.Id(r)!=Ledger.Id(current)) throw new Conflict("Stale output epoch"); u.Exec("UPDATE boundary_outbox SET sent_at=clock_timestamp() WHERE id=@p0",Ledger.Id(row)); return true; });
        }
        var effects=ledger.Status()["effects"]!.DeepClone(); await Command("publish_value",new JsonObject {["value"]=effects,["unit"]="item"},"value:"+effects);
    }
}
public sealed class Controller(Ledger ledger,Settings settings,ILogger<Controller> logger): BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stop) {
        await Task.Yield();
        while(!stop.IsCancellationRequested) {
        Guid? epoch=null; bool owned=false; Adapter? adapter=null;
        try {
            using(var lease=ledger.Db.ConnectLease()) {
                var leaseUnit=new Unit(lease); if(!leaseUnit.One("SELECT pg_try_advisory_lock(8192102) AS held")["held"]!.GetValue<bool>()) throw new Conflict("Another controller owns this simulator"); owned=true;
                var run=ledger.Status()["run"]!.AsObject(); epoch=Ledger.Id(run,"epoch");
                if(settings.Mode=="helics" && run["state"]!.ToString() is "failed" or "stalled" or "finalized") throw new Conflict("Run requires operator recovery");
                bool initialized=settings.Mode=="standalone"; var waiting=Stopwatch.StartNew(); bool pending=false;
                if(settings.Mode=="helics") {
                    var configured=settings.Providers.Where(x=>x.Value!.ToString()=="helics").Select(x=>x.Key).Order(); if(!configured.SequenceEqual(settings.Peers.Select(x=>x.Key).Order())||settings.Outputs.Count==0) throw new Conflict("Connected mode needs explicit peer routes and outputs");
                    adapter=new Adapter(ledger,settings,run); adapter.Begin(); await adapter.Command("initialize",new JsonObject(),"initialize");
                }
                var timeout=double.Parse(Settings.Env("HELICS_TIMEOUT_SECONDS","60"),System.Globalization.CultureInfo.InvariantCulture);
                while(!stop.IsCancellationRequested) {
                    leaseUnit.Exec("SELECT 1"); run=ledger.Status()["run"]!.AsObject(); epoch=Ledger.Id(run,"epoch"); ledger.Heartbeat("controller");
                    if(run["state"]!.ToString() is "failed" or "stalled" or "finalized") {
                        if(settings.Mode=="standalone") { await Task.Delay(100,stop); continue; }
                        break;
                    }
                    if(run["state"]!.ToString()=="finalizing") {
                        if(adapter is null) throw new Conflict("Native finalization requires its owning adapter session");
                        var result=await adapter.Command("finalize",new JsonObject(),"finalize");
                        if(result["state"]?.ToString()!="finalized") throw new Conflict("Adapter did not acknowledge finalization");
                        adapter.CompleteFinalization();
                        break;
                    }
                    try {
                        if(adapter is not null) {
                            if((!initialized||pending)&&waiting.Elapsed.TotalSeconds>timeout) throw new Conflict("Native initialization/time grant timed out; synthetic fallback forbidden");
                            var poll=await adapter.Command("poll",new JsonObject()); var state=poll["state"]?.ToString();
                            if(state is "stalled" or "finalized" or "failed") throw new Conflict("Adapter native state lost: "+state);
                            initialized=state=="executing"; pending=poll["pending"]?.GetValue<bool>()??throw new Validation("Adapter pending flag required");
                            if(!initialized) { adapter.PollSettled(poll); await Task.Delay(50,stop); continue; }
                            var grant=Rules.Number(poll["granted"]); if(grant<Ledger.Num(run,"granted")||grant>1e20) throw new Conflict("Native grant reversed or federation ended unexpectedly");
                            if(grant>Ledger.Num(run,"granted")) ledger.Grant(grant,epoch.Value);
                            var ack=new JsonArray(); foreach(var message in poll["messages"]!.AsArray()) { var envelope=message!["envelope"]!.AsObject(); ledger.Ingest(envelope,Rules.Text(message["source"])); ack.Add(envelope["event_id"]!.DeepClone()); }
                            if(ack.Count>0) await adapter.Command("receive_ack",new JsonObject {["event_ids"]=ack});
                            adapter.PollSettled(poll);
                            run=ledger.Status()["run"]!.AsObject(); if(!pending) await adapter.Settle(run);
                        }
                    } catch(NativeFinalizationPending) { continue; }
                    if(run["state"]!.ToString()=="held") { await Task.Delay(100,stop); continue; }
                    if(Settings.Env("AUTONOMOUS_SAMPLE","true").Equals("true",StringComparison.OrdinalIgnoreCase)) { try { ledger.Seed(); } catch(Conflict) when(settings.Mode=="standalone") { } }
                    var target=Ledger.Num(run,"granted")+settings.Quantum;
                    if(adapter is not null&&!pending&&ledger.Prepare(target,epoch.Value)) { await adapter.Command("request_time",new JsonObject {["target"]=target,["committed"]=Ledger.Num(run,"granted"),["pending_work"]=0,["pending_outputs"]=0}); pending=true; waiting.Restart(); }
                    else if(adapter is null&&(DateTimeOffset.UtcNow-DateTimeOffset.Parse(run["anchor"]!.ToString())).TotalSeconds*run["speed"]!.GetValue<int>()>=settings.Quantum&&ledger.Prepare(target,epoch.Value)) { try { ledger.Grant(target,epoch.Value); } catch(Conflict) { if(Ledger.Id(ledger.Status()["run"]!.AsObject(),"epoch")==epoch) throw; } }
                    await Task.Delay(50,stop);
                }
            }
        } catch(OperationCanceledException) when(stop.IsCancellationRequested) { if(owned&&settings.Mode=="helics") ledger.Stall("Connected controller stopped; coordinate new epoch",epoch); break; }
        catch(Exception error) when(settings.Mode=="standalone" && error is NpgsqlException or TimeoutException) {
            logger.LogWarning(error,"Controller database unavailable; retaining run while reacquiring lease");
            try { await Task.Delay(1000,stop); } catch(OperationCanceledException) when(stop.IsCancellationRequested) { break; }
            continue;
        }
        catch(Exception error) { logger.LogError(error,"Controller stalled; operator recovery required"); if(owned) ledger.Stall(error.Message,epoch); }
        break;
        }
    }
}
