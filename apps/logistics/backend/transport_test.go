package main

import (
 "context"
 "encoding/json"
 "fmt"
 "net/http/httptest"
 "strings"
 "sync"
 "testing"
 "github.com/google/uuid"
)

// A missing transport endpoint, early physical movement or lost custody fails these real SQL tests.
func transportRequest(t *testing.T,s *Store,method,path,key string,body row,code int) row {
 t.Helper(); raw,_:=json.Marshal(body); req:=httptest.NewRequest(method,path,strings.NewReader(string(raw)));req.SetBasicAuth("employee","employee");req.Header.Set("Idempotency-Key",key)
 w:=httptest.NewRecorder();api(s,func()bool{return true}).ServeHTTP(w,req)
 if w.Code!=code {t.Fatalf("%s %s: want %d got %d %s",method,path,code,w.Code,w.Body.String())}
 var v row;if err:=json.Unmarshal(w.Body.Bytes(),&v);err!=nil {t.Fatal(err)};return v
}
func transportSnapshot(t *testing.T,s *Store) row { return transportRequest(t,s,"GET","/api/transport","",nil,200) }
func transportCommand(t *testing.T,s *Store,action string,fields row) row {
 t.Helper();ctx:=context.Background();r,err:=s.Run(ctx);if err!=nil{t.Fatal(err)}
 due:=num(r,"requested")+1;if num(r,"granted")>=due {due=num(r,"granted")+1}
 body:=row{"run_id":r["id"],"epoch":r["epoch"],"due_at":due,"action":action};for k,v:=range fields {body[k]=v}
 c:=transportRequest(t,s,"POST","/api/transport/commands",uuid.NewString(),body,200)
 if ok,e:=s.Prepare(ctx,due,r["epoch"].(string));e!=nil||!ok {t.Fatalf("prepare %v %v",ok,e)}
 if _,e:=s.Grant(ctx,due,r["epoch"].(string));e!=nil {t.Fatal(e)};if e:=s.Heartbeat(ctx,"controller","");e!=nil{t.Fatal(e)}
 if result,e:=s.Execute(ctx,c["id"].(string));e!=nil||result!="completed" {t.Fatalf("execute %s %v",result,e)}
 snap:=transportSnapshot(t,s);for _,v:=range snap["commands"].([]any){command:=v.(map[string]any);if command["id"]==c["id"]{return command}}
 t.Fatal("command absent");return nil
}
func requestedTransfer(t *testing.T,s *Store,quantity int) string {
 t.Helper();c:=transportCommand(t,s,"request",row{"route":"WAREHOUSE-DISPATCH","sku":"PRODUCT","quantity":quantity,"correlation_id":uuid.NewString()})
 if c["status"]!="completed"{t.Fatalf("request %v",c)};return c["id"].(string)
}
func transferByID(t *testing.T,s *Store,id string) row {t.Helper();for _,v:=range transportSnapshot(t,s)["transfers"].([]any){r:=v.(map[string]any);if r["id"]==id{return r}};t.Fatal("transfer absent");return nil}
func TestTransportLifecycleKeepsCustodyUntilReceipt(t *testing.T){
 s:=testStore(t);ctx:=context.Background();id:=requestedTransfer(t,s,8)
 for _,step:=range []struct{action,state,custody string;fields row}{
 {"assign","assigned","origin",row{"reference":id,"vehicle":"TRUCK-1"}},
 {"load","loaded","vehicle",row{"reference":id}},
 {"depart","in_transit","vehicle",row{"reference":id}},
 }{c:=transportCommand(t,s,step.action,step.fields);tr:=transferByID(t,s,id);if c["status"]!="completed"||tr["status"]!=step.state||tr["custody"]!=step.custody{t.Fatalf("%s %v %v",step.action,c,tr)}}
 tr:=transferByID(t,s,id);if tr["arrived_at"]!=nil||tr["received_at"]!=nil||num(tr,"planned_eta")!=14{t.Fatalf("ETA falsely arrived: %v",tr)}
 c:=transportCommand(t,s,"arrive",row{"reference":id});if c["status"]!="rejected"||transferByID(t,s,id)["status"]!="in_transit"{t.Fatalf("early arrival %v",c)}
 r,_:=s.Run(ctx);if ok,e:=s.Prepare(ctx,14,r["epoch"].(string));e!=nil||!ok{t.Fatal(e)};s.Grant(ctx,14,r["epoch"].(string));s.Heartbeat(ctx,"controller","")
 var arrival string;if e:=s.DB.QueryRow(ctx,"SELECT id::text FROM jobs WHERE run_id=$1 AND due_at=14 AND status='pending'",r["id"]).Scan(&arrival);e!=nil{t.Fatal(e)}
 if ok,_:=s.Prepare(ctx,15,r["epoch"].(string));ok{t.Fatal("advanced over unsettled arrival")}
 var wg sync.WaitGroup;for i:=0;i<6;i++{wg.Add(1);go func(){defer wg.Done();if _,e:=s.Execute(ctx,arrival);e!=nil{t.Error(e)}}()};wg.Wait()
 tr=transferByID(t,s,id);if tr["status"]!="arrived"||num(tr,"arrived_at")!=14||tr["received_at"]!=nil{t.Fatalf("arrival %v",tr)}
 for _,a:=range []string{"unload","receive"}{if c:=transportCommand(t,s,a,row{"reference":id});c["status"]!="completed"{t.Fatalf("%s %v",a,c)}}
 tr=transferByID(t,s,id);if tr["status"]!="received"||tr["custody"]!="destination"{t.Fatal(tr)}
 var arrivals int;if e:=s.DB.QueryRow(ctx,"SELECT count(*) FROM transport_movements WHERE transfer_id=$1 AND action='arrive'",id).Scan(&arrivals);e!=nil||arrivals!=1{t.Fatalf("duplicate arrival effects %d %v",arrivals,e)}
 c=transportCommand(t,s,"arrive",row{"reference":id});if c["status"]!="rejected"{t.Fatal("arrived twice")}
}
func TestTransportFleetCapacityAndConflictingAssignment(t *testing.T){
 s:=testStore(t);first:=requestedTransfer(t,s,8);second:=requestedTransfer(t,s,8);large:=requestedTransfer(t,s,101)
 for _,v:=range []struct{id,status string}{{large,"rejected"},{first,"completed"},{second,"rejected"}}{c:=transportCommand(t,s,"assign",row{"reference":v.id,"vehicle":"TRUCK-1"});if c["status"]!=v.status{t.Fatalf("capacity/assignment %v",c)}}
 if tr:=transferByID(t,s,second);tr["status"]!="requested"||tr["vehicle"]!=nil{t.Fatalf("partial failed assignment %v",tr)}
 c:=transportCommand(t,s,"depart",row{"reference":first});if c["status"]!="rejected"{t.Fatal("departed before load")}
}
func TestTransportHTTPValidationReplayAuditAndEpoch(t *testing.T){
 s:=testStore(t);ctx:=context.Background();r,_:=s.Run(ctx);body:=row{"run_id":r["id"],"epoch":r["epoch"],"due_at":1,"action":"request","route":"WAREHOUSE-DISPATCH","sku":"PRODUCT","quantity":5,"correlation_id":uuid.NewString()}
 a:=transportRequest(t,s,"POST","/api/transport/commands","replay",body,200);b:=transportRequest(t,s,"POST","/api/transport/commands","replay",body,200);if a["id"]!=b["id"]{t.Fatal("replay duplicated")}
 body["quantity"]=6;transportRequest(t,s,"POST","/api/transport/commands","replay",body,409)
 for _,v:=range []any{true,1.5,"2",0,nil}{body["quantity"]=v;transportRequest(t,s,"POST","/api/transport/commands",uuid.NewString(),body,422)}
 body["quantity"]=5;body["vehicle"]="TRUCK-1";transportRequest(t,s,"POST","/api/transport/commands","extra",body,422);delete(body,"vehicle")
 if _,e:=s.Control(ctx,"reset",1,r["id"].(string),nil,nil);e!=nil{t.Fatal(e)}
 transportRequest(t,s,"POST","/api/transport/commands","old",body,409)
 if result,e:=s.Execute(ctx,a["id"].(string));e!=nil||result!="fenced"{t.Fatalf("stale delivery %s %v",result,e)}
 var count int;s.DB.QueryRow(ctx,"SELECT count(*) FROM command_audit WHERE outcome='accepted'").Scan(&count);if count!=2{t.Fatal(fmt.Sprint("accepted audit ",count))}
}
