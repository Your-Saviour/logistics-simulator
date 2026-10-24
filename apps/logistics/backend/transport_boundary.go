package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"strings"
	"time"
)

type TransportEnvelope struct {
	SchemaVersion    string          `json:"schema_version"`
	Type             string          `json:"type"`
	EventID          string          `json:"event_id"`
	FederationID     string          `json:"federation_id"`
	RunID            string          `json:"run_id"`
	Epoch            string          `json:"epoch"`
	CorrelationID    string          `json:"correlation_id"`
	CausationID      string          `json:"causation_id"`
	AggregateID      string          `json:"aggregate_id"`
	AggregateVersion int             `json:"aggregate_version"`
	Source           string          `json:"source"`
	Destination      string          `json:"destination"`
	Boundary         string          `json:"boundary"`
	EffectiveTime    float64         `json:"effective_time"`
	WallTime         string          `json:"wall_time"`
	QuantityUnit     string          `json:"quantity_unit"`
	Payload          json.RawMessage `json:"payload"`
}

func (s *Store) IngestTransport(ctx context.Context, raw []byte, source string) (result string, e error) {
	var env TransportEnvelope
	if e = strictJSON(bytes.NewReader(raw), &env); e != nil {
		return
	}
	for _, id := range []string{env.EventID, env.RunID, env.Epoch, env.CorrelationID, env.CausationID, env.AggregateID} {
		if _, e = uuid.Parse(id); e != nil {
			return
		}
	}
	peer, ok := s.C.Peers[env.Boundary]
	if !ok || peer.Source != env.Source || peer.Endpoint != source || env.Destination != "logistics" || env.FederationID != s.C.FederationID {
		return "", Conflict("Unconfigured HELICS sender or federation")
	}
	if strings.HasPrefix(env.Type, "handling.") {
		return s.ingestCustody(ctx, raw, env, source)
	}
	if env.SchemaVersion != "1.0" || env.QuantityUnit != "item" || (env.AggregateVersion < 1 || (env.Type != "storage.transfer.completed.v1" && env.AggregateVersion != 1)) || !finite(env.EffectiveTime) || env.EffectiveTime < 0 {
		return "", errors.New("Invalid transport envelope metadata")
	}
	if _, e = time.Parse(time.RFC3339Nano, env.WallTime); e != nil {
		return
	}
	var payload row
	if e = json.Unmarshal(env.Payload, &payload); e != nil {
		return
	}
	if payload == nil {
		return "", errors.New("Transport payload required")
	}
	var expected []HandlingManifest
	var expectedErr error
	if env.Type == "logistics.request.v1" {
		expected, expectedErr = parseExpectedManifest(payload, env)
	}
	if expectedErr != nil {
		return "", expectedErr
	}
	customerDestination := ""
	if expected != nil {
		customerDestination = payload["customer_destination"].(string)
		delete(payload, "unit_manifest")
		delete(payload, "customer_destination")
	} else if env.Type == "logistics.request.v1" {
		if payload["unit_manifest"] == nil {
			delete(payload, "unit_manifest")
		}
		if payload["customer_destination"] == nil {
			delete(payload, "customer_destination")
		} else {
			return "", Conflict("Customer destination requires an authorized expected manifest")
		}
	}
	command := row{"run_id": env.RunID, "epoch": env.Epoch, "due_at": env.EffectiveTime}
	switch env.Type {
	case "storage.transfer.completed.v1":
		if env.Source != "storage" || env.Boundary != "transport" {
			return "", Conflict("Storage transfer requires storage transport peer")
		}
		var tr struct {
			UnitManifest  []HandlingManifest `json:"unit_manifest"`
			ID            string             `json:"id"`
			RunID         string             `json:"run_id"`
			ReservationID string             `json:"reservation_id"`
			SKU           string             `json:"sku"`
			Origin        string             `json:"origin"`
			Destination   string             `json:"destination"`
			Quantity      int                `json:"quantity"`
			CorrelationID string             `json:"correlation_id"`
			Status        string             `json:"status"`
			Version       int                `json:"version"`
		}
		if e = strictJSON(bytes.NewReader(env.Payload), &tr); e != nil {
			return
		}
		if _, e = uuid.Parse(tr.ReservationID); e != nil {
			return
		}
		if tr.ID != env.AggregateID || tr.RunID != env.RunID || tr.CorrelationID != env.CorrelationID || tr.Version != env.AggregateVersion || tr.Status != "in_transit" || !transportCode.MatchString(tr.Origin) || !transportCode.MatchString(tr.Destination) {
			return "", Conflict("Storage transfer metadata differs from its envelope")
		}
		command["action"] = "request"
		command["correlation_id"] = env.CorrelationID
		payload = row{"route": "PENDING", "sku": tr.SKU, "quantity": tr.Quantity, "external_reference": tr.ID}
	case "logistics.request.v1":
		if env.Boundary != "transport" {
			return "", Conflict("Transport request requires transport boundary")
		}
		command["action"] = "request"
		command["correlation_id"] = env.CorrelationID
	case "logistics.receipt.v1":
		if env.Boundary != "destinations" {
			return "", Conflict("Receipt requires destinations boundary")
		}
		command["action"] = "receive"
	default:
		return "", errors.New("Unknown transport input type")
	}
	for k, v := range payload {
		if _, exists := command[k]; exists {
			return "", errors.New("Payload overrides transport metadata")
		}
		command[k] = v
	}
	body, _ := json.Marshal(command)
	c, err := parseTransport(bytes.NewReader(body))
	if err != nil && env.Type != "storage.transfer.completed.v1" {
		return "", err
	}
	if expected != nil {
		c.ExpectedUnits = expected
		c.ExpectedSource = env.Source
		c.CustomerDestination = customerDestination
	}
	e = s.transaction(ctx, func(tx pgx.Tx) error {
		r, err := lockRun(ctx, tx)
		if err != nil {
			return err
		}
		if env.RunID != r["id"] || env.Epoch != r["epoch"] {
			result = "fenced"
			return nil
		}
		prior, err := object(ctx, tx, "SELECT * FROM transport_peer_commands WHERE event_id=$1", env.EventID)
		if err == nil {
			old, _ := json.Marshal(prior["body"])
			var v any
			json.Unmarshal(raw, &v)
			canonical, _ := json.Marshal(v)
			if string(old) != string(canonical) {
				return Conflict("Peer event ID reused with different content")
			}
			result = "duplicate"
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var exists bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_peer_commands WHERE run_id=$1 AND source=$2 AND aggregate_id=$3)", env.RunID, env.Source, env.AggregateID).Scan(&exists); err != nil {
			return err
		}
		if exists {
			return Conflict("Peer aggregate already accepted")
		}
		if env.Type == "storage.transfer.completed.v1" {
			var transfer row
			json.Unmarshal(env.Payload, &transfer)
			c.Route = ""
			for _, route := range transportConfig(r).Routes {
				if route.Origin == transfer["origin"] && route.Destination == transfer["destination"] {
					c.Route = route.Code
					break
				}
			}
			if c.Route == "" {
				return Conflict("No configured route for storage transfer")
			}
		}
		if env.EffectiveTime < num(r, "granted") || !active(r) {
			return Conflict("Late event or inactive run")
		}
		if env.Type == "logistics.receipt.v1" {
			tr, err := object(ctx, tx, "SELECT correlation_id::text FROM transport_transfers WHERE id=$1 AND run_id=$2", c.Reference, r["id"])
			if errors.Is(err, pgx.ErrNoRows) {
				return Conflict("Unknown transfer receipt reference")
			}
			if err != nil {
				return err
			}
			if tr["correlation_id"] != env.CorrelationID {
				return Conflict("Receipt correlation differs from transfer")
			}
		}
		// A legacy quantity-only transfer is an observation, not unit custody.
		if env.Type == "storage.transfer.completed.v1" {
			if _, err = tx.Exec(ctx, "INSERT INTO transport_peer_commands(run_id,source,aggregate_id,event_id,body) VALUES($1,$2,$3,$4,$5)", r["id"], env.Source, env.AggregateID, env.EventID, raw); err != nil {
				return err
			}
			if _, err = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3)", env.EventID, r["id"], r["epoch"]); err != nil {
				return err
			}
			result = "observed"
			return nil
		}
		// Native input at the current grant is eligible now, unlike employee scheduling.
		id := uuid.NewString()
		jobPayload, _ := json.Marshal(row{"transport": c})
		cmdRaw, _ := json.Marshal(c)
		if _, err = tx.Exec(ctx, "INSERT INTO jobs(id,run_id,epoch,idempotency_key,due_at,original_due_at,payload) VALUES($1,$2,$3,$4,$5,$5,$6)", id, r["id"], r["epoch"], "boundary:"+env.EventID, c.DueAt, jobPayload); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO transport_commands(id,run_id,command,provider) VALUES($1,$2,$3,true)", id, r["id"], cmdRaw); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO transport_peer_commands(run_id,source,aggregate_id,event_id,body) VALUES($1,$2,$3,$4,$5)", r["id"], env.Source, env.AggregateID, env.EventID, raw); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "INSERT INTO inbox(event_id,run_id,epoch) VALUES($1,$2,$3)", env.EventID, r["id"], r["epoch"]); err != nil {
			return err
		}
		result = "accepted"
		return nil
	})
	return
}
func transportBoundaryEnvelope(c Config, r, out row, route Output) row {
	body := out["envelope"].(map[string]any)
	tr := body["transfer"].(map[string]any)
	routeBody, _ := json.Marshal(route)
	eventID := uuid.NewSHA1(uuid.MustParse(out["id"].(string)), routeBody).String()
	result := row{"schema_version": "1.0", "type": body["type"], "event_id": eventID, "federation_id": c.FederationID, "run_id": r["id"], "epoch": r["epoch"], "correlation_id": tr["correlation_id"], "causation_id": body["command_id"], "aggregate_id": tr["id"], "aggregate_version": tr["version"], "source": "logistics", "destination": route.Destination, "boundary": route.Boundary, "effective_time": num(body, "time") + c.Quantum, "wall_time": out["created_at"], "quantity_unit": "item", "payload": tr}
	if route.Destination == "storage" {
		result["type"] = "storage.transfer.arrived.v1"
		result["aggregate_id"] = body["command_id"]
		result["aggregate_version"] = 1
		result["payload"] = row{"reference": tr["external_reference"]}
	}
	return result
}
