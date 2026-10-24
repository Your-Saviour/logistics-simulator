package main

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

//go:embed handling-facility.json
var handlingFacility []byte

type physicalLocation struct {
	ID         string   `json:"id"`
	Owner      string   `json:"owner"`
	Kind       string   `json:"kind"`
	Compatible []string `json:"compatible"`
}

var physicalLocations = func() map[string]physicalLocation {
	var catalog struct {
		Locations []physicalLocation `json:"locations"`
	}
	if err := json.Unmarshal(handlingFacility, &catalog); err != nil {
		panic(err)
	}
	locations := map[string]physicalLocation{}
	for _, location := range catalog.Locations {
		locations[location.ID] = location
	}
	return locations
}()

func freeHandlingPosition(ctx context.Context, tx pgx.Tx, run row, prefix, category string) (string, error) {
	occupied, err := objects(ctx, tx, "SELECT position FROM transport_handling_units WHERE run_id=$1 AND epoch=$2 AND position IS NOT NULL UNION SELECT destination AS position FROM transport_handling_units WHERE run_id=$1 AND epoch=$2 AND state='in_transit'", run["id"], run["epoch"])
	if err != nil {
		return "", err
	}
	used := map[string]bool{}
	for _, unit := range occupied {
		used[unit["position"].(string)] = true
	}
	ids := []string{}
	for id, location := range physicalLocations {
		if location.Owner == "logistics" && strings.HasPrefix(id, prefix) && !used[id] {
			for _, allowed := range location.Compatible {
				if allowed == category {
					ids = append(ids, id)
				}
			}
		}
	}
	sort.Strings(ids)
	if len(ids) == 0 {
		return "", Conflict("No compatible physical slot capacity; whole unit remains at its recorded position")
	}
	return ids[0], nil
}

func handlingUnit(unit row) row {
	result := row{"owner": "logistics", "contents": []row{{"sku": unit["sku"], "quantity": unit["quantity"]}}}
	for _, field := range []string{"id", "barcode", "run_id", "epoch", "version", "custody_generation", "last_sequence", "category", "state", "position", "origin", "destination", "handoff_id"} {
		result[field] = unit[field]
	}
	return result
}

func handlingSnapshot(ctx context.Context, tx pgx.Tx, run row) (row, error) {
	units, err := objects(ctx, tx, "SELECT * FROM transport_handling_units WHERE run_id=$1 AND epoch=$2 ORDER BY id", run["id"], run["epoch"])
	if err != nil {
		return nil, err
	}
	values := []row{}
	for _, unit := range units {
		values = append(values, handlingUnit(unit))
	}
	contexts := []row{}
	for _, unit := range units {
		contexts = append(contexts, row{"unit_id": unit["id"], "logical_location": unit["logical_location"], "transfer_id": unit["transfer_id"]})
	}
	movements, err := objects(ctx, tx, "SELECT id,unit_id,barcode,run_id,epoch,sequence,custody_generation,origin,destination,simulation_time,action,\"references\",correlation_id FROM transport_unit_movements WHERE run_id=$1 AND epoch=$2 ORDER BY unit_id,sequence", run["id"], run["epoch"])
	if err != nil {
		return nil, err
	}
	return row{"version": 1, "catalog_version": 1, "units": values, "unit_context": contexts, "movements": movements, "handoffs": []row{}, "lineage": []row{}}, nil
}

func handlingMovement(ctx context.Context, tx pgx.Tx, run, job, unit row, action string, origin any, destination string, correlation string, transfer any) error {
	updated, err := object(ctx, tx, "UPDATE transport_handling_units SET last_sequence=last_sequence+1,version=version+1 WHERE id=$1 RETURNING *", unit["id"])
	if err != nil {
		return err
	}
	references, _ := json.Marshal(row{"transfer_id": transfer, "batch_id": nil, "shipment_id": nil})
	_, err = tx.Exec(ctx, "INSERT INTO transport_unit_movements(id,unit_id,barcode,run_id,epoch,command_id,sequence,custody_generation,action,origin,destination,simulation_time,\"references\",correlation_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)", uuid.NewString(), unit["id"], unit["barcode"], run["id"], run["epoch"], job["id"], int(num(updated, "last_sequence")), int(num(updated, "custody_generation")), action, origin, destination, run["granted"], references, correlation)
	return err
}

