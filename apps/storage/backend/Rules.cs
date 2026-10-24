using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
namespace Storage;
public class Validation(string message): Exception(message);
public class Conflict(string message): Exception(message);
public static class Rules
{
    public static void Fields(JsonObject body, params string[] allowed) { if(body.Any(x=>!allowed.Contains(x.Key))) throw new Validation("Unknown field"); }
    public static double Number(JsonNode? node) { if(node is not JsonValue v || !v.TryGetValue<double>(out var n) || !double.IsFinite(n)) throw new Validation("Finite numeric value required"); return n; }
    public static int Integer(JsonNode? node,int min,int max) { if(node is not JsonValue v || !v.TryGetValue<int>(out var n) || n<min || n>max) throw new Validation($"Integer between {min} and {max} required"); return n; }
    public static string Text(JsonNode? node) { if(node is not JsonValue v || !v.TryGetValue<string>(out var s) || string.IsNullOrEmpty(s)) throw new Validation("Nonempty string required"); return s; }
    public static Guid Uuid(JsonNode? node) { if(!Guid.TryParseExact(Text(node),"D",out var g)) throw new Validation("UUID required"); return g; }
    public static (double Due,int Quantity) Job(JsonObject body) { Fields(body,"due_at","quantity"); var due=Number(body["due_at"]); if(due<0) throw new Validation("Nonnegative due_at required"); return (due,Integer(body["quantity"],1,10000)); }
    public static int Quantity(int seed,string app,string boundary,long slot) => 1+(int)(BinaryPrimitives.ReadUInt32BigEndian(SHA256.HashData(Encoding.UTF8.GetBytes($"{seed}:{app}:{boundary}:{slot}")))%10);
    public static Guid Uuid5(Guid ns,string name) { var hash=SHA1.HashData(ns.ToByteArray(true).Concat(Encoding.UTF8.GetBytes(name)).ToArray()); hash[6]=(byte)((hash[6]&15)|80); hash[8]=(byte)((hash[8]&63)|128); return new Guid(hash.AsSpan(0,16),true); }
    public static JsonObject Envelope(JsonObject body) {
        Fields(body,"schema_version","type","event_id","federation_id","run_id","epoch","correlation_id","causation_id","aggregate_id","aggregate_version","source","destination","boundary","effective_time","wall_time","quantity_unit","payload");
        foreach(var key in new[]{"event_id","run_id","epoch","correlation_id","causation_id","aggregate_id"}) Uuid(body[key]);
        foreach(var key in new[]{"federation_id","source","destination","boundary"}) if(Text(body[key]).Length>128) throw new Validation("Routing field too long");
        if(Text(body["schema_version"])!="1.0" || Text(body["quantity_unit"])!="item" || Number(body["effective_time"])<0) throw new Validation("Invalid envelope version, type, unit or time");
        Integer(body["aggregate_version"],1,int.MaxValue);
        if(Text(body["type"])=="sample.completed.v1") { var payload=body["payload"] as JsonObject??throw new Validation("Payload object required"); Fields(payload,"quantity"); Integer(payload["quantity"],1,10000); }
        else WarehouseProviders.Input(body);
        if(body["wall_time"] is not null && !DateTimeOffset.TryParse(Text(body["wall_time"]),out _)) throw new Validation("Invalid wall_time"); return body;
    }
}
public sealed class Scenario
{
    public readonly JsonObject Body;
    public readonly int Seed, Interval;
    public readonly TimeZoneInfo Zone;
    public readonly DateTimeOffset Start;
    public readonly TimeOnly Open,Close;
    public readonly int[] Weekdays;
    public Scenario(JsonObject body) {
        Rules.Fields(body,"seed","time_zone","start_at","business_open","business_close","business_weekdays","interval_seconds","warehouse");
        Seed=body["seed"] is null?1:Rules.Integer(body["seed"],0,int.MaxValue); Interval=body["interval_seconds"] is null?30:Rules.Integer(body["interval_seconds"],1,86400);
        var zone=body["time_zone"] is null?"Australia/Adelaide":Rules.Text(body["time_zone"]);
        try { Zone=TimeZoneInfo.FindSystemTimeZoneById(zone); } catch(TimeZoneNotFoundException) { throw new Validation("Unknown scenario timezone"); }
        var start=body["start_at"] is null?"2026-01-05T08:00:00+10:30":Rules.Text(body["start_at"]);
        if(!Regex.IsMatch(start,@"(Z|[+-]\d\d:\d\d)$") || !DateTimeOffset.TryParse(start,CultureInfo.InvariantCulture,DateTimeStyles.None,out Start)) throw new Validation("Scenario start_at needs an explicit UTC offset");
        Open=ParseTime(body["business_open"],"08:00:00"); Close=ParseTime(body["business_close"],"17:00:00");
        if(Open>=Close) throw new Validation("Business hours must increase within one day");
        Weekdays=body["business_weekdays"] is null?[0,1,2,3,4]:body["business_weekdays"]!.AsArray().Select(x=>Rules.Integer(x,0,6)).ToArray();
        if(Weekdays.Length==0||Weekdays.Distinct().Count()!=Weekdays.Length) throw new Validation("Unique business weekdays required");
        Body=new JsonObject { ["seed"]=Seed,["time_zone"]=zone,["start_at"]=Start.ToString("O"),["business_open"]=Open.ToString("HH:mm:ss"),["business_close"]=Close.ToString("HH:mm:ss"),["business_weekdays"]=new JsonArray(Weekdays.Select(x=>(JsonNode?)JsonValue.Create(x)).ToArray()),["interval_seconds"]=Interval };
        if(body["warehouse"] is not null) Body["warehouse"]=Warehouse.Configuration(body["warehouse"] as JsonObject??throw new Validation("Warehouse configuration object required"));
    }
    static TimeOnly ParseTime(JsonNode? node,string fallback) { if(!TimeOnly.TryParse(node is null?fallback:Rules.Text(node),CultureInfo.InvariantCulture,out var result)||result.Second!=0||result.Millisecond!=0) throw new Validation("Whole local minute required"); return result; }
    public DateTimeOffset Instant(double seconds)=>TimeZoneInfo.ConvertTime(Start.AddSeconds(seconds),Zone);
    public double NextDue(double after,double delay) {
        if(!double.IsFinite(after)||!double.IsFinite(delay)||after<0||delay<=0) throw new Validation("Finite nonnegative time and positive delay required");
        var candidate=Instant(after+delay); int Day(DateTime d)=>((int)d.DayOfWeek+6)%7;
        if(Weekdays.Contains(Day(candidate.Date))&&TimeOnly.FromDateTime(candidate.DateTime)>=Open&&TimeOnly.FromDateTime(candidate.DateTime)<Close) return after+delay;
        for(var n=0;n<8;n++) { var day=candidate.Date.AddDays(n); if(!Weekdays.Contains(Day(day))) continue; var local=DateTime.SpecifyKind(day+Open.ToTimeSpan(),DateTimeKind.Unspecified);
            for(var minute=0;Zone.IsInvalidTime(local)&&minute<181;minute++) local=local.AddMinutes(1);
            var offsets=Zone.IsAmbiguousTime(local)?Zone.GetAmbiguousTimeOffsets(local):[Zone.GetUtcOffset(local)];
            foreach(var stamp in offsets.Select(offset=>new DateTimeOffset(local,offset)).OrderBy(x=>x.UtcTicks)) if(stamp>=candidate && TimeOnly.FromDateTime(local)<Close) return (stamp-Start).TotalSeconds;
        } throw new Validation("No business opening within a week");
    }
}
