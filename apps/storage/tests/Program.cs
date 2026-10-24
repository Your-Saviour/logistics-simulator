using Storage;
using Npgsql;
using System.Text.Json.Nodes;
int count = 0;
var secure=new Npgsql.NpgsqlConnectionStringBuilder(Database.ConnectionString("postgresql://user:p%40ss@db:5432/storage?sslmode=verify-full&sslrootcert=%2Fcerts%2Fca.pem&connect_timeout=4"));
if(secure.SslMode!=Npgsql.SslMode.VerifyFull||secure.RootCertificate!="/certs/ca.pem"||secure.Timeout!=4||secure.Password!="p@ss") throw new Exception("Database URL TLS and timeout options lost");
count++;
void Check(bool result, string name) { if (!result) throw new Exception(name); count++; Console.WriteLine("PASS " + name); }
void Invalid(string json) { try { Rules.Job(JsonNode.Parse(json)!.AsObject()); throw new Exception("Accepted invalid command: " + json); } catch (Validation) { count++; } }
foreach (var raw in new[]{"{\"due_at\":1,\"quantity\":true}","{\"due_at\":1,\"quantity\":1.5}","{\"due_at\":1,\"quantity\":\"1\"}","{\"due_at\":-1,\"quantity\":1}","{\"due_at\":1,\"quantity\":1,\"extra\":1}","{\"due_at\":1,\"quantity\":10001}","{\"quantity\":1}"}) Invalid(raw);
var valid=Rules.Job(JsonNode.Parse("{\"due_at\":1.5,\"quantity\":3}")!.AsObject());
Check(valid.Due==1.5 && valid.Quantity==3,"valid fractional seconds and strict quantity");
var scenario = new Scenario(new JsonObject());
Check(scenario.Instant(0).ToString("yyyy-MM-ddTHH:mm:sszzz")=="2026-01-05T08:00:00+10:30","scenario offset");
Check(scenario.NextDue(9*3600-1,1)==86400,"closing rolls to next opening");
var dst=new Scenario(JsonNode.Parse("{\"time_zone\":\"Australia/Adelaide\",\"start_at\":\"2026-10-03T08:00:00+09:30\",\"business_weekdays\":[0,1,2,3,4,5,6]}")!.AsObject());
Check(dst.NextDue(9*3600,1)==23*3600,"DST calendar uses elapsed UTC seconds");
Check(Rules.Quantity(1,"storage","supply",1)==2,"seeded SHA256 quantity compatibility");
Console.WriteLine($"{count} checks passed");
if (Environment.GetEnvironmentVariable("STORAGE_INTEGRATION")=="true") {
    var settings=new Settings(); var db=new Database(settings); db.Migrate(); var ledger=new Ledger(db,settings);
    var existing=ledger.Status()["run"]!.AsObject();
    ledger.Control("reset",new JsonObject {["confirm_run_id"]=existing["id"]!.DeepClone()},new Audit(Guid.NewGuid(),"operator","operator","test:reset","","tests"));
    var run=ledger.Status()["run"]!.AsObject(); var epoch=Ledger.Id(run,"epoch"); var audit=new Audit(Guid.NewGuid(),"employee","employee","POST /api/jobs","test","local");
    foreach(var action in new[]{"hold","resume","speed","finalize","reset"}) {
        foreach(var field in new[]{"run_id","epoch"}) {
            var precondition=new JsonObject {["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["confirm_run_id"]=run["id"]!.DeepClone()};precondition[field]=Guid.NewGuid().ToString();
            try { ledger.Control(action,precondition,audit);throw new Exception("Stale control accepted"); }catch(Conflict){Check(ledger.Status()["run"]!["state"]!.ToString()=="running","stale control rejected before mutation: "+action+" "+field);}
        }
    }
    var receiptAudit=audit with { Actor="receipt-test",Action="POST /api/control/hold",Key="hold-receipt" };
    var firstHold=ledger.Control("hold",new JsonObject(),receiptAudit);
    ledger.Control("resume",new JsonObject(),audit);
    var retryHold=ledger.Control("hold",new JsonObject(),receiptAudit);
    Check(ledger.Status()["run"]!["state"]!.ToString()=="running"&&JsonNode.DeepEquals(firstHold,retryHold),"lost control response replays receipt without overwriting another actor resume");
    try {ledger.Control("resume",new JsonObject(),receiptAudit with {Action="POST /api/control/resume"});throw new Exception("Changed keyed action accepted");}catch(Conflict){Check(true,"control receipt rejects changed action");}
    var infrastructure=new Warehouse(ledger,settings).Projection()["health"] as JsonObject;
    Check(infrastructure is not null&&infrastructure["pending_jobs"] is not null&&infrastructure["dead_letters"] is not null&&infrastructure["heartbeats"] is JsonArray,"projection exposes safe infrastructure health");
    var job=ledger.Schedule("test:"+Guid.NewGuid(),2,7,audit); var jobId=Ledger.Id(job);
    Check(ledger.Execute(jobId)=="waiting","workers cannot execute before persisted grant");
    ledger.Heartbeat("controller"); Check(ledger.Prepare(2,epoch),"empty completion barrier permits request");
    ledger.Grant(1,epoch); Check(ledger.Execute(jobId)=="waiting","earlier grant does not authorize requested time");
    try { ledger.Grant(3,epoch); throw new Exception("Grant beyond request accepted"); } catch(Conflict) { count++; }
    ledger.Grant(2,epoch); Check(!ledger.Prepare(3,epoch),"due work blocks next time request");
    var outcomes=await Task.WhenAll(Enumerable.Range(0,8).Select(_=>Task.Run(()=>ledger.Execute(jobId))));
    Check(outcomes.Count(x=>x=="completed")==1&&outcomes.Count(x=>x=="duplicate")==7,"concurrent delivery applies sample effect once");
    Check(ledger.Status()["effects"]!.GetValue<long>()==7,"exact sample effect quantity");
    Check(ledger.Prepare(3,epoch),"committed completion unlocks next request");
    var operatorAudit=audit with { Role="operator",Actor="operator" };
    ledger.Control("hold",new JsonObject(),operatorAudit);
    Check(!ledger.Grant(3,epoch),"local hold prevents grants");
    var oldRun=Ledger.Id(run); ledger.Control("reset",new JsonObject {["confirm_run_id"]=oldRun.ToString()},operatorAudit);
    Check(ledger.Execute(jobId)=="fenced","reset fences old delivery");
    try { ledger.Grant(3,epoch); throw new Exception("Stale epoch accepted"); } catch(Conflict) { count++; }
    var retry=ledger.Schedule("retry:"+Guid.NewGuid(),2,1); var retryId=Ledger.Id(retry);
    Check(ledger.Fail(retryId,new Exception("domain"))=="retry","first domain failure retains work");
    Check(ledger.Fail(retryId,new Exception("domain"))=="retry","second domain failure retains work");
    Check(ledger.Fail(retryId,new Exception("domain"))=="dead"&&ledger.Status()["run"]!["state"]!.ToString()=="failed","retry limit dead letters and fails run");
    var current=ledger.Status()["run"]!.AsObject(); ledger.Control("reset",new JsonObject {["confirm_run_id"]=current["id"]!.DeepClone()},operatorAudit);
    var native=ledger.Status()["run"]!.AsObject(); var nativeId=Ledger.Id(native); var nativeEpoch=Ledger.Id(native,"epoch");
    db.Transaction(u=> { u.Exec("UPDATE runs SET mode='helics' WHERE id=@p0",nativeId); u.Exec("INSERT INTO storage_adapter_sessions(run_id,epoch,session_id,native_pending,native_state) VALUES (@p0,@p1,@p2,true,'initializing')",nativeId,nativeEpoch,Guid.NewGuid()); return true; });
    Check(!ledger.Prepare(1,nativeEpoch),"native initialization blocks time request intent");
    db.Transaction(u=> { u.Exec("UPDATE storage_adapter_sessions SET native_pending=false,native_state='executing' WHERE run_id=@p0",nativeId); return true; });
    Check(ledger.Prepare(1,nativeEpoch),"settled native state permits time request intent");
    Check(db.Transaction(u=>u.One("SELECT native_pending FROM storage_adapter_sessions WHERE run_id=@p0",nativeId)["native_pending"]!.GetValue<bool>()),"time request persists pending fence before any adapter HTTP");
    try { ledger.Control("finalize",new JsonObject(),operatorAudit); throw new Exception("Pending native request finalized"); } catch(Conflict) { count++; }
    db.Transaction(u=> { u.Exec("UPDATE storage_adapter_sessions SET native_pending=false,native_state='executing' WHERE run_id=@p0",nativeId); return true; });
    var finalizing=ledger.Control("finalize",new JsonObject(),operatorAudit);
    Check(finalizing["run"]!["state"]!.ToString()=="finalizing","connected finalize waits for native acknowledgement");
    ledger.Stall("Native finalization unavailable",nativeEpoch);
    Check(ledger.Status()["run"]!["state"]!.ToString()=="stalled","native finalization failure remains visible");
    db.Transaction(u=> { u.Exec("DELETE FROM storage_adapter_sessions WHERE run_id=@p0",nativeId); u.Exec("UPDATE runs SET mode='standalone',requested=0 WHERE id=@p0",nativeId); return true; });
    ledger.Control("reset",new JsonObject {["confirm_run_id"]=nativeId.ToString()},operatorAudit);
    var checksum=db.Transaction(u=>u.One("SELECT checksum FROM schema_migrations WHERE name='001_bootstrap.sql'")["checksum"]!.ToString());
    db.Transaction(u=>{u.Exec("UPDATE schema_migrations SET checksum='tampered' WHERE name='001_bootstrap.sql'");return true;});
    try { try { db.Migrate(); throw new Exception("Edited migration accepted"); } catch(Conflict) { count++; } }
    finally { db.Transaction(u=>{u.Exec("UPDATE schema_migrations SET checksum=@p0 WHERE name='001_bootstrap.sql'",checksum);return true;}); }
    await using(var connection=await Broker.Connect(settings.Amqp)) { await using var channel=await Broker.Channel(connection);
        var rejected=false; try { await Broker.Publish(channel,"unroutable:"+Guid.NewGuid(),Guid.NewGuid(),new JsonObject {["job_id"]=Guid.NewGuid().ToString()}); } catch(RabbitMQ.Client.Exceptions.PublishException) { rejected=true; }
        Check(rejected,"mandatory unrouteable publish fails confirmation");
        await Broker.Publish(channel,Broker.Queue,Guid.NewGuid(),new JsonObject {["job_id"]=Guid.NewGuid().ToString()}); var delivery=await channel.BasicGetAsync(Broker.Queue,false); Check(delivery is not null,"confirmed persistent publication reaches queue");
        await channel.BasicNackAsync(delivery!.DeliveryTag,false,false); await Task.Delay(200); var dead=await channel.BasicGetAsync("sample.jobs.dead.v1",false); Check(dead is not null,"manual reject routes delivery to durable DLQ"); await channel.BasicAckAsync(dead!.DeliveryTag,false);
    }
    // The actual worker must dead-letter JSON null and continue to valid work.
    var workerRun=ledger.Status()["run"]!.AsObject();
    var afterPoison=ledger.Schedule("after-poison:"+Guid.NewGuid(),1,4); var afterPoisonId=Ledger.Id(afterPoison);
    ledger.Heartbeat("controller"); Check(ledger.Prepare(1,Ledger.Id(workerRun,"epoch")),"prepare poison-following sample"); ledger.Grant(1,Ledger.Id(workerRun,"epoch"));
    await using(var connection=await Broker.Connect(settings.Amqp)) { await using var channel=await Broker.Channel(connection);
        await channel.BasicPublishAsync("",Broker.Queue,mandatory:true,basicProperties:new RabbitMQ.Client.BasicProperties {Persistent=true,ContentType="application/json"},body:System.Text.Encoding.UTF8.GetBytes("null"));
        using var worker=new Worker(ledger,settings,Microsoft.Extensions.Logging.Abstractions.NullLogger<Worker>.Instance);
        await worker.StartAsync(CancellationToken.None); bool poisonDead=false,validCompleted=false;
        try { for(int i=0;i<60&&!(poisonDead&&validCompleted);i++) {
                var dead=await channel.BasicGetAsync("sample.jobs.dead.v1",false);
                if(dead is not null) { poisonDead|=System.Text.Encoding.UTF8.GetString(dead.Body.Span)=="null"; await channel.BasicAckAsync(dead.DeliveryTag,false); }
                validCompleted=ledger.Status()["jobs"]!.AsArray().Any(j=>Ledger.Id(j!.AsObject())==afterPoisonId&&j["status"]!.ToString()=="completed");
                await Task.Delay(100);
            }
        } finally { using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(10)); await worker.StopAsync(deadline.Token); }
        Check(poisonDead,"worker dead letters JSON null instead of redelivering forever");
        Check(validCompleted&&ledger.Status()["effects"]!.GetValue<long>()==4,"worker continues to next valid job after poison");
    }
    ledger.Control("hold",new JsonObject(),operatorAudit); var beforeLeaseLoss=ledger.Status()["run"]!.AsObject();
    using(var controller=new Controller(ledger,settings,Microsoft.Extensions.Logging.Abstractions.NullLogger<Controller>.Instance)) {
        await controller.StartAsync(CancellationToken.None); int? originalPid=null,newPid=null;
        int? ControllerPid()=>db.Transaction(u=> { var rows=u.Query("SELECT pid FROM pg_locks WHERE locktype='advisory' AND classid=0 AND objid=8192102 AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) LIMIT 1"); return rows.Count==0?(int?)null:rows[0]["pid"]!.GetValue<int>(); });
        try {
            for(int i=0;i<100&&originalPid is null;i++) { originalPid=ControllerPid(); if(originalPid is null) await Task.Delay(50); }
            Check(originalPid is not null,"standalone controller owns its database lease");
            db.Transaction(u=> { u.Exec("SELECT pg_terminate_backend(@p0)",originalPid!.Value); return true; });
            for(int i=0;i<100;i++) { newPid=ControllerPid(); if(newPid is not null&&newPid!=originalPid) break; await Task.Delay(50); }
            var retained=ledger.Status()["run"]!.AsObject();
            Check(retained["state"]!.ToString()=="held"&&Ledger.Id(retained)==Ledger.Id(beforeLeaseLoss)&&Ledger.Id(retained,"epoch")==Ledger.Id(beforeLeaseLoss,"epoch"),"standalone database lease loss retains active run and epoch");
            Check(newPid is not null&&newPid!=originalPid,"standalone controller reacquires lease after database disconnect");
        } finally { using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(10)); await controller.StopAsync(deadline.Token); }
    }
    // A new physical session must acquire ownership after controller disposal.
    // Reusing the pooled connector here would hide a deferred session reset.
    var leaseProbeOptions=new NpgsqlConnectionStringBuilder(Database.ConnectionString(settings.Database)) { Pooling=false };
    using(var leaseProbe=new NpgsqlConnection(leaseProbeOptions.ConnectionString)) {
        leaseProbe.Open();
        Check(new Unit(leaseProbe).One("SELECT pg_try_advisory_lock(8192102) AS held")["held"]!.GetValue<bool>(),"stopped controller releases lease to another physical session");
    }
    await HandlingUnitTests.Run(ledger,settings,Check);
    CustodyTests.Run(ledger,settings,Check);
    FinishedCustodyTests.Run(ledger,settings,Check);
    ShippingCustodyTests.Run(ledger,settings,Check);
    await WarehouseTests.Run(ledger,settings,Check);
    WarehouseBoundaryTests.Run(ledger,settings,Check);
    Console.WriteLine($"{count} total checks passed (PostgreSQL and RabbitMQ)");
}