func intakeHandling(ctx context.Context, tx pgx.Tx, run, job row, command TransportCommand) error {
	location := command.Location
	if location == "" {
		location = "WAREHOUSE"
	}
	known := false
	for _, configured := range transportConfig(run).Locations {
		if configured.Code == location {
			known = true
		}
	}
	if !known {
		return Conflict("Unknown logical intake location")
	}
	prefix := "logistics.outbound.staging"
	if command.Category == "raw" {
		prefix = "logistics.inbound.dock"
	}
	for _, entry := range command.Units {
		var exists bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE id=$1)", entry.ID).Scan(&exists); err != nil {
			return err
		}
		if exists {
			return Conflict("Handling-unit identity already exists; replay the original intake")
		}
		position, err := freeHandlingPosition(ctx, tx, run, prefix, command.Category)
		if err != nil {
			return err
		}
		unit, err := object(ctx, tx, "INSERT INTO transport_handling_units(id,barcode,run_id,epoch,sku,quantity,category,logical_location,state,position,command_id) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'available',$9,$10) RETURNING *", entry.ID, "HU-"+strings.ToUpper(strings.ReplaceAll(entry.ID, "-", "")), run["id"], run["epoch"], command.SKU, entry.Quantity, command.Category, location, position, job["id"])
		if err != nil {
			return err
		}
		if err = handlingMovement(ctx, tx, run, job, unit, "receive", nil, position, command.CorrelationID, nil); err != nil {
			return err
		}
	}
	return nil
}

func reserveHandling(ctx context.Context, tx pgx.Tx, run, transfer row, command TransportCommand) error {
	if len(command.UnitIDs) == 0 {
		return Conflict("Explicit whole-unit identities required; legacy quantity-only transfers cannot allocate stock")
	}
	units := []row{}
	seen := map[string]bool{}
	total := 0
	category := ""
	for _, identity := range command.UnitIDs {
		parsed, err := uuid.Parse(identity)
		if err != nil {
			return Conflict("Invalid whole-unit identity")
		}
		identity = parsed.String()
		if seen[identity] {
			return Conflict("Duplicate whole-unit identity")
		}
		seen[identity] = true
		unit, err := object(ctx, tx, "SELECT * FROM transport_handling_units WHERE id=$1 AND run_id=$2 AND epoch=$3", identity, run["id"], run["epoch"])
		if errors.Is(err, pgx.ErrNoRows) {
			return Conflict("Whole unit is unavailable; await a confirmed custody handoff")
		}
		if err != nil {
			return err
		}
		if unit["state"] != "available" || unit["logical_location"] != transfer["origin"] || unit["sku"] != command.SKU {
			return Conflict("Whole unit is allocated, at another origin, or has incompatible contents")
		}
		if category != "" && category != unit["category"] {
			return Conflict("One truck transfer requires a compatible whole-unit category")
		}
		category = unit["category"].(string)
		total += int(num(unit, "quantity"))
		units = append(units, unit)
	}
	if total != command.Quantity {
		return Conflict("Transport quantity must exactly equal the selected whole units; no splitting or overfulfilment")
	}
	for _, unit := range units {
		if _, err := tx.Exec(ctx, "UPDATE transport_handling_units SET state='reserved',transfer_id=$1,version=version+1 WHERE id=$2", transfer["id"], unit["id"]); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, "INSERT INTO transport_unit_allocations(transfer_id,unit_id) VALUES($1,$2)", transfer["id"], unit["id"]); err != nil {
			return err
		}
	}
	return nil
}

