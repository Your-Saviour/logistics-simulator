using System.Text.Json.Nodes;
namespace Storage;

// All mutations execute inside the existing run lock and warehouse savepoint.
public static class HandlingUnits
{
    static readonly Dictionary<string,JsonObject> Locations=JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"handling-facility.json")))!["locations"]!.AsArray().Select(n=>n!.AsObject()).ToDictionary(n=>n["id"]!.ToString());
    public static bool ManufacturingInput(string id)=>Locations.TryGetValue(id,out var location)&&location["owner"]!.ToString()=="manufacturing"&&location["kind"]!.ToString()=="cell_input"&&location["compatible"]!.AsArray().Any(n=>n!.ToString()=="raw");
    public static bool ShippingInput(string id)=>Locations.TryGetValue(id,out var location)&&location["owner"]!.ToString()=="shipping"&&location["kind"]!.ToString()=="dock"&&location["compatible"]!.AsArray().Any(n=>n!.ToString()=="finished");
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
    public static void Capacity(Unit u,JsonObject run,string position,string category,string? kind=null,Guid? claimant=null) {
        if(u.Query("SELECT 1 FROM warehouse_fleet_jobs WHERE run_id=@p0 AND epoch=@p1 AND request->>'destination'=@p2 AND receipt IS NULL AND (@p3::uuid IS NULL OR request->>'unit_id'<>@p3::text)",Ledger.Id(run),Ledger.Id(run,"epoch"),position,claimant).Count>0)throw new Conflict("Physical destination is reserved by a pending fleet move");
        Location(position,category,kind);
        if(u.Query("SELECT 1 FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND (position=@p2 OR (state='in_transit' AND destination=@p2)) AND (@p3::uuid IS NULL OR id<>@p3) UNION ALL SELECT 1 FROM warehouse_custody_receivers WHERE run_id=@p0 AND epoch=@p1 AND destination=@p2 AND state='accepted'",Ledger.Id(run),Ledger.Id(run,"epoch"),position,claimant).Count>0) throw new Conflict("Physical slot capacity exceeded; unit remains at its recorded position");
    }
    public static string Free(Unit u,JsonObject run,string prefix,string category) {
        var occupied=u.Query("SELECT position FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND position IS NOT NULL UNION SELECT destination AS position FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND state='in_transit' UNION SELECT destination AS position FROM warehouse_custody_receivers WHERE run_id=@p0 AND epoch=@p1 AND state='accepted' UNION SELECT request->>'destination' AS position FROM warehouse_fleet_jobs WHERE run_id=@p0 AND epoch=@p1 AND receipt IS NULL",Ledger.Id(run),Ledger.Id(run,"epoch")).Select(r=>r["position"]!.ToString()).ToHashSet();
        return Locations.Values.Where(l=>l["id"]!.ToString().StartsWith(prefix)&&l["compatible"]!.AsArray().Any(c=>c!.ToString()==category)).Select(l=>l["id"]!.ToString()).Order().FirstOrDefault(p=>!occupied.Contains(p))??throw new Conflict("No compatible physical slots available; retry after capacity is freed");
    }
    public static JsonObject Contract(JsonObject row)=>new() {
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
        ["quarantine"]=CustodyQuarantine.Snapshot(u,run),["handoffs"]=Handoffs(u,run),["lineage"]=new JsonArray(),
        ["legacy_stock"]=Ledger.Array(u.Query("SELECT s.sku,s.location,s.on_hand-COALESCE(sum(h.quantity) FILTER(WHERE h.state IN ('available','reserved') OR (h.state='in_transit' AND h.transfer_id IS NULL AND h.destination LIKE 'storage.%')),0) AS unplaced_quantity FROM warehouse_stock s LEFT JOIN warehouse_handling_units h ON h.run_id=s.run_id AND h.sku=s.sku AND h.logical_location=s.location WHERE s.run_id=@p0 GROUP BY s.run_id,s.sku,s.location,s.on_hand HAVING s.on_hand<>COALESCE(sum(h.quantity) FILTER(WHERE h.state IN ('available','reserved') OR (h.state='in_transit' AND h.transfer_id IS NULL AND h.destination LIKE 'storage.%')),0) ORDER BY s.sku,s.location",Ledger.Id(run)))
    };
    static JsonArray Handoffs(Unit u,JsonObject run) {var result=StorageCustody.Snapshot(u,run);foreach(var h in FinishedCustody.Snapshot(u,run))result.Add(h!.DeepClone());return result;}
    static void Headroom(JsonObject unit,int versions=1,int sequences=0,int generations=0) {
        if((long)unit["version"]!.GetValue<int>()+versions>int.MaxValue||(long)unit["last_sequence"]!.GetValue<int>()+sequences>int.MaxValue||(long)unit["custody_generation"]!.GetValue<int>()+generations>int.MaxValue)throw new Conflict("Handling-unit counters exhausted; reconcile before another physical transition");
    }
    public static void Movement(Unit u,JsonObject run,Guid command,JsonObject unit,string action,string? origin,string destination,Guid correlation,Guid? transfer=null) {
        Headroom(u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(unit)),1,1);
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
    public static void Reserve(Unit u,JsonObject run,JsonObject reservation,Settings settings) {
        var sku=reservation["sku"]!.ToString();var location=reservation["location"]!.ToString();
        var stock=u.One("SELECT on_hand FROM warehouse_stock WHERE run_id=@p0 AND sku=@p1 AND location=@p2",Ledger.Id(run),sku,location)["on_hand"]!.GetValue<int>();
        var tracked=u.One("SELECT COALESCE(sum(quantity),0) AS n FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND sku=@p2 AND logical_location=@p3 AND (state IN ('available','reserved') OR (state='in_transit' AND transfer_id IS NULL AND destination LIKE 'storage.%'))",Ledger.Id(run),Ledger.Id(run,"epoch"),sku,location)["n"]!.GetValue<long>();
        if(stock!=tracked) throw new Conflict("Legacy unplaced stock requires an explicit conversion manifest before whole-unit allocation");
        var candidates=u.Query("SELECT * FROM warehouse_handling_units WHERE run_id=@p0 AND epoch=@p1 AND sku=@p2 AND logical_location=@p3 AND state='available' AND NOT EXISTS(SELECT 1 FROM warehouse_fleet_jobs f WHERE f.run_id=@p0 AND f.epoch=@p1 AND f.request->>'unit_id'=warehouse_handling_units.id::text AND f.receipt IS NULL) ORDER BY id",Ledger.Id(run),Ledger.Id(run,"epoch"),sku,location);
        var target=reservation["quantity"]!.GetValue<int>();var paths=new Dictionary<int,List<JsonObject>> {[0]=[]};
        var production=reservation["purpose"]!.ToString()=="production";var maximum=production?4:8;
        // Reserve + coordinated pick departure/arrival + custody departure +
        // receipt need five versions. Legacy picks and production need four.
        var coordinatedCustomer=!production&&settings.FleetMode=="coordinated";
        var versionCost=coordinatedCustomer?5:4;
        foreach(var candidate in candidates) {
            if(candidate["version"]!.GetValue<int>()>int.MaxValue-versionCost||candidate["last_sequence"]!.GetValue<int>()>int.MaxValue-3||(production||coordinatedCustomer)&&candidate["custody_generation"]!.GetValue<int>()>int.MaxValue-1)continue;
            var quantity=candidate["quantity"]!.GetValue<int>();
            foreach(var entry in paths.ToArray()) {var next=entry.Key+quantity;var count=entry.Value.Count+1;if(next<=target&&(count<=maximum)&&(!paths.TryGetValue(next,out var old)||count<old.Count))paths[next]=[..entry.Value,candidate];}
        }
        if(!paths.TryGetValue(target,out var selected)) throw new Conflict("No exact available whole-unit allocation; requests cannot split units or overfulfil");
        if(reservation["purpose"]!.ToString()=="production"&&selected.Count>4)throw new Conflict("Production input capacity permits at most four whole units per reservation");
        foreach(var unit in selected) {
            u.Exec("UPDATE warehouse_handling_units SET state='reserved',reservation_id=@p0,version=version+1 WHERE id=@p1",Ledger.Id(reservation),Ledger.Id(unit));
            u.Exec("INSERT INTO warehouse_unit_allocations VALUES (@p0,@p1)",Ledger.Id(reservation),Ledger.Id(unit));
        }
    }
    public static void Release(Unit u,JsonObject reservation) {if(u.Query("SELECT 1 FROM warehouse_handling_units h JOIN warehouse_fleet_jobs f ON f.request->>'unit_id'=h.id::text AND f.run_id=h.run_id AND f.epoch=h.epoch WHERE h.reservation_id=@p0 AND f.receipt IS NULL",Ledger.Id(reservation)).Count>0)throw new Conflict("Reservation has unresolved physical fleet movement");foreach(var unit in u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND state='reserved'",Ledger.Id(reservation)))Headroom(unit);u.Exec("UPDATE warehouse_handling_units SET state='available',reservation_id=NULL,version=version+1 WHERE reservation_id=@p0 AND state='reserved'",Ledger.Id(reservation));}
    public static void Pick(Unit u,JsonObject run,Guid command,JsonObject reservation,Settings settings) {
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND (state='reserved' OR (state='in_transit' AND handoff_id=@p1)) ORDER BY id",Ledger.Id(reservation),command);
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>()) throw new Conflict("Legacy reservation has no reconciled whole-unit allocation");
        if(settings.FleetMode!="coordinated") {
            foreach(var unit in units) {var destination=Free(u,run,"storage.outbound.dock",unit["category"]!.ToString());u.Exec("UPDATE warehouse_handling_units SET position=@p0 WHERE id=@p1",destination,Ledger.Id(unit));Movement(u,run,command,unit,"retrieve",Rules.Text(unit["position"]),destination,Ledger.Id(reservation,"correlation_id"));}return;
        }
        var requests=new Dictionary<Guid,JsonObject>();var completed=new HashSet<Guid>();
        foreach(var unit in units) {
            var id=Ledger.Id(unit);var old=u.Query("SELECT * FROM warehouse_fleet_jobs WHERE id=@p0",Fleet.Job(id,command,unit["custody_generation"]!.GetValue<int>())).FirstOrDefault();
            if(old?["receipt"] is JsonObject){completed.Add(id);continue;}
            Headroom(unit,unit["state"]!.ToString()=="in_transit"?1:2,1);
            var destination=old?["request"]?["destination"]?.ToString()??Free(u,run,"storage.outbound.dock",unit["category"]!.ToString());
            requests[id]=old?["request"]?.AsObject()??Fleet.Request(u,run,settings,id,command,unit["custody_generation"]!.GetValue<int>(),Rules.Text(unit["position"]??unit["origin"]),destination);
        }
        var waiting=false;
        foreach(var unit in units) {
            var id=Ledger.Id(unit);if(completed.Contains(id))continue;var request=requests[id];var destination=Rules.Text(request["destination"]);
            try {Fleet.Local(u,run,settings,command,unit,destination);}
            catch(FleetWait){waiting=true;continue;}
            u.Exec("UPDATE warehouse_handling_units SET state='reserved',position=@p0,origin=NULL,destination=NULL,handoff_id=NULL WHERE id=@p1",destination,id);
            Movement(u,run,command,unit,"retrieve",Rules.Text(unit["position"]??unit["origin"]),destination,Ledger.Id(reservation,"correlation_id"));
            Fleet.Proof(u,run,request,"receipt");
        }
        if(waiting)throw new FleetWait("fleet awaiting remaining picked units");
    }
    // Each locally received unit releases its whole-trip route before another
    // unit needs it. Aggregate completion never gates a per-unit physical proof.
    public static JsonObject Transfer(Unit u,JsonObject run,Settings settings,Guid command,JsonObject reservation,string logicalDestination) {
        if(u.Query("SELECT 1 FROM warehouse_transfers WHERE reservation_id=@p0 AND id<>@p1",Ledger.Id(reservation),command).Count>0)throw new Conflict("Reservation already has a durable transfer command");
        var transfer=u.Query("SELECT * FROM warehouse_transfers WHERE id=@p0",command).FirstOrDefault();
        if(transfer is null) {
            Warehouse.Capacity(u,Ledger.Id(run),logicalDestination,reservation["quantity"]!.GetValue<int>(),command);
            transfer=u.One("INSERT INTO warehouse_transfers(id,run_id,reservation_id,sku,origin,destination,quantity,correlation_id,status) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7,'awaiting_acceptance') RETURNING *",command,Ledger.Id(run),Ledger.Id(reservation),Rules.Text(reservation["sku"]),Rules.Text(reservation["location"]),logicalDestination,reservation["quantity"]!.GetValue<int>(),Ledger.Id(reservation,"correlation_id"));
        }
        var units=u.Query("SELECT h.* FROM warehouse_unit_allocations a JOIN warehouse_handling_units h ON h.id=a.unit_id WHERE a.reservation_id=@p0 ORDER BY h.id",Ledger.Id(reservation));
        if(units.Sum(item=>item["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>())throw new Conflict("Internal transfer requires an exact native whole-unit allocation");
        var requests=new Dictionary<Guid,JsonObject>();var completed=new HashSet<Guid>();
        foreach(var unit in units) {
            var id=Ledger.Id(unit);var old=u.Query("SELECT * FROM warehouse_fleet_jobs WHERE native_command=@p0 AND request->>'unit_id'=@p1",command,id.ToString()).FirstOrDefault();
            if(old?["receipt"] is JsonObject){completed.Add(id);continue;}
            Headroom(unit,unit["state"]!.ToString()=="in_transit"?1:2,unit["state"]!.ToString()=="in_transit"?1:2);
            var destination=old?["request"]?["destination"]?.ToString()??Free(u,run,logicalDestination=="DISPATCH"?"storage.dispatch.dock":"storage.finished_receipt.dock",Rules.Text(unit["category"]));
            Capacity(u,run,destination,Rules.Text(unit["category"]),claimant:id);
            var request=old?["request"]?.AsObject()??Fleet.Request(u,run,settings,id,command,unit["custody_generation"]!.GetValue<int>(),Rules.Text(unit["position"]??unit["origin"]),destination);requests[id]=request;
            u.Exec("UPDATE warehouse_fleet_jobs SET native_command=@p0,logical_destination=@p1,quantity=@p2 WHERE id=@p3",command,logicalDestination,unit["quantity"]!.GetValue<int>(),Ledger.Id(request));
        }
        var waiting=false;
        foreach(var unit in units) {
            var id=Ledger.Id(unit);if(completed.Contains(id))continue;var request=requests[id];var destination=Rules.Text(request["destination"]);var quantity=unit["quantity"]!.GetValue<int>();
            var portion=(JsonObject)reservation.DeepClone();portion["quantity"]=quantity;
            if(unit["state"]!.ToString()!="in_transit") {
                try {Fleet.Require(u,run,request,"pickup_ready",settings.FleetOffset);}catch(FleetWait){waiting=true;continue;}
                u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,transfer_id=@p1 WHERE id=@p2",destination,command,id);
                Movement(u,run,command,unit,"depart",Rules.Text(request["origin"]),destination,Ledger.Id(reservation,"correlation_id"),command);
                Warehouse.Move(u,run,command,"transfer",portion,-quantity,-quantity,unit:id);Fleet.Proof(u,run,request,"departure");
            }
            try {Fleet.Require(u,run,request,"arrival",settings.FleetOffset);}catch(FleetWait){waiting=true;continue;}
            Warehouse.Capacity(u,Ledger.Id(run),logicalDestination,quantity,command);
            u.Exec("UPDATE warehouse_handling_units SET state='available',position=@p0,logical_location=@p1,origin=NULL,destination=NULL,handoff_id=NULL,reservation_id=NULL WHERE id=@p2",destination,logicalDestination,id);
            Movement(u,run,command,unit,"unload",Rules.Text(request["origin"]),destination,Ledger.Id(reservation,"correlation_id"),command);
            Warehouse.Move(u,run,command,"arrive",portion,quantity,0,logicalDestination,id);Fleet.Proof(u,run,request,"receipt");
        }
        if(waiting)throw new FleetWait("fleet awaiting remaining internal transfer units");
        u.Exec("UPDATE warehouse_reservations SET status='transferred',version=version+1 WHERE id=@p0 AND status='picked'",Ledger.Id(reservation));
        return u.One("UPDATE warehouse_transfers SET status='received',version=version+1 WHERE id=@p0 AND status='awaiting_acceptance' RETURNING *",command);
    }
    public static JsonObject Issue(Unit u,JsonObject run,Settings settings,Guid command,JsonObject reservation) {
        var units=u.Query("SELECT h.* FROM warehouse_unit_allocations a JOIN warehouse_handling_units h ON h.id=a.unit_id WHERE a.reservation_id=@p0 ORDER BY h.id",Ledger.Id(reservation));
        if(units.Count>4||units.Sum(item=>item["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>())throw new Conflict("Production issue requires an exact allocation of at most four native units");
        var requests=new Dictionary<Guid,JsonObject>();var index=0;
        foreach(var unit in units) {
            var id=Ledger.Id(unit);var old=u.Query("SELECT * FROM warehouse_fleet_jobs WHERE native_command=@p0 AND request->>'unit_id'=@p1",command,id.ToString()).FirstOrDefault();
            var destination=$"manufacturing.cell01.input{++index:00}";
            var request=old?["request"]?.AsObject()??Fleet.Request(u,run,settings,id,Rules.Uuid5(command,id.ToString()),unit["custody_generation"]!.GetValue<int>()+1,Rules.Text(unit["position"]),destination);requests[id]=request;
            u.Exec("UPDATE warehouse_fleet_jobs SET native_command=@p0 WHERE id=@p1",command,Ledger.Id(request));
        }
        var waiting=false;
        foreach(var unit in units) {
            var id=Ledger.Id(unit);var request=requests[id];if(u.One("SELECT departure FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request))["departure"] is JsonObject)continue;
            try {Fleet.Require(u,run,request,"pickup_ready",settings.FleetOffset);}catch(FleetWait){waiting=true;continue;}
            Headroom(unit,1,1,1);var destination=Rules.Text(request["destination"]);var handoff=Rules.Uuid5(command,id.ToString());
            u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,custody_generation=custody_generation+1 WHERE id=@p2",destination,handoff,id);
            Movement(u,run,command,unit,"depart",Rules.Text(request["origin"]),destination,Ledger.Id(reservation,"correlation_id"));
            var portion=(JsonObject)reservation.DeepClone();var count=unit["quantity"]!.GetValue<int>();portion["quantity"]=count;
            Warehouse.Move(u,run,command,"issue",portion,-count,-count,unit:id);Fleet.Proof(u,run,request,"departure");
        }
        if(waiting)throw new FleetWait("fleet awaiting remaining issue pickups");
        u.Exec("UPDATE warehouse_reservations SET status='issued',version=version+1 WHERE id=@p0 AND status='reserved'",Ledger.Id(reservation));
        var result=(JsonObject)reservation.DeepClone();result["status"]="issued";return result;
    }
    public static void Depart(Unit u,JsonObject run,Guid command,JsonObject reservation,JsonObject? transfer=null,Settings? settings=null) {
        var units=u.Query("SELECT * FROM warehouse_handling_units WHERE reservation_id=@p0 AND state='reserved' ORDER BY id",Ledger.Id(reservation));
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=reservation["quantity"]!.GetValue<int>()) throw new Conflict("No reconciled whole-unit allocation remains for departure");
        if(transfer is null&&units.Count>4) throw new Conflict("Manufacturing input capacity requires at most four whole units per handoff");
        var index=0;
        foreach(var unit in units) {
            Headroom(unit,1,1,transfer is null?1:0);
            var handoff=transfer is null?Rules.Uuid5(command,Ledger.Id(unit).ToString()):Ledger.Id(transfer);
            JsonObject? fleetRequest=null;
            if(settings?.FleetMode=="coordinated")fleetRequest=u.One("SELECT request FROM warehouse_fleet_jobs WHERE id=@p0",Fleet.Job(Ledger.Id(unit),handoff,unit["custody_generation"]!.GetValue<int>()+(transfer is null?1:0)))["request"]!.AsObject();
            var destination=fleetRequest?["destination"]?.ToString()??(transfer is null?$"manufacturing.cell01.input{++index:00}":Free(u,run,transfer["destination"]!.ToString()=="DISPATCH"?"storage.dispatch.dock":"storage.finished_receipt.dock",unit["category"]!.ToString()));
            u.Exec("UPDATE warehouse_handling_units SET state='in_transit',origin=position,position=NULL,destination=@p0,handoff_id=@p1,transfer_id=@p2,custody_generation=custody_generation+@p3 WHERE id=@p4",destination,handoff,transfer is null?null:Ledger.Id(transfer),transfer is null?1:0,Ledger.Id(unit));
            if(fleetRequest is not null)Fleet.Proof(u,run,fleetRequest,"departure");
            Movement(u,run,command,unit,"depart",unit["position"]!.ToString(),destination,Ledger.Id(reservation,"correlation_id"),transfer is null?null:Ledger.Id(transfer));
        }
    }
    public static void Arrive(Unit u,JsonObject run,Guid command,JsonObject transfer,Settings settings) {
        var units=settings.FleetMode=="coordinated"?u.Query("SELECT h.* FROM warehouse_unit_allocations a JOIN warehouse_handling_units h ON h.id=a.unit_id WHERE a.reservation_id=@p0 ORDER BY h.id",Ledger.Id(transfer,"reservation_id")):u.Query("SELECT * FROM warehouse_handling_units WHERE transfer_id=@p0 AND state='in_transit' ORDER BY id",Ledger.Id(transfer));
        if(units.Sum(row=>row["quantity"]!.GetValue<int>())!=transfer["quantity"]!.GetValue<int>()) throw new Conflict("Legacy transfer requires operator whole-unit reconciliation");
        if(settings.FleetMode=="coordinated") {
            var waiting=false;
            foreach(var unit in units) {
                var id=Ledger.Id(unit);var request=u.One("SELECT request FROM warehouse_fleet_jobs WHERE native_command=@p0 AND request->>'unit_id'=@p1",Ledger.Id(transfer),id.ToString())["request"]!.AsObject();
                if(u.One("SELECT receipt FROM warehouse_fleet_jobs WHERE id=@p0",Ledger.Id(request))["receipt"] is JsonObject)continue;
                try {Fleet.Require(u,run,request,"arrival",settings.FleetOffset);}catch(FleetWait){waiting=true;continue;}
                var destination=Rules.Text(request["destination"]);var logical=Rules.Text(transfer["destination"]);var quantity=unit["quantity"]!.GetValue<int>();Capacity(u,run,destination,Rules.Text(unit["category"]),claimant:id);Warehouse.Capacity(u,Ledger.Id(run),logical,quantity,Ledger.Id(transfer));
                u.Exec("UPDATE warehouse_handling_units SET state='available',position=@p0,logical_location=@p1,origin=NULL,destination=NULL,handoff_id=NULL,reservation_id=NULL WHERE id=@p2",destination,logical,id);
                Movement(u,run,command,unit,"unload",Rules.Text(request["origin"]),destination,Ledger.Id(transfer,"correlation_id"),Ledger.Id(transfer));
                var portion=(JsonObject)transfer.DeepClone();portion["quantity"]=quantity;Warehouse.Move(u,run,command,"arrive",portion,quantity,0,logical,id);Fleet.Proof(u,run,request,"receipt");
            }
            if(waiting)throw new FleetWait("fleet awaiting remaining transfer arrivals");return;
        }
        foreach(var unit in units) {
            var destination=unit["destination"]!.ToString();Capacity(u,run,destination,unit["category"]!.ToString(),claimant:Ledger.Id(unit));
            u.Exec("UPDATE warehouse_handling_units SET state='available',position=@p0,logical_location=@p1,origin=NULL,destination=NULL,handoff_id=NULL,reservation_id=NULL WHERE id=@p2",destination,transfer["destination"]!.ToString(),Ledger.Id(unit));
            Movement(u,run,command,unit,"unload",unit["origin"]!.ToString(),destination,Ledger.Id(transfer,"correlation_id"),Ledger.Id(transfer));
        }
    }
    public static JsonObject Move(Unit u,JsonObject run,Guid command,JsonObject body,Settings settings) {
        var unit=u.Query("SELECT * FROM warehouse_handling_units WHERE id=@p0 AND run_id=@p1 AND epoch=@p2",Rules.Uuid(body["unit_id"]),Ledger.Id(run),Ledger.Id(run,"epoch")).FirstOrDefault()??throw new Conflict("Handling unit is not in this run");
        var ownTransit=settings.FleetMode=="coordinated"&&unit["state"]!.ToString()=="in_transit"&&unit["handoff_id"]?.ToString()==command.ToString();
        if(unit["state"]!.ToString()!="available"&&!ownTransit) throw new Conflict("Only available whole units can change shelf/staging position");
        var destination=Rules.Text(body["destination"]); var action=Rules.Text(body["action"]);var category=unit["category"]!.ToString();
        Capacity(u,run,destination,category,action=="putaway"?"shelf":"dock",Ledger.Id(unit));
        if(action=="retrieve"&&!(unit["position"]??unit["origin"])!.ToString().StartsWith("storage."+category+".r")) throw new Conflict("Retrieval requires a confirmed shelf position");
        if(settings.FleetMode=="coordinated")Headroom(unit,ownTransit?1:2,1);
        JsonObject? fleetRequest=settings.FleetMode=="coordinated"?Fleet.Local(u,run,settings,command,unit,destination):null;
        u.Exec("UPDATE warehouse_handling_units SET state='available',position=@p0,origin=NULL,destination=NULL,handoff_id=NULL WHERE id=@p1",destination,Ledger.Id(unit));
        if(fleetRequest is not null)Fleet.Proof(u,run,fleetRequest,"receipt");
        var correlation=unit;
        Movement(u,run,command,unit,action,(unit["position"]??unit["origin"])!.ToString(),destination,Ledger.Id(correlation,"correlation_id"));
        var result=Contract(u.One("SELECT * FROM warehouse_handling_units WHERE id=@p0",Ledger.Id(unit)));
        result["correlation_id"]=correlation["correlation_id"]!.DeepClone();return result;
    }
}
