using System.Text.Json.Nodes;
namespace Storage;
public sealed record Audit(Guid RequestId,string Actor,string Role,string Action,string Key,string Peer,Guid? RunId=null);
public sealed class Ledger(Database database,Settings settings)
{
    public Database Db=database;
    public static Guid Id(JsonObject o,string key="id")=>Guid.Parse(o[key]!.ToString());
    public static double Num(JsonObject o,string key)=>o[key]!.GetValue<double>();
    public static void AuditRow(Unit u,Guid run,Audit? a,string outcome,int status,Guid? target=null) { if(a is null) return; u.Exec("INSERT INTO command_audit(id,run_id,actor,role,request_id,action,outcome,status_code,idempotency_key,peer,target_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7,@p8,@p9,@p10)",Guid.NewGuid(),run,a.Actor,a.Role,a.RequestId,a.Action,outcome,status,a.Key,a.Peer,target); }
    public JsonObject Status()=>Db.Transaction(Status);
    public static JsonObject Status(Unit u) { var run=u.Run(); var id=Id(run); return new JsonObject { ["run"]=run,["jobs"]=Array(u.Query("SELECT * FROM jobs WHERE run_id=@p0 ORDER BY created_at DESC LIMIT 100",id)),["effects"]=u.One("SELECT COALESCE(sum(quantity),0) AS n FROM effects WHERE run_id=@p0",id)["n"]!.DeepClone(),["heartbeats"]=Array(u.Query("SELECT role,seen_at,detail,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats")),["pending_boundary_outputs"]=u.One("SELECT count(*) AS n FROM boundary_outbox WHERE run_id=@p0 AND sent_at IS NULL",id)["n"]!.DeepClone() }; }

