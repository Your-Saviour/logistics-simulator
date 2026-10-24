using Storage;
using System.Text.Json.Nodes;

public static class WarehouseTests
{
    public static async Task Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"warehouse-test","operator","warehouse:test","","tests");
        void Reset() { var r=ledger.Status()["run"]!.AsObject(); ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit); }
        Reset(); var warehouse=new Warehouse(ledger,settings); var correlation=Guid.NewGuid();
        JsonObject Body(string action,JsonObject? fields=null) {
            var r=ledger.Status()["run"]!.AsObject(); var body=fields??new JsonObject(); body["action"]=action; body["run_id"]=r["id"]!.DeepClone(); body["epoch"]=r["epoch"]!.DeepClone(); body["due_at"]=Math.Max(Ledger.Num(r,"granted"),Ledger.Num(r,"requested"))+settings.Quantum;
            if(action=="expect"&&body["units"] is null) body["units"]=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=body["quantity"]!.DeepClone()});return body;
        }
        void Advance() { var r=ledger.Status()["run"]!.AsObject(); var next=Ledger.Num(r,"granted")+settings.Quantum; ledger.Heartbeat("controller"); check(ledger.Prepare(next,Ledger.Id(r,"epoch")),"warehouse barrier allows next quantum"); ledger.Grant(next,Ledger.Id(r,"epoch")); }
        JsonObject Stock(string sku,string loc)=>warehouse.Snapshot()["inventory"]!.AsArray().Select(x=>x!.AsObject()).Single(x=>x["sku"]!.ToString()==sku&&x["location"]!.ToString()==loc);
        JsonObject Fields(string sku,string loc,int quantity,string? purpose=null) { var f=new JsonObject {["sku"]=sku,["location"]=loc,["quantity"]=quantity,["correlation_id"]=correlation.ToString()}; if(purpose is not null) f["purpose"]=purpose; return f; }
        JsonObject Reference(Guid id)=>new() {["reference"]=id.ToString()};
        JsonObject Done(Guid id)=>warehouse.Snapshot()["commands"]!.AsArray().Select(x=>x!.AsObject()).Single(x=>Ledger.Id(x)==id);
        Guid Submit(string action,JsonObject fields) { var row=warehouse.Submit(Guid.NewGuid().ToString(),Body(action,fields),audit); var id=Ledger.Id(row); Advance(); check(ledger.Execute(id)=="completed","warehouse command settles through existing job worker path"); return id; }
        Guid Expect(string sku,string loc,int qty,params int[] sizes) { var fields=Fields(sku,loc,qty);fields["units"]=new JsonArray((sizes.Length==0?[qty]:sizes).Select(q=>(JsonNode?)new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=q}).ToArray());return Submit("expect",fields); }
        void Receive(string sku,string loc,int qty,params int[] sizes) { var receipt=Expect(sku,loc,qty,sizes); Submit("receive",Reference(receipt)); }
        check(warehouse.Snapshot()["inventory"]!.AsArray().All(x=>x!["on_hand"]!.GetValue<int>()==0),"new run starts with explicit empty inventory");
        var receiptId=Expect("COMPONENT","RAW-A",10,7,2,1);
        var body=Body("receive",Reference(receiptId)); var key=Guid.NewGuid().ToString(); var command=warehouse.Submit(key,body,audit); var id=Ledger.Id(command);
        check(Ledger.Id(warehouse.Submit(key,body,audit))==id,"warehouse API replay retains command identity");
        check(ledger.Execute(id)=="waiting","warehouse effects wait for grant"); Advance();
        var deliveries=await Task.WhenAll(Enumerable.Range(0,8).Select(_=>Task.Run(()=>ledger.Execute(id))));
        check(deliveries.Count(x=>x=="completed")==1&&deliveries.Count(x=>x=="duplicate")==7,"concurrent redeliveries receive exactly once");
        check(Stock("COMPONENT","RAW-A")["on_hand"]!.GetValue<int>()==10,"receipt commits exact stock");
        var second=Submit("receive",Reference(receiptId)); check(Done(second)["status"]!.ToString()=="rejected","new command cannot receive an already received receipt");
        var reserveBody=Body("reserve",Fields("COMPONENT","RAW-A",7,"production"));
        var contenders=await Task.WhenAll(Enumerable.Range(0,2).Select(_=>Task.Run(()=>warehouse.Submit(Guid.NewGuid().ToString(),reserveBody,audit)))); Advance();
        await Task.WhenAll(contenders.Select(c=>Task.Run(()=>ledger.Execute(Ledger.Id(c)))));
        var winner=contenders.Select(c=>Done(Ledger.Id(c))).Single(c=>c["status"]!.ToString()=="completed");
        check(contenders.Count(c=>Done(Ledger.Id(c))["status"]!.ToString()=="rejected")==1&&Stock("COMPONENT","RAW-A")["reserved"]!.GetValue<int>()==7,"concurrent reservations never double reserve");
        var issue=Submit("issue",Reference(Ledger.Id(winner))); check(Done(issue)["status"]!.ToString()=="completed"&&Stock("COMPONENT","RAW-A")["on_hand"]!.GetValue<int>()==3&&Stock("COMPONENT","RAW-A")["reserved"]!.GetValue<int>()==0,"material issue consumes exactly its reservation");
        Receive("PRODUCT","FINISHED-A",10,6,4);
        var reservation=Submit("reserve",Fields("PRODUCT","FINISHED-A",6,"customer"));
        var invalid=Submit("issue",Reference(reservation)); check(Done(invalid)["status"]!.ToString()=="rejected"&&Stock("PRODUCT","FINISHED-A")["reserved"]!.GetValue<int>()==6,"invalid workflow leaves stock and reservation unchanged");
        Submit("pick",Reference(reservation));
        var bad=Reference(reservation); bad["destination"]="UNKNOWN"; var rejected=Submit("transfer",bad);
        check(Done(rejected)["status"]!.ToString()=="rejected"&&Stock("PRODUCT","FINISHED-A")["on_hand"]!.GetValue<int>()==10,"invalid transfer rolls back departure");
        var transfer=Reference(reservation); transfer["destination"]="DISPATCH"; var transferId=Submit("transfer",transfer);
        check(Stock("PRODUCT","FINISHED-A")["on_hand"]!.GetValue<int>()==4&&Stock("PRODUCT","DISPATCH")["on_hand"]!.GetValue<int>()==0,"departure tracks goods in transit until receipt");
        // Fill the destination before arrival; receiving the transfer must be all or nothing.
        Receive("PRODUCT","DISPATCH",250);
        var full=Submit("arrive",Reference(transferId)); check(Done(full)["status"]!.ToString()=="rejected"&&warehouse.Snapshot()["transfers"]![0]!["status"]!.ToString()=="in_transit","capacity rejection retains in-transit stock");
        var movesBefore=warehouse.Snapshot()["movements"]!.AsArray().Count;
        var capacity=Expect("COMPONENT","DISPATCH",1); var capacityReceive=Submit("receive",Reference(capacity));
        check(Done(capacityReceive)["status"]!.ToString()=="rejected"&&warehouse.Snapshot()["movements"]!.AsArray().Count==movesBefore,"capacity counts all SKUs and rejects without movement writes");
        var release=Submit("reserve",Fields("COMPONENT","RAW-A",2,"production")); Submit("release",Reference(release));
        check(Stock("COMPONENT","RAW-A")["available"]!.GetValue<int>()==3,"release restores available quantity");
        ledger.Db.Transaction(u=>{ var r=u.Run();u.Exec("INSERT INTO warehouse_movements(id,command_id,run_id,action,sku,location,on_hand_delta,reserved_delta,quantity,correlation_id,reference,simulation_time) SELECT gen_random_uuid(),@p0,@p1,'receive','COMPONENT','TEST-'||n,1,0,1,@p2,@p0,0 FROM generate_series(1,205) n",id,Ledger.Id(r),correlation);return true; });
        var method=typeof(Warehouse).GetMethod("Projection");
        check(method is not null,"warehouse exposes source projection");
        JsonObject Projection()=>(JsonObject)method!.Invoke(warehouse,null)!;
        var projection=Projection();
        check(projection["effects"]!.GetValue<long>()==0&&projection["version"]!.GetValue<int>()==1&&projection["source"]!.ToString()=="storage","projection version and source");
        check(projection["events"]!.AsArray().Count>205,"projection keeps durable warehouse movements");
        check(projection["events"]!.AsArray().All(e=>e!["id"] is JsonValue&&e["correlation_id"]!.ToString()==correlation.ToString()&&e["simulation_time"] is not null),"projection preserves movement identity correlation and simulation time");
        check(projection["cursor"]!.ToString()==Projection()["cursor"]!.ToString(),"unchanged projection retains cursor");
        var stale=Body("reserve",Fields("COMPONENT","RAW-A",1,"production")); var staleCommand=warehouse.Submit(Guid.NewGuid().ToString(),stale,audit);
        Reset(); check(Projection()["events"]!.AsArray().Count==0,"projection reset excludes previous-run history"); check(ledger.Execute(Ledger.Id(staleCommand))=="fenced"&&warehouse.Snapshot()["movements"]!.AsArray().Count==0,"reset fences old deliveries and isolates stock history");
        try { warehouse.Submit(Guid.NewGuid().ToString(),stale,audit); throw new Exception("Stale warehouse request accepted"); } catch(Conflict) { check(true,"stale browser run/epoch cannot mutate new inventory"); }
        foreach(var q in new JsonNode?[]{JsonValue.Create(true),JsonValue.Create("1"),JsonValue.Create(1.5),JsonValue.Create(0)}) {
            var f=Body("expect",Fields("PRODUCT","DISPATCH",1)); f["quantity"]=q;
            try { warehouse.Submit(Guid.NewGuid().ToString(),f,audit); throw new Exception("Invalid quantity accepted"); } catch(Validation) { check(true,"strict warehouse quantities"); }
        }
        // A new worker/ledger object sees the same pending job after process loss.
        var restart=warehouse.Submit(Guid.NewGuid().ToString(),Body("expect",Fields("COMPONENT","RAW-A",2)),audit); Advance();
        var replacement=new Ledger(ledger.Db,settings); check(replacement.Execute(Ledger.Id(restart))=="completed"&&ledger.Execute(Ledger.Id(restart))=="duplicate","replacement worker resumes durable warehouse command once");
        Reset();
        Receive("COMPONENT","RAW-A",500,499,1);
        var ownedBody=Body("expect",Fields("COMPONENT","RAW-A",1));
        var owned=ledger.Db.Transaction(u=>Warehouse.Submit(u,u.Run(),"warehouse:test-owned",ownedBody,audit,settings.Quantum,true));
        Advance(); ledger.Execute(Ledger.Id(owned));
        var providers=settings.Providers;
        try {
            settings.Providers=new JsonObject {["supply"]="helics",["requests"]="helics"};
            ledger.Seed(); Advance();
            var auto=warehouse.Snapshot()["commands"]!.AsArray().Select(c=>c!.AsObject()).Single(c=>c["status"]!.ToString()=="pending");
            ledger.Execute(Ledger.Id(auto)); check(Done(Ledger.Id(auto))["status"]!.ToString()=="rejected","automatic receiving reports a full location");
            // This capacity-retry fixture uses a synthetic destination. A real
            // connected issue cannot free stock without configured acceptance.
            var free=Submit("reserve",Fields("COMPONENT","RAW-A",1,"production"));
            settings.Providers["requests"]="synthetic";Submit("issue",Reference(free));settings.Providers["requests"]="helics";
            var later=ledger.Status()["run"]!.AsObject(); var laterTime=Math.Ceiling((Ledger.Num(later,"granted")+1)/30)*30+1;
            check(ledger.Prepare(laterTime,Ledger.Id(later,"epoch")),"settled capacity rejection leaves clock eligible"); ledger.Grant(laterTime,Ledger.Id(later,"epoch"));
            ledger.Seed(); Advance();
            foreach(var pending in warehouse.Snapshot()["commands"]!.AsArray().Select(c=>c!.AsObject()).Where(c=>c["status"]!.ToString()=="pending")) ledger.Execute(Ledger.Id(pending));
            check(warehouse.Snapshot()["receipts"]!.AsArray().Single(c=>Ledger.Id(c!.AsObject())==Ledger.Id(owned))!["status"]!.ToString()=="received"&&Stock("COMPONENT","RAW-A")["on_hand"]!.GetValue<int>()==500,"automatic receiving retries next slot after capacity is freed");
        } finally { settings.Providers=providers; }
        Reset();
    }
}
