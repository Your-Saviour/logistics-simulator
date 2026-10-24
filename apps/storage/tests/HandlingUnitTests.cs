using Storage;
using System.Text.Json.Nodes;

public static class HandlingUnitTests
{
    public static async Task Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"handling-test","operator","test:handling","","tests");
        void Reset() { var old=ledger.Status()["run"]!.AsObject(); ledger.Control("reset",new JsonObject {["confirm_run_id"]=old["id"]!.DeepClone()},audit); }
        Reset(); var warehouse=new Warehouse(ledger,settings); var correlation=Guid.NewGuid();
        JsonObject Body(string action,JsonObject fields) {
            var run=ledger.Status()["run"]!.AsObject(); var body=(JsonObject)fields.DeepClone();
            body["action"]=action; body["run_id"]=run["id"]!.DeepClone(); body["epoch"]=run["epoch"]!.DeepClone();
            body["due_at"]=Math.Max(Ledger.Num(run,"requested"),Ledger.Num(run,"granted"))+settings.Quantum; return body;
        }
        void Advance() { var run=ledger.Status()["run"]!.AsObject(); var time=Ledger.Num(run,"granted")+settings.Quantum; ledger.Heartbeat("controller"); check(ledger.Prepare(time,Ledger.Id(run,"epoch")),"unit work respects grant barrier"); ledger.Grant(time,Ledger.Id(run,"epoch")); }
        JsonObject Done(Guid command)=>warehouse.Snapshot()["commands"]!.AsArray().Select(x=>x!.AsObject()).Single(x=>Ledger.Id(x)==command);
        Guid Submit(string action,JsonObject fields) { var command=warehouse.Submit(Guid.NewGuid().ToString(),Body(action,fields),audit); Advance(); ledger.Execute(Ledger.Id(command)); return Ledger.Id(command); }
        JsonObject Ref(Guid id)=>new() {["reference"]=id.ToString()};
        var four=Guid.NewGuid(); var six=Guid.NewGuid();
        var expected=Submit("expect",new JsonObject {["sku"]="COMPONENT",["quantity"]=10,["location"]="RAW-A",["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=four.ToString(),["quantity"]=4},new JsonObject {["id"]=six.ToString(),["quantity"]=6})});
        check(Done(expected)["status"]!.ToString()=="completed","whole-unit receipt manifest accepted");
        var receive=Submit("receive",Ref(expected));
        check(Done(receive)["status"]!.ToString()=="completed","whole-unit receipt commits");
        JsonObject Handling()=>warehouse.Snapshot()["handling"]!.AsObject();
        JsonObject Unit(Guid id)=>Handling()["units"]!.AsArray().Select(x=>x!.AsObject()).Single(x=>Ledger.Id(x)==id);
        check(Handling()["units"]!.AsArray().Count==2&&Unit(four)["barcode"]!.ToString()=="HU-"+four.ToString("N").ToUpperInvariant(),"receipt creates unique immutable barcodes");
        check(Unit(four)["position"]!.ToString().StartsWith("storage.inbound.dock")&&Unit(four)["contents"]![0]!["quantity"]!.GetValue<int>()==4,"receipt records exact inbound endpoint and whole contents");
        var duplicate=Submit("receive",Ref(expected));
        check(Done(duplicate)["status"]!.ToString()=="rejected"&&Handling()["units"]!.AsArray().Count==2,"duplicate receipt cannot duplicate units");
        JsonObject Reserve(int quantity)=>new() {["sku"]="COMPONENT",["quantity"]=quantity,["location"]="RAW-A",["correlation_id"]=correlation.ToString(),["purpose"]="production"};
        var partial=Submit("reserve",Reserve(5));
        check(Done(partial)["status"]!.ToString()=="rejected"&&Done(partial)["error"]!.ToString().Contains("whole"),"partial-unit demand is explicit and leaves all units available");
        var body=Body("reserve",Reserve(6));
        var commands=await Task.WhenAll(Enumerable.Range(0,2).Select(_=>Task.Run(()=>warehouse.Submit(Guid.NewGuid().ToString(),body,audit)))); Advance();
        await Task.WhenAll(commands.Select(c=>Task.Run(()=>ledger.Execute(Ledger.Id(c)))));
        var winner=commands.Single(c=>Done(Ledger.Id(c))["status"]!.ToString()=="completed");
        check(commands.Count(c=>Done(Ledger.Id(c))["status"]!.ToString()=="rejected")==1&&Unit(six)["state"]!.ToString()=="reserved","concurrent requests allocate a whole unit once");
        var placed=Submit("putaway",new JsonObject {["unit_id"]=four.ToString(),["destination"]="storage.raw.r01.b01.l02"});
        check(Done(placed)["status"]!.ToString()=="completed"&&Unit(four)["position"]!.ToString()=="storage.raw.r01.b01.l02","putaway records exact elevated shelf endpoint");
        Submit("release",Ref(Ledger.Id(winner)));
        var full=Submit("putaway",new JsonObject {["unit_id"]=six.ToString(),["destination"]="storage.raw.r01.b01.l02"});
        check(Done(full)["status"]!.ToString()=="rejected"&&Unit(six)["position"]!.ToString().StartsWith("storage.inbound.dock"),"occupied shelf rejection preserves source placement");
        var incompatible=Submit("putaway",new JsonObject {["unit_id"]=six.ToString(),["destination"]="storage.finished.r01.b01.l01"});
        check(Done(incompatible)["status"]!.ToString()=="rejected","raw unit cannot occupy finished shelf");
        var moves=Handling()["movements"]!.AsArray();
        check(moves.Count==3&&moves.All(m=>m!["barcode"] is not null&&m["epoch"] is not null&&m["sequence"] is not null),"physical history retains barcode scope and per-unit sequence without reservation movements");
        var replacement=new Warehouse(new Ledger(ledger.Db,settings),settings);
        check(JsonNode.DeepEquals(Handling(),replacement.Snapshot()["handling"]),"unit state and physical history survive process replacement");
        var projection=warehouse.Projection();
        check(projection["snapshot"]!["handling"]!["units"]!.AsArray().Count==2,"department projection includes real unit ledger");
        var original=Unit(four)["contents"]!.DeepClone();
        var stale=Body("putaway",new JsonObject {["unit_id"]=four.ToString(),["destination"]="storage.raw.r01.b02.l01"});
        Reset();
        try { warehouse.Submit(Guid.NewGuid().ToString(),stale,audit); throw new Exception("Old unit command accepted"); } catch(Conflict) { check(true,"unit commands fence stale epochs"); }
        check(Handling()["units"]!.AsArray().Count==0,"new run excludes old unit occupancy");
        ledger.Db.Transaction(u=> { var run=u.Run();Warehouse.Ensure(u,run);u.Exec("UPDATE warehouse_stock SET on_hand=10 WHERE run_id=@p0 AND sku='COMPONENT' AND location='RAW-A'",Ledger.Id(run));return true; });
        var legacy=Submit("reserve",Reserve(4));
        check(Done(legacy)["status"]!.ToString()=="rejected"&&Done(legacy)["error"]!.ToString().Contains("conversion"),"legacy aggregate quantities cannot silently become allocated units");
        var conversion=Body("convert",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=10,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=four.ToString(),["quantity"]=4,["position"]="storage.raw.r01.b01.l01"},new JsonObject {["id"]=six.ToString(),["quantity"]=6,["position"]="storage.raw.r01.b02.l01"})});
        // IDs cannot be recycled from the previous run; conversion uses fresh identities.
        conversion["units"]![0]!["id"]=Guid.NewGuid().ToString();conversion["units"]![1]!["id"]=Guid.NewGuid().ToString();
        var badConversion=(JsonObject)conversion.DeepClone();badConversion["units"]![1]!["position"]="storage.raw.r01.b01.l01";
        var failed=Submit("convert",badConversion);
        check(Done(failed)["status"]!.ToString()=="rejected"&&Handling()["units"]!.AsArray().Count==0,"conversion capacity failure rolls back every unit");
        conversion["due_at"]=Body("convert",new JsonObject())["due_at"]!.DeepClone();
        var conversionKey=Guid.NewGuid().ToString();var convert=warehouse.Submit(conversionKey,conversion,audit);Advance();ledger.Execute(Ledger.Id(convert));
        check(Done(Ledger.Id(convert))["status"]!.ToString()=="completed"&&Handling()["units"]!.AsArray().Count==2&&Handling()["movements"]!.AsArray().Count==0,"explicit legacy conversion conserves quantities without invented physical history");
        check(Ledger.Id(warehouse.Submit(conversionKey,conversion,audit))==Ledger.Id(convert),"conversion retry returns durable command identity");
        var after=Submit("reserve",Reserve(4));check(Done(after)["status"]!.ToString()=="completed","converted units support exact allocation");
        Reset();
        var finished=Submit("expect",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=10,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=3},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=5})});Submit("receive",Ref(finished));
        var allocation=Submit("reserve",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=10,["purpose"]="customer",["correlation_id"]=correlation.ToString()});Submit("pick",Ref(allocation));
        var departure=Ref(allocation);departure["destination"]="DISPATCH";var transfer=Submit("transfer",departure);
        var pending=Handling()["units"]!.AsArray();
        check(pending.All(n=>n!["position"] is null&&n["state"]!.ToString()=="in_transit")&&pending.Select(n=>n!["destination"]!.ToString()).Distinct().Count()==3,"multi-unit departure retains distinct intended endpoints without fabricated placement");
        var spare=Guid.NewGuid();var extra=Submit("expect",new JsonObject {["sku"]="PRODUCT",["location"]="FINISHED-A",["quantity"]=1,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=spare.ToString(),["quantity"]=1})});Submit("receive",Ref(extra));
        Submit("putaway",new JsonObject {["unit_id"]=spare.ToString(),["destination"]="storage.finished.r01.b01.l01"});
        var claimed=Submit("retrieve",new JsonObject {["unit_id"]=spare.ToString(),["destination"]=pending[0]!["destination"]!.DeepClone()});
        check(Done(claimed)["status"]!.ToString()=="rejected","intended in-transit endpoints reserve capacity against competing placement");
        var arrival=Submit("arrive",Ref(transfer));
        check(Done(arrival)["status"]!.ToString()=="completed"&&Handling()["units"]!.AsArray().All(n=>n!["position"] is not null&&n["state"]!.ToString()=="available"),"multi-unit arrival places every whole unit once");
        Reset();
        var candidates=new JsonArray();for(int i=1;i<=5;i++)candidates.Add(new JsonObject {["id"]=$"18000000-0000-4000-8000-{i:000000000000}",["quantity"]=1});var large=Guid.Parse("f8000000-0000-4000-8000-000000000001");candidates.Add(new JsonObject {["id"]=large.ToString(),["quantity"]=5});
        var supplied=Submit("expect",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=10,["correlation_id"]=correlation.ToString(),["units"]=candidates});Submit("receive",Ref(supplied));var minimal=Submit("reserve",Reserve(5));
        check(Done(minimal)["status"]!.ToString()=="completed"&&Unit(large)["state"]!.ToString()=="reserved"&&Handling()["units"]!.AsArray().Count(n=>n!["state"]!.ToString()=="reserved")==1,"production selection considers later smaller-footprint whole-unit solutions");
        var fourLarge=Guid.Parse("e8000000-0000-4000-8000-000000000001");var extraFour=Submit("expect",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=4,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=fourLarge.ToString(),["quantity"]=4})});Submit("receive",Ref(extraFour));var fewer=Submit("reserve",Reserve(4));
        check(Done(fewer)["status"]!.ToString()=="completed"&&Unit(fourLarge)["state"]!.ToString()=="reserved","production minimizes unit footprint even when an earlier four-unit solution already fits");
        Reset();
    }
}