func allocatedHandling(ctx context.Context, tx pgx.Tx, transfer row) ([]row, error) {
	units, err := objects(ctx, tx, "SELECT * FROM transport_handling_units WHERE transfer_id=$1 ORDER BY id", transfer["id"])
	if err != nil {
		return nil, err
	}
	total := 0
	for _, unit := range units {
		total += int(num(unit, "quantity"))
	}
	if total != int(num(transfer, "quantity")) {
		return nil, Conflict("Legacy transport has no reconciled whole-unit manifest")
	}
	return units, nil
}

func loadHandling(ctx context.Context, tx pgx.Tx, run, job, transfer row) error {
	units, err := allocatedHandling(ctx, tx, transfer)
	if err != nil {
		return err
	}
	index := 0
	for i, vehicle := range transportConfig(run).Vehicles {
		if vehicle.Code == transfer["vehicle"] {
			index = i + 1
		}
	}
	if index < 1 || index > 4 {
		return Conflict("Assigned vehicle has no fixed physical truck positions")
	}
	for _, unit := range units {
		prefix := "logistics.outbound"
		if unit["category"] == "raw" {
			prefix = "logistics.inbound"
		}
		position, err := freeHandlingPosition(ctx, tx, run, fmt.Sprintf("%s.truck%02d.slot", prefix, index), unit["category"].(string))
		if err != nil {
			return err
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET position=$1 WHERE id=$2", position, unit["id"]); err != nil {
			return err
		}
		if err = handlingMovement(ctx, tx, run, job, unit, "load", unit["position"], position, transfer["correlation_id"].(string), transfer["id"]); err != nil {
			return err
		}
	}
	return nil
}

func departHandling(ctx context.Context, tx pgx.Tx, run, transfer row) error {
	units, err := allocatedHandling(ctx, tx, transfer)
	if err != nil {
		return err
	}
	for _, unit := range units {
		destination := "external." + strings.ToLower(transfer["destination"].(string))
		if transfer["destination"] != "CUSTOMER" {
			prefix := "logistics.outbound.staging"
			if unit["category"] == "raw" {
				prefix = "logistics.inbound.dock"
			}
			destination, err = freeHandlingPosition(ctx, tx, run, prefix, unit["category"].(string))
			if err != nil {
				return err
			}
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='in_transit',origin=position,position=NULL,destination=$1,handoff_id=$2,version=version+1 WHERE id=$3", destination, transfer["id"], unit["id"]); err != nil {
			return err
		}
	}
	return nil
}

func unloadHandling(ctx context.Context, tx pgx.Tx, run, job, transfer row) error {
	units, err := allocatedHandling(ctx, tx, transfer)
	if err != nil {
		return err
	}
	for _, unit := range units {
		position := unit["destination"].(string)
		if strings.HasPrefix(position, "external.") {
			continue
		}
		var occupied bool
		if err = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM transport_handling_units WHERE run_id=$1 AND epoch=$2 AND id<>$3 AND (position=$4 OR (state='in_transit' AND destination=$4)))", run["id"], run["epoch"], unit["id"], position).Scan(&occupied); err != nil {
			return err
		}
		if occupied {
			return Conflict("Unloading position capacity unavailable; unit remains in transit")
		}
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='reserved',position=$1,logical_location=$2,origin=NULL,destination=NULL,handoff_id=NULL WHERE id=$3", position, transfer["destination"], unit["id"]); err != nil {
			return err
		}
		if err = handlingMovement(ctx, tx, run, job, unit, "unload", unit["origin"], position, transfer["correlation_id"].(string), transfer["id"]); err != nil {
			return err
		}
	}
	return nil
}

func receiveHandling(ctx context.Context, tx pgx.Tx, transfer row) error {
	if _, err := allocatedHandling(ctx, tx, transfer); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, "UPDATE transport_handling_units SET state=CASE WHEN position IS NULL THEN 'dispatched' ELSE 'available' END,transfer_id=NULL,version=version+1 WHERE transfer_id=$1", transfer["id"]); err != nil {
		return err
	}
	_, err := tx.Exec(ctx, "UPDATE transport_unit_allocations SET active=false WHERE transfer_id=$1", transfer["id"])
	return err
}
