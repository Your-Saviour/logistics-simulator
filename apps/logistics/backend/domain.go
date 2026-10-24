package main

import (
	"bytes"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"
)

type Conflict string

func (e Conflict) Error() string { return string(e) }
func finite(n float64) bool      { return !math.IsNaN(n) && !math.IsInf(n, 0) }
func strictJSON(r io.Reader, v any) error {
	const maximumBody = 1 << 20
	raw, err := io.ReadAll(io.LimitReader(r, maximumBody+1))
	if err != nil {
		return err
	}
	if len(raw) > maximumBody {
		return errors.New("JSON body exceeds 1 MiB")
	}
	raw = bytes.TrimSpace(raw)
	// Commands require objects; configuration also uses typed arrays. Neither
	// representation permits JSON null or scalar values at the top level.
	if len(raw) == 0 || (raw[0] != '{' && raw[0] != '[') {
		return errors.New("expected a JSON object or array")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if err = d.Decode(v); err != nil {
		return err
	}
	if d.Decode(new(any)) != io.EOF {
		return errors.New("expected one JSON value")
	}
	return nil
}

type JobCommand struct {
	DueAt    float64 `json:"due_at"`
	Quantity int     `json:"quantity"`
}

func parseJob(r io.Reader) (JobCommand, error) {
	var raw struct {
		DueAt    *float64 `json:"due_at"`
		Quantity *int     `json:"quantity"`
	}
	err := strictJSON(r, &raw)
	if err != nil {
		return JobCommand{}, err
	}
	if raw.DueAt == nil || raw.Quantity == nil || !finite(*raw.DueAt) || *raw.DueAt < 0 || *raw.Quantity < 1 || *raw.Quantity > 10000 {
		return JobCommand{}, errors.New("finite nonnegative due_at and integer quantity 1..10000 required")
	}
	return JobCommand{*raw.DueAt, *raw.Quantity}, nil
}

type Scenario struct {
	Seed             int    `json:"seed"`
	TimeZone         string `json:"time_zone"`
	StartAt          string `json:"start_at"`
	BusinessOpen     string `json:"business_open"`
	BusinessClose    string `json:"business_close"`
	BusinessWeekdays []int  `json:"business_weekdays"`
	IntervalSeconds  int    `json:"interval_seconds"`
}

func defaultScenario() Scenario {
	return Scenario{1, "Australia/Adelaide", "2026-01-05T08:00:00+10:30", "08:00:00", "17:00:00", []int{0, 1, 2, 3, 4}, 30}
}
func minute(s string) (int, error) {
	for _, layout := range []string{"15:04:05", "15:04"} {
		v, e := time.Parse(layout, s)
		if e == nil && v.Second() == 0 {
			return v.Hour()*60 + v.Minute(), nil
		}
	}
	return 0, errors.New("whole local minutes required")
}
func (s Scenario) Validate() error {
	_, e := time.LoadLocation(s.TimeZone)
	if e != nil {
		return e
	}
	if _, e = time.Parse(time.RFC3339Nano, s.StartAt); e != nil {
		return e
	}
	o, e := minute(s.BusinessOpen)
	if e != nil {
		return e
	}
	c, e := minute(s.BusinessClose)
	if e != nil || o >= c {
		return errors.New("business hours must increase")
	}
	if s.Seed < 0 || s.Seed > 2147483647 || s.IntervalSeconds < 1 || s.IntervalSeconds > 86400 || len(s.BusinessWeekdays) == 0 {
		return errors.New("invalid scenario bounds")
	}
	seen := map[int]bool{}
	for _, v := range s.BusinessWeekdays {
		if v < 0 || v > 6 || seen[v] {
			return errors.New("weekdays must be unique integers 0..6")
		}
		seen[v] = true
	}
	return nil
}
func (s Scenario) instant(seconds float64) time.Time {
	start, _ := time.Parse(time.RFC3339Nano, s.StartAt)
	loc, _ := time.LoadLocation(s.TimeZone)
	return start.Add(time.Duration(seconds * float64(time.Second))).In(loc)
}
func nextBusinessDue(s Scenario, after, delay float64) (float64, error) {
	if e := s.Validate(); e != nil {
		return 0, e
	}
	if !finite(after) || !finite(delay) || after < 0 || delay <= 0 {
		return 0, errors.New("finite nonnegative time and positive delay required")
	}
	candidate := s.instant(after + delay)
	open, _ := minute(s.BusinessOpen)
	close, _ := minute(s.BusinessClose)
	weekday := func(t time.Time) bool {
		w := (int(t.Weekday()) + 6) % 7
		for _, d := range s.BusinessWeekdays {
			if w == d {
				return true
			}
		}
		return false
	}
	m := candidate.Hour()*60 + candidate.Minute()
	if weekday(candidate) && m >= open && m < close {
		return after + delay, nil
	}
	start, _ := time.Parse(time.RFC3339Nano, s.StartAt)
	// Search real UTC minutes, which handles skipped and repeated local openings.
	t := candidate.Truncate(time.Minute)
	if t.Before(candidate) {
		t = t.Add(time.Minute)
	}
	for i := 0; i < 9*24*60; i++ {
		m = t.Hour()*60 + t.Minute()
		if weekday(t) && m >= open && m < close {
			return t.Sub(start).Seconds(), nil
		}
		t = t.Add(time.Minute)
	}
	return 0, errors.New("no business opening")
}

type Account struct {
	Username string   `json:"username"`
	Password string   `json:"password"`
	Role     string   `json:"role"`
	Scopes   []string `json:"scopes,omitempty"`
}
type Principal struct {
	Username string   `json:"username"`
	Role     string   `json:"role"`
	Scopes   []string `json:"scopes"`
}

func (p Principal) Can(scope string) bool {
	for _, s := range p.Scopes {
		if s == scope {
			return true
		}
	}
	return false
}

var permissions = map[string][]string{"operator": {"status:read", "jobs:write", "runs:control", "audit:read"}, "employee": {"status:read", "jobs:write"}, "service": {"status:read", "jobs:write"}}

type Config struct {
	HELICSTimeout                                                                                              time.Duration
	Username, Password, DatabaseURL, AMQPURL, Mode, RunID, Epoch, FederationID, AdapterURL, AdapterToken, Role string
	Identities                                                                                                 []Account
	Providers                                                                                                  map[string]string
	Quantum                                                                                                    float64
	Scenario                                                                                                   Scenario
	Autonomous                                                                                                 bool
	Peers                                                                                                      map[string]Peer
	Outputs                                                                                                    []Output
}
type Peer struct {
	Endpoint string `json:"endpoint"`
	Source   string `json:"source"`
}
type Output struct {
	Endpoint    string `json:"endpoint"`
	Destination string `json:"destination"`
	Boundary    string `json:"boundary"`
}

func (c Config) accounts() []Account {
	return append([]Account{{Username: c.Username, Password: c.Password, Role: "operator"}}, c.Identities...)
}
func (c Config) validateAccounts() error {
	seen := map[string]bool{}
	for _, a := range c.accounts() {
		allowed, ok := permissions[a.Role]
		if !ok || a.Username == "" || strings.Contains(a.Username, ":") || a.Password == "" || seen[a.Username] {
			return errors.New("invalid or duplicate independent identity")
		}
		seen[a.Username] = true
		for _, s := range a.Scopes {
			found := false
			for _, p := range allowed {
				if p == s {
					found = true
				}
			}
			if !found {
				return errors.New("identity permissions exceed role")
			}
		}
	}
	return nil
}
func (c Config) identify(user, password string) (Principal, bool) {
	var result Principal
	ok := false
	for _, a := range c.accounts() {
		u := subtle.ConstantTimeCompare([]byte(user), []byte(a.Username))
		p := subtle.ConstantTimeCompare([]byte(password), []byte(a.Password))
		if u&p == 1 {
			scopes := append([]string{}, a.Scopes...)
			if a.Scopes == nil {
				scopes = []string{}
				if a.Role != "service" {
					scopes = append(scopes, permissions[a.Role]...)
				}
			}
			sort.Strings(scopes)
			result = Principal{a.Username, a.Role, scopes}
			ok = true
		}
	}
	return result, ok
}
func env(k, def string) string {
	if v, ok := os.LookupEnv(k); ok {
		return v
	}
	return def
}
func loadConfig() (Config, error) {
	c := Config{Username: env("APP_USERNAME", "operator"), Password: os.Getenv("APP_PASSWORD"), DatabaseURL: os.Getenv("DATABASE_URL"), AMQPURL: os.Getenv("AMQP_URL"), Mode: env("CLOCK_MODE", "standalone"), Role: env("ROLE", "api"), RunID: os.Getenv("FEDERATION_RUN_ID"), Epoch: os.Getenv("FEDERATION_EPOCH"), FederationID: os.Getenv("FEDERATION_ID"), AdapterURL: os.Getenv("HELICS_ADAPTER_URL"), AdapterToken: os.Getenv("HELICS_ADAPTER_TOKEN"), Scenario: defaultScenario(), Autonomous: env("AUTONOMOUS_SAMPLE", "true") == "true"}
	var e error
	seconds, timeoutErr := strconv.ParseFloat(env("HELICS_TIMEOUT_SECONDS", "60"), 64)
	if timeoutErr != nil || !finite(seconds) || seconds <= 0 || seconds > 86400 {
		return c, errors.New("HELICS_TIMEOUT_SECONDS must be finite in (0,86400]")
	}
	c.HELICSTimeout = time.Duration(seconds * float64(time.Second))
	c.Quantum, e = strconv.ParseFloat(env("HANDOFF_QUANTUM", "1"), 64)
	if e != nil || !finite(c.Quantum) || c.Quantum < 1 {
		return c, errors.New("quantum must be finite and >=1")
	}
	if env("SIMULATOR", "logistics") != "logistics" {
		return c, errors.New("SIMULATOR must be logistics")
	}
	if e = strictJSON(strings.NewReader(env("APP_IDENTITIES", "[]")), &c.Identities); e != nil {
		return c, e
	}
	if e = c.validateAccounts(); e != nil {
		return c, e
	}
	if e = strictJSON(strings.NewReader(env("SCENARIO", "{}")), &c.Scenario); e != nil {
		return c, e
	}
	if e = c.Scenario.Validate(); e != nil {
		return c, e
	}
	if e = json.Unmarshal([]byte(env("BOUNDARY_PROVIDERS", "{}")), &c.Providers); e != nil {
		return c, e
	}
	if len(c.Providers) == 0 && c.Mode == "standalone" {
		c.Providers = map[string]string{"transport": "synthetic", "destinations": "synthetic"}
	}
	if len(c.Providers) != 2 {
		return c, errors.New("explicit transport and destinations providers required")
	}
	connected := false
	for _, b := range []string{"transport", "destinations"} {
		v := c.Providers[b]
		if v != "synthetic" && v != "helics" {
			return c, errors.New("invalid boundary provider")
		}
		connected = connected || v == "helics"
	}
	if c.Mode != "standalone" && c.Mode != "helics" || c.Mode == "standalone" && connected || c.Mode == "helics" && !connected {
		return c, errors.New("incompatible mode/providers")
	}
	if c.Mode == "helics" {
		if _, e = uuid.Parse(c.RunID); e != nil {
			return c, e
		}
		if _, e = uuid.Parse(c.Epoch); e != nil {
			return c, e
		}
		if c.FederationID == "" || c.AdapterURL == "" || c.AdapterToken == "" {
			return c, errors.New("connected mode requires federation identity and authenticated adapter")
		}
		if e = strictJSON(strings.NewReader(env("HELICS_PEERS", "{}")), &c.Peers); e != nil {
			return c, e
		}
		if e = strictJSON(strings.NewReader(env("HELICS_OUTPUTS", "[]")), &c.Outputs); e != nil {
			return c, e
		}
		n := 0
		for b, p := range c.Peers {
			if c.Providers[b] != "helics" || p.Endpoint == "" || p.Source == "" {
				return c, errors.New("invalid connected peer route")
			}
			n++
		}
		required := 0
		for _, v := range c.Providers {
			if v == "helics" {
				required++
			}
		}
		if n != required || len(c.Outputs) == 0 {
			return c, errors.New("connected peers and outputs required")
		}
	}
	return c, nil
}
func seededInput(s Scenario, run, epoch, boundary string, slot int, due float64) map[string]any {
	digest := sha256.Sum256([]byte(fmt.Sprintf("%d:logistics:%s:%d", s.Seed, boundary, slot)))
	id := uuid.NewSHA1(uuid.MustParse(run), []byte(fmt.Sprintf("%s:%s:%d:%d", epoch, boundary, slot, s.Seed)))
	kind := "demand"
	if boundary == "destinations" {
		kind = "carrier"
	}
	return map[string]any{"schema_version": "1.0", "input_id": id.String(), "run_id": run, "epoch": epoch, "application": "logistics", "boundary": boundary, "kind": kind, "provider": "synthetic", "effective_time": due, "quantity": 1 + int(binary.BigEndian.Uint32(digest[:4])%10), "quantity_unit": "item"}
}
func scenarioFrom(r row) Scenario {
	s := defaultScenario()
	raw, _ := json.Marshal(r["scenario"])
	_ = json.Unmarshal(raw, &s)
	return s
}

func (s *Scenario) UnmarshalJSON(data []byte) error {
	type plain Scenario
	v := plain(defaultScenario())
	d := json.NewDecoder(strings.NewReader(string(data)))
	d.DisallowUnknownFields()
	if e := d.Decode(&v); e != nil {
		return e
	}
	*s = Scenario(v)
	return s.Validate()
}

func (c Config) adapterTimeout() time.Duration {
	if c.HELICSTimeout > 0 {
		return c.HELICSTimeout
	}
	return 60 * time.Second
}
