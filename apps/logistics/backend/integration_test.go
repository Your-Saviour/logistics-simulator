package main

import (
	"context"
	"fmt"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

func testStore(t *testing.T) *Store {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("set TEST_DATABASE_URL for isolated real PostgreSQL verification")
	}
	p, e := pgxpool.New(context.Background(), url)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(p.Close)
	s := &Store{DB: p, C: Config{Mode: "standalone", Scenario: defaultScenario(), Quantum: 1, Username: "operator", Password: "secret", Identities: []Account{{Username: "employee", Password: "employee", Role: "employee"}, {Username: "robot", Password: "robot", Role: "service", Scopes: []string{"jobs:write", "status:read"}}}}}
	_, e = p.Exec(context.Background(), "DO $$ BEGIN IF to_regclass('runs') IS NOT NULL THEN TRUNCATE command_audit,outbox,boundary_outbox,effects,jobs,inbox,runs,heartbeats CASCADE; END IF; END $$")
	if e != nil {
		t.Fatal(e)
	}
	if e = s.Migrate(context.Background()); e != nil {
		t.Fatal(e)
	}
	_, e = p.Exec(context.Background(), "TRUNCATE command_audit,outbox,boundary_outbox,effects,jobs,inbox,runs,heartbeats CASCADE")
	if e != nil {
		t.Fatal(e)
	}
	if e = s.Migrate(context.Background()); e != nil {
		t.Fatal(e)
	}
	return s
}
func TestAPIValidationPermissionsReplayAndAudit(t *testing.T) {
	s := testStore(t)
	h := api(s, func() bool { return true })
	request := func(path, body, user, pass, key string) (int, string) {
		r := httptest.NewRequest("POST", path, strings.NewReader(body))
		r.SetBasicAuth(user, pass)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", key)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Header().Get("X-Request-ID") == "" {
			t.Error("missing request correlation")
		}
		return w.Code, w.Body.String()
	}
	for _, v := range []struct {
		path, body, user, pass, key string
		status                      int
	}{{"/api/jobs", `{"due_at":1,"quantity":1}`, "operator", "secret", "x", 200}, {"/api/jobs", `{"due_at":1,"quantity":1}`, "operator", "secret", "x", 200}, {"/api/jobs", `{"due_at":1,"quantity":2}`, "operator", "secret", "x", 409}, {"/api/jobs", `{"due_at":1,"quantity":true}`, "operator", "secret", "y", 422}, {"/api/jobs", `{"due_at":1,"quantity":1,"extra":2}`, "operator", "secret", "y", 422}, {"/api/control/hold", `{}`, "employee", "employee", "", 403}, {"/api/control/hold", `{}`, "robot", "robot", "", 403}, {"/api/jobs", `{"due_at":1,"quantity":1}`, "operator", "wrong", "z", 401}, {"/api/jobs", `{"due_at":1,"quantity":1}`, "operator", "secret", "synthetic:reserved", 409}} {
		if code, body := request(v.path, v.body, v.user, v.pass, v.key); code != v.status {
			t.Errorf("%s expected %d got %d %s", v.path, v.status, code, body)
		}
	}
	var jobs, accepted, rejected int
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM jobs").Scan(&jobs)
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM command_audit WHERE outcome='accepted'").Scan(&accepted)
	s.DB.QueryRow(context.Background(), "SELECT count(*) FROM command_audit WHERE outcome='rejected'").Scan(&rejected)
	if jobs != 1 || accepted != 2 || rejected != 7 {
		t.Fatalf("atomic ledger jobs=%d accepted=%d rejected=%d", jobs, accepted, rejected)
	}
}
func TestDurableGrantBarrierConcurrentDuplicateAndResetFence(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	job, e := s.Schedule(ctx, "one", JobCommand{1, 3}, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	id := job["id"].(string)
	if result, e := s.Execute(ctx, id); e != nil || result != "waiting" {
		t.Fatalf("ungranted work executed: %s %v", result, e)
	}
	r, _ := s.Run(ctx)
	epoch := r["epoch"].(string)
	if ok, e := s.Prepare(ctx, 1, epoch); e != nil || !ok {
		t.Fatal(e)
	}
	if _, e = s.Grant(ctx, 1, epoch); e != nil {
		t.Fatal(e)
	}
	if ok, _ := s.Prepare(ctx, 2, epoch); ok {
		t.Fatal("advanced with outstanding work")
	}
	s.Heartbeat(ctx, "controller", "")
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, e := s.Execute(ctx, id)
			if e != nil {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	var effects int
	s.DB.QueryRow(ctx, "SELECT sum(quantity) FROM effects").Scan(&effects)
	if effects != 3 {
		t.Fatalf("duplicate effects %d", effects)
	}
	if ok, e := s.Prepare(ctx, 2, epoch); !ok || e != nil {
		t.Fatalf("completed barrier failed %v", e)
	}
	old := r["id"].(string)
	_, e = s.Control(ctx, "reset", 1, old, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Grant(ctx, 2, epoch); e == nil {
		t.Fatal("old epoch granted new run")
	}
	if result, e := s.Execute(ctx, id); e != nil || result != "fenced" {
		t.Fatalf("old delivery not fenced %s %v", result, e)
	}
}
func TestAcceptedCommandAuditRollsBackTogether(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	_, e := s.Schedule(ctx, "rollback", JobCommand{1, 1}, &Audit{RunID: uuid.NewString(), Actor: "employee", Role: "employee", RequestID: "invalid-uuid", Action: "POST /api/jobs"}, nil)
	if e == nil {
		t.Fatal("expected audit constraint failure")
	}
	var count int
	s.DB.QueryRow(ctx, "SELECT count(*) FROM jobs WHERE idempotency_key='rollback'").Scan(&count)
	if count != 0 {
		t.Fatalf("job survived audit rollback %d", count)
	}
}
func TestRetryBudgetFencesFailedRun(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	job, e := s.Schedule(ctx, "fail", JobCommand{1, 1}, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	for i := 1; i <= 3; i++ {
		result, e := s.Fail(ctx, job["id"].(string), "bad sample")
		expected := "retry"
		if i == 3 {
			expected = "dead"
		}
		if e != nil || result != expected {
			t.Fatal(fmt.Sprint(result, e))
		}
	}
	r, _ := s.Run(ctx)
	if r["state"] != "failed" {
		t.Fatal("dead job did not fence clock")
	}
}

// Cancellation after a rejection must not erase its healthy-database audit.
type disconnectRecorder struct {
	*httptest.ResponseRecorder
	cancel context.CancelFunc
}

func (w *disconnectRecorder) WriteHeader(code int) {
	w.ResponseRecorder.WriteHeader(code)
	if code >= 400 {
		w.cancel()
	}
}
func TestRejectedAuditSurvivesClientDisconnect(t *testing.T) {
	s := testStore(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := httptest.NewRequest("POST", "/api/jobs", strings.NewReader(`{"due_at":1,"quantity":-1}`)).WithContext(ctx)
	r.SetBasicAuth("employee", "employee")
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", "disconnect")
	recorder := httptest.NewRecorder()
	w := &disconnectRecorder{recorder, cancel}
	api(s, func() bool { return true }).ServeHTTP(w, r)
	if recorder.Code != 422 || ctx.Err() == nil {
		t.Fatalf("fixture did not reject/cancel: %d %v", recorder.Code, ctx.Err())
	}
	var count int
	if e := s.DB.QueryRow(context.Background(), "SELECT count(*) FROM command_audit WHERE request_id=$1 AND actor='employee' AND outcome='rejected' AND status_code=422", recorder.Header().Get("X-Request-ID")).Scan(&count); e != nil || count != 1 {
		t.Fatalf("rejected audit missing after disconnect: %d %v", count, e)
	}
}

func TestConnectedFinalizeWaitsForNativeAcknowledgement(t *testing.T) {
	s := testStore(t)
	ctx := context.Background()
	r, _ := s.Run(ctx)
	_, e := s.DB.Exec(ctx, "UPDATE runs SET mode='helics' WHERE id=$1", r["id"])
	if e != nil {
		t.Fatal(e)
	}
	_, e = s.DB.Exec(ctx, "INSERT INTO logistics_adapter_sessions(run_id,epoch,session_id,native_state,pending,processing) VALUES($1,$2,$3,'executing',false,false)", r["id"], r["epoch"], uuid.NewString())
	if e != nil {
		t.Fatal(e)
	}
	result, e := s.Control(ctx, "finalize", 1, "", nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	if result["run"].(map[string]any)["state"] != "finalizing" {
		t.Fatal("SQL claimed finalization before native acknowledgement")
	}
	if e = s.Stall(ctx, r["epoch"].(string), "native finalize unavailable"); e != nil {
		t.Fatal(e)
	}
	after, _ := s.Run(ctx)
	if after["state"] != "stalled" {
		t.Fatal("native finalize failure did not become visible")
	}
}
