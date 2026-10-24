using Storage;
using System.Text.Json.Nodes;
public static class WarehouseBoundaryTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"test","operator","test:boundary","","tests");
        void Reset() { var r=ledger.Status()["run"]!.AsObject(); ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit); }
        Reset(); var r=ledger.Status()["run"]!.AsObject(); var correlation=Guid.NewGuid();
        var envelope=new JsonObject {["schema_version"]="1.0",["type"]="storage.receipt.v1",["event_id"]=Guid.NewGuid().ToString(),["federation_id"]="warehouse-test",["run_id"]=r["id"]!.DeepClone(),["epoch"]=r["epoch"]!.DeepClone(),["correlation_id"]=correlation.ToString(),["causation_id"]=Guid.NewGuid().ToString(),["aggregate_id"]=Guid.NewGuid().ToString(),["aggregate_version"]=1,["source"]="supplier",["destination"]="storage",["boundary"]="supply",["effective_time"]=1.0,["quantity_unit"]="item",["payload"]=new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=3} };
        envelope["payload"]!["units"]=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=3});
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
        PeerCommands(ledger,settings,check,audit);
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
    static void PeerCommands(Ledger ledger,Settings settings,Action<bool,string> check,Audit audit) {
        var run=ledger.Status()["run"]!.AsObject(); var runId=Ledger.Id(run); var warehouse=new Warehouse(ledger,settings);
        var providers=settings.Providers; var peers=settings.Peers; var federation=settings.Federation;var outputs=settings.Outputs;
        var correlation=Guid.NewGuid(); double time=0;
        JsonObject Input(string type,JsonObject payload) => new() { ["schema_version"]="1.0",["type"]="storage."+type+".v1",["event_id"]=Guid.NewGuid().ToString(),["federation_id"]="warehouse-test",["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["correlation_id"]=correlation.ToString(),["causation_id"]=Guid.NewGuid().ToString(),["aggregate_id"]=Guid.NewGuid().ToString(),["aggregate_version"]=1,["source"]="shipping",["destination"]="storage",["boundary"]="requests",["effective_time"]=++time,["quantity_unit"]="item",["payload"]=payload };
        void Execute(Guid id) { ledger.Heartbeat("controller"); ledger.Db.Transaction(u=> { u.Run(); u.Exec("UPDATE runs SET granted=@p0,requested=@p0 WHERE id=@p1",time,runId); return true; }); check(ledger.Execute(id)=="completed","peer command completes its durable job"); }
        (JsonObject envelope,Guid command) Send(string type,JsonObject payload) {
            var envelope=Input(type,payload); check(ledger.Ingest(envelope,"shipping/events")=="accepted","shipping "+type+" input accepted");
            var command=ledger.Db.Transaction(u=>Ledger.Id(u.One("SELECT command_id AS id FROM warehouse_boundary_commands WHERE event_id=@p0",Ledger.Id(envelope,"event_id")))); Execute(command); return (envelope,command);
        }
        JsonObject Fact(Guid id) => ledger.Db.Transaction(u=>u.One("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,id.ToString())["envelope"]!.AsObject());
        try {
            settings.Providers=new JsonObject { ["supply"]="helics",["requests"]="helics" }; settings.Federation="warehouse-test";settings.Outputs=new JsonArray(new JsonObject {["destination"]="shipping",["boundary"]="goods",["endpoint"]="shipping/events"});
            settings.Peers=new JsonObject { ["requests"]=new JsonArray(new JsonObject { ["endpoint"]="shipping/events",["source"]="shipping" },new JsonObject {["endpoint"]="manufacturing/events",["source"]="manufacturing"}) };
            var initial=warehouse.Submit("peer-stock-receipt",new JsonObject {["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["due_at"]=++time,["action"]="expect",["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=10,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=3},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=5})},audit);Execute(Ledger.Id(initial));
            var received=warehouse.Submit("peer-stock-confirm",new JsonObject {["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["due_at"]=++time,["action"]="receive",["reference"]=Ledger.Id(initial).ToString()},audit);Execute(Ledger.Id(received));
            ledger.Db.Transaction(u=> { u.Run();u.Exec("UPDATE runs SET mode='helics' WHERE id=@p0",runId);return true; });
            var reserved=Send("request",new JsonObject { ["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=3,["purpose"]="customer" });
            check(Fact(reserved.command)["causation_id"]?.ToString()==reserved.envelope["event_id"]!.ToString(),"completed boundary fact retains incoming event causation");
            ledger.Seed();
            check(warehouse.Snapshot()["commands"]!.AsArray().Count==3&&warehouse.Snapshot()["reservations"]![0]!["status"]!.ToString()=="reserved","HELICS requests leave reservations for explicit peer decisions");
            var foreign=Input("release",new JsonObject {["reference"]=reserved.command.ToString()});foreign["source"]="manufacturing";check(ledger.Ingest(foreign,"manufacturing/events")=="accepted","second configured request peer can submit its own boundary input");var foreignCommand=ledger.Db.Transaction(u=>Ledger.Id(u.One("SELECT command_id AS id FROM warehouse_boundary_commands WHERE event_id=@p0",Ledger.Id(foreign,"event_id"))));Execute(foreignCommand);
            check(ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",foreignCommand))["status"]!.ToString()=="rejected"&&warehouse.Snapshot()["reservations"]![0]!["status"]!.ToString()=="reserved","configured peer cannot release another peer's reservation");
            var picked=Send("pick",new JsonObject { ["reference"]=reserved.command.ToString() });
            ledger.Seed();
            check(warehouse.Snapshot()["commands"]!.AsArray().Count==5&&warehouse.Snapshot()["transfers"]!.AsArray().Count==0,"HELICS requests leave picked stock for explicit peer transfer");
            var destinations=new JsonObject();foreach(var unit in Fact(reserved.command)["payload"]!["unit_manifest"]!.AsArray())destinations[unit!["id"]!.ToString()]="shipping.outbound.staging.r01.b01";
            var transferred=Send("transfer",new JsonObject { ["reference"]=reserved.command.ToString(),["destination"]="DISPATCH",["unit_destinations"]=destinations });
            check(warehouse.Snapshot()["transfers"]![0]!["status"]!.ToString()=="awaiting_acceptance"&&ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,transferred.command.ToString()).Count)==0,"transfer outcome waits for real receiver acceptance");
            var offer=ledger.Db.Transaction(u=>u.One("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'type'='handling.offered.v1'",runId)["envelope"]!.AsObject());var acceptance=(JsonObject)offer.DeepClone();acceptance["source"]="shipping";acceptance["destination"]="storage";acceptance["boundary"]="requests";acceptance["type"]="handling.accepted.v1";acceptance["event_id"]=Guid.NewGuid().ToString();acceptance["effective_time"]=++time;acceptance["payload"]!["state"]="accepted";
            ledger.Ingest(acceptance,"shipping/events");var acceptedJob=ledger.Db.Transaction(u=>Ledger.Id(u.One("SELECT id FROM jobs WHERE idempotency_key=@p0","boundary:"+acceptance["event_id"]!.ToString())));Execute(acceptedJob);
            check(Fact(picked.command)["causation_id"]!.ToString()==picked.envelope["event_id"]!.ToString()&&Fact(transferred.command)["causation_id"]!.ToString()==transferred.envelope["event_id"]!.ToString(),"pick and transfer facts match their incoming intents");
            check(warehouse.Snapshot()["transfers"]![0]!["status"]!.ToString()=="in_transit","explicit peer pick and transfer dispatch reserved goods");
            var second=Send("request",new JsonObject { ["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=2,["purpose"]="customer" });
            Send("release",new JsonObject { ["reference"]=second.command.ToString() });
            check(warehouse.Snapshot()["reservations"]!.AsArray().Any(x=>x!["id"]!.ToString()==second.command.ToString()&&x["status"]!.ToString()=="released"),"peer release returns reserved stock");
            var shortage=Send("request",new JsonObject { ["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=100,["purpose"]="customer" });
            var rejected=Fact(shortage.command);
            check(rejected["type"]!.ToString()=="storage.command.rejected.v1"&&rejected["causation_id"]!.ToString()==shortage.envelope["event_id"]!.ToString()&&rejected["aggregate_id"]!.ToString()==shortage.envelope["aggregate_id"]!.ToString()&&rejected["correlation_id"]!.ToString()==correlation.ToString()&&rejected["aggregate_version"]!.GetValue<int>()==1,"shortage rejection retains intent identity and correlation");
            check(rejected["payload"]!["action"]!.ToString()=="reserve"&&rejected["payload"]!["reason"]!.ToString().Contains("Insufficient")&&rejected["payload"]!["request"]!["quantity"]!.GetValue<int>()==100,"shortage rejection contains original command and reason");
            var original=ledger.Db.Transaction(u=>u.One("SELECT command FROM warehouse_commands WHERE id=@p0",shortage.command)["command"]!);
            check(JsonNode.DeepEquals(rejected["payload"]!["request"],original),"rejection retains the complete original warehouse command");
            var stock=warehouse.Snapshot()["inventory"]!.AsArray().Single(x=>x!["sku"]!.ToString()=="PRODUCT"&&x["location"]!.ToString()=="FINISHED-A")!;
            check(stock["on_hand"]!.GetValue<int>()==7&&stock["reserved"]!.GetValue<int>()==0,"shortage leaves stock and reservations unchanged");
            check(ledger.Execute(shortage.command)=="duplicate"&&ledger.Ingest(shortage.envelope,"shipping/events")=="duplicate","shortage retries retain one durable rejected outcome");
            check(ledger.Db.Transaction(u=>u.One("SELECT count(*) AS count FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,shortage.command.ToString())["count"]!.GetValue<long>())==1,"shortage retry creates no duplicate rejection fact");
            var missing=Send("release",new JsonObject { ["reference"]=Guid.NewGuid().ToString() });
            check(Fact(missing.command)["correlation_id"]!.ToString()==correlation.ToString(),"reference rejection retains incoming correlation without a warehouse record");
            var legacy=Input("request",new JsonObject { ["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=100,["purpose"]="customer" });
            ledger.Ingest(legacy,"shipping/events");
            var legacyCommand=ledger.Db.Transaction(u=> { var id=Ledger.Id(u.One("SELECT command_id AS id FROM warehouse_boundary_commands WHERE event_id=@p0",Ledger.Id(legacy,"event_id"))); u.Exec("UPDATE jobs SET payload=payload-'boundary' WHERE id=@p0",id); return id; });
            Execute(legacyCommand);
            check(ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",legacyCommand)["status"]!.ToString())=="rejected"&&ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,legacyCommand.ToString()).Count)==0,"legacy pending boundary rejection settles without inventing missing correlation");
            var employee=warehouse.Submit("employee-shortage",new JsonObject { ["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["due_at"]=++time,["action"]="reserve",["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=100,["purpose"]="customer",["correlation_id"]=correlation.ToString() },audit);
            Execute(Ledger.Id(employee));
            check(ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,Ledger.Id(employee).ToString()).Count)==0,"employee rejection creates no boundary fact");
            ledger.Db.Transaction(u=> { u.Exec("UPDATE runs SET mode='standalone' WHERE id=@p0",runId); return true; });
            var standalone=Send("request",new JsonObject { ["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=100,["purpose"]="customer" });
            check(ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'job_id'=@p1",runId,standalone.command.ToString()).Count)==0,"standalone rejection creates no boundary fact");
        } finally {
            settings.Providers=providers; settings.Peers=peers; settings.Federation=federation;settings.Outputs=outputs;
            ledger.Db.Transaction(u=> { u.Exec("UPDATE runs SET mode='standalone' WHERE id=@p0",runId); return true; });
        }
    }

}
