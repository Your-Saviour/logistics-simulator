using Storage;
using Npgsql;
using System.Text.Json;
using System.Text.Json.Nodes;
var settings=new Settings(); var database=new Database(settings); database.Migrate(); var ledger=new Ledger(database,settings);
var warehouse=new Warehouse(ledger,settings);
var builder=WebApplication.CreateBuilder(args); builder.WebHost.UseUrls("http://0.0.0.0:8000");
builder.Services.AddSingleton(settings); builder.Services.AddSingleton(database); builder.Services.AddSingleton(ledger);
if(settings.Role=="worker") builder.Services.AddHostedService<Worker>();
if(settings.Role=="controller") builder.Services.AddHostedService<Controller>();
var app=builder.Build();
app.Use(async (ctx,next)=> {
    var command=ctx.Request.Method=="POST"&&ctx.Request.Path.StartsWithSegments("/api");
    var audit=new Audit(Guid.NewGuid(),"anonymous","anonymous",ctx.Request.Method+" "+ctx.Request.Path,ctx.Request.Headers["Idempotency-Key"].ToString(),ctx.Connection.RemoteIpAddress?.ToString()??""); ctx.Response.Headers["X-Request-ID"]=audit.RequestId.ToString();
    try {
        if(command) audit=audit with { RunId=ledger.Scope() };
        if(!ctx.Request.Path.StartsWithSegments("/api/health")) {
            var identity=settings.Identify(ctx.Request.Headers.Authorization.ToString()); if(identity is null) { ctx.Response.StatusCode=401; await ctx.Response.WriteAsJsonAsync(new {detail="Invalid username or password"}); return; }
            audit=audit with { Actor=identity.Username,Role=identity.Role }; ctx.Items["identity"]=identity;
            var scope=ctx.Request.Path.StartsWithSegments("/api/control")?"runs:control":ctx.Request.Path=="/api/audit"?"audit:read":command?"jobs:write":"status:read";
            if(!identity.Scopes.Contains(scope)) { ctx.Response.StatusCode=403; await ctx.Response.WriteAsJsonAsync(new { detail="This identity cannot perform the requested action" }); return; }
        }
        ctx.Items["audit"]=audit; await next(ctx);
    } catch(Exception e) when(e is Conflict or Validation or JsonException or InvalidOperationException or FormatException or NpgsqlException or TimeoutException) {
        ctx.Response.StatusCode=e is Conflict?409:e is NpgsqlException or TimeoutException?503:422;
        await ctx.Response.WriteAsJsonAsync(new { detail=e is NpgsqlException or TimeoutException?"Database unavailable; retry with the same idempotency key":e.Message });
    } finally {
        if(command&&ctx.Response.StatusCode>=400&&audit.RunId is not null) { try { ledger.Rejected(audit,ctx.Response.StatusCode); } catch(Exception e) { app.Logger.LogError(e,"Rejected command audit unavailable {RequestId}",audit.RequestId); } }
    }
});
app.MapGet("/api/health/live",()=>new { application="storage",alive=true });
app.MapGet("/api/health/ready",async ()=> { try { var status=ledger.Status(); var broker=await Broker.Ready(settings.Amqp); var roles=status["heartbeats"]!.AsArray().Where(x=>x!["healthy"]!.GetValue<bool>()).Select(x=>x!["role"]!.ToString()).ToHashSet(); var ready=broker&&roles.Contains("worker")&&roles.Contains("controller")&&status["run"]!["state"]!.ToString() is not ("failed" or "stalled"); return Results.Json(new { application="storage",database=true,broker,ready },statusCode:ready?200:503); } catch(Exception) { return Results.Json(new { application="storage",ready=false },statusCode:503); } });
app.MapGet("/api/projection",()=>warehouse.Projection());
app.MapGet("/api/status",(HttpContext ctx)=> { var status=ledger.Status(); var identity=(Identity)ctx.Items["identity"]!; status["identity"]=new JsonObject {["username"]=identity.Username,["role"]=identity.Role,["scopes"]=new JsonArray(identity.Scopes.Order().Select(s=>(JsonNode?)JsonValue.Create(s)).ToArray())}; status["application"]="storage"; status["providers"]=settings.Providers.DeepClone(); status["quantum"]=settings.Quantum; status["simulation_time"]=new Scenario(status["run"]!["scenario"]!.AsObject()).Instant(Ledger.Num(status["run"]!.AsObject(),"granted")).ToString("O"); return status; });
async Task<JsonObject> Body(HttpContext ctx) { if(ctx.Request.ContentLength>65536) throw new Validation("Command too large"); return (await JsonNode.ParseAsync(ctx.Request.Body))?.AsObject()??throw new Validation("JSON object required"); }
app.MapPost("/api/jobs",async (HttpContext ctx)=> { var body=await Body(ctx); var job=Rules.Job(body); var key=ctx.Request.Headers["Idempotency-Key"].ToString(); if(key.Length is <1 or >128) throw new Validation("Idempotency-Key length must be 1..128"); if(new[]{"synthetic:","boundary:","synthetic-sample:","warehouse:"}.Any(key.StartsWith)) throw new Conflict("This idempotency key namespace is reserved for internal providers"); return ledger.Schedule(key,job.Due,job.Quantity,(Audit)ctx.Items["audit"]!); });
app.MapPost("/api/control/{action}",async (HttpContext ctx,string action)=>ledger.Control(action,await Body(ctx),(Audit)ctx.Items["audit"]!));
app.MapGet("/api/warehouse",()=>warehouse.Snapshot());
app.MapPost("/api/warehouse/commands",async (HttpContext ctx)=> { var body=await Body(ctx); return warehouse.Submit(ctx.Request.Headers["Idempotency-Key"].ToString(),body,(Audit)ctx.Items["audit"]!); });
app.MapGet("/api/sources",()=>new JsonArray()); app.MapGet("/api/audit",()=>ledger.Audits());
app.Run();
