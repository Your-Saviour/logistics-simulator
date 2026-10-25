using Storage;
using System.Text.Json.Nodes;
public static class FleetBatchTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"fleet-batch-test","operator","test:fleet-batch","","tests");
        void Reset(){var r=ledger.Status()["run"]!.AsObject();ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit);}
        Reset();var warehouse=new Warehouse(ledger,settings);var units=new[]{Guid.NewGuid(),Guid.NewGuid()}.Order().ToArray();
        JsonObject Submit(string action,JsonObject b){var r=ledger.Status()["run"]!.AsObject();b["action"]=action;b["run_id"]=r["id"]!.DeepClone();b["epoch"]=r["epoch"]!.DeepClone();b["due_at"]=Ledger.Num(r,"granted")+1;return warehouse.Submit(Guid.NewGuid().ToString(),b,audit);}
        string Execute(JsonObject command){var r=ledger.Status()["run"]!.AsObject();ledger.Heartbeat("controller");check(ledger.Prepare(Ledger.Num(r,"granted")+1,Ledger.Id(r,"epoch")),"shared-route batch wait leaves grant barrier open");ledger.Grant(Ledger.Num(r,"granted")+1,Ledger.Id(r,"epoch"));return ledger.Execute(Ledger.Id(command));}
        JsonObject FleetRow(Guid command,Guid unit)=>ledger.Db.Transaction(u=>u.One("SELECT * FROM warehouse_fleet_jobs WHERE id=@p0",Fleet.Job(unit,command,0)));
        void Fact(Guid command,Guid unit,string kind){var r=FleetRow(command,unit)["request"]!.AsObject();var b=(JsonObject)r.DeepClone();b["job_id"]=r["id"]!.DeepClone();b["robot_id"]="robot-01";b["route_version"]=1;b["kind"]=kind;b["effective_time"]=Ledger.Num(ledger.Status()["run"]!.AsObject(),"granted");ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=@p0 WHERE id=@p1",new JsonObject {["request"]=r.DeepClone(),["events"]=new JsonArray(new JsonObject {["body"]=b})},Ledger.Id(r));return true;});}
        int Stock(string location)=>ledger.Db.Transaction(u=>u.One("SELECT on_hand FROM warehouse_stock WHERE run_id=@p0 AND sku='PRODUCT' AND location=@p1",ledger.Scope(),location)["on_hand"]!.GetValue<int>());
        try {
            ledger.Db.Transaction(u=>{var r=u.Run();Warehouse.Ensure(u,r);u.Exec("UPDATE warehouse_stock SET on_hand=2 WHERE run_id=@p0 AND sku='PRODUCT' AND location='FINISHED-A'",Ledger.Id(r));return true;});
            var convert=Submit("convert",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=2,["correlation_id"]=Guid.NewGuid().ToString(),["units"]=new JsonArray(units.Select((id,i)=>(JsonNode?)new JsonObject {["id"]=id.ToString(),["quantity"]=1,["position"]=$"storage.finished.r01.b01.l{i+1:00}"}).ToArray())});Execute(convert);
            JsonObject Customer()=>new() {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=2,["purpose"]="customer",["correlation_id"]=Guid.NewGuid().ToString()};
            void Counters(int version,int generation=0)=>ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_handling_units SET version=@p0,custody_generation=@p1 WHERE run_id=@p2 AND category='finished'",version,generation,ledger.Scope());return true;});
            bool Rejected(JsonObject c)=>ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",Ledger.Id(c))["status"]!.ToString())=="rejected";
            Counters(int.MaxValue-4);
            var legacy=Submit("reserve",Customer());Execute(legacy);check(!Rejected(legacy),"disabled customer allocation retains its four-increment version boundary");
            var release=Submit("release",new JsonObject {["reference"]=legacy["id"]!.DeepClone()});Execute(release);
            Counters(int.MaxValue-4);settings.FleetMode="coordinated";settings.FleetRun=Guid.NewGuid().ToString();settings.FleetEpoch=Guid.NewGuid().ToString();
            var exhaustedVersion=Submit("reserve",Customer());Execute(exhaustedVersion);check(Rejected(exhaustedVersion),"coordinated customer allocation rejects a unit lacking the fifth version increment before offering it");
            check(ledger.Db.Transaction(u=>u.One("SELECT reserved FROM warehouse_stock WHERE run_id=@p0 AND sku='PRODUCT' AND location='FINISHED-A'",ledger.Scope())["reserved"]!.GetValue<int>())==0&&ledger.Db.Transaction(u=>u.Query("SELECT state FROM warehouse_handling_units WHERE run_id=@p0 AND category='finished'",ledger.Scope()).All(row=>row["state"]!.ToString()=="available")),"failed coordinated headroom check freezes no stock or whole-unit manifest");
            Counters(int.MaxValue-5,int.MaxValue);
            var exhaustedGeneration=Submit("reserve",Customer());Execute(exhaustedGeneration);check(Rejected(exhaustedGeneration),"coordinated customer allocation preserves one downstream custody generation");
            Counters(int.MaxValue-5);
            var reservation=Submit("reserve",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=2,["purpose"]="customer",["correlation_id"]=Guid.NewGuid().ToString()});Execute(reservation);
            check(!Rejected(reservation),"coordinated customer allocation accepts the exact five-increment boundary");
            var pick=Submit("pick",new JsonObject {["reference"]=reservation["id"]!.DeepClone()});check(Execute(pick)=="waiting","two shelf units request shared-bay fleet work");
            Fact(Ledger.Id(pick),units[0],"pickup_ready");check(Execute(pick)=="waiting","first shelf pickup departs independently");
            Fact(Ledger.Id(pick),units[0],"arrival");check(Execute(pick)=="waiting","batch remains pending while second shared-route unit has no facts");
            check(FleetRow(Ledger.Id(pick),units[0])["receipt"] is JsonObject,"first shelf arrival commits receipt before second can obtain the shared route");
            check(FleetRow(Ledger.Id(pick),units[1])["departure"] is null&&Stock("FINISHED-A")==2,"first local receipt invents no sibling departure or stock retirement");
            Fact(Ledger.Id(pick),units[1],"pickup_ready");Execute(pick);Fact(Ledger.Id(pick),units[1],"arrival");check(Execute(pick)=="completed","serial shared-route shelf jobs complete one aggregate pick");
            var transfer=Submit("transfer",new JsonObject {["reference"]=reservation["id"]!.DeepClone(),["destination"]="DISPATCH"});check(Execute(transfer)=="waiting","batch internal transfer reserves its destinations");
            Fact(Ledger.Id(transfer),units[0],"pickup_ready");check(Execute(transfer)=="waiting","first transfer departs while sibling awaits the same physical route");
            check(FleetRow(Ledger.Id(transfer),units[0])["departure"] is JsonObject&&Stock("FINISHED-A")==1&&Stock("DISPATCH")==0,"one departure retires only its native source quantity and proves no receipt");
            Fact(Ledger.Id(transfer),units[0],"arrival");check(Execute(transfer)=="waiting","first transfer arrival preserves pending aggregate state");
            check(FleetRow(Ledger.Id(transfer),units[0])["receipt"] is JsonObject&&Stock("FINISHED-A")==1&&Stock("DISPATCH")==1,"first transfer arrival commits destination stock and receipt before sibling route assignment");
            Fact(Ledger.Id(transfer),units[1],"pickup_ready");Execute(transfer);Fact(Ledger.Id(transfer),units[1],"arrival");check(Execute(transfer)=="completed","serial transfer units finish aggregate receipt without a route deadlock");
            check(Stock("FINISHED-A")==0&&Stock("DISPATCH")==2,"per-unit progress conserves complete native stock");
            check(ledger.Db.Transaction(u=>u.Query("SELECT version FROM warehouse_handling_units WHERE run_id=@p0 AND category='finished'",ledger.Scope()).All(row=>row["version"]!.GetValue<int>()==int.MaxValue)),"exact-boundary coordinated reserve, pick and transfer finish all five increments without overflow");
            var arrive=Submit("arrive",new JsonObject {["reference"]=transfer["id"]!.DeepClone()});check(Execute(arrive)=="completed"&&Stock("DISPATCH")==2,"explicit arrival after coordinated aggregate receipt is idempotent");
            var raw=new[]{Guid.NewGuid(),Guid.NewGuid()}.Order().ToArray();
            ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_stock SET on_hand=2 WHERE run_id=@p0 AND sku='COMPONENT' AND location='RAW-A'",ledger.Scope());return true;});
            var rawConversion=Submit("convert",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=2,["correlation_id"]=Guid.NewGuid().ToString(),["units"]=new JsonArray(raw.Select((id,i)=>(JsonNode?)new JsonObject {["id"]=id.ToString(),["quantity"]=1,["position"]=$"storage.raw.r01.b01.l{i+1:00}"}).ToArray())});Execute(rawConversion);
            var production=Submit("reserve",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=2,["purpose"]="production",["correlation_id"]=Guid.NewGuid().ToString()});Execute(production);
            var issue=Submit("issue",new JsonObject {["reference"]=production["id"]!.DeepClone()});check(Execute(issue)=="waiting","two production inputs persist independent pickup requests");
            var first=ledger.Db.Transaction(u=>u.One("SELECT request FROM warehouse_fleet_jobs WHERE native_command=@p0 AND request->>'unit_id'=@p1",Ledger.Id(issue),raw[0].ToString())["request"]!.AsObject());
            var pickup=(JsonObject)first.DeepClone();pickup["job_id"]=first["id"]!.DeepClone();pickup["robot_id"]="robot-01";pickup["kind"]="pickup_ready";pickup["route_version"]=1;
            ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=@p0 WHERE id=@p1",new JsonObject {["request"]=first.DeepClone(),["events"]=new JsonArray(new JsonObject {["body"]=pickup})},Ledger.Id(first));return true;});
            check(Execute(issue)=="waiting","production batch retains a durable sibling wait after first pickup");
            check(ledger.Db.Transaction(u=>u.One("SELECT on_hand FROM warehouse_stock WHERE run_id=@p0 AND sku='COMPONENT' AND location='RAW-A'",ledger.Scope())["on_hand"]!.GetValue<int>())==1&&ledger.Db.Transaction(u=>u.One("SELECT departure FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(first))["departure"] is JsonObject),"first production pickup commits native departure and exact stock without all-ready proof gating");
        }finally{settings.FleetMode="disabled";Reset();}
    }
}
