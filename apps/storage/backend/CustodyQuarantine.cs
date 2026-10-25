using System.Text.Json.Nodes;
namespace Storage;

public static class CustodyQuarantine
{
    static bool Seen(Unit u,JsonObject run,JsonObject e)=>u.Query("SELECT 1 FROM warehouse_custody_quarantine WHERE run_id=@p0 AND epoch=@p1 AND event_id=@p2 AND envelope=@p3",Ledger.Id(run),Ledger.Id(run,"epoch"),Ledger.Id(e,"event_id"),e).Count>0;
    public static void Record(Unit u,JsonObject run,JsonObject e,string endpoint,string phase,string reason,Guid? command=null){
        if(u.Query("SELECT 1 FROM warehouse_custody_quarantine WHERE run_id=@p0 AND epoch=@p1 AND event_id=@p2 AND envelope=@p3 AND phase=@p4 AND reason=@p5",Ledger.Id(run),Ledger.Id(run,"epoch"),Ledger.Id(e,"event_id"),e,phase,reason).Count>0)return;
        u.Exec("INSERT INTO warehouse_custody_quarantine(id,run_id,epoch,event_id,envelope,endpoint,phase,reason,command_id,simulation_time) VALUES (@p0,@p1,@p2,@p3,@p4,@p5,@p6,@p7,@p8,@p9)",Guid.NewGuid(),Ledger.Id(run),Ledger.Id(run,"epoch"),Ledger.Id(e,"event_id"),e,endpoint,phase,reason,command,Ledger.Num(run,"granted"));
    }
    public static string Ingest(Ledger ledger,Settings settings,JsonObject e,string endpoint){
        var header=(JsonObject)e.DeepClone();header["type"]="sample.completed.v1";header["payload"]=new JsonObject {["quantity"]=1};Rules.Envelope(header);
        var boundary=Rules.Text(e["boundary"]);if(e["destination"]!.ToString()!="storage"||e["federation_id"]!.ToString()!=settings.Federation||settings.Providers[boundary]?.ToString()!="helics"||!settings.HasPeer(boundary,Rules.Text(e["source"]),endpoint))throw new Conflict("Unconfigured custody peer");
        if(ledger.Db.Transaction(u=>Seen(u,u.Run(),e)))return "quarantined";
        try {var result=e["payload"] is JsonObject h&&h["source"]?.ToString() is "manufacturing" or "logistics"?FinishedCustody.Ingest(ledger,settings,e,endpoint):StorageCustody.Ingest(ledger,settings,e,endpoint);if(result!="fenced")return result;
            ledger.Db.Transaction(u=>{Record(u,u.Run(),e,endpoint,"ingest","Custody run or epoch mismatch");return true;});
        }catch(Exception error)when(error is Conflict or Validation){ledger.Db.Transaction(u=>{Record(u,u.Run(),e,endpoint,"ingest",error.Message);return true;});}
        return "quarantined";
    }
    public static JsonArray Snapshot(Unit u,JsonObject run)=>Ledger.Array(u.Query("SELECT * FROM warehouse_custody_quarantine WHERE run_id=@p0 AND epoch=@p1 ORDER BY recorded_at,id",Ledger.Id(run),Ledger.Id(run,"epoch")));
}
