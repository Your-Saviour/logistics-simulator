package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// SQL JSON uses []any for contents; the local builder uses []row. Compare the
// serialized manifest so container types do not reject identical unit records.
func sameSourceManifest(unit row, frozen any) bool {
	actual, err := json.Marshal(handlingUnit(unit))
	if err != nil {
		return false
	}
	expected, err := json.Marshal(frozen)
	return err == nil && bytes.Equal(actual, expected)
}

// Only a completed native truck unload can initiate raw custody to Storage.
func (s *Store) beginSourceCustody(ctx context.Context, tx pgx.Tx, r, j row, c TransportCommand) error {
	peer, configured := s.C.Peers["destinations"]
	if !configured || s.C.Providers["destinations"] != "helics" || peer.Source != "storage" {
		return Conflict("Raw Storage handoff requires its configured destinations peer")
	}
	if !custodyEndpoint(c.Destination, "storage", "raw") || !strings.HasPrefix(c.Destination, "storage.inbound.dock") {
		return Conflict("Raw Storage handoff requires an exact inbound receiving dock")
	}
	unit, err := object(ctx, tx, "SELECT * FROM transport_handling_units WHERE id=$1 AND run_id=$2 AND epoch=$3", c.Reference, r["id"], r["epoch"])
	if errors.Is(err, pgx.ErrNoRows) {
		return Conflict("Raw unit is not in this run")
	}
	if err != nil {
		return err
	}
	if unit["category"] != "raw" || unit["state"] != "available" || unit["transfer_id"] != nil || !strings.HasPrefix(unit["position"].(string), "logistics.inbound.dock") {
		return Conflict("Only an available unloaded raw unit can enter Storage custody")
	}
	var unloaded bool
	if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_unit_movements m JOIN transport_transfers t ON t.id::text=m.references->>'transfer_id' WHERE m.unit_id=$1 AND m.run_id=$2 AND m.epoch=$3 AND m.action='unload' AND m.destination=$4 AND m.origin LIKE 'logistics.inbound.truck%' AND t.status='received')", unit["id"], r["id"], r["epoch"], unit["position"]).Scan(&unloaded); err != nil {
		return err
	}
	if !unloaded {
		return Conflict("Raw handoff requires a confirmed truck unload and completed transport receipt")
	}
	if num(unit, "version") > handlingMaxCounter-3 || num(unit, "last_sequence") > handlingMaxCounter-2 || num(unit, "custody_generation") >= handlingMaxCounter {
		return Conflict("Raw custody counters lack departure and receipt headroom")
	}
	unit, err = object(ctx, tx, "UPDATE transport_handling_units SET state='reserved',version=version+1 WHERE id=$1 RETURNING *", unit["id"])
	if err != nil {
		return err
	}
	h := row{"id": j["id"], "run_id": r["id"], "epoch": r["epoch"], "source": "logistics", "destination_owner": "storage", "origin": unit["position"], "destination": c.Destination, "state": "offered", "unit": handlingUnit(unit), "departure_token": nil, "receipt_id": nil, "reason": nil}
	raw, _ := json.Marshal(h)
	if _, err = tx.Exec(ctx, "INSERT INTO transport_source_custody(id,run_id,epoch,unit_id,correlation_id,state,offer,command_id) VALUES($1,$2,$3,$4,$5,'offered',$6,$1)", j["id"], r["id"], r["epoch"], unit["id"], c.CorrelationID, raw); err != nil {
		return err
	}
	return s.publishSourceCustody(ctx, tx, r, h, c.CorrelationID)
}

func (s *Store) publishSourceCustody(ctx context.Context, tx pgx.Tx, r, h row, correlation string) error {
	id := uuid.NewSHA1(uuid.MustParse(h["id"].(string)), []byte("logistics:"+h["state"].(string))).String()
	// Reuse the complete first envelope, including its wall timestamp, on retry.
	old, err := object(ctx, tx, "SELECT envelope FROM boundary_outbox WHERE run_id=$1 AND envelope->>'event_id'=$2 LIMIT 1", r["id"], id)
	var raw []byte
	if err == nil {
		raw, _ = json.Marshal(old["envelope"])
	} else if errors.Is(err, pgx.ErrNoRows) {
		payload, _ := json.Marshal(h)
		e := TransportEnvelope{SchemaVersion: "1.0", Type: "handling." + h["state"].(string) + ".v1", EventID: id, FederationID: s.C.FederationID, RunID: r["id"].(string), Epoch: r["epoch"].(string), CorrelationID: correlation, CausationID: h["id"].(string), AggregateID: h["id"].(string), AggregateVersion: int(num(h["unit"].(map[string]any), "version")), Source: "logistics", Destination: "storage", Boundary: "supply", EffectiveTime: num(r, "granted") + s.C.Quantum, WallTime: time.Now().UTC().Format(time.RFC3339Nano), QuantityUnit: "item", Payload: payload}
		raw, _ = json.Marshal(e)
	} else {
		return err
	}
	_, err = tx.Exec(ctx, "INSERT INTO boundary_outbox(id,run_id,envelope) SELECT $1,$2,$3::jsonb WHERE NOT EXISTS(SELECT 1 FROM boundary_outbox WHERE run_id=$2 AND envelope->>'event_id'=$4 AND (sent_at IS NULL OR sent_at>clock_timestamp()-interval '5 seconds'))", uuid.NewString(), r["id"], raw, id)
	return err
}

