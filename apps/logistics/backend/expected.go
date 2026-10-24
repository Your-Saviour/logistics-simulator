package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func parseExpectedManifest(payload row, env TransportEnvelope) ([]HandlingManifest, error) {
	value, exists := payload["unit_manifest"]
	if !exists || value == nil {
		return nil, nil
	}
	if env.Source != "shipping" || env.Type != "logistics.request.v1" {
		return nil, Conflict("Expected manifests require the Shipping request authority")
	}
	destination, ok := payload["customer_destination"].(string)
	if !ok || !transportCode.MatchString(destination) {
		return nil, Conflict("Expected carrier request requires its exact customer destination")
	}
	raw, _ := json.Marshal(value)
	var manifest []HandlingManifest
	if err := strictJSON(bytes.NewReader(raw), &manifest); err != nil {
		return nil, err
	}
	if len(manifest) < 1 || len(manifest) > 8 {
		return nil, Conflict("Expected whole manifest requires 1..8 truck units")
	}
	var ids []string
	rawIDs, _ := json.Marshal(payload["unit_ids"])
	if err := json.Unmarshal(rawIDs, &ids); err != nil {
		return nil, err
	}
	if len(ids) != len(manifest) {
		return nil, Conflict("Expected IDs and manifest differ")
	}
	seen := map[string]int{}
	total := 0
	for _, unit := range manifest {
		if _, err := uuid.Parse(unit.ID); err != nil {
			return nil, err
		}
		if unit.Quantity < 1 || unit.Quantity > 10000 || seen[unit.ID] != 0 {
			return nil, Conflict("Invalid or duplicate expected whole unit")
		}
		seen[unit.ID] = unit.Quantity
		total += unit.Quantity
	}
	for _, id := range ids {
		if seen[id] == 0 {
			return nil, Conflict("Expected IDs and manifest differ")
		}
		delete(seen, id)
	}
	if total != int(num(payload, "quantity")) || payload["external_reference"] != env.AggregateID {
		return nil, Conflict("Expected contents or peer request identity mismatch")
	}
	return manifest, nil
}
func planExpectedUnits(ctx context.Context, tx pgx.Tx, r, transfer row, c TransportCommand) error {
	var provider bool
	if err := tx.QueryRow(ctx, "SELECT provider FROM transport_commands WHERE id=$1", transfer["id"]).Scan(&provider); err != nil {
		return err
	}
	if !provider || c.ExpectedSource != "shipping" || transfer["origin"] != "DISPATCH" || len(c.ExpectedUnits) < 1 || len(c.ExpectedUnits) > 8 {
		return Conflict("Expected stock requires a private Shipping dispatch request")
	}
	capable := false
	for index, vehicle := range transportConfig(r).Vehicles {
		if index < 4 && vehicle.Capacity >= c.Quantity {
			capable = true
		}
	}
	if !capable {
		return Conflict("No configured vehicle can carry the complete whole-unit manifest")
	}
	for _, unit := range c.ExpectedUnits {
		var occupied bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE id=$1) OR EXISTS(SELECT 1 FROM transport_expected_units WHERE unit_id=$1 AND active)", unit.ID).Scan(&occupied); err != nil {
			return err
		}
		if occupied {
			return Conflict("Expected handling unit is already known or allocated")
		}
		if _, err := tx.Exec(ctx, "INSERT INTO transport_expected_units(transfer_id,unit_id,source,sku,quantity,run_id,epoch) VALUES($1,$2,$3,$4,$5,$6,$7)", transfer["id"], unit.ID, c.ExpectedSource, c.SKU, unit.Quantity, r["id"], r["epoch"]); err != nil {
			return err
		}
	}
	return nil
}
func expectedCustody(ctx context.Context, tx pgx.Tx, r, h row, correlation string) (row, error) {
	unit := h["unit"].(map[string]any)
	expected, err := object(ctx, tx, "SELECT e.*,t.origin,t.status,t.vehicle,t.correlation_id FROM transport_expected_units e JOIN transport_transfers t ON t.id=e.transfer_id WHERE e.unit_id=$1 AND e.active", unit["id"])
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	item := unit["contents"].([]any)[0].(map[string]any)
	if expected["run_id"] != r["id"] || expected["epoch"] != r["epoch"] || expected["source"] != h["source"] || expected["sku"] != item["sku"] || num(expected, "quantity") != num(item, "quantity") || unit["category"] != "finished" || expected["correlation_id"] != correlation {
		return nil, Conflict("Custody does not match the exact expected shipment unit")
	}
	if expected["status"] == "requested" {
		return nil, custodyCapacity{}
	}
	if expected["status"] != "assigned" || expected["vehicle"] == nil {
		return nil, Conflict("Expected custody requires an assigned vehicle before loading")
	}
	if expected["destination"] != h["destination"] {
		return nil, Conflict("Custody changed the assigned receiving endpoint")
	}
	return expected, nil
}

// Assign all receiving endpoints atomically before the sender can relinquish
// any unit; partially admitted manifests must not fill every staging slot.
func reserveExpectedDestinations(ctx context.Context, tx pgx.Tx, r, transfer row) error {
	units, err := objects(ctx, tx, "SELECT * FROM transport_expected_units WHERE transfer_id=$1 AND active ORDER BY unit_id", transfer["id"])
	if err != nil {
		return err
	}
	if len(units) == 0 {
		return nil
	}
	destinations := row{}
	for _, unit := range units {
		position, err := freeHandlingPosition(ctx, tx, r, "logistics.outbound.staging", "finished")
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_expected_units SET destination=$1 WHERE transfer_id=$2 AND unit_id=$3", position, transfer["id"], unit["unit_id"]); err != nil {
			return err
		}
		destinations[unit["unit_id"].(string)] = position
	}
	raw, _ := json.Marshal(destinations)
	_, err = tx.Exec(ctx, "UPDATE transport_transfers SET unit_destinations=$1 WHERE id=$2", raw, transfer["id"])
	return err
}