    public static JsonArray Array(List<JsonObject> rows)=>new(rows.Cast<JsonNode?>().ToArray());
    public Guid Scope()=>Db.Transaction(u=>Id(u.Run()));
    public void Rejected(Audit a,int status)=>Db.Transaction(u=> { AuditRow(u,a.RunId??Id(u.Run()),a,"rejected",status); return true; });
    public JsonArray Audits()=>Db.Transaction(u=>Array(u.Query("SELECT * FROM command_audit ORDER BY recorded_at DESC,id DESC LIMIT 100")));
    public void Heartbeat(string role,string detail="")=>Db.Transaction(u=> { u.Exec("INSERT INTO heartbeats(role,detail) VALUES (@p0,@p1) ON CONFLICT(role) DO UPDATE SET seen_at=clock_timestamp(),detail=EXCLUDED.detail",role,detail); return true; });
    public JsonObject Schedule(string key,double due,int quantity,Audit? audit=null,JsonObject? boundary=null)=>Db.Transaction(u=> {
        var run=u.Run(); var id=Id(run); var payload=new JsonObject {["quantity"]=quantity};
        if(string.IsNullOrEmpty(key)||key.Length>128||!double.IsFinite(due)||quantity<1||quantity>10000) throw new Validation("Valid key, due time and quantity required");
        if(boundary is not null&&(boundary["run_id"]!.ToString()!=id.ToString()||boundary["epoch"]!.ToString()!=run["epoch"]!.ToString())) throw new Conflict("Seeded input belongs to different epoch");
        var old=u.Query("SELECT * FROM jobs WHERE run_id=@p0 AND idempotency_key=@p1",id,key).FirstOrDefault();
        if(old is not null) { if(Num(old,"original_due_at")!=due||!JsonNode.DeepEquals(old["payload"],payload)||!JsonNode.DeepEquals(old["boundary_input"],boundary)) throw new Conflict("Idempotency key already used with a different command"); AuditRow(u,id,audit,"accepted",200,Id(old)); return old; }
        if(run["state"]!.ToString() is not ("running" or "held") ||due<Math.Max(Num(run,"granted"),Num(run,"requested"))+settings.Quantum) throw new Conflict("Schedule at least one quantum beyond granted/requested time in an active run");
        var job=u.One("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload,boundary_input) VALUES (@p0,@p1,@p2,@p3,@p4,@p4,@p5,@p6) RETURNING *",Guid.NewGuid(),id,Id(run,"epoch"),key,due,payload,boundary); AuditRow(u,id,audit,"accepted",200,Id(job)); return job;
    });
    public static bool Outstanding(Unit u,JsonObject r)=>u.One("SELECT EXISTS(SELECT 1 FROM jobs WHERE run_id=@p0 AND due_at<=@p1 AND status NOT IN ('completed','fenced')) OR EXISTS(SELECT 1 FROM boundary_outbox WHERE run_id=@p0 AND sent_at IS NULL) AS busy",Id(r),Num(r,"granted"))["busy"]!.GetValue<bool>();
    public JsonObject Control(string action,JsonObject body,Audit audit) {
        Rules.Fields(body,"speed","confirm_run_id","scenario","run_id","epoch"); var speed=body["speed"] is null?1:Rules.Integer(body["speed"],int.MinValue,int.MaxValue); var confirmation=body["confirm_run_id"] is null?(Guid?)null:Rules.Uuid(body["confirm_run_id"]); var scenario=body["scenario"] is null?null:new Scenario(body["scenario"]!.AsObject());
        if(scenario is not null&&action!="reset") throw new Conflict("Scenario changes require a confirmed new run");
        return Db.Transaction(u=> { var r=u.Run(); var id=Id(r); if(body["run_id"] is not null&&Rules.Uuid(body["run_id"])!=id||body["epoch"] is not null&&Rules.Uuid(body["epoch"])!=Id(r,"epoch")) throw new Conflict("Control belongs to a different run or epoch");
            var key=(action is "hold" or "resume")&&audit.Action.StartsWith("POST /api/control/")&&!string.IsNullOrEmpty(audit.Key)?audit.Key:null;
            if(key is not null) { if(key.Length>128) throw new Validation("Idempotency-Key length must be 1..128"); var old=u.Query("SELECT action,request,response FROM control_receipts WHERE run_id=@p0 AND actor=@p1 AND idempotency_key=@p2",id,audit.Actor,key).FirstOrDefault(); if(old is not null) { if(old["action"]!.ToString()!=action||!JsonNode.DeepEquals(old["request"],body)) throw new Conflict("Idempotency key already used with a different control"); AuditRow(u,id,audit,"accepted",200);return (JsonObject)old["response"]!.DeepClone(); } }
            switch(action) {
            case "reset":
                if(confirmation!=id) throw new Conflict("Reset requires the current run ID as confirmation");
                if(r["mode"]!.ToString()=="helics") throw new Conflict("Finalize federation and allocate new deployment run/epoch; live reset forbidden");
                u.Exec("UPDATE runs SET current=false WHERE id=@p0",id); u.Exec("INSERT INTO runs(id,epoch,mode,scenario) VALUES (@p0,@p1,@p2,@p3)",Guid.NewGuid(),Guid.NewGuid(),settings.Mode,scenario?.Body??r["scenario"]!); break;
            case "hold": case "resume": if(r["state"]!.ToString() is not ("running" or "held")) throw new Conflict("Cannot resume failed, stalled or finalized run"); u.Exec("UPDATE runs SET state=@p0,anchor=clock_timestamp() WHERE id=@p1",action=="hold"?"held":"running",id); break;
            case "speed": if(r["mode"]!.ToString()!="standalone"||!new[]{1,5,20,60}.Contains(speed)) throw new Conflict("Only standalone speeds 1,5,20,60 supported"); u.Exec("UPDATE runs SET speed=@p0,anchor=clock_timestamp() WHERE id=@p1",speed,id); break;
            case "finalize": if(Outstanding(u,r)) throw new Conflict("Hold and settle current-time work before finalizing");
                if(r["mode"]!.ToString()=="helics") {
                    if(u.Query("SELECT 1 FROM storage_adapter_sessions WHERE run_id=@p0 AND epoch=@p1 AND NOT native_pending AND native_state='executing'",id,Id(r,"epoch")).Count==0) throw new Conflict("Native initialization, request or receive is unsettled; hold and wait before finalizing");
                    u.Exec("UPDATE storage_adapter_sessions SET native_pending=true,native_state='finalizing' WHERE run_id=@p0 AND epoch=@p1",id,Id(r,"epoch"));
                    u.Exec("UPDATE runs SET state='finalizing' WHERE id=@p0 AND epoch=@p1",id,Id(r,"epoch"));
                } else u.Exec("UPDATE runs SET state='finalized' WHERE id=@p0",id);
                break;
            default: throw new Conflict("Unknown control");
        } AuditRow(u,id,audit,"accepted",200); var response=Status(u);if(key is not null)u.Exec("INSERT INTO control_receipts(run_id,actor,idempotency_key,action,request,response) VALUES (@p0,@p1,@p2,@p3,@p4,@p5)",id,audit.Actor,key,action,body,response);return response; });
    }
    public string Execute(Guid job)=>Db.Transaction(u=> { var r=u.Run(); var j=u.Query("SELECT * FROM jobs WHERE id=@p0 FOR UPDATE",job).FirstOrDefault();
        if(j is null||Id(j,"run_id")!=Id(r)||Id(j,"epoch")!=Id(r,"epoch")) return "fenced";
        var state=j["status"]!.ToString(); if(state=="completed") return "duplicate"; if(state=="dead") return "dead";
        if(r["state"]!.ToString()!="running"||Num(j,"due_at")>Num(r,"granted")||u.Query("SELECT 1 FROM heartbeats WHERE role='controller' AND seen_at>clock_timestamp()-interval '15 seconds'").Count==0||!u.One("SELECT retry_after<=clock_timestamp() AS ready FROM jobs WHERE id=@p0",job)["ready"]!.GetValue<bool>()) return "waiting";
        u.Exec("INSERT INTO inbox(event_id,run_id,epoch) VALUES (@p0,@p1,@p2) ON CONFLICT DO NOTHING",job,Id(r),Id(r,"epoch"));
        try {
        if(j["payload"]?["finished_custody"] is JsonObject) { FinishedCustody.Execute(u,r,settings,j);u.Exec("UPDATE jobs SET status='completed',error=NULL WHERE id=@p0",job);return "completed"; }
        if(j["payload"]?["custody"] is JsonObject) { StorageCustody.Execute(u,r,settings,j);u.Exec("UPDATE jobs SET status='completed',error=NULL WHERE id=@p0",job);return "completed"; }
        if(j["payload"]?["warehouse"] is JsonObject) { Warehouse.Execute(u,r,j,settings); u.Exec("UPDATE jobs SET status='completed',error=NULL WHERE id=@p0",job); return "completed"; }
        var quantity=j["payload"]!["quantity"]!.GetValue<int>(); u.Exec("INSERT INTO effects(job_id,run_id,quantity) VALUES (@p0,@p1,@p2)",job,Id(r),quantity); u.Exec("UPDATE jobs SET status='completed',error=NULL WHERE id=@p0",job);
        if(r["mode"]!.ToString()=="helics"&&!j["idempotency_key"]!.ToString().StartsWith("boundary:")) u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2)",Guid.NewGuid(),Id(r),new JsonObject {["job_id"]=job.ToString(),["quantity"]=quantity,["time"]=Num(r,"granted")}); return "completed";
        } catch(FleetWait wait) { Fleet.Defer(u,r,j,settings,wait);return "waiting"; }
    });
    public string Fail(Guid job,Exception error)=>Db.Transaction(u=> { var r=u.Run(); var j=u.Query("SELECT * FROM jobs WHERE id=@p0 FOR UPDATE",job).FirstOrDefault(); if(j is null||Id(j,"run_id")!=Id(r)||j["status"]!.ToString() is "completed" or "dead") return j?["status"]?.ToString()=="dead"?"dead":"fenced";
        var attempts=j["attempts"]!.GetValue<int>()+1; u.Exec("UPDATE jobs SET attempts=@p0,status=@p1,error=@p2,retry_after=clock_timestamp()+interval '2 seconds' WHERE id=@p3",attempts,attempts>=3?"dead":"pending",error.Message[..Math.Min(1000,error.Message.Length)],job);
        if(attempts>=3) u.Exec("UPDATE runs SET state='failed',error='Job retry limit exceeded' WHERE id=@p0",Id(r)); return attempts>=3?"dead":"retry"; });
    public List<JsonObject> Dispatchable()=>Db.Transaction(u=> { var r=u.Run(); if(r["state"]!.ToString()!="running") return [];
        foreach(var job in u.Query("SELECT id FROM jobs WHERE run_id=@p0 AND due_at<=@p1 AND status IN ('pending','queued') AND retry_after<=clock_timestamp()",Id(r),Num(r,"granted"))) u.Exec("INSERT INTO outbox(id,job_id,run_id) VALUES (@p0,@p1,@p2) ON CONFLICT(job_id) DO NOTHING",Guid.NewGuid(),Id(job),Id(r));
        return u.Query("SELECT o.id,o.job_id FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.run_id=@p0 AND j.status IN ('pending','queued') AND j.retry_after<=clock_timestamp() AND o.retry_after<=clock_timestamp()",Id(r)); });
    public void Published(Guid id)=>Db.Transaction(u=> { u.Run(); u.Exec("UPDATE outbox SET sent_at=clock_timestamp(),retry_after=clock_timestamp()+interval '5 seconds' WHERE id=@p0",id); return true; });
    public bool Prepare(double target,Guid epoch)=>Db.Transaction(u=> { var r=u.Run(); if(Id(r,"epoch")!=epoch||r["state"]!.ToString()!="running"||Outstanding(u,r)) return false; if(!double.IsFinite(target)||target<=Num(r,"granted")) throw new Conflict("Next request must advance time");
        if(r["mode"]!.ToString()=="helics") {
            if(u.Query("SELECT 1 FROM storage_adapter_sessions WHERE run_id=@p0 AND epoch=@p1 AND NOT native_pending AND native_state='executing'",Id(r),Id(r,"epoch")).Count==0) return false;
            u.Exec("UPDATE storage_adapter_sessions SET native_pending=true WHERE run_id=@p0",Id(r));
        }
        u.Exec("UPDATE runs SET committed=granted,requested=@p0 WHERE id=@p1",target,Id(r)); return true; });
    public bool Grant(double grant,Guid epoch)=>Db.Transaction(u=> { var r=u.Run(); if(Id(r,"epoch")!=epoch) throw new Conflict("Stale controller epoch"); if(r["state"]!.ToString() is "failed" or "stalled" or "finalizing" or "finalized"||r["mode"]!.ToString()=="standalone"&&r["state"]!.ToString()=="held") return false;
        if(!double.IsFinite(grant)||grant<Num(r,"granted")||grant>Num(r,"requested")) throw new Conflict("Grant must be finite, monotonic and no later than requested");
        u.Exec("UPDATE runs SET granted=@p0,anchor=clock_timestamp() WHERE id=@p1",grant,Id(r)); return true; });
    public void Stall(string error,Guid? epoch)=>Db.Transaction(u=> { if(!u.One("SELECT pg_try_advisory_xact_lock(8192102) AS held")["held"]!.GetValue<bool>()) return false; var r=u.Run(); if(epoch is not null&&Id(r,"epoch")!=epoch) return false; if(r["state"]!.ToString() is "failed" or "stalled" or "finalized") return false; u.Exec("UPDATE runs SET state='stalled',error=@p0 WHERE current",error[..Math.Min(error.Length,1000)]); return true; });
    public void Seed()=>WarehouseProviders.Seed(this,settings);
    public string Ingest(JsonObject envelope,string source) { if(envelope["type"]?.ToString().StartsWith("handling.")==true)return CustodyQuarantine.Ingest(this,settings,envelope,source);Rules.Envelope(envelope);var boundary=Rules.Text(envelope["boundary"]);
        if(!settings.HasPeer(boundary,Rules.Text(envelope["source"]),source)||envelope["destination"]!.ToString()!="storage"||envelope["federation_id"]!.ToString()!=settings.Federation||settings.Providers[boundary]!.ToString()!="helics") throw new Conflict("Boundary owner/routing mismatch");
        return Db.Transaction(u=> { var r=u.Run(); if(Id(envelope,"run_id")!=Id(r)||Id(envelope,"epoch")!=Id(r,"epoch")) return "fenced"; var eventId=Id(envelope,"event_id"); if(u.Query("SELECT 1 FROM inbox WHERE event_id=@p0",eventId).Count>0) return "duplicate"; var due=Num(envelope,"effective_time"); if(due<Num(r,"granted")) throw new Conflict("Late event cannot change committed history");
            u.Exec("INSERT INTO inbox(event_id,run_id,epoch) VALUES (@p0,@p1,@p2)",eventId,Id(r),Id(r,"epoch"));
            if(envelope["type"]!.ToString()!="sample.completed.v1") {
                if(u.Query("SELECT 1 FROM warehouse_boundary_commands WHERE run_id=@p0 AND source=@p1 AND type=@p2 AND aggregate_id=@p3",Id(r),Rules.Text(envelope["source"]),Rules.Text(envelope["type"]),Id(envelope,"aggregate_id")).Count>0) throw new Conflict("Boundary command aggregate already accepted; replay the original event ID");
                var command=Warehouse.Submit(u,r,"boundary:"+eventId,WarehouseProviders.Input(envelope),null,settings.Quantum,true);
                u.Exec("UPDATE jobs SET payload=payload || jsonb_build_object('boundary',@p0::jsonb) WHERE id=@p1",envelope,Id(command));
                u.Exec("INSERT INTO warehouse_boundary_commands(run_id,source,type,aggregate_id,event_id,command_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5)",Id(r),Rules.Text(envelope["source"]),Rules.Text(envelope["type"]),Id(envelope,"aggregate_id"),eventId,Id(command)); return "accepted";
            }
            u.Exec("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (@p0,@p1,@p2,@p3,@p4,@p4,@p5)",Guid.NewGuid(),Id(r),Id(r,"epoch"),"boundary:"+eventId,due,envelope["payload"]!); return "accepted";
        });
    }
}
