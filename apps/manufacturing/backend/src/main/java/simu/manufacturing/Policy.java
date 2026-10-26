package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;
final class Policy {
 static void fields(JsonNode b,String... allowed){
  if(b==null||!b.isObject())throw new IllegalArgumentException("JSON object required");
  var names=new HashSet<>(Arrays.asList(allowed));b.fieldNames().forEachRemaining(k->{if(!names.contains(k))throw new IllegalArgumentException("Unknown field: "+k);});
 }
 static double time(JsonNode n){if(n==null||!n.isNumber()||!Double.isFinite(n.doubleValue())||n.doubleValue()<0)throw new IllegalArgumentException("Finite nonnegative simulation seconds required");return n.doubleValue();}
 static int integer(JsonNode n,int min,int max){if(n==null||!n.isIntegralNumber()||!n.canConvertToInt()||n.intValue()<min||n.intValue()>max)throw new IllegalArgumentException("Integer in range "+min+".."+max+" required");return n.intValue();}
 static JsonNode job(JsonNode b){fields(b,"due_at","quantity");time(b.get("due_at"));integer(b.get("quantity"),1,10000);return b;}
 static Set<String> scopes(String role){return switch(role){case "operator"->Set.of("status:read","jobs:write","runs:control","audit:read","scenarios:manage");case "employee"->Set.of("status:read","jobs:write");case "service"->Set.of();default->throw new IllegalArgumentException("Invalid role");};}
 static UUID uuid(JsonNode n){if(n==null||!n.isTextual())throw new IllegalArgumentException("UUID required");try{var u=UUID.fromString(n.asText());if(!u.toString().equalsIgnoreCase(n.asText()))throw new IllegalArgumentException();return u;}catch(Exception e){throw new IllegalArgumentException("UUID required");}}
 static void envelope(JsonNode b){
  fields(b,"schema_version","type","event_id","federation_id","run_id","epoch","correlation_id","causation_id","aggregate_id","aggregate_version","source","destination","boundary","effective_time","wall_time","quantity_unit","payload");
  for(String k:List.of("event_id","run_id","epoch","correlation_id","causation_id","aggregate_id"))uuid(b.get(k));
  for(String k:List.of("federation_id","source","destination","boundary"))if(!b.path(k).isTextual()||b.path(k).asText().isEmpty())throw new IllegalArgumentException("Required: "+k);
  if(!b.path("schema_version").asText("1.0").equals("1.0")||!b.path("type").asText("sample.completed.v1").equals("sample.completed.v1")||!b.path("quantity_unit").asText("item").equals("item"))throw new IllegalArgumentException("Unknown event version/type/unit");
  integer(b.get("aggregate_version"),1,Integer.MAX_VALUE);time(b.get("effective_time"));fields(b.get("payload"),"quantity");integer(b.get("payload").get("quantity"),1,10000);
  if(b.has("wall_time"))java.time.OffsetDateTime.parse(b.get("wall_time").asText());
 }
}
