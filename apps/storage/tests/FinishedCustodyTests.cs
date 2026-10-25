using Storage;
using System.Text.Json.Nodes;

public static class FinishedCustodyTests
{
    public static void Run(Ledger ledger,Settings settings,Action<bool,string> check) {
        RunCase(ledger,settings,check,false);
        RunCase(ledger,settings,check,true);
    }
    static void RunCase(Ledger ledger,Settings settings,Action<bool,string> check,bool rawInbound) {
        var source=rawInbound?"logistics":"manufacturing";
        var category=rawInbound?"raw":"finished";var sku=rawInbound?"COMPONENT":"PRODUCT";
        var logical=rawInbound?"RAW-A":"FINISHED-A";
        var origin=rawInbound?"logistics.inbound.dock01":"manufacturing.cell01.output01";
        var destination=rawInbound?"storage.inbound.dock01":"storage.finished_receipt.dock01";
        var shelf=rawInbound?"storage.raw.r01.b01.l04":"storage.finished.r01.b01.l04";
        var feedbackOwner=rawInbound?"manufacturing":"shipping";
        var feedbackBoundary=rawInbound?"materials":"goods";
        var audit=new Audit(Guid.NewGuid(),"finished-custody","operator","test:custody","","tests");
        var originalProviders=settings.Providers;var originalPeers=settings.Peers;var originalOutputs=settings.Outputs;var federation=settings.Federation;
        void Reset(){var r=ledger.Status()["run"]!.AsObject();ledger.Control("reset",new JsonObject {["confirm_run_id"]=r["id"]!.DeepClone()},audit);}
        Reset();double time=0;var warehouse=new Warehouse(ledger,settings);
        JsonObject Handling()=>warehouse.Snapshot()["handling"]!.AsObject();
        JsonObject Stock()=>warehouse.Snapshot()["inventory"]!.AsArray().Single(n=>n!["sku"]!.ToString()==sku&&n["location"]!.ToString()==logical)!.AsObject();
        JsonObject Offer(){var r=ledger.Status()["run"]!.AsObject();var id=Guid.NewGuid();var handoff=Guid.NewGuid();return new JsonObject {
            ["schema_version"]="1.0",["type"]="handling.offered.v1",["event_id"]=Guid.NewGuid().ToString(),["federation_id"]="finished-custody",["run_id"]=r["id"]!.DeepClone(),["epoch"]=r["epoch"]!.DeepClone(),["correlation_id"]=Guid.NewGuid().ToString(),["causation_id"]=handoff.ToString(),["aggregate_id"]=handoff.ToString(),["aggregate_version"]=2,["source"]=source,["destination"]="storage",["boundary"]="supply",["effective_time"]=++time,["wall_time"]="2026-10-25T00:00:00Z",["quantity_unit"]="item",
            ["payload"]=new JsonObject {["id"]=handoff.ToString(),["run_id"]=r["id"]!.DeepClone(),["epoch"]=r["epoch"]!.DeepClone(),["source"]=source,["destination_owner"]="storage",["origin"]=origin,["destination"]=destination,["state"]="offered",["departure_token"]=null,["receipt_id"]=null,["reason"]=null,
                ["unit"]=new JsonObject {["id"]=id.ToString(),["barcode"]="HU-"+id.ToString("N").ToUpperInvariant(),["run_id"]=r["id"]!.DeepClone(),["epoch"]=r["epoch"]!.DeepClone(),["owner"]=source,["category"]=category,["state"]="reserved",["contents"]=new JsonArray(new JsonObject {["sku"]=sku,["quantity"]=2}),["version"]=2,["last_sequence"]=1,["custody_generation"]=0,["position"]=origin,["origin"]=null,["destination"]=null,["handoff_id"]=null}}};}
        Guid Receive(JsonObject e){check(ledger.Ingest(e,source+"/events")=="accepted",category+" custody input accepted from "+source+" by configured native receiver");var id=ledger.Db.Transaction(u=>Ledger.Id(u.One("SELECT id FROM jobs WHERE idempotency_key=@p0","boundary:"+e["event_id"]!.ToString())));ledger.Heartbeat("controller");ledger.Db.Transaction(u=>{var r=u.Run();u.Exec("UPDATE runs SET granted=@p0,requested=@p0 WHERE id=@p1",time,Ledger.Id(r));return true;});check(ledger.Execute(id)=="completed","finished custody executes inside native worker transaction");return id;}
        try {
            ledger.Db.Transaction(u=>{var r=u.Run();u.Exec("UPDATE runs SET mode='helics' WHERE id=@p0",Ledger.Id(r));return true;});
            settings.Federation="finished-custody";settings.Providers=new JsonObject {["supply"]="helics",["requests"]="synthetic"};settings.Peers=new JsonObject {["supply"]=new JsonObject {["source"]=source,["endpoint"]=source+"/events"}};settings.Outputs=new JsonArray(new JsonObject {["destination"]=source,["boundary"]=rawInbound?"destinations":"materials",["endpoint"]=source+"/events"});
            var offer=Offer();var stale=(JsonObject)offer.DeepClone();stale["event_id"]=Guid.NewGuid().ToString();var staleEpoch=Guid.NewGuid().ToString();stale["epoch"]=staleEpoch;stale["payload"]!["epoch"]=staleEpoch;stale["payload"]!["unit"]!["epoch"]=staleEpoch;
            check(ledger.Ingest(stale,source+"/events")=="quarantined","stale custody scope is durably quarantined rather than discarded");check(ledger.Ingest(stale,source+"/events")=="quarantined"&&Handling()["quarantine"]!.AsArray().Count==1,"repeated stale evidence retains one inspectable case");check(Stock()["on_hand"]!.GetValue<int>()==0&&Handling()["units"]!.AsArray().Count==0,"scope quarantine changes no stock or placement");
            Receive(offer);
            check(Handling()["handoffs"]!.AsArray().Count==1,"finished receiver persists positive dock acceptance");check(Handling()["units"]!.AsArray().Count==0&&Stock()["on_hand"]!.GetValue<int>()==0,"capacity acceptance cannot create a unit or stock");
            var competing=Offer();var rejected=Receive(competing);check(ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",rejected))["status"]!.ToString()=="rejected","two offers cannot claim the same receiving dock");
            var departed=(JsonObject)offer.DeepClone();departed["type"]="handling.departed.v1";departed["event_id"]=Guid.NewGuid().ToString();departed["effective_time"]=++time;departed["aggregate_version"]=3;var h=departed["payload"]!.AsObject();h["state"]="departed";var unit=h["unit"]!.AsObject();unit["state"]="in_transit";unit["position"]=null;unit["origin"]=h["origin"]!.DeepClone();unit["destination"]=h["destination"]!.DeepClone();unit["handoff_id"]=h["id"]!.DeepClone();unit["version"]=3;unit["last_sequence"]=2;unit["custody_generation"]=1;
            h["departure_token"]=new JsonObject {["id"]=Guid.NewGuid().ToString(),["handoff_id"]=h["id"]!.DeepClone(),["unit_id"]=unit["id"]!.DeepClone(),["run_id"]=h["run_id"]!.DeepClone(),["epoch"]=h["epoch"]!.DeepClone(),["unit_version"]=3,["last_sequence"]=2,["custody_generation"]=1};
            var corrupt=(JsonObject)departed.DeepClone();corrupt["event_id"]=Guid.NewGuid().ToString();corrupt["payload"]!["unit"]!["contents"]![0]!["quantity"]=3;Receive(corrupt);check(Stock()["on_hand"]!.GetValue<int>()==0,"changed contents cannot import stock");check(Handling()["quarantine"]!.AsArray().Count==2,"rejected departure proof is inspectable alongside scope quarantine");
            foreach(var field in new[]{"owner","category","state","barcode"}){var malformed=(JsonObject)offer.DeepClone();malformed["event_id"]=Guid.NewGuid().ToString();malformed["payload"]!["unit"]![field]=null;check(ledger.Ingest(malformed,source+"/events")=="quarantined","null custody unit "+field+" is quarantined without an application failure");}
            Receive(departed);var imported=Handling()["units"]!.AsArray().Single()!;
            check(imported["id"]!.ToString()==unit["id"]!.ToString()&&imported["barcode"]!.ToString()==unit["barcode"]!.ToString(),"receipt preserves Manufacturing output identity and barcode");check(imported["position"]!.ToString()==destination&&imported["last_sequence"]!.GetValue<int>()==3&&imported["version"]!.GetValue<int>()==4&&imported["custody_generation"]!.GetValue<int>()==1,"receipt continues counters at the positively accepted dock");check(Stock()["on_hand"]!.GetValue<int>()==2,"matching departure adds finished stock exactly once");check(ledger.Ingest(departed,source+"/events")=="duplicate"&&Stock()["on_hand"]!.GetValue<int>()==2,"duplicate departure cannot manufacture another unit or quantity");
            var feedback=ledger.Db.Transaction(u=>u.Query("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'type'='storage.receive.completed.v1' AND envelope->'payload'->>'sku'=@p1",Ledger.Id(offer,"run_id"),sku));
            check(feedback.Count==1&&feedback[0]["envelope"]!["destination"]!.ToString()==feedbackOwner&&feedback[0]["envelope"]!["boundary"]!.ToString()==feedbackBoundary&&feedback[0]["envelope"]!["correlation_id"]!.ToString()==offer["correlation_id"]!.ToString(),"actual finished custody receipt publishes one routed stock notification for waiting Shipping production");
            // Exhausted imported counters reject locally without overflowing PostgreSQL.
            var unitId=Rules.Uuid(unit["id"]);
            Guid Local(string action,JsonObject fields){var r=ledger.Status()["run"]!.AsObject();fields["run_id"]=r["id"]!.DeepClone();fields["epoch"]=r["epoch"]!.DeepClone();fields["due_at"]=++time;fields["action"]=action;var c=warehouse.Submit(Guid.NewGuid().ToString(),fields,audit);ledger.Heartbeat("controller");ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE runs SET granted=@p0,requested=@p0 WHERE current",time);return true;});ledger.Execute(Ledger.Id(c));return Ledger.Id(c);}
            foreach(var counter in new[]{"version","last_sequence"}){
                ledger.Db.Transaction(u=>{u.Run();u.Exec($"UPDATE warehouse_handling_units SET {counter}=@p0 WHERE id=@p1",int.MaxValue,unitId);return true;});
                try {var exhausted=Local("putaway",new JsonObject {["unit_id"]=unitId.ToString(),["destination"]=shelf});check(ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",exhausted))["status"]!.ToString()=="rejected","exhausted imported "+counter+" rejects movement as a durable business outcome");}
                finally {ledger.Db.Transaction(u=>{u.Run();u.Exec($"UPDATE warehouse_handling_units SET {counter}=@p0 WHERE id=@p1",counter=="version"?4:3,unitId);return true;});}
            }
            ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE warehouse_handling_units SET version=@p0 WHERE id=@p1",int.MaxValue,unitId);return true;});
            try {var exhausted=Local("reserve",new JsonObject {["sku"]=sku,["location"]=logical,["quantity"]=2,["purpose"]="customer",["correlation_id"]=Guid.NewGuid().ToString()});check(ledger.Db.Transaction(u=>u.One("SELECT status FROM warehouse_commands WHERE id=@p0",exhausted))["status"]!.ToString()=="rejected","exhausted imported unit cannot overflow customer reservation");}
            finally {ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE warehouse_handling_units SET version=4 WHERE id=@p0",unitId);return true;});}
            var receipt=ledger.Db.Transaction(u=>u.One("SELECT envelope FROM boundary_outbox WHERE run_id=@p0 AND envelope->>'type'='handling.received.v1' AND envelope->'payload'->>'id'=@p1",Ledger.Id(offer,"run_id"),offer["aggregate_id"]!.ToString())["envelope"]!.AsObject());
            check(receipt["destination"]!.ToString()==source&&receipt["boundary"]!.ToString()==(rawInbound?"destinations":"materials"),"custody receipt returns to the exact source boundary");
            var ack=(JsonObject)departed.DeepClone();ack["type"]="handling.acknowledged.v1";ack["event_id"]=Guid.NewGuid().ToString();ack["effective_time"]=++time;ack["payload"]!["state"]="acknowledged";ack["payload"]!["receipt_id"]=receipt["payload"]!["receipt_id"]!.DeepClone();Receive(ack);check(Handling()["handoffs"]!.AsArray().Single()!["state"]!.ToString()=="acknowledged","receiver closes matching acknowledgement without a second stock mutation");
        }finally {settings.Providers=originalProviders;settings.Peers=originalPeers;settings.Outputs=originalOutputs;settings.Federation=federation;ledger.Db.Transaction(u=>{u.Run();u.Exec("UPDATE runs SET mode='standalone' WHERE current");return true;});Reset();}
    }
}
