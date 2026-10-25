using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;
namespace Storage;
public sealed class FleetWait(string reason):Exception(reason);

// These methods run under the native run lock. Only Pump performs HTTP, after
// reading committed intents and before opening its response transaction.
public static class Fleet
{
    public static Guid Job(Guid unit,Guid handoff,int generation)=>Rules.Uuid5(unit,$"fleet:{handoff}:{generation}");
    public static JsonObject Request(Unit u,JsonObject run,Settings settings,Guid unit,Guid handoff,int generation,string origin,string destination,string producer="storage",JsonObject? source=null) {
        var id=Job(unit,handoff,generation);var old=u.Query("SELECT * FROM warehouse_fleet_jobs WHERE id=@p0",id).FirstOrDefault();
        if(old is not null) {
            var request=old["request"]!.AsObject();
            if(Ledger.Id(old,"run_id")!=Ledger.Id(run)||Ledger.Id(old,"epoch")!=Ledger.Id(run,"epoch")||request["run_id"]!.ToString()!=settings.FleetRun||request["epoch"]!.ToString()!=settings.FleetEpoch||request["origin"]!.ToString()!=origin||request["destination"]!.ToString()!=destination)throw new Conflict("Fleet job scope or immutable route changed");
            return request;
        }
        if(producer=="storage"&&u.Query("SELECT 1 FROM warehouse_fleet_jobs WHERE run_id=@p0 AND epoch=@p1 AND request->>'unit_id'=@p2 AND receipt IS NULL",Ledger.Id(run),Ledger.Id(run,"epoch"),unit.ToString()).Count>0)throw new Conflict("Whole unit already has an unresolved fleet move");
        source??=run;
        var body=new JsonObject {["version"]=1,["id"]=id.ToString(),["run_id"]=settings.FleetRun,["epoch"]=settings.FleetEpoch,["producer"]=producer,["source_run_id"]=source["id"]?.DeepClone()??source["run_id"]!.DeepClone(),["source_epoch"]=source["epoch"]!.DeepClone(),["unit_id"]=unit.ToString(),["origin"]=origin,["destination"]=destination,["custody_generation"]=generation,["effective_time"]=Ledger.Num(run,"granted")};
        u.Exec("INSERT INTO warehouse_fleet_jobs(id,run_id,epoch,request) VALUES (@p0,@p1,@p2,@p3)",id,Ledger.Id(run),Ledger.Id(run,"epoch"),body);
        if(producer=="storage")Outbox(u,id,"request",body);return body;
    }
    static void Outbox(Unit u,Guid job,string kind,JsonObject body)=>u.Exec("INSERT INTO warehouse_fleet_outbox(id,job_id,kind,body) VALUES (@p0,@p1,@p2,@p3) ON CONFLICT(job_id,kind) DO NOTHING",Rules.Uuid5(job,"storage:"+kind),job,kind,body);
    public static void Require(Unit u,JsonObject run,JsonObject request,string kind,double offset=0) {
        var observation=u.One("SELECT observation FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request))["observation"] as JsonObject;
        var events=observation?["events"] as JsonArray;
        var physical=events?.Select(n=>n is JsonObject envelope?envelope["body"] as JsonObject:null).FirstOrDefault(b=>b?["kind"]?.ToString()==kind&&Matches(request,b));
        if(physical is null||Ledger.Num(physical,"effective_time")>Ledger.Num(run,"granted")+offset)throw new FleetWait("fleet awaiting "+kind);
    }
    static bool Matches(JsonObject request,JsonObject body) {
        foreach(var key in new[]{"run_id","epoch","unit_id","source_run_id","source_epoch","origin","destination","custody_generation","producer"})if(!JsonNode.DeepEquals(request[key],body[key]))return false;
        return JsonNode.DeepEquals(request["id"],body["job_id"])&&body["route_version"]?.ToString()=="1"&&body["robot_id"] is JsonValue robot&&robot.TryGetValue<string>(out var robotId)&&!string.IsNullOrWhiteSpace(robotId)&&robotId.Length<=128&&body["effective_time"] is JsonValue value&&value.TryGetValue<double>(out var time)&&double.IsFinite(time)&&time>=0;
    }
    public static void Proof(Unit u,JsonObject run,JsonObject request,string kind) {
        var row=u.One("SELECT * FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request));if(row[kind] is not null)return;
        var body=new JsonObject {["job_id"]=request["id"]!.DeepClone(),["unit_id"]=request["unit_id"]!.DeepClone(),["run_id"]=request["run_id"]!.DeepClone(),["epoch"]=request["epoch"]!.DeepClone(),["source_run_id"]=run["id"]!.DeepClone(),["source_epoch"]=run["epoch"]!.DeepClone(),["custody_generation"]=request["custody_generation"]!.DeepClone(),["endpoint"]=request[kind=="departure"?"origin":"destination"]!.DeepClone(),["effective_time"]=Ledger.Num(run,"granted")};
        u.Exec("UPDATE warehouse_fleet_jobs SET "+kind+"=@p0 WHERE id=@p1",body,Ledger.Id(request));Outbox(u,Ledger.Id(request),kind,body);
    }
    public static JsonObject Local(Unit u,JsonObject run,Settings settings,Guid command,JsonObject unit,string destination) {
        var request=Request(u,run,settings,Ledger.Id(unit),command,unit["custody_generation"]!.GetValue<int>(),Rules.Text(unit["position"]??unit["origin"]),destination);
        if(unit["state"]!.ToString()!="in_transit") {
            Require(u,run,request,"pickup_ready",settings.FleetOffset);
            u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,version=version+1 WHERE id=@p2",destination,command,Ledger.Id(unit));
            Proof(u,run,request,"departure");
        }
        Require(u,run,request,"arrival",settings.FleetOffset);return request;
    }
    public static void Defer(Unit u,JsonObject run,JsonObject job,Settings settings,FleetWait wait) {
        u.Exec("UPDATE jobs SET status='pending',due_at=@p0,error=@p1 WHERE id=@p2",Ledger.Num(run,"granted")+settings.Quantum,wait.Message,Ledger.Id(job));
        u.Exec("UPDATE warehouse_commands SET error=@p0 WHERE id=@p1",wait.Message,Ledger.Id(job));
    }
    public static JsonObject Config(Settings settings)=>new() {["mode"]=settings.FleetMode,["run_id"]=settings.FleetMode=="coordinated"?settings.FleetRun:null,["epoch"]=settings.FleetMode=="coordinated"?settings.FleetEpoch:null};
    public static async Task Pump(Ledger ledger,Settings settings,CancellationToken stop) {
        if(settings.FleetMode!="coordinated")return;
        using var client=new HttpClient { BaseAddress=new Uri(settings.FleetUrl.TrimEnd('/')+"/"),Timeout=TimeSpan.FromSeconds(3) };client.DefaultRequestHeaders.Authorization=new AuthenticationHeaderValue("Bearer",settings.FleetToken);
        var deliveries=ledger.Db.Transaction(u=>{var run=u.Run();return u.Query("SELECT o.* FROM warehouse_fleet_outbox o JOIN warehouse_fleet_jobs f ON f.id=o.job_id WHERE f.run_id=@p0 AND f.epoch=@p1 AND o.sent_at IS NULL AND o.retry_after<=clock_timestamp() ORDER BY CASE kind WHEN 'receipt' THEN 0 WHEN 'departure' THEN 1 ELSE 2 END,o.retry_after,id LIMIT 16",Ledger.Id(run),Ledger.Id(run,"epoch"));});
        foreach(var row in deliveries) {try {
            var path="v1/jobs"+(row["kind"]!.ToString()=="request"?"":"/"+row["job_id"]+"/proofs/"+row["kind"]);
            using var response=await client.PostAsync(path,new StringContent(row["body"]!.ToJsonString(),Encoding.UTF8,"application/json"),stop);response.EnsureSuccessStatusCode();
            ledger.Db.Transaction(u=>{var run=u.Run();u.Exec("UPDATE warehouse_fleet_outbox o SET sent_at=clock_timestamp() FROM warehouse_fleet_jobs f WHERE o.id=@p0 AND f.id=o.job_id AND f.run_id=@p1 AND f.epoch=@p2",Ledger.Id(row),Ledger.Id(run),Ledger.Id(run,"epoch"));return true;});
        }catch(Exception e) when(e is HttpRequestException or TaskCanceledException) {if(stop.IsCancellationRequested)throw;ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_outbox SET retry_after=clock_timestamp()+interval '1 second' WHERE id=@p0 AND sent_at IS NULL",Ledger.Id(row));return true;});}}
        var jobs=ledger.Db.Transaction(u=>{var run=u.Run();return u.Query("SELECT * FROM warehouse_fleet_jobs WHERE run_id=@p0 AND epoch=@p1 AND receipt IS NULL AND poll_after<=clock_timestamp() ORDER BY poll_after,id LIMIT 16",Ledger.Id(run),Ledger.Id(run,"epoch"));});
        foreach(var row in jobs) {try {
            var observation=JsonNode.Parse(await client.GetStringAsync("v1/jobs/"+row["id"],stop))!.AsObject();
            if(observation["fleet_scope"] is not JsonObject scope||scope["run_id"]?.ToString()!=row["run_id"]!.ToString()||scope["epoch"]?.ToString()!=row["epoch"]!.ToString()||Ledger.Num(scope,"offset")!=settings.FleetOffset)throw new InvalidOperationException("Fleet source mapping mismatch");
            var expected=(JsonObject)row["request"]!.DeepClone();
            if(expected["producer"]!.ToString()!="storage")expected["effective_time"]=observation["request"]?["effective_time"]?.DeepClone();
            if(!JsonNode.DeepEquals(observation["request"],expected))throw new InvalidOperationException("Fleet immutable request mismatch");
            ledger.Db.Transaction(u=>{var run=u.Run();u.Exec("UPDATE warehouse_fleet_jobs SET observation=@p0,error=NULL,poll_after=clock_timestamp()+interval '0.1 seconds' WHERE id=@p1 AND run_id=@p2 AND epoch=@p3",observation,Ledger.Id(row),Ledger.Id(run),Ledger.Id(run,"epoch"));return true;});
        }catch(Exception e) when(e is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException or InvalidOperationException or FormatException) {if(stop.IsCancellationRequested)throw;ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET poll_after=clock_timestamp()+interval '1 second' WHERE id=@p0",Ledger.Id(row));return true;});}}
    }
}

// Fleet dependency retries must never monopolize the native consumer: that
// consumer commits deferred waits so the controller can close each grant.
public sealed class FleetDelivery(Ledger ledger,Settings settings,ILogger<FleetDelivery> logger):BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stop) {
        await Task.Yield();
        while(!stop.IsCancellationRequested) {
            try {await Fleet.Pump(ledger,settings,stop);}
            catch(OperationCanceledException) when(stop.IsCancellationRequested){break;}
            catch(Exception error){logger.LogWarning(error,"Fleet unavailable; native transport remains deferred");}
            try {await Task.Delay(250,stop);}catch(OperationCanceledException) when(stop.IsCancellationRequested){break;}
        }
    }
}
