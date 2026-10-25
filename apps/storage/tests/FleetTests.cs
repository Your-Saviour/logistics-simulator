using Storage;
using System.Text.Json.Nodes;
public static class FleetTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"fleet-test","operator","test:fleet","","tests");
        var old=ledger.Status()["run"]!.AsObject();ledger.Control("reset",new JsonObject {["confirm_run_id"]=old["id"]!.DeepClone()},audit);
        var warehouse=new Warehouse(ledger,settings);var unit=Guid.NewGuid();var correlation=Guid.NewGuid();
        JsonObject Submit(string action,JsonObject body) {
            var run=ledger.Status()["run"]!.AsObject();body["action"]=action;body["run_id"]=run["id"]!.DeepClone();body["epoch"]=run["epoch"]!.DeepClone();body["due_at"]=Ledger.Num(run,"granted")+1;
            return warehouse.Submit(Guid.NewGuid().ToString(),body,audit);
        }
        void Advance() {var run=ledger.Status()["run"]!.AsObject();ledger.Heartbeat("controller");check(ledger.Prepare(Ledger.Num(run,"granted")+1,Ledger.Id(run,"epoch")),"fleet waits permit next native clock request");ledger.Grant(Ledger.Num(run,"granted")+1,Ledger.Id(run,"epoch"));}
        ledger.Db.Transaction(u=>{var run=u.Run();Warehouse.Ensure(u,run);u.Exec("UPDATE warehouse_stock SET on_hand=1 WHERE run_id=@p0 AND sku='COMPONENT' AND location='RAW-A'",Ledger.Id(run));return true;});
        var convert=Submit("convert",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=1,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=unit.ToString(),["quantity"]=1,["position"]="storage.inbound.dock01"})});Advance();ledger.Execute(Ledger.Id(convert));
        settings.FleetMode="coordinated";settings.FleetRun=Guid.NewGuid().ToString();settings.FleetEpoch=Guid.NewGuid().ToString();
        try {
            var move=Submit("putaway",new JsonObject {["unit_id"]=unit.ToString(),["destination"]="storage.raw.r01.b01.l01"});Advance();
            check(ledger.Execute(Ledger.Id(move))=="waiting","coordinated putaway waits for pickup without immediate placement");
            var request=ledger.Db.Transaction(u=>u.One("SELECT request FROM warehouse_fleet_jobs WHERE id=@p0",Fleet.Job(unit,Ledger.Id(move),0))["request"]!.AsObject());
            JsonObject Unit()=>warehouse.Snapshot()["handling"]!["units"]!.AsArray().Single(n=>n!["id"]!.ToString()==unit.ToString())!.AsObject();
            check(Unit()["position"]!.ToString()=="storage.inbound.dock01","pickup wait retains confirmed source position");
            var reserved=false;try {ledger.Db.Transaction(u=>{HandlingUnits.Capacity(u,u.Run(),"storage.raw.r01.b01.l01","raw");return true;});}catch(Conflict){reserved=true;}
            check(reserved,"pending fleet request reserves destination before robot pickup");
            var initial=request.ToJsonString();Advance();ledger.Execute(Ledger.Id(move));
            check(ledger.Db.Transaction(u=>u.One("SELECT request FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request))["request"]!.ToJsonString())==initial,"request retry preserves effective time and identity");
            void Event(string kind,double time) {var body=(JsonObject)request.DeepClone();body.Remove("id");body["job_id"]=request["id"]!.DeepClone();body["kind"]=kind;body["route_version"]=1;body["robot_id"]="robot-01";body["effective_time"]=time;ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=@p0 WHERE id=@p1",new JsonObject {["request"]=request.DeepClone(),["events"]=new JsonArray(new JsonObject {["body"]=body})},Ledger.Id(request));return true;});}
            Event("pickup_ready",0);Advance();check(ledger.Execute(Ledger.Id(move))=="waiting","pickup commits transit and waits for arrival");
            check(Unit()["state"]!.ToString()=="in_transit"&&Unit()["position"] is null,"moving unit is nonallocatable and has no fabricated shelf placement");
            check(ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM warehouse_fleet_outbox WHERE job_id=@p0 AND kind='departure'",Ledger.Id(request)).Count)==1,"departure proof commits with native transit");
            var now=Ledger.Num(ledger.Status()["run"]!.AsObject(),"granted");Event("arrival",now+3);Advance();check(ledger.Execute(Ledger.Id(move))=="waiting","future arrival cannot complete at an earlier native grant");
            Advance();ledger.Execute(Ledger.Id(move));Advance();check(ledger.Execute(Ledger.Id(move))=="completed","eligible arrival completes native placement");
            check(Unit()["position"]!.ToString()=="storage.raw.r01.b01.l01"&&ledger.Execute(Ledger.Id(move))=="duplicate","arrival places once and retry is idempotent");
            check(ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM warehouse_fleet_outbox WHERE job_id=@p0 AND kind='receipt'",Ledger.Id(request)).Count)==1,"receipt proof commits with confirmed shelf placement");
            var product=Guid.NewGuid();
            ledger.Db.Transaction(u=>{var run=u.Run();u.Exec("UPDATE warehouse_stock SET on_hand=1 WHERE run_id=@p0 AND sku='PRODUCT' AND location='FINISHED-A'",Ledger.Id(run));return true;});
            var finished=Submit("convert",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=1,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=product.ToString(),["quantity"]=1,["position"]="storage.finished.r01.b01.l01"})});Advance();ledger.Execute(Ledger.Id(finished));
            var reserve=Submit("reserve",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=1,["purpose"]="customer",["correlation_id"]=correlation.ToString()});Advance();check(ledger.Execute(Ledger.Id(reserve))=="completed","coordinated stock reserves through native whole-unit rules");
            var pick=Submit("pick",new JsonObject {["reference"]=reserve["id"]!.DeepClone()});Advance();check(ledger.Execute(Ledger.Id(pick))=="waiting","customer pick waits for physical shelf retrieval");
            void Physical(Guid command,string kind) {
                var id=Fleet.Job(product,command,0);var r=ledger.Db.Transaction(u=>u.One("SELECT request FROM warehouse_fleet_jobs WHERE id=@p0",id)["request"]!.AsObject());
                var b=(JsonObject)r.DeepClone();b.Remove("id");b["job_id"]=id.ToString();b["kind"]=kind;b["robot_id"]="robot-01";b["route_version"]=1;b["effective_time"]=Ledger.Num(ledger.Status()["run"]!.AsObject(),"granted");
                ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=@p0 WHERE id=@p1",new JsonObject {["request"]=r.DeepClone(),["events"]=new JsonArray(new JsonObject {["body"]=b})},id);return true;});
            }
            Physical(Ledger.Id(pick),"pickup_ready");Advance();check(ledger.Execute(Ledger.Id(pick))=="waiting","picked load remains transit until staging arrival");
            Physical(Ledger.Id(pick),"arrival");Advance();check(ledger.Execute(Ledger.Id(pick))=="completed","physical staging arrival confirms customer pick");
            var transfer=Submit("transfer",new JsonObject {["reference"]=reserve["id"]!.DeepClone(),["destination"]="DISPATCH"});Advance();check(ledger.Execute(Ledger.Id(transfer))=="waiting","internal transfer cannot depart before pickup readiness");
            Physical(Ledger.Id(transfer),"pickup_ready");Advance();check(ledger.Execute(Ledger.Id(transfer))=="waiting","internal transfer departure preserves native stock retirement while awaiting receipt");
            Physical(Ledger.Id(transfer),"arrival");Advance();check(ledger.Execute(Ledger.Id(transfer))=="completed","internal transfer physical arrival commits native receipt before aggregate completion");
            var arrive=Submit("arrive",new JsonObject {["reference"]=transfer["id"]!.DeepClone()});Advance();check(ledger.Execute(Ledger.Id(arrive))=="completed","explicit internal transfer arrival replays committed physical receipt");

        } finally {settings.FleetMode="disabled";var current=ledger.Status()["run"]!.AsObject();ledger.Control("reset",new JsonObject {["confirm_run_id"]=current["id"]!.DeepClone()},audit);}
    }
    public static async Task Transport(Ledger ledger,Settings settings,Action<bool,string> check) {
        var run=ledger.Status()["run"]!.AsObject();var unit=Guid.NewGuid();var command=Guid.NewGuid();
        var oldUrl=settings.FleetUrl;var oldToken=settings.FleetToken;
        settings.FleetMode="coordinated";settings.FleetRun=Guid.NewGuid().ToString();settings.FleetEpoch=Guid.NewGuid().ToString();settings.FleetUrl="http://127.0.0.1:18775";settings.FleetToken="fleet-private-test";
        var request=ledger.Db.Transaction(u=>Fleet.Request(u,u.Run(),settings,unit,command,0,"storage.inbound.dock01","storage.raw.r01.b01.l01"));
        using var server=new System.Net.HttpListener();server.Prefixes.Add(settings.FleetUrl+"/");server.Start();var bodies=new List<string>();var committed=true;var authorized=true;var admitted=false;var proofCommitted=true;var receiptDelivered=false;Guid? blocked=null;var admittedJobs=new HashSet<Guid>();
        var serving=Task.Run(async ()=>{
            try {while(server.IsListening) {
                var context=await server.GetContextAsync();authorized&=context.Request.Headers["Authorization"]=="Bearer fleet-private-test";
                var path=context.Request.Url!.AbsolutePath;
                if(context.Request.HttpMethod=="POST") {
                    using var reader=new StreamReader(context.Request.InputStream);var body=await reader.ReadToEndAsync();
                    if(path=="/v1/jobs") {
                        var incoming=JsonNode.Parse(body)!.AsObject();
                        if(Ledger.Id(incoming)==blocked){context.Response.StatusCode=409;context.Response.Close();continue;}
                        if(Ledger.Id(incoming)!=Ledger.Id(request)&&!receiptDelivered){context.Response.StatusCode=409;context.Response.Close();continue;}
                        bodies.Add(body);committed&=ledger.Db.Transaction(u=>JsonNode.DeepEquals(u.One("SELECT request FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(incoming))["request"],incoming));
                        // Admission committed, but its first HTTP reply is lost/retryable.
                        admittedJobs.Add(Ledger.Id(incoming));admitted=true;context.Response.StatusCode=bodies.Count==1?503:200;
                    } else {
                        if(path.EndsWith("/proofs/receipt"))receiptDelivered=true;
                        proofCommitted&=ledger.Db.Transaction(u=>u.One("SELECT departure FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request))["departure"] is JsonObject);
                        context.Response.StatusCode=200;
                    }
                    await context.Response.OutputStream.WriteAsync(System.Text.Encoding.UTF8.GetBytes("{}"));
                } else {
                    context.Response.StatusCode=admitted?200:404;
                    var body=(JsonObject)request.DeepClone();body.Remove("id");body["job_id"]=request["id"]!.DeepClone();body["kind"]="pickup_ready";body["route_version"]=1;body["robot_id"]="robot-01";
                    var response=new JsonObject {["request"]=request.DeepClone(),["fleet_scope"]=new JsonObject {["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["offset"]=0},["events"]=new JsonArray(new JsonObject {["body"]=body})};
                    await context.Response.OutputStream.WriteAsync(System.Text.Encoding.UTF8.GetBytes(response.ToJsonString()));
                }
                context.Response.Close();
            }}catch(System.Net.HttpListenerException){}catch(ObjectDisposedException){}
        });
        try {
            await Fleet.Pump(ledger,settings,CancellationToken.None);
            check(ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM warehouse_fleet_outbox WHERE job_id=@p0 AND sent_at IS NULL",Ledger.Id(request)).Count)==1,"lost admission reply retains durable request for retry");
            await Task.Delay(1100);await Fleet.Pump(ledger,settings,CancellationToken.None);
            check(bodies.Count==2&&bodies[0]==bodies[1]&&committed&&authorized,"HTTP retries exact committed request with private authentication after SQL commit");
            ledger.Db.Transaction(u=>{Fleet.Require(u,u.Run(),request,"pickup_ready");Fleet.Proof(u,u.Run(),request,"departure");return true;});
            await Fleet.Pump(ledger,settings,CancellationToken.None);
            check(proofCommitted&&ledger.Db.Transaction(u=>u.Query("SELECT 1 FROM warehouse_fleet_outbox WHERE job_id=@p0 AND kind='departure' AND sent_at IS NOT NULL",Ledger.Id(request)).Count)==1,"HTTP proof delivery observes committed native proof before marking delivery");
            ledger.Db.Transaction(u=>{Fleet.Proof(u,u.Run(),request,"receipt");Fleet.Request(u,u.Run(),settings,unit,Guid.NewGuid(),0,"storage.raw.r01.b01.l01","storage.outbound.dock01");return true;});
            await Fleet.Pump(ledger,settings,CancellationToken.None);
            check(receiptDelivered,"committed old receipt is delivered before an immediate next-unit request can conflict and block it");
            var independent=ledger.Db.Transaction(u=>{var r=u.Run();var bad=Fleet.Request(u,r,settings,Guid.NewGuid(),Guid.NewGuid(),0,"storage.inbound.dock01","storage.raw.r01.b02.l01");blocked=Ledger.Id(bad);return Fleet.Request(u,r,settings,Guid.NewGuid(),Guid.NewGuid(),0,"storage.inbound.dock02","storage.raw.r01.b03.l01");});
            await Fleet.Pump(ledger,settings,CancellationToken.None);
            check(admittedJobs.Contains(Ledger.Id(independent)),"one conflicting outbox item cannot prevent an independent committed request from delivery");
            ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=jsonb_set(observation,'{events,0,body,effective_time}','5'::jsonb) WHERE id=@p0",Ledger.Id(request));return true;});
            var future=false;try{ledger.Db.Transaction(u=>{Fleet.Require(u,u.Run(),request,"pickup_ready");return true;});}catch(FleetWait){future=true;}
            check(future,"unmapped future fleet event remains ineligible");
            ledger.Db.Transaction(u=>{Fleet.Require(u,u.Run(),request,"pickup_ready",5);return true;});check(true,"configured source time offset authorizes eligible mapped physical fact");
            ledger.Db.Transaction(u=>{u.Exec("UPDATE warehouse_fleet_jobs SET observation=jsonb_set(observation,'{events,0,body,epoch}',to_jsonb(@p0::text)) WHERE id=@p1",Guid.NewGuid().ToString(),Ledger.Id(request));return true;});
            var fenced=false;try{ledger.Db.Transaction(u=>{Fleet.Require(u,u.Run(),request,"pickup_ready",5);return true;});}catch(FleetWait){fenced=true;}
            check(fenced,"matching time cannot authorize a physical proof from another fleet epoch");

        } finally {server.Stop();await serving;settings.FleetMode="disabled";settings.FleetUrl=oldUrl;settings.FleetToken=oldToken;}
    }
    public static void Configuration(Action<bool,string> check) {
        var previous=Environment.GetEnvironmentVariable("FLEET_MODE");
        try {
            Environment.SetEnvironmentVariable("FLEET_MODE","coordinated");
            var rejected=false;try { _=new Settings(); }catch(Validation){rejected=true;}
            check(rejected,"coordinated fleet requires explicit scope and private credentials");
        } finally {Environment.SetEnvironmentVariable("FLEET_MODE",previous);}
    }
}
