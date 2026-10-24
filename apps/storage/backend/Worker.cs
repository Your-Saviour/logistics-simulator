using System.Text;
using System.Text.Json.Nodes;
using Npgsql;
using RabbitMQ.Client;
namespace Storage;
public static class Broker
{
    public const string Queue="sample.jobs.v1";
    public static async Task<IConnection> Connect(string url)=>await new ConnectionFactory { Uri=new Uri(url),AutomaticRecoveryEnabled=false,RequestedHeartbeat=TimeSpan.FromSeconds(30),RequestedConnectionTimeout=TimeSpan.FromSeconds(5) }.CreateConnectionAsync();
    public static async Task<IChannel> Channel(IConnection connection) {
        var c=await connection.CreateChannelAsync(new CreateChannelOptions(publisherConfirmationsEnabled:true,publisherConfirmationTrackingEnabled:true));
        await c.ExchangeDeclareAsync("sample.dead.v1",ExchangeType.Direct,durable:true); await c.QueueDeclareAsync("sample.jobs.dead.v1",durable:true,exclusive:false,autoDelete:false); await c.QueueBindAsync("sample.jobs.dead.v1","sample.dead.v1","dead");
        await c.QueueDeclareAsync(Queue,durable:true,exclusive:false,autoDelete:false,arguments:new Dictionary<string,object?> { ["x-dead-letter-exchange"]="sample.dead.v1",["x-dead-letter-routing-key"]="dead" }); await c.BasicQosAsync(0,1,false); return c;
    }
    public static async Task<bool> Ready(string url) { try { await using var c=await Connect(url); return c.IsOpen; } catch(Exception) { return false; } }
    public static async Task Publish(IChannel channel,string route,Guid messageId,JsonObject message) { await channel.BasicPublishAsync("",route,mandatory:true,basicProperties:new BasicProperties { Persistent=true,ContentType="application/json",MessageId=messageId.ToString() },body:Encoding.UTF8.GetBytes(message.ToJsonString())); }
}
public sealed class Worker(Ledger ledger,Settings settings,ILogger<Worker> logger): BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stop) { await Task.Yield(); while(!stop.IsCancellationRequested) {
        try { await using var connection=await Broker.Connect(settings.Amqp); await using var channel=await Broker.Channel(connection);
            while(!stop.IsCancellationRequested) {
                foreach(var row in ledger.Dispatchable()) { await Broker.Publish(channel,Broker.Queue,Ledger.Id(row),new JsonObject {["job_id"]=row["job_id"]!.DeepClone()}); ledger.Published(Ledger.Id(row)); }
                var message=await channel.BasicGetAsync(Broker.Queue,autoAck:false,cancellationToken:stop);
                if(message is not null) {
                    Guid id;
                    try { if(JsonNode.Parse(message.Body.Span) is not JsonObject body) throw new Validation("Message must be an object"); Rules.Fields(body,"job_id"); id=Rules.Uuid(body["job_id"]); }
                    catch(Exception e) when(e is System.Text.Json.JsonException or Validation or InvalidOperationException) { await channel.BasicNackAsync(message.DeliveryTag,false,false,stop); continue; }
                    string result;
                    try { result=ledger.Execute(id); }
                    catch(NpgsqlException) { throw; }
                    catch(Exception error) { result=ledger.Fail(id,error); }
                    // Every path above commits its ledger transaction before consumer ACK.
                    if(result=="dead") await channel.BasicNackAsync(message.DeliveryTag,false,false,stop); else await channel.BasicAckAsync(message.DeliveryTag,false,stop);
                }
                ledger.Heartbeat("worker"); await Task.Delay(100,stop);
            }
        } catch(OperationCanceledException) when(stop.IsCancellationRequested) { break; }
        catch(Exception error) { logger.LogWarning(error,"Worker dependency unavailable; broker deliveries remain unacknowledged"); await Task.Delay(2000,stop); }
    } }
}
