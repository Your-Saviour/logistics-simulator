package main

import (
	"context"
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestWholeTransportUnitsKeepBarcodesAndRejectPartialOrDoubleAllocation(t *testing.T) {
	s := testStore(t)
	four, six := uuid.NewString(), uuid.NewString()
	intake := transportCommand(t, s, "intake", row{"sku": "PRODUCT", "category": "finished", "quantity": 10, "correlation_id": uuid.NewString(), "units": []row{{"id": four, "quantity": 4}, {"id": six, "quantity": 6}}})
	if intake["status"] != "completed" {
		t.Fatalf("intake: %v", intake)
	}
	unit := func(id string) row {
		for _, value := range transportSnapshot(t, s)["handling"].(map[string]any)["units"].([]any) {
			u := value.(map[string]any)
			if u["id"] == id {
				return u
			}
		}
		t.Fatalf("unit %s absent", id)
		return nil
	}
	if unit(four)["barcode"] != "HU-"+strings.ToUpper(strings.ReplaceAll(four, "-", "")) || !strings.HasPrefix(unit(four)["position"].(string), "logistics.outbound.staging") {
		t.Fatalf("missing recorded identity or placement: %v", unit(four))
	}
	request := func(quantity int, ids []string) row {
		return transportCommand(t, s, "request", row{"route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": quantity, "correlation_id": uuid.NewString(), "unit_ids": ids})
	}
	if command := request(5, []string{four}); command["status"] != "rejected" || !strings.Contains(command["reason"].(string), "whole") {
		t.Fatalf("partial unit accepted: %v", command)
	}
	first := request(4, []string{four})
	if first["status"] != "completed" {
		t.Fatal(first)
	}
	if second := request(4, []string{four}); second["status"] != "rejected" {
		t.Fatalf("allocated unit twice: %v", second)
	}
	transfer := first["id"].(string)
	transportCommand(t, s, "assign", row{"reference": transfer, "vehicle": "TRUCK-1"})
	loaded := transportCommand(t, s, "load", row{"reference": transfer})
	if loaded["status"] != "completed" || !strings.HasPrefix(unit(four)["position"].(string), "logistics.outbound.truck01.slot") || unit(six)["state"] != "available" {
		t.Fatalf("load changed wrong unit or fabricated a truck position: %v", unit(four))
	}
	before := transportSnapshot(t, s)["handling"].(map[string]any)["movements"].([]any)
	duplicate := transportCommand(t, s, "load", row{"reference": transfer})
	if duplicate["status"] != "rejected" || len(transportSnapshot(t, s)["handling"].(map[string]any)["movements"].([]any)) != len(before) {
		t.Fatal("duplicate loading changed physical history")
	}
	departure := transportCommand(t, s, "depart", row{"reference": transfer})
	if departure["status"] != "completed" || unit(four)["position"] != nil || unit(four)["state"] != "in_transit" || unit(four)["origin"] == nil || unit(four)["destination"] == nil {
		t.Fatalf("departure invented a confirmed position: %v", unit(four))
	}
	projection, err := s.Projection(context.Background())
	if err != nil || projection["snapshot"].(row)["handling"] == nil {
		t.Fatalf("unit projection missing: %v", err)
	}
}

func TestFullTruckLoadRollsBackEveryWholeUnitAndMovement(t *testing.T) {
	s := testStore(t)
	ids := []string{}
	manifest := []row{}
	for i := 0; i < 9; i++ {
		id := uuid.NewString()
		ids = append(ids, id)
		manifest = append(manifest, row{"id": id, "quantity": 1})
	}
	intake := transportCommand(t, s, "intake", row{"sku": "PRODUCT", "category": "finished", "quantity": 9, "correlation_id": uuid.NewString(), "units": manifest})
	if intake["status"] != "completed" {
		t.Fatal(intake)
	}
	request := transportCommand(t, s, "request", row{"route": "WAREHOUSE-DISPATCH", "sku": "PRODUCT", "quantity": 9, "correlation_id": uuid.NewString(), "unit_ids": ids})
	if request["status"] != "completed" {
		t.Fatal(request)
	}
	transfer := request["id"].(string)
	transportCommand(t, s, "assign", row{"reference": transfer, "vehicle": "TRUCK-1"})
	load := transportCommand(t, s, "load", row{"reference": transfer})
	if load["status"] != "rejected" || !strings.Contains(load["reason"].(string), "slot") {
		t.Fatalf("eight-position truck accepted nine units: %v", load)
	}
	handling := transportSnapshot(t, s)["handling"].(map[string]any)
	if len(handling["movements"].([]any)) != 9 {
		t.Fatal("rejected loading retained partial physical history")
	}
	for _, item := range handling["units"].([]any) {
		unit := item.(map[string]any)
		if !strings.HasPrefix(unit["position"].(string), "logistics.outbound.staging") || unit["state"] != "reserved" {
			t.Fatalf("rejected loading moved a unit: %v", unit)
		}
	}
}
