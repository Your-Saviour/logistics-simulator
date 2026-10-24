package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.*;
final class Settings {
 final Map<String,String> env;
 final String database,amqp,mode,role,run,epoch,federation;
 final double quantum;
 final JsonNode providers,scenario,peers,outputs;
 final List<Account> accounts=new ArrayList<>();
 record Account(String username,String password,String role,Set<String> scopes){Map<String,Object> publicValue(){return Map.of("username",username,"role",role,"scopes",scopes.stream().sorted().toList());}}
 Settings(Map<String,String> e){
  env=Map.copyOf(e);database=get("DATABASE_URL","");amqp=get("AMQP_URL","");mode=get("CLOCK_MODE","standalone");role=get("ROLE","api");run=get("FEDERATION_RUN_ID","");epoch=get("FEDERATION_EPOCH","");federation=get("FEDERATION_ID","");quantum=Double.parseDouble(get("HANDOFF_QUANTUM","1"));
  if(!get("SIMULATOR","manufacturing").equals("manufacturing")||!Set.of("standalone","helics").contains(mode)||!Set.of("api","worker","controller").contains(role)||!Double.isFinite(quantum)||quantum<1)throw new IllegalArgumentException("Invalid application/role/clock/quantum");
  var p=Json.parse(get("BOUNDARY_PROVIDERS",mode.equals("standalone")?"{\"materials\":\"synthetic\",\"demand\":\"synthetic\",\"power\":\"synthetic\"}":"{}"));
  Policy.fields(p,"materials","demand","power");if(p.size()!=3)throw new IllegalArgumentException("Explicit materials, demand and power providers required");
  p.forEach(v->{if(!Set.of("synthetic","helics").contains(v.asText())||(mode.equals("standalone")&&!v.asText().equals("synthetic")))throw new IllegalArgumentException("Invalid boundary provider");});
  if(mode.equals("helics")&&!p.toString().contains("helics"))throw new IllegalArgumentException("Connected mode needs HELICS boundary");providers=p;
  var scenarioInput=Json.parse(get("SCENARIO","{}"));String preset=get("SCENARIO_PRESET","");if(!preset.isEmpty()){if(!preset.equals("pump-assembly"))throw new IllegalArgumentException("Unknown scenario preset");try(var input=new org.springframework.core.io.ClassPathResource("scenarios/pump-assembly.json").getInputStream()){var base=(com.fasterxml.jackson.databind.node.ObjectNode)Json.parse(new String(input.readAllBytes(),StandardCharsets.UTF_8));Policy.fields(scenarioInput,"seed","time_zone","start_at","business_open","business_close","business_weekdays","interval_seconds","manufacturing");scenarioInput.fields().forEachRemaining(e2->base.set(e2.getKey(),e2.getValue()));scenarioInput=base;}catch(java.io.IOException error){throw new IllegalArgumentException("Scenario preset unavailable",error);}}scenario=Scenario.normalize(scenarioInput);peers=Json.parse(get("HELICS_PEERS","{}"));outputs=Json.parse(get("HELICS_OUTPUTS","[]"));
  var identities=Json.parse(get("APP_IDENTITIES","[]"));if(!identities.isArray())throw new IllegalArgumentException("APP_IDENTITIES must be array");
  add(get("APP_USERNAME","operator"),get("APP_PASSWORD",""),"operator",null);
  for(var a:identities){Policy.fields(a,"username","password","role","scopes");add(a.path("username").asText(),a.path("password").asText(),a.path("role").asText(),a.get("scopes"));}
 }
 void add(String user,String password,String role,JsonNode requested){
  if(user.isEmpty()||user.contains(":")||password.isEmpty()||accounts.stream().anyMatch(a->a.username.equals(user)))throw new IllegalArgumentException("Independent nonempty unique credentials required");
  var allowed=role.equals("service")?Set.of("status:read","jobs:write"):Policy.scopes(role);Set<String> scopes=new HashSet<>(Policy.scopes(role));
  if(requested!=null){if(!requested.isArray())throw new IllegalArgumentException("Scopes must be array");scopes.clear();for(var s:requested){if(!s.isTextual()||!allowed.contains(s.asText()))throw new IllegalArgumentException("Permissions exceed role");scopes.add(s.asText());}}
  accounts.add(new Account(user,password,role,Set.copyOf(scopes)));
 }
 String get(String k,String fallback){return env.getOrDefault(k,fallback);}
 Account identify(String header){
  if(header==null||!header.startsWith("Basic "))return null;String[] pair;
  try{pair=new String(Base64.getDecoder().decode(header.substring(6)),StandardCharsets.UTF_8).split(":",2);}catch(Exception e){return null;}
  if(pair.length!=2)return null;Account found=null;
  for(var a:accounts){boolean u=MessageDigest.isEqual(pair[0].getBytes(StandardCharsets.UTF_8),a.username.getBytes(StandardCharsets.UTF_8));boolean p=MessageDigest.isEqual(pair[1].getBytes(StandardCharsets.UTF_8),a.password.getBytes(StandardCharsets.UTF_8));if(u&p)found=a;}
  return found;
 }
}
