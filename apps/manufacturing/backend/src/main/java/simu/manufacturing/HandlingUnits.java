package simu.manufacturing;

import com.fasterxml.jackson.databind.JsonNode;
import java.sql.*;
import java.util.*;
import static simu.manufacturing.Store.*;

/** Physical ledger. Caller holds the existing current-run lock and transaction. */
final class HandlingUnits {
 static final JsonNode CATALOG=loadCatalog();
 static JsonNode loadCatalog(){try(var stream=HandlingUnits.class.getResourceAsStream("/handling-facility.json")){if(stream==null)throw new IllegalStateException("Fixed handling catalog missing");return Json.M.readTree(stream);}catch(Exception e){throw new IllegalStateException("Cannot load fixed handling catalog",e);}}
 static void manifest(JsonNode body){
  var units=body.path("units");if(!units.isArray()||units.isEmpty()||units.size()>256)throw new IllegalArgumentException("Explicit whole-unit manifest required (1..256 units)");
  var ids=new HashSet<UUID>();int total=0;for(var unit:units){Policy.fields(unit,"id","quantity",body.path("action").asText().equals("convert")?"position":"quantity");if(!ids.add(Policy.uuid(unit.get("id"))))throw new IllegalArgumentException("Duplicate handling-unit identity");total+=Policy.integer(unit.get("quantity"),1,10000);if(body.path("action").asText().equals("convert")&&(!unit.path("position").isTextual()||unit.path("position").asText().isBlank()))throw new IllegalArgumentException("Explicit conversion position required");}
  if(total!=Policy.integer(body.get("quantity"),1,10000))throw new IllegalArgumentException("Whole-unit contents must exactly equal supply quantity");
 }
 static String cell(JsonNode config,String line){int index=0;for(var entry:config.path("lines")){index++;if(entry.path("code").asText().equals(line)){if(index>4)throw new Conflict("Fixed facility has four production cells");return "manufacturing.cell%02d".formatted(index);}}throw new Conflict("Unknown production cell for line");}
 static String free(Connection c,Map<String,Object> run,String prefix)throws SQLException{
  var occupied=new HashSet<String>();for(var unit:rows(c,"SELECT position FROM production_handling_units WHERE run_id=? AND epoch=? AND position IS NOT NULL UNION SELECT destination AS position FROM production_custody WHERE run_id=? AND epoch=? AND state='accepted' UNION SELECT destination AS position FROM production_material_expected WHERE run_id=? AND epoch=? AND state='expected'",run.get("id"),run.get("epoch"),run.get("id"),run.get("epoch"),run.get("id"),run.get("epoch")))occupied.add(unit.get("position").toString());
  for(var location:CATALOG.path("locations")){String id=location.path("id").asText();if(id.startsWith(prefix)&&!occupied.contains(id))return id;}return null;
 }
 static void insert(Connection c,Map<String,Object> run,UUID id,String sku,int quantity,String category,String position,Object command,Object batch)throws SQLException{
  insert(c,run,id,sku,quantity,category,position,command,batch,true);
 }
 static void insert(Connection c,Map<String,Object> run,UUID id,String sku,int quantity,String category,String position,Object command,Object batch,boolean recordMovement)throws SQLException{
  if(one(c,"SELECT id FROM production_handling_units WHERE id=?",id)!=null)throw new Conflict("Handling-unit identity already exists; replay the original command");
  sql(c,"INSERT INTO production_handling_units(id,barcode,run_id,epoch,sku,quantity,category,state,position,command_id,batch_id,last_sequence) VALUES (?,?,?,?,?,?,?,'available',?,?,?,?)",id,"HU-"+id.toString().replace("-","").toUpperCase(Locale.ROOT),run.get("id"),run.get("epoch"),sku,quantity,category,position,command,batch,recordMovement?1:0);
  if(!recordMovement)return;
  var references=new LinkedHashMap<String,Object>();references.put("transfer_id",null);references.put("batch_id",batch);references.put("shipment_id",null);
  sql(c,"INSERT INTO production_unit_movements(id,unit_id,barcode,run_id,epoch,sequence,custody_generation,action,origin,destination,simulation_time,\"references\") VALUES (?,?,?,?,?,1,0,?,NULL,?,?,?::jsonb)",uuid5(id,"initial-movement"),id,"HU-"+id.toString().replace("-","").toUpperCase(Locale.ROOT),run.get("id"),run.get("epoch"),category.equals("raw")?"receive":"produce",position,run.get("granted"),Json.write(references));
 }
 static void supply(Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode body,JsonNode config)throws SQLException{
  String prefix=cell(config,config.path("lines").get(0).path("code").asText())+".input";
  for(var entry:body.path("units")){String position=free(c,run,prefix);if(position==null)throw new Conflict("Production input cell capacity unavailable; whole units were not received");insert(c,run,Policy.uuid(entry.get("id")),body.path("sku").asText(),entry.path("quantity").asInt(),"raw",position,job.get("id"),null);}
 }
 static void convert(Connection c,Map<String,Object> run,Map<String,Object> job,JsonNode body)throws SQLException{
  if(one(c,"SELECT 1 FROM production_orders WHERE run_id=? AND status<>'completed'",run.get("id"))!=null)throw new Conflict("Drain active production before legacy conversion");
  String sku=body.path("sku").asText();var stock=one(c,"SELECT quantity FROM production_materials WHERE run_id=? AND sku=?",run.get("id"),sku);
  if(stock==null||((Number)stock.get("quantity")).intValue()!=body.path("quantity").asInt()||one(c,"SELECT 1 FROM production_handling_units WHERE run_id=? AND sku=? AND state IN ('available','reserved','in_transit')",run.get("id"),sku)!=null)throw new Conflict("Conversion must exactly conserve untouched legacy raw materials");
  for(var entry:body.path("units")){
   String position=entry.path("position").asText();JsonNode location=null;for(var candidate:CATALOG.path("locations"))if(candidate.path("id").asText().equals(position))location=candidate;
   if(location==null||!location.path("owner").asText().equals("manufacturing")||!location.path("kind").asText().equals("cell_input"))throw new Conflict("Legacy raw materials require a compatible production input position");
   if(one(c,"SELECT 1 FROM production_handling_units WHERE run_id=? AND epoch=? AND position=? UNION ALL SELECT 1 FROM production_custody WHERE run_id=? AND epoch=? AND destination=? AND state='accepted' UNION ALL SELECT 1 FROM production_material_expected WHERE run_id=? AND epoch=? AND destination=? AND state='expected'",run.get("id"),run.get("epoch"),position,run.get("id"),run.get("epoch"),position,run.get("id"),run.get("epoch"),position)!=null)throw new Conflict("Conversion position capacity exceeded");
   insert(c,run,Policy.uuid(entry.get("id")),sku,entry.path("quantity").asInt(),"raw",position,job.get("id"),null,false);
  }
 }
 static List<Map<String,Object>> exact(Connection c,Map<String,Object> run,String sku,int target,String cell,Object batch,boolean unassigned,int maximumVersion)throws SQLException{
  var units=rows(c,"SELECT * FROM production_handling_units WHERE run_id=? AND epoch=? AND sku=? AND category='raw' AND state IN ('available','reserved') AND position LIKE ? AND (batch_id=? OR (? AND batch_id IS NULL)) AND version<=? ORDER BY id",run.get("id"),run.get("epoch"),sku,cell+".input%",batch,unassigned,maximumVersion);
  var paths=new HashMap<Integer,List<Map<String,Object>>>();paths.put(0,List.of());
  for(var unit:units){int quantity=((Number)unit.get("quantity")).intValue();for(var total:new ArrayList<>(paths.keySet())){int next=total+quantity;if(next>target||paths.containsKey(next))continue;var selection=new ArrayList<>(paths.get(total));selection.add(unit);paths.put(next,selection);}if(paths.containsKey(target))return paths.get(target);}
  return null;
 }
 static Map<String,Integer> reserveExistingInputs(Connection c,Map<String,Object> run,Map<String,Object> order,JsonNode product,JsonNode config)throws SQLException{
  var missing=new LinkedHashMap<String,Integer>();String cell=cell(config,order.get("line").toString());var fields=product.path("bom").fields();
  while(fields.hasNext()){var field=fields.next();int needed=field.getValue().asInt()*((Number)order.get("quantity")).intValue();var candidates=rows(c,"SELECT * FROM production_handling_units WHERE run_id=? AND epoch=? AND sku=? AND category='raw' AND state IN ('available','reserved') AND position LIKE ? AND (batch_id IS NULL OR batch_id=?) AND (version<=? OR (batch_id=? AND state='reserved' AND version<?)) ORDER BY id",run.get("id"),run.get("epoch"),field.getKey(),cell+".input%",order.get("id"),Integer.MAX_VALUE-2,order.get("id"),Integer.MAX_VALUE);
   var paths=new HashMap<Integer,List<Map<String,Object>>>();paths.put(0,List.of());for(var unit:candidates){int quantity=((Number)unit.get("quantity")).intValue();var previous=paths.entrySet().stream().map(e->Map.entry(e.getKey(),e.getValue())).toList();for(var entry:previous){int total=entry.getKey()+quantity;int count=entry.getValue().size()+1;if(total>needed||paths.containsKey(total)&&paths.get(total).size()<=count)continue;var selected=new ArrayList<>(entry.getValue());selected.add(unit);paths.put(total,selected);}}
   int supplied=Collections.max(paths.keySet());for(var unit:paths.get(supplied))if(!order.get("id").equals(unit.get("batch_id"))||!unit.get("state").equals("reserved"))sql(c,"UPDATE production_handling_units SET state='reserved',batch_id=?,version=version+1 WHERE id=?",order.get("id"),unit.get("id"));if(supplied<needed)missing.put(field.getKey(),needed-supplied);
  }return missing;
 }
 static String consume(Connection c,Map<String,Object> run,Map<String,Object> order,JsonNode product,JsonNode config)throws SQLException{
  var selected=new ArrayList<Map<String,Object>>();String cell=cell(config,order.get("line").toString());var fields=product.path("bom").fields();
  while(fields.hasNext()){var field=fields.next();int needed=field.getValue().asInt()*((Number)order.get("quantity")).intValue();var units=exact(c,run,field.getKey(),needed,cell,order.get("id"),!Boolean.TRUE.equals(order.get("materials_requested")),Integer.MAX_VALUE);if(units==null)return "No exact whole-unit inputs assigned to this batch at "+cell+": "+field.getKey()+" needs "+needed+"; units cannot be split";selected.addAll(units);}
  for(var unit:selected)if(((Number)unit.get("version")).intValue()==Integer.MAX_VALUE||((Number)unit.get("last_sequence")).intValue()==Integer.MAX_VALUE)return "Handling-unit counter exhausted; reconcile before consumption";
  var references=new LinkedHashMap<String,Object>();references.put("transfer_id",null);references.put("batch_id",order.get("id"));references.put("shipment_id",null);
  for(var unit:selected){
   sql(c,"INSERT INTO production_unit_inputs(batch_id,unit_id,simulation_time) VALUES (?,?,?)",order.get("id"),unit.get("id"),run.get("granted"));
   if(sql(c,"UPDATE production_handling_units SET state='consumed',position=NULL,version=version+1,last_sequence=last_sequence+1 WHERE id=? AND state IN ('available','reserved')",unit.get("id"))!=1)throw new Conflict("Whole recipe input changed before consumption");
   // Consumption happens at the recorded input endpoint. This is a terminal
   // lifecycle event, not a journey to a fabricated processing coordinate.
   sql(c,"INSERT INTO production_unit_movements(id,unit_id,barcode,run_id,epoch,sequence,custody_generation,action,origin,destination,simulation_time,\"references\") VALUES (?,?,?,?,?,?,?,'consume',?,?,?,?::jsonb)",uuid5(uuid(order.get("id")),"consume:"+unit.get("id")),unit.get("id"),unit.get("barcode"),run.get("id"),run.get("epoch"),((Number)unit.get("last_sequence")).intValue()+1,unit.get("custody_generation"),unit.get("position"),unit.get("position"),run.get("granted"),Json.write(references));
  }return null;
 }
 static String outputPosition(Connection c,Map<String,Object> run,Map<String,Object> order,JsonNode config)throws SQLException{return free(c,run,cell(config,order.get("line").toString())+".output");}
 static void finish(Connection c,Map<String,Object> run,Map<String,Object> job,Map<String,Object> order,JsonNode product,int output,int scrap,String position)throws SQLException{
  UUID outputId=uuid5(uuid(order.get("id")),"handling-output");
  if(output>0)insert(c,run,outputId,order.get("product").toString(),output,"finished",position,job.get("id"),order.get("id"));
  var inputs=rows(c,"SELECT unit_id FROM production_unit_inputs WHERE batch_id=? ORDER BY unit_id",order.get("id")).stream().map(row->row.get("unit_id")).toList();
  var lineage=new LinkedHashMap<String,Object>();UUID id=uuid5(uuid(order.get("id")),"handling-lineage");lineage.put("id",id);lineage.put("run_id",run.get("id"));lineage.put("epoch",run.get("epoch"));lineage.put("batch_id",order.get("id"));lineage.put("input_unit_ids",inputs);lineage.put("output_unit_ids",output>0?List.of(outputId):List.of());lineage.put("product",order.get("product"));lineage.put("recipe",product.path("bom"));lineage.put("batch_quantity",order.get("quantity"));lineage.put("output_quantity",output);lineage.put("scrap_quantity",scrap);lineage.put("simulation_time",run.get("granted"));
  sql(c,"INSERT INTO production_unit_lineage(id,run_id,epoch,batch_id,payload) VALUES (?,?,?,?,?::jsonb)",id,run.get("id"),run.get("epoch"),order.get("id"),Json.write(lineage));
 }
 static Map<String,Object> unit(Map<String,Object> row){var value=new LinkedHashMap<String,Object>();for(var field:List.of("id","barcode","run_id","epoch","version","custody_generation","last_sequence","category","state","position","origin","destination","handoff_id"))value.put(field,row.get(field));value.put("owner","manufacturing");value.put("contents",List.of(Map.of("sku",row.get("sku"),"quantity",row.get("quantity"))));return value;}
 static Map<String,Object> snapshot(Connection c,Map<String,Object> run)throws SQLException{
  var result=new LinkedHashMap<String,Object>();result.put("version",1);result.put("catalog_version",1);
  result.put("units",rows(c,"SELECT * FROM production_handling_units WHERE run_id=? AND epoch=? ORDER BY id",run.get("id"),run.get("epoch")).stream().map(HandlingUnits::unit).toList());
  result.put("movements",rows(c,"SELECT * FROM production_unit_movements WHERE run_id=? AND epoch=? ORDER BY unit_id,sequence",run.get("id"),run.get("epoch")));
  result.put("lineage",rows(c,"SELECT payload FROM production_unit_lineage WHERE run_id=? AND epoch=? ORDER BY id",run.get("id"),run.get("epoch")).stream().map(row->json(row.get("payload"))).toList());
  result.put("input_allocations",rows(c,"SELECT i.* FROM production_unit_inputs i JOIN production_orders o ON o.id=i.batch_id WHERE o.run_id=? ORDER BY i.batch_id,i.unit_id",run.get("id")));
  result.put("legacy_stock",rows(c,"SELECT m.sku,m.quantity-COALESCE(sum(u.quantity) FILTER(WHERE u.state IN ('available','reserved')),0) AS unplaced_quantity FROM production_materials m LEFT JOIN production_handling_units u ON u.run_id=m.run_id AND u.sku=m.sku AND u.category='raw' WHERE m.run_id=? GROUP BY m.run_id,m.sku,m.quantity HAVING m.quantity<>COALESCE(sum(u.quantity) FILTER(WHERE u.state IN ('available','reserved')),0) ORDER BY m.sku",run.get("id")));
  var handoffs=Custody.snapshot(c,run);handoffs.addAll(OutputCustody.snapshot(c,run));result.put("handoffs",handoffs);result.put("quarantine",CustodyQuarantine.snapshot(c,run));return result;
 }
}