func (s *Store) applySourceCustody(ctx context.Context, tx pgx.Tx, r, j, h row, correlation string) error {
	old, err := object(ctx, tx, "SELECT * FROM transport_source_custody WHERE id=$1 AND run_id=$2 AND epoch=$3", h["id"], r["id"], r["epoch"])
	if errors.Is(err, pgx.ErrNoRows) {
		return Conflict("Storage proof has no matching outgoing raw handoff")
	}
	if err != nil {
		return err
	}
	if old["correlation_id"] != correlation {
		return Conflict("Raw custody correlation changed")
	}
	expected := copyCustody(old["offer"].(map[string]any))
	if h["state"] == "accepted" {
		expected["state"] = "accepted"
		if !reflect.DeepEqual(expected, h) {
			return Conflict("Storage acceptance changed the reserved raw manifest")
		}
		if old["state"] != "offered" {
			payload := copyCustody(old["departure"].(map[string]any))
			if old["state"] == "acknowledged" {
				payload = copyCustody(old["receipt"].(map[string]any))
				payload["state"] = "acknowledged"
			}
			return s.publishSourceCustody(ctx, tx, r, payload, correlation)
		}
		unit, err := object(ctx, tx, "SELECT * FROM transport_handling_units WHERE id=$1", old["unit_id"])
		if err != nil {
			return err
		}
		if !sameSourceManifest(unit, old["offer"].(map[string]any)["unit"]) {
			return Conflict("Offered raw custody changed before departure")
		}
		fleet := fleetRequest(r, unit["id"].(string), h["id"].(string), h["origin"].(string), h["destination"].(string), "logistics", int(num(unit, "custody_generation"))+1)
		if err = fleetGate(ctx, tx, r, fleet, "pickup_ready", false); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='in_transit',origin=position,position=NULL,destination=$1,handoff_id=$2,custody_generation=custody_generation+1 WHERE id=$3", h["destination"], h["id"], unit["id"]); err != nil {
			return err
		}
		if err = handlingMovement(ctx, tx, r, j, unit, "depart", h["origin"], h["destination"].(string), correlation, nil); err != nil {
			return err
		}
		unit, err = object(ctx, tx, "SELECT * FROM transport_handling_units WHERE id=$1", unit["id"])
		if err != nil {
			return err
		}
		expected["state"] = "departed"
		expected["unit"] = handlingUnit(unit)
		expected["departure_token"] = row{"id": uuid.NewSHA1(uuid.MustParse(h["id"].(string)), []byte("logistics:departure-token")).String(), "handoff_id": h["id"], "unit_id": unit["id"], "run_id": r["id"], "epoch": r["epoch"], "unit_version": unit["version"], "last_sequence": unit["last_sequence"], "custody_generation": unit["custody_generation"]}
		raw, _ := json.Marshal(expected)
		if _, err = tx.Exec(ctx, "UPDATE transport_source_custody SET state='departed',departure=$1 WHERE id=$2", raw, h["id"]); err != nil {
			return err
		}
		if err = fleetProof(ctx, tx, r, fleet, "departure"); err != nil {
			return err
		}
		return s.publishSourceCustody(ctx, tx, r, expected, correlation)
	}
	if h["state"] != "received" || old["departure"] == nil {
		return Conflict("Storage receipt requires committed source departure")
	}
	expected = copyCustody(old["departure"].(map[string]any))
	expected["state"] = "received"
	expected["receipt_id"] = h["receipt_id"]
	if !reflect.DeepEqual(expected, h) || old["receipt"] != nil && !reflect.DeepEqual(old["receipt"], h) {
		return Conflict("Storage receipt changed raw departure or receipt identity")
	}
	if old["state"] != "acknowledged" {
		unit, err := object(ctx, tx, "SELECT * FROM transport_handling_units WHERE id=$1", old["unit_id"])
		if err != nil {
			return err
		}
		if !sameSourceManifest(unit, old["departure"].(map[string]any)["unit"]) {
			return Conflict("Receipt cannot retire a different raw custody generation")
		}
		if err = handlingCounterRoom(unit, false); err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='dispatched',version=version+1 WHERE id=$1", unit["id"]); err != nil {
			return err
		}
		raw, _ := json.Marshal(h)
		if _, err = tx.Exec(ctx, "UPDATE transport_source_custody SET state='acknowledged',receipt=$1 WHERE id=$2", raw, h["id"]); err != nil {
			return err
		}
	}
	expected["state"] = "acknowledged"
	return s.publishSourceCustody(ctx, tx, r, expected, correlation)
}
