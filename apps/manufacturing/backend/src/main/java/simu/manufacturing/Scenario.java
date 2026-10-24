package simu.manufacturing;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.time.*;
import java.util.*;
final class Scenario {
 static JsonNode normalize(JsonNode b){
  Policy.fields(b,"seed","time_zone","start_at","business_open","business_close","business_weekdays","interval_seconds","manufacturing");
  ObjectNode s=(ObjectNode)Json.parse("{\"seed\":1,\"time_zone\":\"Australia/Adelaide\",\"start_at\":\"2026-01-05T08:00:00+10:30\",\"business_open\":\"08:00:00\",\"business_close\":\"17:00:00\",\"business_weekdays\":[0,1,2,3,4],\"interval_seconds\":30}");
  b.fields().forEachRemaining(e->s.set(e.getKey(),e.getValue()));
  Policy.integer(s.get("seed"),0,Integer.MAX_VALUE);Policy.integer(s.get("interval_seconds"),1,86400);
  ZoneId.of(s.path("time_zone").asText());OffsetDateTime.parse(s.path("start_at").asText());
  var open=LocalTime.parse(s.path("business_open").asText());var close=LocalTime.parse(s.path("business_close").asText());
  if(!open.isBefore(close)||open.getSecond()!=0||open.getNano()!=0||close.getSecond()!=0||close.getNano()!=0)throw new IllegalArgumentException("Increasing whole-minute business hours required");
  var days=s.get("business_weekdays");var seen=new HashSet<Integer>();
  if(!days.isArray()||days.isEmpty())throw new IllegalArgumentException("Business weekdays required");
  for(var d:days)if(!seen.add(Policy.integer(d,0,6)))throw new IllegalArgumentException("Duplicate weekday");
  if(s.has("manufacturing"))s.set("manufacturing",Production.config(s.get("manufacturing")));
  return s;
 }
 static ZonedDateTime instant(JsonNode s,double seconds){return OffsetDateTime.parse(s.path("start_at").asText()).toInstant().plusNanos((long)(seconds*1e9)).atZone(ZoneId.of(s.path("time_zone").asText()));}
 static double nextDue(JsonNode raw,double after,double delay){
  var s=normalize(raw);if(!Double.isFinite(after)||after<0||!Double.isFinite(delay)||delay<=0)throw new IllegalArgumentException("Invalid simulation delay");
  var candidate=instant(s,after+delay);var open=LocalTime.parse(s.path("business_open").asText());var close=LocalTime.parse(s.path("business_close").asText());
  var days=new HashSet<Integer>();s.get("business_weekdays").forEach(d->days.add(d.intValue()));
  if(days.contains(candidate.getDayOfWeek().getValue()-1)&&!candidate.toLocalTime().isBefore(open)&&candidate.toLocalTime().isBefore(close))return after+delay;
  for(int offset=0;offset<8;offset++){
   var date=candidate.toLocalDate().plusDays(offset);if(!days.contains(date.getDayOfWeek().getValue()-1))continue;
   var wall=date.atTime(open);var rules=candidate.getZone().getRules();
   for(int gap=0;gap<=180;gap++,wall=wall.plusMinutes(1)){
    var offsets=rules.getValidOffsets(wall);if(offsets.isEmpty())continue;
    for(var zoneOffset:offsets){var opening=wall.toInstant(zoneOffset);if(!opening.isBefore(candidate.toInstant())&&wall.toLocalTime().isBefore(close))return Duration.between(instant(s,0).toInstant(),opening).toMillis()/1000.0;}
    break;
   }
  }
  throw new IllegalArgumentException("No business opening in next week");
 }
}
