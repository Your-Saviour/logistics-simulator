using System.Text.Json.Nodes;
namespace Storage;

// All mutations execute inside the existing run lock and warehouse savepoint.
public static class HandlingUnits
{
    static readonly Dictionary<string,JsonObject> Locations=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"handling-facility.json")))!["locations"]!.AsArray().Select(n=>n!.AsObject()).ToDictionary(n=>n["id"]!.ToString());
    public static void ValidateManifest(JsonObject body) {
        if(body["units"] is not JsonArray units||units.Count is <1 or >256) throw new Validation("Explicit whole-unit manifest required (1..256 units); legacy stock needs conversion");
        var ids=new HashSet<Guid>(); var total=0;
        foreach(var n in units) {
            var unit=n as JsonObject??throw new Validation("Unit manifest object required"); Rules.Fields(unit,"id","quantity",body["action"]?.ToString()=="convert"?"position":"quantity");
            if(!ids.Add(Rules.Uuid(unit["id"]))) throw new Validation("Duplicate unit identity in receipt manifest");
            total+=Rules.Integer(unit["quantity"],1,10000);
            if(body["action"]?.ToString()=="convert") Rules.Text(unit["position"]);
        }
        if(total!=Rules.Integer(body["quantity"],1,10000)) throw new Validation("Whole-unit contents must exactly equal receipt quantity");
    }
    static JsonObject Location(string position,string category,string? kind=null) {
        if(!Locations.TryGetValue(position,out var location)||location["owner"]!.ToString()!="storage"||!location["compatible"]!.AsArray().Any(c=>c!.ToString()==category)||(kind is not null&&location["kind"]!.ToString()!=kind)) throw new Conflict("Incompatible physical position for this whole unit");
        return location;
    }
    static void Capacity(Unit u,JsonObject run,string position,string category,string? kind=null,Guid? claimant=null) {
        Location(position,category,kind);
        if(u.Query("SELECT 1 FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND (position=@p2 OR (state='in_transit' AND destination=@p2)) AND (@p3::uuid IS NULL OR id<>@p3)",Ledger.Id(run),Ledger.Id(run,"epoch"),position,claimant).Count>0) throw new Conflict("Physical slot capacity exceeded; unit remains at its recorded position");
    }
    static string Free(Unit u,JsonObject run,string prefix,string category) {
        var occupied=u.Query("SELECT position FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND position IS NOT NULL UNION SELECT destination AS position FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND state='in_transit'",Ledger.Id(run),Ledger.Id(run,"epoch")).Select(r=>r["position"]!.ToString()).ToHashSet();
        return Locations.Values.Where(l=>l["id"]!.ToString().StartsWith(prefix)&&l["compatible"]!.AsArray().Any(c=>c!.ToString()==category)).Select(l=>l["id"]!.ToString()).Order().FirstOrDefault(p=>!occupied.Contains(p))??throw new Conflict("No compatible physical slots available; retry after capacity is freed");
    }
    static JsonObject Contract(JsonObject row)=>new() {
        ["id"]=row["id"]!.DeepClone(),["barcode"]=row["barcode"]!.DeepClone(),["run_id"]=row["run_id"]!.DeepClone(),["epoch"]=row["epoch"]!.DeepClone(),
        ["version"]=row["version"]!.DeepClone(),["custody_generation"]=row["custody_generation"]!.DeepClone(),["last_sequence"]=row["last_sequence"]!.DeepClone(),
        ["category"]=row["category"]!.DeepClone(),["state"]=row["state"]!.DeepClone(),["owner"]="storage",
        ["position"]=row["position"]?.DeepClone(),["origin"]=row["origin"]?.DeepClone(),["destination"]=row["destination"]?.DeepClone(),["handoff_id"]=row["handoff_id"]?.DeepClone(),
        ["contents"]=new JsonArray(new JsonObject {["sku"]=row["sku"]!.DeepClone(),["quantity"]=row["quantity"]!.DeepClone()})
    };
    public static JsonObject Snapshot(Unit u,JsonObject run)=>new() {
        ["version"]=1,["catalog_version"]=1,
        ["units"]=new JsonArray(u.Query("SELECT * FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 ORDER BY id",Ledger.Id(run),Ledger.Id(run,"epoch")).Select(r=>(JsonNode?)Contract(r)).ToArray()),
        ["movements"]=Ledger.Array(u.Query("SELECT id,unit_id,barcode,run_id,epoch,sequence,custody_generation,origin,destination,simulation_time,action,\"references\",correlation_id FROM warehouse_unit_movements WHERE run_id=@p0 AND epoch=@p1 ORDER BY unit_id,sequence",Ledger.Id(run),Ledger.Id(run,"epoch"))),
        ["handoffs"]=new JsonArray(),["lineage"]=new JsonArray(),
        ["legacy_stock"]=Ledger.Array(u.Query("SELECT s.sku,s.location,s.on_hand-COALESCE(sum(h.quantity) FILTER(WHERE h.state IN ('available','reserved')),0) AS unplaced_quantity FROM warehouse_stock s LEFT JOIN warehouse_handling_units h ON h.run_id=s.run_id AND h.sku=s.sku AND h.logical_location=s.location WHERE s.run_id=@p0 GROUP BY s.run_id,s.sku,s.location,s.on_hand HAVING s.on_hand<>COALESCE(sum(h.quantity) FILTER(WHERE h.state IN ('available','reserved')),0) ORDER BY s.sku,s.location",Ledger.Id(run)))
    };
    static void Movement(Unit u,JsonObject run,Guid command,JsonObject unit,string action,string? origin,string destination,Guid correlation,Guid? transfer=null) {
        u.Exec("UPDATE warehouse_handling_units SET last_sequence=last_sequence+1,version=version+1 WHERE id=@p0",Ledger.Id(unit));
        var updated=u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(unit));
        u.Exec("INSERT INTO warehouse_unit_movements(id,unit_id,barcode,run_id,epoch,command_id,sequence,custody_generation,action,origin,destination,simulation_time,\"references\",correlation_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7,@p8,@p9,@p10,@p11,@p12,@p13)",Guid.NewGuid(),Ledger.Id(unit),unit["barcode"]!.ToString(),Ledger.Id(run),Ledger.Id(run,"epoch"),command,updated["last_sequence"]!.GetValue<int>(),updated["custody_generation"]!.GetValue<int>(),action,origin,destination,Ledger.Num(run,"granted"),new JsonObject {["transfer_id"]=transfer?.ToString(),["batch_id"]=null,["shipment_id"]=null},correlation);
    }
    public static void Receive(Unit u,JsonObject run,Guid command,JsonObject receipt) {
        var manifest=receipt["unit_manifest"] as JsonArray??throw new Conflict("Legacy receipt has no unit manifest; reconcile it before receipt");
        var category=u.One("SELECT kind FROM warehouse_catalog WHERE run_id=@p0 AND sku=@p1",Ledger.Id(run),receipt["sku"]!.ToString())["kind"]!.ToString();
        foreach(var n in manifest) {
            var entry=n!.AsObject(); var id=Ledger.Id(entry);
            if(u.Query("SELECT 1 FROM warehouse_handling_units WHERE id=@p0",id).Count>0) throw new Conflict("Unit identity already received; replay the original receipt");
            var position=Free(u,run,category=="raw"?"storage.inbound.dock":"storage.finished_receipt.dock",category);
            u.Exec("INSERT INTO warehouse_handling_units(id,barcode,run_id,epoch,sku,quantity,category,state,logical_location,position,receipt_id,correlation_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,'available',@p7,@p8,@p9,@p10)",id,"HU-"+id.ToString("N").ToUpperInvariant(),Ledger.Id(run),Ledger.Id(run,"epoch"),receipt["sku"]!.ToString(),entry["quantity"]!.GetValue<int>(),category,receipt["location"]!.ToString(),position,Ledger.Id(receipt),Ledger.Id(receipt,"correlation_id"));
            Movement(u,run,command,u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",id),"receive",null,position,Ledger.Id(receipt,"correlation_id"));
        }
    }
    public static JsonObject Convert(Unit u,JsonObject run,Guid command,JsonObject body) {
        if(u.Query("SELECT 1 FROM warehouse_reservations WHERE run_id=@p0 AND status IN ('reserved','picked') UNION ALL SELECT 1 FROM warehouse_transfers WHERE run_id=@p0 AND status='in_transit' UNION ALL SELECT 1 FROM warehouse_receipts WHERE run_id=@p0 AND status='expected'",Ledger.Id(run)).Count>0) throw new Conflict("Drain active receipts, reservations and transfers before legacy conversion");
        var sku=Rules.Text(body["sku"]);var location=Rules.Text(body["location"]);
        var stock=u.Query("SELECT s.*,c.kind FROM warehouse_stock s JOIN warehouse_catalog c USING(run_id,sku) WHERE s.run_id=@p0 AND s.sku=@p1 AND s.location=@p2",Ledger.Id(run),sku,location).FirstOrDefault()??throw new Conflict("Unknown legacy stock location");
        if(stock["on_hand"]!.GetValue<int>()!=body["quantity"]!.GetValue<int>()||stock["reserved"]!.GetValue<int>()!=0||u.Query("SELECT 1 FROM warehouse_handling_units WHERE run_id=@p0 AND sku=@p1 AND logical_location=@p2",Ledger.Id(run),sku,location).Count>0) throw new Conflict("Conversion must exactly reconcile untouched unreserved legacy stock");
        var category=stock["kind"]!.ToString();var ids=new JsonArray();
        foreach(var n in body["units"]!.AsArray()) {
            var entry=n!.AsObject();var id=Ledger.Id(entry);var position=Rules.Text(entry["position"]);
            if(u.Query("SELECT 1 FROM warehouse_handling_units WHERE id=@p0",id).Count>0) throw new Conflict("Conversion cannot reuse a handling-unit identity");
            Capacity(u,run,position,category);
            u.Exec("INSERT INTO warehouse_handling_units(id,barcode,run_id,epoch,sku,quantity,category,state,logical_location,position,conversion_id,correlation_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,'available',@p7,@p8,@p9,@p10)",id,"HU-"+id.ToString("N").ToUpperInvariant(),Ledger.Id(run),Ledger.Id(run,"epoch"),sku,entry["quantity"]!.GetValue<int>(),category,location,position,command,Rules.Uuid(body["correlation_id"]));ids.Add(id.ToString());
        }
        return new JsonObject {["id"]=command.ToString(),["correlation_id"]=body["correlation_id"]!.DeepClone(),["units"]=ids,["conversion"]=true};
    }
    public static void Reserve(Unit u,JsonObject run,JsonObject reservation) {
        var sku=reservation["sku"]!.ToString();var location=reservation["location"]!.ToString();
        var stock=u.One("SELECT on_hand FROM warehouse_stock WHERE run_id=@p0 AND sku=@p1 AND location=@p2",Ledger.Id(run),sku,location)["on_hand"]!.GetValue<int>();
        var tracked=u.One("SELECT COALESCE(sum(quantity),0) AS n FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND sku=@p2 AND logical_location=@p3 AND state IN ('available','reserved')",Ledger.Id(run),Ledger.Id(run,"epoch"),sku,location)["n"]!.GetValue<long>();
        if(stock!=tracked) throw new Conflict("Legacy unplaced stock requires an explicit conversion manifest before whole-unit allocation");
        var candidates=u.Query("SELECT * FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND sku=@p2 AND logical_location=@p3 AND state='available' ORDER BY id",Ledger.Id(run),Ledger.Id(run,"epoch"),sku,location);
        var target=reservation["quantity"]!.GetValue<int>();var paths=new Dictionary<int,List<JsonObject>> {[0]=[]};
        foreach(var candidate in candidates) {
            var quantity=candidate["quantity"]!.GetValue<int>();
            foreach(var entry in paths.ToArray()) { var next=entry.Key+quantity; if(next<=target&&!paths.ContainsKey(next)) paths[next]=[..entry.Value,candidate]; }
            if(paths.ContainsKey(target)) break;
        }
        if(!paths.TryGetValue(target,out var selected)) throw new Conflict("No exact available whole-unit allocation; requests cannot split units or overfulfil");
        foreach(var unit in selected) {
            u.Exec("UPDATE warehouse_handling_units SET state='reserved',reservation_id=@p0,version=version+1 WHERE id=@p1",Ledger.Id(reservation),Ledger.Id(unit));
            u.Exec("INSERT INTO warehouse_unit_allocations VALUES (@p0,@p1)",Ledger.Id(reservation),Ledger.Id(unit));
        }
    }
    public static void Release(Unit u,JsonObject reservation) =>u.Exec("UPDATE warehouse_handling_units SET state='available',reservation_id=NULL,version=version+1 WHERE reservation_id=@p0 AND state='reserved'",Ledger.Id(reservation));
    public static void Pick(Unit u,JsonObject run,Guid command,JsonObject reservation) {
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND state='reserved' ORDER BY id",Ledger.Id(reservation));
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>()) throw new Conflict("Legacy reservation has no reconciled whole-unit allocation");
        foreach(var unit in units) {
            var destination=Free(u,run,"storage.outbound.dock",unit["category"]!.ToString());
            u.Exec("UPDATE warehouse_handling_units SET position=@p0 WHERE id=@p1",destination,Ledger.Id(unit));
            Movement(u,run,command,unit,"retrieve",unit["position"]!.ToString(),destination,Ledger.Id(reservation,"correlation_id"));
        }
    }
    public static void Depart(Unit u,JsonObject run,Guid command,JsonObject reservation,JsonObject? transfer=null) {
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND state='reserved' ORDER BY id",Ledger.Id(reservation));
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>()) throw new Conflict("No reconciled whole-unit allocation remains for departure");
        if(transfer is null&&units.Count>4) throw new Conflict("Manufacturing input capacity requires at most four whole units per handoff");
        var index=0;
        foreach(var unit in units) {
            var destination=transfer is null?$"manufacturing.cell01.input{++index:00}":Free(u,run,transfer["destination"]!.ToString()=="DISPATCH"?"storage.dispatch.dock":"storage.finished_receipt.dock",unit["category"]!.ToString());
            var handoff=transfer is null?Rules.Uuid5(command,Ledger.Id(unit).ToString()):Ledger.Id(transfer);
            u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,transfer_id=@p2,custody_generation=custody_generation+@p3 WHERE id=@p4",destination,handoff,transfer is null?null:Ledger.Id(transfer),transfer is null?1:0,Ledger.Id(unit));
            Movement(u,run,command,unit,"depart",unit["position"]!.ToString(),destination,Ledger.Id(reservation,"correlation_id"),transfer is null?null:Ledger.Id(transfer));
        }
    }
    public static void Arrive(Unit u,JsonObject run,Guid command,JsonObject transfer) {
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE transfer_id=@p0 AND state='in_transit' ORDER BY id",Ledger.Id(transfer));
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=transfer["quantity"]!.GetValue<int>()) throw new Conflict("Legacy transfer requires operator whole-unit reconciliation");
        foreach(var unit in units) {
            var destination=unit["destination"]!.ToString();Capacity(u,run,destination,unit["category"]!.ToString(),claimant:Ledger.Id(unit));
            u.Exec("UPDATE warehouse_handling_units SET state='available',position=@p0,logical_location=@p1,origin=NULL,destination=NULL,handoff_id=NULL,reservation_id=NULL WHERE id=@p2",destination,transfer["destination"]!.ToString(),Ledger.Id(unit));
            Movement(u,run,command,unit,"unload",unit["origin"]!.ToString(),destination,Ledger.Id(transfer,"correlation_id"),Ledger.Id(transfer));
        }
    }
    public static JsonObject Move(Unit u,JsonObject run,Guid command,JsonObject body) {
        var unit=u.Query("SELECT * FROM warehouse_handling_units WHERE id=@p0 AND run_id=@p1 AND epoch=@p2",Rules.Uuid(body["unit_id"]),Ledger.Id(run),Ledger.Id(run,"epoch")).FirstOrDefault()??throw new Conflict("Handling unit is not in this run");
        if(unit["state"]!.ToString()!="available") throw new Conflict("Only available whole units can change shelf/staging position");
        var destination=Rules.Text(body["destination"]); var action=Rules.Text(body["action"]);var category=unit["category"]!.ToString();
        Capacity(u,run,destination,category,action=="putaway"?"shelf":"dock");
        if(action=="retrieve"&&!unit["position"]!.ToString().StartsWith("storage."+category+".r")) throw new Conflict("Retrieval requires a confirmed shelf position");
        u.Exec("UPDATE warehouse_handling_units SET position=@p0 WHERE id=@p1",destination,Ledger.Id(unit));
        var correlation=unit;
        Movement(u,run,command,unit,action,unit["position"]!.ToString(),destination,Ledger.Id(correlation,"correlation_id"));
        var result=Contract(u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(unit)));
        result["correlation_id"]=correlation["correlation_id"]!.DeepClone();return result;
    }
}
