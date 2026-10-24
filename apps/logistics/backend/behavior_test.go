package main

import (
	"strings"
	"testing"
	"time"
)

// Removing strict JSON validation must fail this test: quantities cannot be coerced.
func TestJobCommandRejectsCoercionAndUnknownFields(t *testing.T) {
	for _, body := range []string{`{"due_at":1,"quantity":true}`, `{"due_at":1,"quantity":1.0}`, `{"due_at":1,"quantity":0}`, `{"due_at":-1,"quantity":1}`, `{"due_at":1,"quantity":1,"extra":1}`, `{"quantity":1}`, `{"due_at":null,"quantity":1}`} {
		if _, err := parseJob(strings.NewReader(body)); err == nil {
			t.Errorf("accepted invalid command %s", body)
		}
	}
	if j, err := parseJob(strings.NewReader(`{"due_at":1,"quantity":2}`)); err != nil || j.Quantity != 2 {
		t.Fatalf("valid command rejected: %+v %v", j, err)
	}
}

// Removing the business calendar check must fail this test over a weekend.
func TestBusinessDueSkipsWeekend(t *testing.T) {
	s := defaultScenario()
	s.StartAt = "2026-01-09T16:59:59+10:30"
	due, err := nextBusinessDue(s, 0, 2)
	if err != nil || due != 226801 {
		t.Fatalf("Monday 08:00 expected at 226801 elapsed UTC seconds, got %v %v", due, err)
	}
}

// Service permissions never inherit the operator role's controls.
func TestServiceHasOnlyExplicitScopes(t *testing.T) {
	c := Config{Username: "operator", Password: "secret", Identities: []Account{{Username: "robot", Password: "other", Role: "service"}}}
	p, ok := c.identify("robot", "other")
	if !ok || p.Can("jobs:write") || p.Can("runs:control") {
		t.Fatal("service inherited implicit privileges")
	}
	c.Identities[0].Scopes = []string{"jobs:write"}
	p, ok = c.identify("robot", "other")
	if !ok || !p.Can("jobs:write") || p.Can("runs:control") {
		t.Fatal("explicit service scopes not respected")
	}
}

func TestBusinessCalendarUsesUTCElapsedAcrossDST(t *testing.T) {
	s := defaultScenario()
	s.StartAt = "2026-10-02T16:59:59+09:30"
	due, e := nextBusinessDue(s, 0, 2)
	if e != nil || due != 223201 {
		t.Fatalf("Monday after spring DST expected 223201 seconds, got %v %v", due, e)
	}
}
func TestSeededInputsAreStablePerRunEpochSlot(t *testing.T) {
	s := defaultScenario()
	run := "11111111-1111-4111-8111-111111111111"
	epoch := "22222222-2222-4222-8222-222222222222"
	a := seededInput(s, run, epoch, "transport", 1, 30)
	b := seededInput(s, run, epoch, "transport", 1, 30)
	if a["input_id"] != b["input_id"] || a["quantity"] != b["quantity"] {
		t.Fatal("seeded command is not deterministic")
	}
	c := seededInput(s, run, "33333333-3333-4333-8333-333333333333", "transport", 1, 30)
	if a["input_id"] == c["input_id"] {
		t.Fatal("seeded input leaked identity across epochs")
	}
	if a["quantity"].(int) < 1 || a["quantity"].(int) > 10 {
		t.Fatal("seeded quantity outside contract")
	}
}

func TestPendingNativeGrantTimesOutWithoutAdvancing(t *testing.T) {
	a := &Adapter{Store: &Store{C: Config{}}, PendingSince: time.Now().Add(-time.Minute - time.Second)}
	if e := a.checkPending(true); e == nil {
		t.Fatal("expired native grant remained healthy")
	}
	if e := a.checkPending(false); e != nil || !a.PendingSince.IsZero() {
		t.Fatal("completed grant did not clear pending timeout")
	}
}

func TestControlJSONRequiresObject(t *testing.T) {
	for _, body := range []string{"null", "true", "1", "[]", `"hold"`} {
		command := struct {
			Speed int `json:"speed"`
		}{Speed: 1}
		if err := strictJSON(strings.NewReader(body), &command); err == nil {
			t.Errorf("accepted non-object control body %s", body)
		}
	}
}
