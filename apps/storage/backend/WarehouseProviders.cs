using System.Text.Json.Nodes;
namespace Storage;

public static class WarehouseProviders
{
    public static JsonObject Input(JsonObject envelope) {
        Rules.Integer(envelope["aggregate_version"],1,1);
        var type=Rules.Text(envelope["type"]); var payload=envelope["payload"] as JsonObject??throw new Validation("Payload object required");
        string action,boundary;
        switch(type) {
            case "storage.receipt.v1": action="expect"; boundary="supply"; Rules.Fields(payload,"sku","location","quantity"); break;
            case "storage.request.v1": action="reserve"; boundary="requests"; Rules.Fields(payload,"sku","location","quantity","purpose"); break;
            case "storage.release.v1": action="release"; boundary="requests"; Rules.Fields(payload,"reference"); break;
            case "storage.pick.v1": action="pick"; boundary="requests"; Rules.Fields(payload,"reference"); break;
            case "storage.transfer.v1": action="transfer"; boundary="requests"; Rules.Fields(payload,"reference","destination"); break;
            case "storage.transfer.arrived.v1": action="arrive"; boundary="requests"; Rules.Fields(payload,"reference"); break;
            default: throw new Validation("Unsupported storage boundary event type");
        }
        if(envelope["boundary"]!.ToString()!=boundary) throw new Validation("Storage event type belongs to a different boundary");
        var body=(JsonObject)payload.DeepClone(); body["action"]=action; body["run_id"]=envelope["run_id"]!.DeepClone(); body["epoch"]=envelope["epoch"]!.DeepClone(); body["due_at"]=envelope["effective_time"]!.DeepClone();
        if(action is "expect" or "reserve") body["correlation_id"]=envelope["correlation_id"]!.DeepClone();
        return Warehouse.Validate(body);
    }
    public static void Seed(Ledger ledger,Settings settings)=>ledger.Db.Transaction(u=> {
        var run=u.Run(); if(run["state"]!.ToString()!="running") return false;
        Warehouse.Ensure(u,run); var id=Ledger.Id(run); var scenario=new Scenario(run["scenario"]!.AsObject());
        var threshold=Math.Max(Ledger.Num(run,"granted"),Ledger.Num(run,"requested"))+settings.Quantum;
        var slot=Math.Max(1,(long)Math.Ceiling(threshold/scenario.Interval)); var supplyDue=scenario.NextDue((slot-1)*scenario.Interval,scenario.Interval);
        slot=(long)Math.Ceiling(supplyDue/scenario.Interval);
        var localDue=scenario.NextDue(Math.Max(Ledger.Num(run,"granted"),Ledger.Num(run,"requested")),settings.Quantum);
        void Schedule(string key,string action,JsonObject fields,double due) {
            if(fields["reference"] is not null) {
                if(u.Query("SELECT 1 FROM warehouse_commands WHERE run_id=@p0 AND status='pending' AND command->>'reference'=@p1 AND command->>'action'=@p2",id,fields["reference"]!.ToString(),action).Count>0) return;
                key+=":"+slot;
            }
            key="warehouse:"+key;
            if(u.Query("SELECT 1 FROM jobs WHERE run_id=@p0 AND idempotency_key=@p1",id,key).Count>0) return;
            var body=(JsonObject)fields.DeepClone(); body["action"]=action; body["run_id"]=id.ToString(); body["epoch"]=run["epoch"]!.DeepClone(); body["due_at"]=due;
            Warehouse.Submit(u,run,key,body,new Audit(Guid.NewGuid(),"storage-synthetic","service","warehouse:"+action,key,"controller"),settings.Quantum,true);
        }
        var products=u.Query("SELECT sku,kind FROM warehouse_catalog WHERE run_id=@p0 ORDER BY sku",id);
        var locations=u.Query("SELECT code FROM warehouse_locations WHERE run_id=@p0 ORDER BY code",id);
        string Location(string kind) {
            var preferred=kind=="raw"?"RAW-A":"FINISHED-A";
            return locations.Any(x=>x["code"]!.ToString()==preferred)?preferred:locations[0]["code"]!.ToString();
        }
        foreach(var product in products) {
            var sku=product["sku"]!.ToString(); var kind=product["kind"]!.ToString(); var location=Location(kind);
            var quantity=Rules.Quantity(scenario.Seed,"storage","supply:"+sku,slot);
            var correlation=Rules.Uuid5(id,$"{run["epoch"]}:{scenario.Seed}:{sku}:{slot}").ToString();
            var fields=new JsonObject {["sku"]=sku,["location"]=location,["quantity"]=quantity,["correlation_id"]=correlation};
            if(settings.Providers["supply"]!.ToString()=="synthetic") Schedule($"supply:{sku}:{slot}","expect",fields,supplyDue);
            if(settings.Providers["requests"]!.ToString()=="synthetic") {
                var stock=u.One("SELECT on_hand-reserved AS available FROM warehouse_stock WHERE run_id=@p0 AND sku=@p1 AND location=@p2",id,sku,location);
                var available=stock["available"]!.GetValue<int>();
                if(available>0) { fields["quantity"]=Math.Min(quantity,available); fields["purpose"]=kind=="raw"?"production":"customer"; Schedule($"demand:{sku}:{slot}","reserve",fields,supplyDue); }
            }
        }
        // Advance only provider-owned records; employee work remains available
        // for employee decisions. Every action still races through Execute().
        string Owned(string table)=>$"SELECT w.* FROM {table} w JOIN jobs j ON j.id=w.id WHERE w.run_id=@p0 AND (j.idempotency_key LIKE 'warehouse:%' OR j.idempotency_key LIKE 'boundary:%')";
        foreach(var receipt in u.Query(Owned("warehouse_receipts")+" AND w.status='expected'",id)) Schedule("receive:"+receipt["id"],"receive",new JsonObject {["reference"]=receipt["id"]!.DeepClone()},localDue);
        foreach(var reservation in u.Query(Owned("warehouse_reservations")+" AND w.status IN ('reserved','picked')",id)) {
            var reference=new JsonObject {["reference"]=reservation["id"]!.DeepClone()};
            var action=reservation["status"]!.ToString()=="picked"?"transfer":reservation["purpose"]!.ToString()=="production"?"issue":"pick";
            // Shipping reserves every line before authorizing customer picks/departures.
            if((action is "pick" or "transfer")&&settings.Providers["requests"]!.ToString()!="synthetic") continue;
            if(action=="transfer") { var origin=reservation["location"]!.ToString(); reference["destination"]=locations.Any(x=>x["code"]!.ToString()=="DISPATCH")&&origin!="DISPATCH"?"DISPATCH":locations.First(x=>x["code"]!.ToString()!=origin)["code"]!.DeepClone(); }
            Schedule(action+":"+reservation["id"],action,reference,localDue);
        }
        if(settings.Providers["requests"]!.ToString()=="synthetic") foreach(var transfer in u.Query(Owned("warehouse_transfers")+" AND w.status='in_transit'",id)) Schedule("arrive:"+transfer["id"],"arrive",new JsonObject {["reference"]=transfer["id"]!.DeepClone()},scenario.NextDue(localDue,settings.Quantum*5));
        return true;
    });
}
