using System.Text.Json.Nodes;
namespace Storage;

// The warehouse owns stock until every promised input endpoint is accepted.
// Source placement, stock retirement, departure proof and outbox commit together.
public static class StorageCustody
{
    static void Complete(JsonObject value,params string[] fields) { Rules.Fields(value,fields);if(fields.Any(f=>!value.ContainsKey(f)))throw new Validation("Complete custody object required"); }
    public static JsonObject Validate(JsonObject e) {
        var h=e["payload"] as JsonObject??throw new Validation("Custody object required");
        Complete(h,"id","run_id","epoch","source","destination_owner","origin","destination","state","unit","departure_token","receipt_id","reason");
        foreach(var key in new[]{"id","run_id","epoch"})Rules.Uuid(h[key]);
        var unit=h["unit"] as JsonObject??throw new Validation("Whole-unit proof required");
        Complete(unit,"id","barcode","run_id","epoch","contents","category","state","owner","version","custody_generation","last_sequence","position","origin","destination","handoff_id");
        var id=Rules.Uuid(unit["id"]);var state=Rules.Text(h["state"]);
        if(state is not ("accepted" or "received")||e["type"]!.ToString()!="handling."+state+".v1"||e["source"]!.ToString()!="manufacturing"||e["destination"]!.ToString()!="storage"||e["boundary"]!.ToString()!="requests"||h["source"]!.ToString()!="storage"||h["destination_owner"]!.ToString()!="manufacturing"||unit["owner"]!.ToString()!="storage"||unit["category"]!.ToString()!="raw")throw new Conflict("Unsupported source custody route or transition");
        foreach(var key in new[]{"run_id","epoch"})if(!JsonNode.DeepEquals(h[key],e[key])||!JsonNode.DeepEquals(unit[key],h[key]))throw new Conflict("Custody scope mismatch");
        if(!JsonNode.DeepEquals(h["id"],e["aggregate_id"])||!JsonNode.DeepEquals(h["id"],e["causation_id"])||!JsonNode.DeepEquals(unit["version"],e["aggregate_version"])||Rules.Text(unit["barcode"])!="HU-"+id.ToString("N").ToUpperInvariant())throw new Conflict("Custody envelope identity mismatch");
        if(unit["contents"] is not JsonArray contents||contents.Count!=1||contents[0] is not JsonObject item)throw new Validation("One complete SKU per native unit required");Complete(item,"sku","quantity");Rules.Text(item["sku"]);Rules.Integer(item["quantity"],1,10000);
        var version=Rules.Integer(unit["version"],1,int.MaxValue);var sequence=Rules.Integer(unit["last_sequence"],0,int.MaxValue);var generation=Rules.Integer(unit["custody_generation"],0,int.MaxValue);
        Rules.Text(h["origin"]);Rules.Text(h["destination"]);if(h["reason"] is not null)Rules.Text(h["reason"]);
        if(state=="accepted") {
            if(version>int.MaxValue-2||sequence>int.MaxValue-2||generation>int.MaxValue-1)throw new Conflict("Custody counters lack departure and receipt headroom");
            if(unit["state"]!.ToString()!="reserved"||!JsonNode.DeepEquals(unit["position"],h["origin"])||unit["origin"] is not null||unit["destination"] is not null||unit["handoff_id"] is not null||h["departure_token"] is not null||h["receipt_id"] is not null)throw new Conflict("Acceptance requires confirmed reserved source placement");
        } else {
            if(version>int.MaxValue-1||sequence<1||sequence>int.MaxValue-1||generation<1)throw new Conflict("Departure counters lack receipt headroom");Rules.Uuid(h["receipt_id"]);
            var token=h["departure_token"] as JsonObject??throw new Validation("Departure token required");Complete(token,"id","handoff_id","unit_id","run_id","epoch","custody_generation","last_sequence","unit_version");Rules.Uuid(token["id"]);
            if(!JsonNode.DeepEquals(token["handoff_id"],h["id"])||!JsonNode.DeepEquals(token["unit_id"],unit["id"])||!JsonNode.DeepEquals(token["unit_version"],unit["version"]))throw new Conflict("Departure token identity mismatch");
            foreach(var key in new[]{"run_id","epoch","custody_generation","last_sequence"})if(!JsonNode.DeepEquals(token[key],unit[key]))throw new Conflict("Departure token scope or sequence mismatch");
            if(unit["state"]!.ToString()!="in_transit"||unit["position"] is not null||!JsonNode.DeepEquals(unit["origin"],h["origin"])||!JsonNode.DeepEquals(unit["destination"],h["destination"])||!JsonNode.DeepEquals(unit["handoff_id"],h["id"]))throw new Conflict("Receipt requires unplaced matching source custody");
        }
        return h;
    }
    public static void RequireReleasable(Unit u,Guid reservation) {
        if(u.Query("SELECT 1 FROM warehouse_custody_sources WHERE reservation_id=@p0",reservation).Count>0)throw new Conflict("Reservation has durable custody promises; cannot release or reallocate");
    }
    public static void Begin(Unit u,JsonObject run,Settings settings,Guid command,JsonObject reservation,JsonObject body) {
        if(settings.Peers["requests"]?["source"]?.ToString()!="manufacturing"||!settings.Outputs.Any(o=>o?["destination"]?.ToString()=="manufacturing"&&o["boundary"]?.ToString()=="materials"))throw new Conflict("Production custody requires configured Manufacturing peer and materials route");
        RequireReleasable(u,Ledger.Id(reservation));
        if(reservation["version"]!.GetValue<int>()==int.MaxValue)throw new Conflict("Reservation counter lacks departure headroom");
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND state='reserved' ORDER BY id",Ledger.Id(reservation));
        if(units.Count is <1 or >4||units.Sum(r=>r["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>())throw new Conflict("Production requires an exact allocation of at most four whole input units");
        if(body["unit_destinations"] is not JsonObject destinations||destinations.Count!=units.Count||destinations.Any(p=>!units.Any(r=>Ledger.Id(r).ToString()==p.Key))||destinations.Select(p=>Rules.Text(p.Value)).Distinct().Count()!=units.Count)throw new Conflict("Explicit exact whole-unit receiving endpoint map required");
        foreach(var destination in destinations) {
            if(!HandlingUnits.ManufacturingInput(Rules.Text(destination.Value)))throw new Conflict("Raw units require known Manufacturing input endpoints");
            if(u.Query("SELECT 1 FROM warehouse_custody_sources WHERE run_id=@p0 AND epoch=@p1 AND offer->>'destination'=@p2 AND state IN ('offered','accepted','departed')",Ledger.Id(run),Ledger.Id(run,"epoch"),Rules.Text(destination.Value)).Count>0)throw new Conflict("Receiving endpoint already has an unresolved source promise");
        }
        foreach(var unit in units) {
            if(unit["category"]!.ToString()!="raw"||unit["position"] is null||unit["version"]!.GetValue<int>()>int.MaxValue-2||unit["last_sequence"]!.GetValue<int>()>int.MaxValue-2||unit["custody_generation"]!.GetValue<int>()>int.MaxValue-1)throw new Conflict("Reserved unit lacks compatible placement or custody counter headroom");
            var id=Rules.Uuid5(command,Ledger.Id(unit).ToString());
            var offer=new JsonObject {["id"]=id.ToString(),["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["source"]="storage",["destination_owner"]="manufacturing",["origin"]=unit["position"]!.DeepClone(),["destination"]=destinations[Ledger.Id(unit).ToString()]!.DeepClone(),["state"]="offered",["unit"]=HandlingUnits.Contract(unit),["departure_token"]=null,["receipt_id"]=null,["reason"]=null};
            u.Exec("INSERT INTO warehouse_custody_sources(id,run_id,epoch,unit_id,reservation_id,command_id,correlation_id,state,offer) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,'offered',@p7)",id,Ledger.Id(run),Ledger.Id(run,"epoch"),Ledger.Id(unit),Ledger.Id(reservation),command,Ledger.Id(reservation,"correlation_id"),offer);Publish(u,run,settings,offer,Ledger.Id(reservation,"correlation_id"));
        }
    }
    public static string Ingest(Ledger ledger,Settings settings,JsonObject e,string endpoint) {
        var h=Validate(e);var peer=settings.Peers["requests"];
        if(settings.Providers["requests"]?.ToString()!="helics"||peer?["source"]?.ToString()!="manufacturing"||peer["endpoint"]?.ToString()!=endpoint||e["federation_id"]!.ToString()!=settings.Federation)throw new Conflict("Unconfigured source custody peer");
        return ledger.Db.Transaction(u=> {
            var run=u.Run();if(Ledger.Id(run)!=Ledger.Id(e,"run_id")||Ledger.Id(run,"epoch")!=Ledger.Id(e,"epoch"))return "fenced";
            var old=u.Query("SELECT * FROM warehouse_custody_events WHERE event_id=@p0",Ledger.Id(e,"event_id")).FirstOrDefault();
            if(old is not null) { if(!JsonNode.DeepEquals(old["envelope"],e))throw new Conflict("Custody event identity changed");if(run["state"]!.ToString() is "running" or "held")Replay(u,run,e);return "duplicate"; }
            if(run["state"]!.ToString() is not ("running" or "held"))throw new Conflict("Inactive source custody run");
            var id=Guid.NewGuid();var due=Math.Max(Ledger.Num(run,"granted"),Ledger.Num(e,"effective_time"));
            u.Exec("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6)",id,Ledger.Id(run),Ledger.Id(run,"epoch"),"boundary:"+Ledger.Id(e,"event_id"),due,Ledger.Num(e,"effective_time"),new JsonObject {["custody"]=e.DeepClone()});
            u.Exec("INSERT INTO warehouse_commands(id,run_id,command) VALUES (@p0,@p1,@p2)",id,Ledger.Id(run),new JsonObject {["action"]="custody",["handoff_id"]=h["id"]!.DeepClone()});
            u.Exec("INSERT INTO warehouse_custody_events VALUES (@p0,@p1,@p2,@p3)",Ledger.Id(e,"event_id"),Ledger.Id(run),e,id);return "accepted";
        });
    }
    public static void Execute(Unit u,JsonObject run,Settings settings,JsonObject job) {
        u.Exec("SAVEPOINT custody_effect");
        try { var result=Apply(u,run,settings,Ledger.Id(job),job["payload"]!["custody"]!.AsObject());u.Exec("UPDATE warehouse_commands SET status='completed',result=@p0,completed_at=@p1 WHERE id=@p2",result,Ledger.Num(run,"granted"),Ledger.Id(job)); }
        catch(Exception error) when(error is Conflict or Validation) {u.Exec("ROLLBACK TO SAVEPOINT custody_effect");u.Exec("UPDATE warehouse_commands SET status='rejected',error=@p0,completed_at=@p1 WHERE id=@p2",error.Message,Ledger.Num(run,"granted"),Ledger.Id(job));}
    }
    static JsonObject Apply(Unit u,JsonObject run,Settings settings,Guid command,JsonObject e) {
        var h=Validate(e);var row=u.Query("SELECT * FROM warehouse_custody_sources WHERE id=@p0 AND run_id=@p1 AND epoch=@p2",Ledger.Id(h),Ledger.Id(run),Ledger.Id(run,"epoch")).FirstOrDefault()??throw new Conflict("Unknown source handoff");
        if(Ledger.Id(e,"correlation_id")!=Ledger.Id(row,"correlation_id"))throw new Conflict("Handoff correlation changed");
        if(h["state"]!.ToString()=="accepted") {
            var expected=(JsonObject)row["offer"]!.DeepClone();expected["state"]="accepted";if(!JsonNode.DeepEquals(expected,h))throw new Conflict("Acceptance changed immutable source offer");
            if(row["state"]!.ToString() is "departed" or "acknowledged")return h;
            u.Exec("UPDATE warehouse_custody_sources SET state='accepted',acceptance=@p0 WHERE id=@p1",h,Ledger.Id(row));
            var all=u.Query("SELECT * FROM warehouse_custody_sources WHERE reservation_id=@p0 ORDER BY unit_id",Ledger.Id(row,"reservation_id"));if(all.Any(r=>r["state"]!.ToString()!="accepted"))return h;
            var reservation=u.One("SELECT * FROM warehouse_reservations WHERE id=@p0 AND run_id=@p1",Ledger.Id(row,"reservation_id"),Ledger.Id(run));if(reservation["status"]!.ToString()!="reserved"||reservation["version"]!.GetValue<int>()==int.MaxValue)throw new Conflict("Source reservation changed or counter exhausted");
            foreach(var member in all) {
                var unit=u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(member,"unit_id"));var offer=member["offer"]!.AsObject();
                if(Ledger.Id(unit,"reservation_id")!=Ledger.Id(reservation)||!JsonNode.DeepEquals(HandlingUnits.Contract(unit),offer["unit"]))throw new Conflict("Reserved source placement or custody generation changed");
                u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,custody_generation=custody_generation+1 WHERE id=@p2",offer["destination"]!.ToString(),Ledger.Id(member),Ledger.Id(unit));
                HandlingUnits.Movement(u,run,command,unit,"depart",unit["position"]!.ToString(),offer["destination"]!.ToString(),Ledger.Id(member,"correlation_id"));
                var departed=(JsonObject)offer.DeepClone();departed["state"]="departed";var transit=HandlingUnits.Contract(u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(unit)));departed["unit"]=transit;
                departed["departure_token"]=new JsonObject {["id"]=Rules.Uuid5(Ledger.Id(member),"departure-token").ToString(),["handoff_id"]=member["id"]!.DeepClone(),["unit_id"]=unit["id"]!.DeepClone(),["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["custody_generation"]=transit["custody_generation"]!.DeepClone(),["last_sequence"]=transit["last_sequence"]!.DeepClone(),["unit_version"]=transit["version"]!.DeepClone()};
                u.Exec("UPDATE warehouse_custody_sources SET state='departed',departure=@p0 WHERE id=@p1",departed,Ledger.Id(member));Publish(u,run,settings,departed,Ledger.Id(member,"correlation_id"));
            }
            var quantity=reservation["quantity"]!.GetValue<int>();Warehouse.Move(u,run,command,"issue",reservation,-quantity,-quantity);u.Exec("UPDATE warehouse_reservations SET status='issued',version=version+1 WHERE id=@p0",Ledger.Id(reservation));return h;
        }
        if(row["departure"] is not JsonObject departure)throw new Conflict("Receipt preceded committed source departure");
        var received=(JsonObject)h.DeepClone();received["state"]="departed";received["receipt_id"]=null;if(!JsonNode.DeepEquals(departure,received))throw new Conflict("Receipt changed source departure proof");
        var ack=(JsonObject)h.DeepClone();ack["state"]="acknowledged";
        if(row["acknowledgement"] is not null) {if(!JsonNode.DeepEquals(row["acknowledgement"],ack))throw new Conflict("Receipt identity changed");return ack;}
        var current=u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(row,"unit_id"));
        if(current["state"]!.ToString()!="in_transit"||Ledger.Id(current,"handoff_id")!=Ledger.Id(h)||!JsonNode.DeepEquals(current["custody_generation"],h["unit"]!["custody_generation"])||!JsonNode.DeepEquals(current["version"],h["unit"]!["version"])||current["version"]!.GetValue<int>()==int.MaxValue)throw new Conflict("Late receipt cannot retire newer source custody");
        u.Exec("UPDATE warehouse_handling_units SET state='dispatched',version=version+1 WHERE id=@p0",Ledger.Id(current));u.Exec("UPDATE warehouse_custody_sources SET state='acknowledged',acknowledgement=@p0 WHERE id=@p1",ack,Ledger.Id(row));Publish(u,run,settings,ack,Ledger.Id(row,"correlation_id"));return ack;
    }
    static void Publish(Unit u,JsonObject run,Settings settings,JsonObject h,Guid correlation) {
        var id=Rules.Uuid5(Ledger.Id(h),"storage:"+h["state"]!.ToString());
        var e=new JsonObject {["schema_version"]="1.0",["type"]="handling."+h["state"]!.ToString()+".v1",["event_id"]=id.ToString(),["federation_id"]=settings.Federation,["run_id"]=run["id"]!.DeepClone(),["epoch"]=run["epoch"]!.DeepClone(),["correlation_id"]=correlation.ToString(),["causation_id"]=h["id"]!.DeepClone(),["aggregate_id"]=h["id"]!.DeepClone(),["aggregate_version"]=h["unit"]!["version"]!.DeepClone(),["source"]="storage",["destination"]="manufacturing",["boundary"]="materials",["effective_time"]=Ledger.Num(run,"granted")+settings.Quantum,["wall_time"]=DateTimeOffset.UtcNow.ToString("O"),["quantity_unit"]="item",["payload"]=h.DeepClone()};
        u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2) ON CONFLICT(id) DO NOTHING",id,Ledger.Id(run),e);
    }
    public static JsonArray Snapshot(Unit u,JsonObject run)=>new(u.Query("SELECT * FROM warehouse_custody_sources WHERE run_id=@p0 AND epoch=@p1 ORDER BY id",Ledger.Id(run),Ledger.Id(run,"epoch")).Select(row=>{var h=(JsonObject)(row["acknowledgement"]??row["departure"]??row["acceptance"]??row["offer"])!.DeepClone();h["state"]=row["state"]!.DeepClone();return (JsonNode?)h;}).ToArray());
    public static void Recover(Unit u,JsonObject run) {
        if(run["state"]!.ToString() is not ("running" or "held"))return;
        foreach(var row in u.Query("SELECT DISTINCT b.envelope FROM boundary_outbox b JOIN warehouse_custody_sources h ON h.id::text=b.envelope->'payload'->>'id' AND h.state=b.envelope->'payload'->>'state' WHERE h.run_id=@p0 AND h.epoch=@p1 AND h.state IN ('offered','departed') AND b.run_id=@p0 AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds'))",Ledger.Id(run),Ledger.Id(run,"epoch")))u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2)",Guid.NewGuid(),Ledger.Id(run),row["envelope"]!);
    }
    static void Replay(Unit u,JsonObject run,JsonObject incoming) {
        var stage=incoming["payload"]!["state"]!.ToString()=="accepted"?"departed":"acknowledged";var id=Rules.Uuid5(Ledger.Id(incoming,"aggregate_id"),"storage:"+stage);
        var old=u.Query("SELECT envelope FROM boundary_outbox b WHERE b.run_id=@p0 AND b.envelope->>'event_id'=@p1 AND NOT EXISTS(SELECT 1 FROM boundary_outbox n WHERE n.run_id=b.run_id AND n.envelope->>'event_id'=b.envelope->>'event_id' AND (n.sent_at IS NULL OR n.sent_at>clock_timestamp()-interval '5 seconds')) LIMIT 1",Ledger.Id(run),id.ToString()).FirstOrDefault();if(old is not null)u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2)",Guid.NewGuid(),Ledger.Id(run),old["envelope"]!);
    }
}
