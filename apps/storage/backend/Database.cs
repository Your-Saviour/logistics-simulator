using Npgsql;
using NpgsqlTypes;
using System.Text.Json;
using System.Text.Json.Nodes;
namespace Storage;
public sealed class Unit(NpgsqlConnection connection)
{
    public NpgsqlConnection Connection=connection;
    public List<JsonObject> Query(string sql,params object?[] args) {
        using var cmd=new NpgsqlCommand(sql,Connection); for(int i=0;i<args.Length;i++) { var v=args[i]; var p=cmd.Parameters.AddWithValue("p"+i,v is JsonNode n?n.ToJsonString():v??DBNull.Value); if(v is JsonNode) p.NpgsqlDbType=NpgsqlDbType.Jsonb; }
        using var reader=cmd.ExecuteReader(); List<JsonObject> rows=[];
        while(reader.Read()) { var row=new JsonObject(); for(int i=0;i<reader.FieldCount;i++) { if(reader.IsDBNull(i)) { row[reader.GetName(i)]=null; continue; } var value=reader.GetValue(i); row[reader.GetName(i)]=reader.GetDataTypeName(i) is "jsonb" or "json"?JsonNode.Parse(value.ToString()!):JsonSerializer.SerializeToNode(value); } rows.Add(row); } return rows;
    }
    public JsonObject One(string sql,params object?[] args)=>Query(sql,args).First();
    public void Exec(string sql,params object?[] args)=>Query(sql,args);
    public JsonObject Run() { Exec("SELECT pg_advisory_xact_lock_shared(8192103)"); for(var i=0;i<10;i++) { var rows=Query("SELECT * FROM runs WHERE current FOR UPDATE"); if(rows.Count>0) return rows[0]; } throw new Conflict("Current run changed repeatedly; retry"); }
}
public sealed class Database(Settings settings)
{
    public static string ConnectionString(string url) {
        if(!url.StartsWith("postgres",StringComparison.OrdinalIgnoreCase)) return url;
        var uri=new Uri(url); var auth=uri.UserInfo.Split(':',2);
        var builder=new NpgsqlConnectionStringBuilder { Host=uri.Host,Port=uri.Port<0?5432:uri.Port,Username=Uri.UnescapeDataString(auth[0]),Password=Uri.UnescapeDataString(auth.ElementAtOrDefault(1)??""),Database=uri.AbsolutePath.TrimStart('/'),Timeout=5,CommandTimeout=10,GssEncryptionMode=GssEncryptionMode.Disable };
        var names=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["sslmode"]="SSL Mode",["sslrootcert"]="Root Certificate",["sslcert"]="SSL Certificate",["sslkey"]="SSL Key",["sslpassword"]="SSL Password",["connect_timeout"]="Timeout",["application_name"]="Application Name",["options"]="Options",["gssencmode"]="GSS Encryption Mode" };
        foreach(var part in uri.Query.TrimStart('?').Split('&',StringSplitOptions.RemoveEmptyEntries)) { var pair=part.Split('=',2); var key=Uri.UnescapeDataString(pair[0]); if(!names.TryGetValue(key,out var mapped)) throw new Validation("Unsupported PostgreSQL URL option: "+key); var value=Uri.UnescapeDataString(pair.ElementAtOrDefault(1)??""); builder[mapped]=key.Equals("sslmode",StringComparison.OrdinalIgnoreCase)?value.Replace("verify-full","VerifyFull",StringComparison.OrdinalIgnoreCase).Replace("verify-ca","VerifyCA",StringComparison.OrdinalIgnoreCase):value; }
        return builder.ConnectionString;
    }
    public NpgsqlConnection Connect() { var db=new NpgsqlConnection(ConnectionString(settings.Database)); db.Open(); return db; }
    public NpgsqlConnection ConnectLease() {
        // A session advisory lock must disappear before the owner records a
        // failure from another connection. Pool reset can be deferred until
        // reuse, so controller ownership requires a dedicated physical session.
        var options=new NpgsqlConnectionStringBuilder(ConnectionString(settings.Database)) { Pooling=false };
        var db=new NpgsqlConnection(options.ConnectionString); db.Open(); return db;
    }
    public T Transaction<T>(Func<Unit,T> action) { using var db=Connect(); using var tx=db.BeginTransaction(); var u=new Unit(db); u.Exec("SELECT pg_advisory_xact_lock_shared(8192103)"); var result=action(u); tx.Commit(); return result; }
    public void Migrate() {
        using var db=Connect(); using var tx=db.BeginTransaction(); var u=new Unit(db); u.Exec("SELECT pg_advisory_xact_lock(8192101)");
        var exists=u.One("SELECT to_regclass('schema_migrations')::text AS name")["name"] is not null;
        var applied=exists?u.Query("SELECT name,checksum FROM schema_migrations").ToDictionary(x=>x["name"]!.ToString(),x=>x["checksum"]!.ToString()):[];
        var files=Directory.GetFiles(Path.Combine(AppContext.BaseDirectory,"migrations"),"*.sql").Order().Select(path=>(Name:Path.GetFileName(path),Sql:File.ReadAllText(path))).ToArray();
        foreach(var f in files) if(applied.TryGetValue(f.Name,out var sum)&&sum!=Checksum(f.Sql)) throw new Conflict("Applied migration was edited: "+f.Name);
        var pending=files.Where(f=>!applied.ContainsKey(f.Name)).ToArray();
        u.Exec(pending.Length>0?"SELECT pg_advisory_xact_lock(8192103)":"SELECT pg_advisory_xact_lock_shared(8192103)");
        if(pending.Length>0) u.Exec("CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())");
        foreach(var f in pending) { u.Exec(f.Sql); u.Exec("INSERT INTO schema_migrations(name,checksum) VALUES (@p0,@p1)",f.Name,Checksum(f.Sql)); }
        var runs=u.Query("SELECT * FROM runs WHERE current"); if(runs.Count==0) u.Exec("INSERT INTO runs(id,epoch,mode,scenario) VALUES (@p0,@p1,@p2,@p3)",settings.Mode=="helics"?Guid.Parse(settings.InitialRun):Guid.NewGuid(),settings.Mode=="helics"?Guid.Parse(settings.InitialEpoch):Guid.NewGuid(),settings.Mode,settings.Scenario.Body);
        var run=u.Run(); if(run["scenario"]!.AsObject().Count==0) u.Exec("UPDATE runs SET scenario=@p0 WHERE id=@p1",settings.Scenario.Body,Guid.Parse(run["id"]!.ToString()));
        if(run["mode"]!.ToString()!=settings.Mode||settings.Mode=="helics"&&(run["id"]!.ToString()!=settings.InitialRun||run["epoch"]!.ToString()!=settings.InitialEpoch)) throw new Conflict("Persisted federation/mode differs; retain and archive database before operator cutover"); tx.Commit();
    }
    public static string Checksum(string sql)=>Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(sql))).ToLowerInvariant();
}
