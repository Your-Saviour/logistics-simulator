package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

final class CustodyQuarantine {
 static void record(Connection c,Map<String,Object> run,JsonNode e,String endpoint,String phase,String reason,Object command)throws SQLException{
  if(one(c,"SELECT 1 FROM production_custody_quarantine WHERE run_id=? AND epoch=? AND event_id=? AND envelope=?::jsonb AND phase=? AND reason=?",run.get("id"),run.get("epoch"),Policy.uuid(e.get("event_id")),Json.write(e),phase,reason)!=null)return;
  sql(c,"INSERT INTO production_custody_quarantine(id,run_id,epoch,event_id,envelope,endpoint,phase,reason,command_id,simulation_time) VALUES (?,?,?,?,?::jsonb,?,?,?,?,?)",UUID.randomUUID(),run.get("id"),run.get("epoch"),Policy.uuid(e.get("event_id")),Json.write(e),endpoint,phase,reason,command,run.get("granted"));
 }
 static String ingest(Store s,JsonNode e,String endpoint){
  var header=(ObjectNode)e.deepCopy();header.put("type","sample.completed.v1");header.set("payload",Json.parse("{\"quantity\":1}"));Policy.envelope(header);
  var peer=s.settings.peers.path(e.path("boundary").asText());if(!s.settings.providers.path(e.path("boundary").asText()).asText().equals("helics")||!peer.path("source").asText().equals(e.path("source").asText())||!peer.path("endpoint").asText().equals(endpoint)||!e.path("destination").asText().equals("manufacturing")||!e.path("federation_id").asText().equals(s.settings.federation))throw new Conflict("Unconfigured custody peer");
  if(s.tx(c->{var r=current(c);return one(c,"SELECT 1 FROM production_custody_quarantine WHERE run_id=? AND epoch=? AND event_id=? AND envelope=?::jsonb",r.get("id"),r.get("epoch"),Policy.uuid(e.get("event_id")),Json.write(e))!=null;}))return "quarantined";
  try{String result=Production.ingest(s,e,endpoint);if(!result.equals("fenced"))return result;s.tx(c->{record(c,current(c),e,endpoint,"ingest","Custody run or epoch mismatch",null);return null;});}
  catch(Conflict|IllegalArgumentException error){s.tx(c->{record(c,current(c),e,endpoint,"ingest",error.getMessage(),null);return null;});}return "quarantined";
 }
 static List<Map<String,Object>> snapshot(Connection c,Map<String,Object> run)throws SQLException{return rows(c,"SELECT * FROM production_custody_quarantine WHERE run_id=? AND epoch=? ORDER BY recorded_at,id",run.get("id"),run.get("epoch"));}
}
