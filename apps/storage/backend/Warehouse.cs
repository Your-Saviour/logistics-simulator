using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
namespace Storage;

// Every caller takes Unit.Run() first. That run-row lock serializes inventory,
// reservations, capacity and clock barriers across APIs and all worker replicas.
public sealed class Warehouse(Ledger ledger,Settings settings)
{
    public static JsonObject Configuration(JsonObject? value=null) {
        value??=JsonNode.Parse("""{"locations":[{"code":"RAW-A","capacity":500},{"code":"FINISHED-A","capacity":500},{"code":"DISPATCH","capacity":250}],"catalog":[{"sku":"COMPONENT","kind":"raw"},{"sku":"PRODUCT","kind":"finished"}]}""")!.AsObject();
        Rules.Fields(value,"locations","catalog");
        var locations=value["locations"] as JsonArray??throw new Validation("Warehouse locations required");
        var catalog=value["catalog"] as JsonArray??throw new Validation("Warehouse catalog required");
        if(locations.Count is <2 or >100||catalog.Count is <1 or >100) throw new Validation("Warehouse needs 2..100 locations and 1..100 SKUs");
        var codes=new HashSet<string>(); foreach(var node in locations) { var row=node as JsonObject??throw new Validation("Location object required"); Rules.Fields(row,"code","capacity"); if(!codes.Add(Code(row["code"]))) throw new Validation("Duplicate location"); Rules.Integer(row["capacity"],1,1000000); }
        codes.Clear(); foreach(var node in catalog) { var row=node as JsonObject??throw new Validation("Catalog object required"); Rules.Fields(row,"sku","kind"); if(!codes.Add(Code(row["sku"]))||Rules.Text(row["kind"]) is not ("raw" or "finished")) throw new Validation("Unique SKU and raw/finished kind required"); }
        return (JsonObject)value.DeepClone();
    }
    static string Code(JsonNode? node) { var code=Rules.Text(node); if(!Regex.IsMatch(code,"^[A-Z0-9][A-Z0-9_-]{0,31}$")) throw new Validation("Code must be 1..32 uppercase letters, digits, underscores or hyphens"); return code; }
    public static JsonObject Validate(JsonObject body) {
        Rules.Uuid(body["run_id"]); Rules.Uuid(body["epoch"]); if(Rules.Number(body["due_at"])<0) throw new Validation("Nonnegative due_at required");
        var action=Rules.Text(body["action"]);
        switch(action) {
            case "expect": case "reserve": case "convert":
                Rules.Fields(body,"run_id","epoch","due_at","action","sku","location","quantity","correlation_id",action=="reserve"?"purpose":"units");
                Code(body["sku"]); Code(body["location"]); Rules.Integer(body["quantity"],1,10000); Rules.Uuid(body["correlation_id"]);
                if(action=="reserve"&&Rules.Text(body["purpose"]) is not ("production" or "customer")) throw new Validation("Reservation purpose must be production or customer");
                if(action is "expect" or "convert") HandlingUnits.ValidateManifest(body); break;
            case "putaway": case "retrieve":
                Rules.Fields(body,"run_id","epoch","due_at","action","unit_id","destination");Rules.Uuid(body["unit_id"]);Rules.Text(body["destination"]);break;
            case "receive": case "release": case "issue": case "pick": case "arrive": case "transfer":
                Rules.Fields(body,"run_id","epoch","due_at","action","reference",action=="transfer"?"destination":action=="issue"?"unit_destinations":"reference"); Rules.Uuid(body["reference"]); if(action=="transfer") Code(body["destination"]);
                if(action=="issue"&&body["unit_destinations"] is not null) {if(body["unit_destinations"] is not JsonObject destinations||destinations.Count is <1 or >4)throw new Validation("One to four explicit input endpoints required");foreach(var pair in destinations){Rules.Uuid(JsonValue.Create(pair.Key));if(!HandlingUnits.ManufacturingInput(Rules.Text(pair.Value)))throw new Validation("Known Manufacturing input endpoint required");}}break;
            default: throw new Validation("Unknown warehouse action");
        }
        return body;
    }
    public static void Ensure(Unit u,JsonObject run) {
        var id=Ledger.Id(run);
        if(u.Query("SELECT 1 FROM warehouse_config WHERE run_id=@p0",id).Count>0) return;
        var config=Configuration(run["scenario"]?["warehouse"] as JsonObject);
        u.Exec("INSERT INTO warehouse_config VALUES (@p0,@p1)",id,config);
        foreach(var l in config["locations"]!.AsArray()) u.Exec("INSERT INTO warehouse_locations VALUES (@p0,@p1,@p2)",id,l!["code"]!.ToString(),l["capacity"]!.GetValue<int>());
        foreach(var p in config["catalog"]!.AsArray()) u.Exec("INSERT INTO warehouse_catalog VALUES (@p0,@p1,@p2)",id,p!["sku"]!.ToString(),p["kind"]!.ToString());
        u.Exec("INSERT INTO warehouse_stock(run_id,sku,location) SELECT c.run_id,c.sku,l.code FROM warehouse_catalog c JOIN warehouse_locations l USING(run_id) WHERE c.run_id=@p0",id);
    }
    public JsonObject Snapshot()=>ledger.Db.Transaction(u=> { var run=u.Run(); Ensure(u,run); var id=Ledger.Id(run);
        return new JsonObject {
            ["run_id"]=id.ToString(),["epoch"]=run["epoch"]!.DeepClone(),["handling"]=HandlingUnits.Snapshot(u,run),
            ["inventory"]=Ledger.Array(u.Query("SELECT s.*,s.on_hand-s.reserved AS available,c.kind FROM warehouse_stock s JOIN warehouse_catalog c USING(run_id,sku) WHERE s.run_id=@p0 ORDER BY s.location,s.sku",id)),
            ["locations"]=Ledger.Array(u.Query("SELECT l.*,COALESCE(sum(s.on_hand),0) AS used FROM warehouse_locations l LEFT JOIN warehouse_stock s ON s.run_id=l.run_id AND s.location=l.code WHERE l.run_id=@p0 GROUP BY l.run_id,l.code ORDER BY l.code",id)),
            ["receipts"]=Ledger.Array(u.Query("SELECT * FROM warehouse_receipts WHERE run_id=@p0 ORDER BY id",id)),
            ["reservations"]=Ledger.Array(u.Query("SELECT * FROM warehouse_reservations WHERE run_id=@p0 ORDER BY id",id)),
            ["transfers"]=Ledger.Array(u.Query("SELECT * FROM warehouse_transfers WHERE run_id=@p0 ORDER BY id",id)),
            ["movements"]=Ledger.Array(u.Query("SELECT * FROM warehouse_movements WHERE run_id=@p0 ORDER BY simulation_time DESC,recorded_at DESC LIMIT 200",id)),
            ["commands"]=Ledger.Array(u.Query("SELECT c.*,j.due_at,j.attempts,j.status AS job_status FROM warehouse_commands c JOIN jobs j USING(id) WHERE c.run_id=@p0 ORDER BY j.created_at DESC LIMIT 200",id))
        };
    });
    // Observers take the same run lock as every warehouse writer, without Ensure writes.
    public JsonObject Projection()=>ledger.Db.Transaction(u=> {
        var run=u.Run(); var id=Ledger.Id(run);
        var movements=u.Query("SELECT * FROM warehouse_movements WHERE run_id=@p0 ORDER BY simulation_time,id",id);
        var snapshot=new JsonObject {
            ["run_id"]=id.ToString(),["epoch"]=run["epoch"]!.DeepClone(),["handling"]=HandlingUnits.Snapshot(u,run),
            ["inventory"]=Ledger.Array(u.Query("SELECT s.*,s.on_hand-s.reserved AS available,c.kind FROM warehouse_stock s JOIN warehouse_catalog c USING(run_id,sku) WHERE s.run_id=@p0 ORDER BY s.location,s.sku",id)),
            ["locations"]=Ledger.Array(u.Query("SELECT l.*,COALESCE(sum(s.on_hand),0) AS used FROM warehouse_locations l LEFT JOIN warehouse_stock s ON s.run_id=l.run_id AND s.location=l.code WHERE l.run_id=@p0 GROUP BY l.run_id,l.code ORDER BY l.code",id)),
            ["receipts"]=Ledger.Array(u.Query("SELECT * FROM warehouse_receipts WHERE run_id=@p0 ORDER BY id",id)),
            ["reservations"]=Ledger.Array(u.Query("SELECT * FROM warehouse_reservations WHERE run_id=@p0 ORDER BY id",id)),
            ["transfers"]=Ledger.Array(u.Query("SELECT * FROM warehouse_transfers WHERE run_id=@p0 ORDER BY id",id)),
            ["movements"]=Ledger.Array(movements),
            ["commands"]=Ledger.Array(u.Query("SELECT c.*,j.due_at,j.attempts,j.status AS job_status FROM warehouse_commands c JOIN jobs j USING(id) WHERE c.run_id=@p0 ORDER BY j.created_at,c.id",id))
        };
        var events=new JsonArray(); foreach(var movement in movements) { var e=(JsonObject)movement.DeepClone();e["id"]="storage:movement:"+movement["id"]!.ToString();e["kind"]="movement";events.Add(e); }
        foreach(var movement in snapshot["handling"]!["movements"]!.AsArray()) { var e=(JsonObject)movement!.DeepClone();e["id"]="storage:unit-movement:"+e["id"]!.ToString();e["kind"]="unit_movement";events.Add(e); }
        var value=new JsonObject {["version"]=1,["source"]="storage",["effects"]=u.One("SELECT COALESCE(sum(quantity),0) AS n FROM effects WHERE run_id=@p0",id)["n"]!.DeepClone(),["run"]=run,["snapshot"]=snapshot,["events"]=events};
        value["health"]=new JsonObject {
            ["heartbeats"]=Ledger.Array(u.Query("SELECT role,seen_at,seen_at>clock_timestamp()-interval '15 seconds' AS healthy FROM heartbeats ORDER BY role")),
            ["pending_jobs"]=u.One("SELECT count(*) AS n FROM jobs WHERE run_id=@p0 AND status IN ('pending','queued')",id)["n"]!.DeepClone(),
            ["dead_letters"]=u.One("SELECT count(*) AS n FROM jobs WHERE run_id=@p0 AND status='dead'",id)["n"]!.DeepClone(),["broker"]=null,["ready"]=null
        };
        value["cursor"]=Database.Checksum(value.ToJsonString());return value;
    });
    public JsonObject Submit(string key,JsonObject body,Audit? audit=null)=>ledger.Db.Transaction(u=>Submit(u,u.Run(),key,body,audit,settings.Quantum));
    public static JsonObject Submit(Unit u,JsonObject run,string key,JsonObject body,Audit? audit,double quantum,bool boundary=false) {
        Validate(body); var id=Ledger.Id(run); var due=Rules.Number(body["due_at"]);
        if(body["action"]!.ToString()=="convert"&&(boundary||audit?.Role!="operator")) throw new Conflict("Only an operator may convert legacy stock with an explicit manifest");
        if(key.Length is <1 or >128) throw new Validation("Idempotency-Key length must be 1..128");
        if(!boundary&&new[]{"warehouse:","boundary:","synthetic:"}.Any(key.StartsWith)) throw new Conflict("Reserved idempotency key namespace");
        if(Rules.Uuid(body["run_id"])!=id||Rules.Uuid(body["epoch"])!=Ledger.Id(run,"epoch")) throw new Conflict("Warehouse command belongs to a different run/epoch; refresh before submitting");
        var old=u.Query("SELECT c.* FROM warehouse_commands c JOIN jobs j USING(id) WHERE c.run_id=@p0 AND j.idempotency_key=@p1",id,key).FirstOrDefault();
        if(old is not null) { if(!JsonNode.DeepEquals(old["command"],body)) throw new Conflict("Idempotency key already used with a different command"); Ledger.AuditRow(u,id,audit,"accepted",200,Ledger.Id(old)); return old; }
        if(u.Query("SELECT 1 FROM jobs WHERE run_id=@p0 AND idempotency_key=@p1",id,key).Count>0) throw new Conflict("Idempotency key already used with a different command");
        if(run["state"]!.ToString() is not ("running" or "held")||due<(boundary?Ledger.Num(run,"granted"):Math.Max(Ledger.Num(run,"granted"),Ledger.Num(run,"requested"))+quantum)) throw new Conflict("Schedule at least one quantum beyond granted/requested time in an active run");
        Ensure(u,run); var command=Guid.NewGuid();
        u.Exec("INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES (@p0,@p1,@p2,@p3,@p4,@p4,@p5)",command,id,Ledger.Id(run,"epoch"),key,due,new JsonObject {["warehouse"]=body.DeepClone()});
        var row=u.One("INSERT INTO warehouse_commands(id,run_id,command) VALUES (@p0,@p1,@p2) RETURNING *",command,id,body);
        Ledger.AuditRow(u,id,audit,"accepted",200,command); return row;
    }
    static JsonObject Record(Unit u,JsonObject run,string table,Guid id) {
        // Table names are fixed at call sites, never supplied by requests.
        return u.Query($"SELECT * FROM {table} WHERE id=@p0 AND run_id=@p1",id,Ledger.Id(run)).FirstOrDefault()??throw new Conflict("Referenced warehouse record does not exist in this run");
    }
    static void State(JsonObject row,string expected) { if(row["status"]!.ToString()!=expected) throw new Conflict($"Expected {expected}; record is {row["status"]}"); }
    static void Capacity(Unit u,Guid run,string location,int quantity) {
        var row=u.Query("SELECT l.capacity,COALESCE(sum(s.on_hand),0) AS used FROM warehouse_locations l LEFT JOIN warehouse_stock s ON s.run_id=l.run_id AND s.location=l.code WHERE l.run_id=@p0 AND l.code=@p1 GROUP BY l.capacity",run,location).FirstOrDefault()??throw new Conflict("Unknown destination location");
        if(row["used"]!.GetValue<long>()+quantity>row["capacity"]!.GetValue<int>()) throw new Conflict("Destination capacity exceeded; stock remains at its current location or in transit");
    }
    public static void Move(Unit u,JsonObject run,Guid command,string action,JsonObject record,int onHand,int reserved,string? destination=null) {
        var id=Ledger.Id(run); var sku=record["sku"]!.ToString(); var location=destination??record["location"]!.ToString(); var quantity=record["quantity"]!.GetValue<int>();
        var changed=u.Query("UPDATE warehouse_stock SET on_hand=on_hand+@p0,reserved=reserved+@p1 WHERE run_id=@p2 AND sku=@p3 AND location=@p4 AND on_hand+@p0>=0 AND reserved+@p1>=0 AND reserved+@p1<=on_hand+@p0 RETURNING *",onHand,reserved,id,sku,location);
        if(changed.Count!=1) throw new Conflict("Insufficient available stock or invalid location/SKU");
        u.Exec("INSERT INTO warehouse_movements(id,command_id,run_id,action,sku,location,on_hand_delta,reserved_delta,quantity,correlation_id,reference,simulation_time) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7,@p8,@p9,@p10,@p11)",Guid.NewGuid(),command,id,action,sku,location,onHand,reserved,quantity,Ledger.Id(record,"correlation_id"),Ledger.Id(record),Ledger.Num(run,"granted"));
    }
    public static void Execute(Unit u,JsonObject run,JsonObject job,Settings settings) {
        Ensure(u,run); var id=Ledger.Id(job); var body=job["payload"]!["warehouse"]!.AsObject(); var action=Rules.Text(body["action"]); var runId=Ledger.Id(run); JsonObject result;
        var boundary=u.Query("SELECT event_id,aggregate_id FROM warehouse_boundary_commands WHERE run_id=@p0 AND command_id=@p1",runId,id).FirstOrDefault();
        // A savepoint makes expected business rejections durable outcomes without
        // retaining any partial writes, or failing the simulation's clock barrier.
        u.Exec("SAVEPOINT warehouse_effect");var custodyOffer=false;
        try {
            if(action=="convert") result=HandlingUnits.Convert(u,run,id,body);
            else if(action is "putaway" or "retrieve") result=HandlingUnits.Move(u,run,id,body);
            else if(action is "expect" or "reserve") {
                var sku=Rules.Text(body["sku"]); var location=Rules.Text(body["location"]); var quantity=Rules.Integer(body["quantity"],1,10000);
                var stock=u.Query("SELECT s.*,c.kind FROM warehouse_stock s JOIN warehouse_catalog c USING(run_id,sku) WHERE s.run_id=@p0 AND s.sku=@p1 AND s.location=@p2",runId,sku,location).FirstOrDefault()??throw new Conflict("Unknown SKU or location");
                if(action=="expect") result=u.One("INSERT INTO warehouse_receipts(id,run_id,sku,location,quantity,correlation_id,unit_manifest) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6) RETURNING *",id,runId,sku,location,quantity,Rules.Uuid(body["correlation_id"]),body["units"]!);
                else {
                    var purpose=Rules.Text(body["purpose"]);
                    if(stock["kind"]!.ToString()!=(purpose=="production"?"raw":"finished")) throw new Conflict("Production requires raw materials; customer picks require finished goods");
                    if(stock["on_hand"]!.GetValue<int>()-stock["reserved"]!.GetValue<int>()<quantity) throw new Conflict("Insufficient available stock; complete quantities required");
                    result=u.One("INSERT INTO warehouse_reservations(id,run_id,sku,location,quantity,correlation_id,purpose) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6) RETURNING *",id,runId,sku,location,quantity,Rules.Uuid(body["correlation_id"]),purpose);
                    HandlingUnits.Reserve(u,run,result);
                    Move(u,run,id,action,result,0,quantity);
                }
            } else {
                var reference=Rules.Uuid(body["reference"]);
                var table=action=="receive"?"warehouse_receipts":action=="arrive"?"warehouse_transfers":"warehouse_reservations";
                result=Record(u,run,table,reference); var quantity=result["quantity"]!.GetValue<int>();
                switch(action) {
                    case "receive":
                        State(result,"expected"); Capacity(u,runId,result["location"]!.ToString(),quantity); HandlingUnits.Receive(u,run,id,result); Move(u,run,id,action,result,quantity,0);
                        u.Exec("UPDATE warehouse_receipts SET status='received',version=version+1 WHERE id=@p0",reference); result["status"]="received"; break;
                    case "release":
                        StorageCustody.RequireReleasable(u,reference);
                        State(result,"reserved"); HandlingUnits.Release(u,result);Move(u,run,id,action,result,0,-quantity); u.Exec("UPDATE warehouse_reservations SET status='released',version=version+1 WHERE id=@p0",reference); result["status"]="released"; break;
                    case "issue":
                        State(result,"reserved"); if(result["purpose"]!.ToString()!="production") throw new Conflict("Only production materials can be issued");
                        if(settings.Providers["requests"]!.ToString()=="helics") { StorageCustody.Begin(u,run,settings,id,result,body);custodyOffer=true;break; }
                        HandlingUnits.Depart(u,run,id,result);Move(u,run,id,action,result,-quantity,-quantity); u.Exec("UPDATE warehouse_reservations SET status='issued',version=version+1 WHERE id=@p0",reference); result["status"]="issued"; break;
                    case "pick":
                        State(result,"reserved"); if(result["purpose"]!.ToString()!="customer") throw new Conflict("Only customer goods can be picked");
                        HandlingUnits.Pick(u,run,id,result);Move(u,run,id,action,result,0,0); u.Exec("UPDATE warehouse_reservations SET status='picked',version=version+1 WHERE id=@p0",reference); result["status"]="picked"; break;
                    case "transfer":
                        State(result,"picked"); var destination=Rules.Text(body["destination"]); var origin=result["location"]!.ToString(); if(destination==origin) throw new Conflict("Transfer destination must differ from origin");
                        if(u.Query("SELECT 1 FROM warehouse_locations WHERE run_id=@p0 AND code=@p1",runId,destination).Count==0) throw new Conflict("Unknown destination");
                        Move(u,run,id,action,result,-quantity,-quantity);
                        u.Exec("UPDATE warehouse_reservations SET status='transferred',version=version+1 WHERE id=@p0",reference);
                        var reservation=(JsonObject)result.DeepClone();
                        result=u.One("INSERT INTO warehouse_transfers(id,run_id,reservation_id,sku,origin,destination,quantity,correlation_id) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7) RETURNING *",id,runId,reference,result["sku"]!.ToString(),origin,destination,quantity,Ledger.Id(result,"correlation_id"));HandlingUnits.Depart(u,run,id,reservation,result); break;
                    case "arrive":
                        State(result,"in_transit"); var target=result["destination"]!.ToString(); Capacity(u,runId,target,quantity); HandlingUnits.Arrive(u,run,id,result);Move(u,run,id,action,result,quantity,0,target);
                        u.Exec("UPDATE warehouse_transfers SET status='received',version=version+1 WHERE id=@p0",reference); result["status"]="received"; break;
                    default: throw new Validation("Unknown warehouse action");
                }
            }
            if(!custodyOffer&&(action is "receive" or "release" or "issue" or "pick" or "arrive")) result["version"]=result["version"]!.GetValue<int>()+1;
            u.Exec("UPDATE warehouse_commands SET status='completed',result=@p0,completed_at=@p1 WHERE id=@p2",result,Ledger.Num(run,"granted"),id);
            if(!custodyOffer&&run["mode"]!.ToString()=="helics") {
                var fact=new JsonObject {["type"]="storage."+action+".completed.v1",["job_id"]=id.ToString(),["causation_id"]=boundary?["event_id"]?.DeepClone()??JsonValue.Create(id.ToString()),["correlation_id"]=result["correlation_id"]!.DeepClone(),["aggregate_id"]=result["id"]!.DeepClone(),["time"]=Ledger.Num(run,"granted"),["payload"]=result.DeepClone()};
                u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2)",Guid.NewGuid(),runId,fact);
            }
        } catch(Conflict error) {
            u.Exec("ROLLBACK TO SAVEPOINT warehouse_effect");
            u.Exec("UPDATE warehouse_commands SET status='rejected',error=@p0,completed_at=@p1 WHERE id=@p2",error.Message,Ledger.Num(run,"granted"),id);
            // Older pending jobs predate durable incoming correlation metadata.
            if(run["mode"]!.ToString()=="helics"&&boundary is not null&&job["payload"]?["boundary"] is JsonObject incoming) {
                var fact=new JsonObject { ["type"]="storage.command.rejected.v1",["job_id"]=id.ToString(),["causation_id"]=boundary["event_id"]!.DeepClone(),["aggregate_id"]=boundary["aggregate_id"]!.DeepClone(),["aggregate_version"]=1,["correlation_id"]=incoming["correlation_id"]!.DeepClone(),["time"]=Ledger.Num(run,"granted"),["payload"]=new JsonObject { ["action"]=action,["reason"]=error.Message,["request"]=body.DeepClone() } };
                u.Exec("INSERT INTO boundary_outbox(id,run_id,envelope) VALUES (@p0,@p1,@p2)",Guid.NewGuid(),runId,fact);
            }
        }
        u.Exec("RELEASE SAVEPOINT warehouse_effect");
    }
}
