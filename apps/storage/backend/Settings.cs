using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
namespace Storage;
public record Identity(string Username,string Password,string Role,string[] Scopes);
public sealed class Settings
{
    public static string Env(string name,string fallback="")=>Environment.GetEnvironmentVariable(name)??fallback;
    public string Mode=Env("CLOCK_MODE","standalone"), Role=Env("ROLE","api"), Database=Env("DATABASE_URL"), Amqp=Env("AMQP_URL"), Federation=Env("FEDERATION_ID"), InitialRun=Env("FEDERATION_RUN_ID"), InitialEpoch=Env("FEDERATION_EPOCH"), AdapterUrl=Env("HELICS_ADAPTER_URL"), AdapterToken=Env("HELICS_ADAPTER_TOKEN");
    public string FleetMode=Env("FLEET_MODE","disabled"), FleetUrl=Env("FLEET_URL"), FleetToken=Env("FLEET_TOKEN"), FleetRun=Env("FLEET_RUN_ID"), FleetEpoch=Env("FLEET_EPOCH");
    public double FleetOffset=double.Parse(Env("FLEET_TIME_OFFSET","0"),System.Globalization.CultureInfo.InvariantCulture);
    public double Quantum=double.Parse(Env("HANDOFF_QUANTUM","1"),System.Globalization.CultureInfo.InvariantCulture);
    public JsonObject Providers=JsonNode.Parse(Env("BOUNDARY_PROVIDERS","{}"))!.AsObject(), Peers=JsonNode.Parse(Env("HELICS_PEERS","{}"))!.AsObject();
    public JsonArray Outputs=JsonNode.Parse(Env("HELICS_OUTPUTS","[]"))!.AsArray();
    public Scenario Scenario=new(JsonNode.Parse(Env("SCENARIO","{}"))!.AsObject());
    public List<Identity> Identities=[];
    static readonly Dictionary<string,string[]> Permissions=new() { ["operator"]=["status:read","jobs:write","runs:control","audit:read"],["employee"]=["status:read","jobs:write"],["service"]=["status:read","jobs:write"] };
    public bool HasPeer(string boundary,string source,string? endpoint=null) {
        var value=Peers[boundary];var routes=value is JsonArray array?array:new JsonArray(value?.DeepClone());
        return routes.Any(p=>p is JsonObject&&p["source"]?.ToString()==source&&(endpoint is null||p["endpoint"]?.ToString()==endpoint));
    }
    public bool HasOutput(string owner,string boundary)=>Outputs.Any(o=>o?["destination"]?.ToString()==owner&&o["boundary"]?.ToString()==boundary);
    public Settings() {
        if(!double.IsFinite(FleetOffset)||FleetOffset<0)throw new Validation("Fleet offset must be finite and nonnegative");
        if(FleetMode is not ("disabled" or "coordinated")||FleetMode=="coordinated"&&(!Guid.TryParse(FleetRun,out _)||!Guid.TryParse(FleetEpoch,out _)||!Uri.TryCreate(FleetUrl,UriKind.Absolute,out var fleetUri)||fleetUri.Scheme is not ("http" or "https")||string.IsNullOrEmpty(FleetToken)))throw new Validation("Coordinated fleet requires URL, private token and run/epoch UUIDs");
        if(Env("SIMULATOR","storage")!="storage" || !new[]{"api","worker","controller"}.Contains(Role) || !new[]{"standalone","helics"}.Contains(Mode)) throw new Validation("Invalid simulator, role or clock mode");
        if(!double.IsFinite(Quantum)||Quantum<1) throw new Validation("Finite quantum of at least one second required");
        if(Providers.Count==0&&Mode=="standalone") Providers=new JsonObject {["supply"]="synthetic",["requests"]="synthetic"};
        if(Providers.Count!=2||!Providers.ContainsKey("supply")||!Providers.ContainsKey("requests")||Providers.Any(x=>x.Value?.ToString() is not ("synthetic" or "helics"))) throw new Validation("Exactly one provider per storage boundary required");
        if(Mode=="standalone"&&Providers.Any(x=>x.Value!.ToString()!="synthetic")) throw new Validation("Standalone requires synthetic providers");
        if(Mode=="helics"&&(!Providers.Any(x=>x.Value!.ToString()=="helics")||!Guid.TryParse(InitialRun,out _)||!Guid.TryParse(InitialEpoch,out _)||string.IsNullOrEmpty(Federation)||string.IsNullOrEmpty(AdapterUrl)||string.IsNullOrEmpty(AdapterToken))) throw new Validation("Connected mode requires providers, run, epoch, federation and private adapter credentials");
        var accounts=JsonNode.Parse(Env("APP_IDENTITIES","[]"))!.AsArray();
        accounts.Insert(0,new JsonObject {["username"]=Env("APP_USERNAME","operator"),["password"]=Env("APP_PASSWORD"),["role"]="operator"});
        foreach(var node in accounts) { var a=node!.AsObject(); var name=Rules.Text(a["username"]); var pass=Rules.Text(a["password"]); var role=Rules.Text(a["role"]);
            if(name.Contains(':')||Identities.Any(x=>x.Username==name)||!Permissions.ContainsKey(role)) throw new Validation("Invalid or duplicate identity");
            var scopes=a["scopes"] is null?(role=="service"?[]:Permissions[role]):a["scopes"]!.AsArray().Select(Rules.Text).ToArray();
            if(scopes.Except(Permissions[role]).Any()) throw new Validation("Identity scopes exceed role");
            Identities.Add(new(name,pass,role,scopes));
        }
    }
    public Identity? Identify(string header) { if(!header.StartsWith("Basic ",StringComparison.OrdinalIgnoreCase)) return null; string raw; try { raw=Encoding.UTF8.GetString(Convert.FromBase64String(header[6..])); } catch(FormatException) { return null; }
        var i=raw.IndexOf(':'); if(i<0) return null; Identity? found=null;
        foreach(var a in Identities) { var user=CryptographicOperations.FixedTimeEquals(SHA256.HashData(Encoding.UTF8.GetBytes(raw[..i])),SHA256.HashData(Encoding.UTF8.GetBytes(a.Username))); var pass=CryptographicOperations.FixedTimeEquals(SHA256.HashData(Encoding.UTF8.GetBytes(raw[(i+1)..])),SHA256.HashData(Encoding.UTF8.GetBytes(a.Password))); if(user&pass) found=a; } return found;
    }
}
