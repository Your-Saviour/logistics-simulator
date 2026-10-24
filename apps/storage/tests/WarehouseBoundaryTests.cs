using Storage;
using System.Text.Json.Nodes;
public static class WarehouseBoundaryTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"test","operator","test:boundary","","tests");
        void Reset() { var r=ledger.Status()["run"]!.AsObject(); ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit); }
        Reset(); var r=ledger.Status()["run"]!.AsObject(); var correlation=Guid.NewGuid();
        var envelope=new JsonObject {["schema_version"]="1.0",["type"]="storage.receipt.v1",["event_id"]=Guid.NewGuid().ToString(),["federation_id"]="warehouse-test",["run_id"]=r["id"]!.DeepClone(),["epoch"]=r["epoch"]!.DeepClone(),["correlation_id"]=correlation.ToString(),["causation_id"]=Guid.NewGuid().ToString(),["aggregate_id"]=Guid.NewGuid().ToString(),["aggregate_version"]=1,["source"]="supplier",["destination"]="storage",["boundary"]="supply",["effective_time"]=1.0,["quantity_unit"]="item",["payload"]=new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=3} };
        Rules.Envelope(envelope); check(true,"domain receipt envelope validates without sample payload assumptions");
        var oldProviders=settings.Providers; var oldPeers=settings.Peers; var federation=settings.Federation;
        try {
            settings.Providers=new JsonObject {["supply"]="helics",["requests"]="helics"}; settings.Federation="warehouse-test";
            settings.Peers=new JsonObject {["supply"]=new JsonObject {["endpoint"]="supplier/events",["source"]="supplier"}};
            check(ledger.Ingest(envelope,"supplier/events")=="accepted"&&ledger.Ingest(envelope,"supplier/events")=="duplicate","boundary receipt input deduplicates atomically with job scheduling");
            var repeated=(JsonObject)envelope.DeepClone(); repeated["event_id"]=Guid.NewGuid().ToString();
            try { ledger.Ingest(repeated,"supplier/events"); throw new Exception("Duplicate aggregate command accepted"); } catch(Conflict) { check(true,"boundary aggregate identity prevents duplicate commands with new event IDs"); }
            try { ledger.Ingest(envelope,"intruder/events"); throw new Exception("Wrong owner accepted"); } catch(Conflict) { check(true,"domain boundary rejects wrong owner"); }
            var stale=(JsonObject)envelope.DeepClone(); stale["event_id"]=Guid.NewGuid().ToString(); stale["epoch"]=Guid.NewGuid().ToString(); check(ledger.Ingest(stale,"supplier/events")=="fenced","domain inputs fence old epochs");
            ledger.Seed(); check(ledger.Status()["jobs"]!.AsArray().Count==1,"HELICS-owned boundaries never synthesize supply or demand");
            ledger.Heartbeat("controller"); ledger.Prepare(1,Ledger.Id(r,"epoch")); ledger.Grant(1,Ledger.Id(r,"epoch"));
            var j=ledger.Status()["jobs"]![0]!.AsObject(); ledger.Execute(Ledger.Id(j));
            check(new Warehouse(ledger,settings).Snapshot()["receipts"]![0]!["correlation_id"]!.ToString()==correlation.ToString(),"boundary receipt retains order/batch correlation");
        } finally { settings.Providers=oldProviders; settings.Peers=oldPeers; settings.Federation=federation; }
        Reset();
        // Drive persisted grants and the same real execution path deterministically.
        var warehouse=new Warehouse(ledger,settings);
        for(var t=0;t<100;t++) {
            ledger.Seed(); var run=ledger.Status()["run"]!.AsObject(); ledger.Heartbeat("controller");
            foreach(var job in ledger.Status()["jobs"]!.AsArray().Select(x=>x!.AsObject()).Where(x=>Ledger.Num(x,"due_at")<=Ledger.Num(run,"granted")&&x["status"]!.ToString()!="completed")) ledger.Execute(Ledger.Id(job));
            if(ledger.Prepare(Ledger.Num(run,"granted")+1,Ledger.Id(run,"epoch"))) ledger.Grant(Ledger.Num(run,"granted")+1,Ledger.Id(run,"epoch"));
        }
        var snapshot=warehouse.Snapshot();
        check(snapshot["movements"]!.AsArray().Any(x=>x!["action"]!.ToString()=="issue"),"seeded production demand issues raw materials independently");
        check(snapshot["transfers"]!.AsArray().Any(x=>x!["status"]!.ToString()=="received"),"seeded customer demand completes pick/transfer/receipt without peers");
        check(snapshot["inventory"]!.AsArray().All(x=>x!["on_hand"]!.GetValue<int>()>=x["reserved"]!.GetValue<int>()),"autonomous lifecycle conserves stock");
        Reset();
    }
}
