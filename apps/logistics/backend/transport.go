package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"io"
	"regexp"
)

type Location struct {
	Code string `json:"code"`
}
type Route struct {
	Code           string  `json:"code"`
	Origin         string  `json:"origin"`
	Destination    string  `json:"destination"`
	JourneySeconds float64 `json:"journey_seconds"`
}
type Vehicle struct {
	Code     string `json:"code"`
	Capacity int    `json:"capacity"`
	Location string `json:"location"`
}
type TransportConfig struct {
	Locations []Location `json:"locations"`
	Routes    []Route    `json:"routes"`
	Vehicles  []Vehicle  `json:"vehicles"`
}

func defaultTransport() TransportConfig {
	return TransportConfig{
		[]Location{{"WAREHOUSE"}, {"DISPATCH"}, {"CUSTOMER"}},
		[]Route{{"WAREHOUSE-DISPATCH", "WAREHOUSE", "DISPATCH", 10}, {"DISPATCH-WAREHOUSE", "DISPATCH", "WAREHOUSE", 10}, {"DISPATCH-CUSTOMER", "DISPATCH", "CUSTOMER", 20}, {"CUSTOMER-DISPATCH", "CUSTOMER", "DISPATCH", 20}},
		[]Vehicle{{"TRUCK-1", 100, "WAREHOUSE"}, {"VAN-1", 25, "DISPATCH"}},
	}
}

var transportCode = regexp.MustCompile(`^[A-Z0-9][A-Z0-9_-]{0,31}$`)

func (c TransportConfig) Validate() error {
	if len(c.Locations) < 2 || len(c.Locations) > 100 || len(c.Routes) < 1 || len(c.Routes) > 100 || len(c.Vehicles) < 1 || len(c.Vehicles) > 100 {
		return errors.New("transport requires 2..100 locations and 1..100 routes and vehicles")
	}
	locations := map[string]bool{}
	routes := map[string]bool{}
	vehicles := map[string]bool{}
	for _, l := range c.Locations {
		if !transportCode.MatchString(l.Code) || locations[l.Code] {
			return errors.New("invalid or duplicate transport location")
		}
		locations[l.Code] = true
	}
	for _, r := range c.Routes {
		if !transportCode.MatchString(r.Code) || routes[r.Code] || !locations[r.Origin] || !locations[r.Destination] || r.Origin == r.Destination || !finite(r.JourneySeconds) || r.JourneySeconds < 1 || r.JourneySeconds > 604800 {
			return errors.New("invalid or duplicate transport route; journey must be 1..604800 seconds")
		}
		routes[r.Code] = true
	}
	for _, v := range c.Vehicles {
		if !transportCode.MatchString(v.Code) || vehicles[v.Code] || !locations[v.Location] || v.Capacity < 1 || v.Capacity > 10000 {
			return errors.New("invalid or duplicate vehicle; capacity must be 1..10000 items")
		}
		vehicles[v.Code] = true
	}
	return nil
}
func transportConfig(r row) TransportConfig {
	s := scenarioFrom(r)
	if s.Transport != nil {
		return *s.Transport
	}
	return defaultTransport()
}

type TransportCommand struct {
	RunID             string  `json:"run_id"`
	Epoch             string  `json:"epoch"`
	DueAt             float64 `json:"due_at"`
	Action            string  `json:"action"`
	Route             string  `json:"route,omitempty"`
	SKU               string  `json:"sku,omitempty"`
	Quantity          int     `json:"quantity,omitempty"`
	CorrelationID     string  `json:"correlation_id,omitempty"`
	Reference         string  `json:"reference,omitempty"`
	Vehicle           string  `json:"vehicle,omitempty"`
	ExternalReference string  `json:"external_reference,omitempty"`
}

func parseTransport(r io.Reader) (TransportCommand, error) {
	var c TransportCommand
	raw, e := io.ReadAll(io.LimitReader(r, (1<<20)+1))
	if e != nil {
		return c, e
	}
	if e = strictJSON(bytes.NewReader(raw), &c); e != nil {
		return c, e
	}
	var fields map[string]json.RawMessage
	if e = json.Unmarshal(raw, &fields); e != nil {
		return c, e
	}
	allowed := map[string]bool{"run_id": true, "epoch": true, "due_at": true, "action": true}
	required := []string{"run_id", "epoch", "due_at", "action"}
	switch c.Action {
	case "request":
		required = append(required, "route", "sku", "quantity", "correlation_id")
		allowed["external_reference"] = true
	case "assign":
		required = append(required, "reference", "vehicle")
	case "load", "depart", "arrive", "unload", "receive":
		required = append(required, "reference")
	default:
		return c, errors.New("unknown transport action")
	}
	for _, k := range required {
		allowed[k] = true
		if fields[k] == nil || string(fields[k]) == "null" {
			return c, errors.New("missing transport field: " + k)
		}
	}
	for k := range fields {
		if !allowed[k] {
			return c, errors.New("field is not valid for transport action: " + k)
		}
	}
	for _, id := range []string{c.RunID, c.Epoch} {
		if _, e = uuid.Parse(id); e != nil {
			return c, e
		}
	}
	if !finite(c.DueAt) || c.DueAt < 0 {
		return c, errors.New("finite nonnegative due_at required")
	}
	if c.Action == "request" {
		if !transportCode.MatchString(c.Route) || !transportCode.MatchString(c.SKU) || c.Quantity < 1 || c.Quantity > 10000 {
			return c, errors.New("valid route, SKU and integer quantity 1..10000 required")
		}
		if _, e = uuid.Parse(c.CorrelationID); e != nil {
			return c, e
		}
		if c.ExternalReference != "" {
			if _, e = uuid.Parse(c.ExternalReference); e != nil {
				return c, e
			}
		}
	} else {
		if _, e = uuid.Parse(c.Reference); e != nil {
			return c, e
		}
	}
	if c.Action == "assign" && !transportCode.MatchString(c.Vehicle) {
		return c, errors.New("valid vehicle required")
	}
	return c, nil
}
