using Storage;
using System.Text.Json.Nodes;

public static class CustodyTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        var audit=new Audit(Guid.NewGuid(),"custody-test","operator","test:custody","","tests");
        void Reset() { var r=ledger.Status()["run"]!.AsObject();ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit); }
        Reset();var warehouse=new Warehouse(ledger,settings);var correlation=Guid.NewGuid();double time=0;
        Guid Submit(string action,JsonObject fields) {
            var r=ledger.Status()["run"]!.AsObject();var body=(JsonObject)fields.DeepClone();body["run_id"]=r["id"]!.DeepClone();body["epoch"]=r["epoch"]!.DeepClone();body["due_at"]=++time;body["action"]=action;
            var command=warehouse.Submit(Guid.NewGuid().ToString(),body,audit);Execute(Ledger.Id(command));return Ledger.Id(command);
        }
        void Execute(Guid id) { ledger.Heartbeat("controller");ledger.Db.Transaction(u=>{var r=u.Run();u.Exec("UPDATE runs SET granted=@p0,requested=@p0 WHERE id=@p1",time,Ledger.Id(r));return true;});check(ledger.Execute(id)=="completed","custody command completes native worker transaction"); }
        JsonObject Handling()=>warehouse.Snapshot()["handling"]!.AsObject();
        JsonObject Stock()=>warehouse.Snapshot()["inventory"]!.AsArray().Single(n=>n!["sku"]!.ToString()=="COMPONENT"&&n["location"]!.ToString()=="RAW-A")!.AsObject();
        JsonObject Command(Guid id)=>ledger.Db.Transaction(u=>u.One("SELECT * FROM warehouse_commands WHERE id=@p0",id));
        var manifest=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2});
        var receipt=Submit("expect",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=4,["correlation_id"]=correlation.ToString(),["units"]=manifest});Submit("receive",new JsonObject {["reference"]=receipt.ToString()});
        var reservation=Submit("reserve",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=4,["purpose"]="production",["correlation_id"]=correlation.ToString()});
        JsonObject Issue(){var destinations=new JsonObject();for(int i=0;i<manifest.Count;i++)destinations[manifest[i]!["id"]!.ToString()]=$"manufacturing.cell02.input{i+1:00}";return new JsonObject {["reference"]=reservation.ToString(),["unit_destinations"]=destinations};}
        var providers=settings.Providers;var peers=settings.Peers;var outputs=settings.Outputs;var federation=settings.Federation;
        try {
            settings.Federation="custody-test";settings.Providers=new JsonObject {["supply"]="synthetic",["requests"]="helics"};settings.Peers=new JsonObject {["requests"]=new JsonObject {["source"]="manufacturing",["endpoint"]="manufacturing/events"}};
            settings.Outputs=new JsonArray();var unrouted=Submit("issue",Issue());
            check(Command(unrouted)["status"]!.ToString()=="rejected"&&Handling()["units"]!.AsArray().All(n=>n!["position"] is not null),"unconfigured connected issue cannot silently fall back to synthetic departure");
            settings.Outputs=new JsonArray(new JsonObject {["destination"]="manufacturing",["boundary"]="materials",["endpoint"]="manufacturing/events"});
            var version=Command(reservation)["result"]!["version"]!.GetValue<int>();
            ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE warehouse_reservations SET version=@p0 WHERE id=@p1",int.MaxValue,reservation);return true;});
            var exhausted=Submit("issue",Issue());
            check(Command(exhausted)["status"]!.ToString()=="rejected"&&Handling()["handoffs"]!.AsArray().Count==0,"exhausted reservation counters reject before promising receiver capacity");
            ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE warehouse_reservations SET version=@p0 WHERE id=@p1",version,reservation);return true;});
            var missing=Submit("issue",new JsonObject {["reference"]=reservation.ToString()});check(Command(missing)["status"]!.ToString()=="rejected","connected issue requires receiver-assigned endpoints");
            var issue=Submit("issue",Issue());
            check(Command(issue)["status"]!.ToString()=="completed","native issue intent is durably planned");
            check(Handling()["units"]!.AsArray().All(n=>n!["state"]!.ToString()=="reserved"&&n["position"] is not null),"unaccepted source offers retain every confirmed unit position");
            check(Stock()["on_hand"]!.GetValue<int>()==4&&Stock()["reserved"]!.GetValue<int>()==4,"offers do not retire owned stock");
            var offers=ledger.Db.Transaction(u=>u.Query("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'type'='handling.offered.v1' ORDER BY id",ledger.Scope()));
            check(offers.Count==2,"issue publishes exactly one durable offer per whole unit");
            check(offers.Select(o=>o["envelope"]!["payload"]!["destination"]!.ToString()).Distinct().Count()==2,"multi-unit issue promises distinct input endpoints");
            ledger.Db.Transaction(u=>{var r=u.Run();u.Exec("UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=@p0",Ledger.Id(r));StorageCustody.Recover(u,r);StorageCustody.Recover(u,r);return true;});
            var retryOffers=ledger.Db.Transaction(u=>u.Query("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND sent_at IS NULL",Ledger.Id(offers[0]["envelope"]!.AsObject(),"run_id")));
            check(retryOffers.Count==2&&retryOffers.All(r=>offers.Any(o=>JsonNode.DeepEquals(o["envelope"],r["envelope"]))),"offer recovery retries original immutable envelopes once per window");
            var release=Submit("release",new JsonObject {["reference"]=reservation.ToString()});check(Command(release)["status"]!.ToString()=="rejected","pending custody fences source release");
            JsonObject Reply(JsonObject original,string stage) {
                var e=(JsonObject)original.DeepClone();e["type"]="handling."+stage+".v1";e["event_id"]=Guid.NewGuid().ToString();e["source"]="manufacturing";e["destination"]="storage";e["boundary"]="requests";e["effective_time"]=++time;e["payload"]!["state"]=stage;
                if(stage=="received")e["payload"]!["receipt_id"]=Guid.NewGuid().ToString();return e;
            }
            Guid Ingest(JsonObject e) {check(ledger.Ingest(e,"manufacturing/events")=="accepted","configured Manufacturing custody input accepted");return ledger.Db.Transaction(u=>Ledger.Id(u.One("SELECT id FROM jobs WHERE run_id=@p0 AND idempotency_key=@p1",Ledger.Id(e,"run_id"),"boundary:"+Ledger.Id(e,"event_id"))));}
            Guid Receive(JsonObject e) {var id=Ingest(e);Execute(id);return id;}
            var first=Reply(offers[0]["envelope"]!.AsObject(),"accepted");
            try {ledger.Ingest(first,"intruder/events");throw new Exception("Unconfigured custody peer accepted");}catch(Conflict){check(true,"custody source validates peer authority");}
            Receive(first);check(Handling()["units"]!.AsArray().All(n=>n!["position"] is not null),"one acceptance cannot partially retire a whole reservation");
            var second=Ingest(Reply(offers[1]["envelope"]!.AsObject(),"accepted"));
            ledger.Db.Transaction(u=>{u.Run();u.Exec("CREATE FUNCTION reject_storage_departure() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.envelope->>'type'='handling.departed.v1' THEN RAISE EXCEPTION 'forced custody publication failure'; END IF; RETURN NEW; END$$; CREATE TRIGGER reject_storage_departure BEFORE INSERT ON boundary_outbox FOR EACH ROW EXECUTE FUNCTION reject_storage_departure()");return true;});
            try {Execute(second);throw new Exception("Broken custody publication committed");}catch(Npgsql.PostgresException){check(Handling()["units"]!.AsArray().All(n=>n!["position"] is not null)&&Stock()["on_hand"]!.GetValue<int>()==4,"publication failure rolls back all source placements and stock retirement");}
            finally {ledger.Db.Transaction(u=>{u.Run();u.Exec("DROP TRIGGER reject_storage_departure ON boundary_outbox; DROP FUNCTION reject_storage_departure()");return true;});}
            Execute(second);
            check(Handling()["units"]!.AsArray().All(n=>n!["position"] is null&&n["state"]!.ToString()=="in_transit"),"all capacity acceptances clear source positions before publishing departure tokens");
            check(Stock()["on_hand"]!.GetValue<int>()==0&&Stock()["reserved"]!.GetValue<int>()==0,"confirmed departure retires owned stock and allocation atomically");
            var departures=ledger.Db.Transaction(u=>u.Query("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'type'='handling.departed.v1' ORDER BY id",Ledger.Id(first,"run_id")));
            check(departures.Count==2&&departures.All(n=>n["envelope"]!["payload"]!["departure_token"] is JsonObject),"every departure has durable source proof");
            var before=Handling()["movements"]!.AsArray().Count;check(ledger.Ingest(first,"manufacturing/events")=="duplicate","late repeated acceptance is idempotent");check(Handling()["movements"]!.AsArray().Count==before,"acceptance replay cannot depart twice");
            var bad=Reply(departures[0]["envelope"]!.AsObject(),"received");bad["payload"]!["unit"]!["custody_generation"]=2;bad["payload"]!["departure_token"]!["custody_generation"]=2;
            var rejected=Receive(bad);check(Command(rejected)["status"]!.ToString()=="rejected"&&Handling()["units"]!.AsArray().All(n=>n!["state"]!.ToString()=="in_transit"),"forged newer generation cannot retire source custody");
            var receipts=departures.Select(d=>Reply(d["envelope"]!.AsObject(),"received")).ToArray();foreach(var received in receipts)Receive(received);
            check(Handling()["units"]!.AsArray().All(n=>n!["state"]!.ToString()=="dispatched"&&n["position"] is null),"matching receipt retires only the same source custody generation");
            check(Handling()["handoffs"]!.AsArray().All(n=>n!["state"]!.ToString()=="acknowledged"),"source projection exposes completed custody proofs");
            var originalAck=ledger.Db.Transaction(u=>u.One("SELECT envelope FROM boundary_outbox WHERE envelope->>'aggregate_id'=@p0 AND envelope->>'type'='handling.acknowledged.v1'",receipts[0]["aggregate_id"]!.ToString())["envelope"]!.DeepClone());
            ledger.Db.Transaction(u=>{var r=u.Run();u.Exec("UPDATE boundary_outbox SET sent_at=clock_timestamp()-interval '10 seconds' WHERE run_id=@p0",Ledger.Id(r));StorageCustody.Recover(u,r);return true;});
            check(ledger.Ingest(receipts[0],"manufacturing/events")=="duplicate","lost acknowledgement retries the identical receipt event");
            var repeatedAck=ledger.Db.Transaction(u=>u.One("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND sent_at IS NULL",Ledger.Id(receipts[0],"run_id"))["envelope"]!);
            check(JsonNode.DeepEquals(originalAck,repeatedAck),"lost acknowledgement retransmits the original complete envelope without another retirement");
            var more=Submit("expect",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=4,["correlation_id"]=correlation.ToString(),["units"]=new JsonArray(new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2},new JsonObject {["id"]=Guid.NewGuid().ToString(),["quantity"]=2})});Submit("receive",new JsonObject {["reference"]=more.ToString()});
            Guid Reserve()=>Submit("reserve",new JsonObject {["sku"]="COMPONENT",["location"]="RAW-A",["quantity"]=2,["purpose"]="production",["correlation_id"]=correlation.ToString()});
            var a=Reserve();var b=Reserve();
            JsonObject Map(Guid reference,string position) {var unit=ledger.Db.Transaction(u=>u.One("SELECT id FROM warehouse_handling_units WHERE reservation_id=@p0",reference));return new JsonObject {["reference"]=reference.ToString(),["unit_destinations"]=new JsonObject {[unit["id"]!.ToString()]=position}};}
            var intent=Submit("issue",Map(a,"manufacturing.cell03.input01"));check(Command(intent)["status"]!.ToString()=="completed","receiver may assign any configured production cell");
            var collision=Submit("issue",Map(b,"manufacturing.cell03.input01"));check(Command(collision)["status"]!.ToString()=="rejected","independent reservations cannot promise the same receiving input");
            var distinct=Submit("issue",Map(b,"manufacturing.cell03.input02"));check(Command(distinct)["status"]!.ToString()=="completed","independent reservations preserve distinct receiver-assigned endpoints");
        } finally {settings.Providers=providers;settings.Peers=peers;settings.Outputs=outputs;settings.Federation=federation;}
        Reset();
    }
}
