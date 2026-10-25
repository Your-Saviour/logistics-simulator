package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type fleetWait struct{}

func (fleetWait) Error() string { return "Waiting for coordinated fleet physical proof" }
func fleetEnabled() bool        { return os.Getenv("FLEET_MODE") == "coordinated" }
func fleetConfig() error {
	mode := env("FLEET_MODE", "disabled")
	if mode != "disabled" && mode != "coordinated" {
		return errors.New("invalid FLEET_MODE")
	}
	if mode == "disabled" {
		return nil
	}
	if offset, err := strconv.ParseFloat(env("FLEET_TIME_OFFSET", "0"), 64); err != nil || !finite(offset) || offset < 0 {
		return errors.New("invalid FLEET_TIME_OFFSET")
	}
	for _, key := range []string{"FLEET_RUN_ID", "FLEET_EPOCH"} {
		if _, err := uuid.Parse(os.Getenv(key)); err != nil {
			return fmt.Errorf("invalid %s", key)
		}
	}
	if os.Getenv("FLEET_TOKEN") == "" || !(strings.HasPrefix(os.Getenv("FLEET_URL"), "http://") || strings.HasPrefix(os.Getenv("FLEET_URL"), "https://")) {
		return errors.New("coordinated fleet requires URL and token")
	}
	return nil
}
func fleetOffset() float64 {
	value, _ := strconv.ParseFloat(env("FLEET_TIME_OFFSET", "0"), 64)
	return value
}
func fleetMetadata() row {
	return row{"mode": env("FLEET_MODE", "disabled"), "run_id": os.Getenv("FLEET_RUN_ID"), "epoch": os.Getenv("FLEET_EPOCH")}
}
func fleetID(unit, handoff string, generation int) string {
	return uuid.NewSHA1(uuid.MustParse(unit), []byte(fmt.Sprintf("fleet:%s:%d", handoff, generation))).String()
}
func fleetFact(request, body row, kind string, grant float64) bool {
	if _, ok := body["effective_time"].(float64); !ok {
		return false
	}
	if body["job_id"] != request["id"] || body["kind"] != kind || num(body, "route_version") != 1 || body["robot_id"] == nil || body["effective_time"] == nil || !finite(num(body, "effective_time")) || num(body, "effective_time") < 0 || num(body, "effective_time") > grant {
		return false
	}
	for _, field := range []string{"unit_id", "run_id", "epoch", "source_run_id", "source_epoch", "origin", "destination", "custody_generation"} {
		if fmt.Sprint(body[field]) != fmt.Sprint(request[field]) {
			return false
		}
	}
	return true
}
func fleetRequest(r row, unit, handoff, origin, destination, producer string, generation int) row {
	return row{"version": 1, "id": fleetID(unit, handoff, generation), "run_id": os.Getenv("FLEET_RUN_ID"), "epoch": os.Getenv("FLEET_EPOCH"), "producer": producer, "source_run_id": r["id"], "source_epoch": r["epoch"], "unit_id": unit, "origin": origin, "destination": destination, "custody_generation": generation, "effective_time": r["granted"]}
}

// The intent commits even when the business command is deferred. No network I/O
// occurs under the native run lock or transaction.
func fleetGate(ctx context.Context, tx pgx.Tx, r, request row, kind string, watch bool) error {
	if !fleetEnabled() {
		return nil
	}
	raw, _ := json.Marshal(request)
	_, err := tx.Exec(ctx, "INSERT INTO transport_fleet_jobs(id,run_id,epoch,request,admitted) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING", request["id"], r["id"], r["epoch"], raw, watch)
	if err != nil {
		return err
	}
	old, err := object(ctx, tx, "SELECT * FROM transport_fleet_jobs WHERE id=$1", request["id"])
	if err != nil {
		return err
	}
	frozen := old["request"].(map[string]any)
	if old["run_id"] != r["id"] || old["epoch"] != r["epoch"] {
		return Conflict("Fleet native scope changed")
	}
	for _, field := range []string{"id", "run_id", "epoch", "producer", "unit_id", "source_run_id", "source_epoch", "origin", "destination", "custody_generation"} {
		if fmt.Sprint(frozen[field]) != fmt.Sprint(request[field]) {
			return Conflict("Fleet immutable request changed: " + field)
		}
	}
	snapshot, _ := old["snapshot"].(map[string]any)
	events, _ := snapshot["events"].([]any)
	for _, event := range events {
		e, ok := event.(map[string]any)
		if !ok {
			continue
		}
		body, ok := e["body"].(map[string]any)
		if ok && e["job_id"] == request["id"] && e["kind"] == kind && fleetFact(frozen, body, kind, num(r, "granted")+fleetOffset()) {
			return nil
		}
	}
	return fleetWait{}
}
func fleetProof(ctx context.Context, tx pgx.Tx, r, request row, kind string) error {
	if !fleetEnabled() {
		return nil
	}
	endpoint := request["origin"]
	if kind == "receipt" {
		endpoint = request["destination"]
	}
	proof := row{"job_id": request["id"], "unit_id": request["unit_id"], "run_id": request["run_id"], "epoch": request["epoch"], "source_run_id": r["id"], "source_epoch": r["epoch"], "custody_generation": request["custody_generation"], "endpoint": endpoint, "effective_time": r["granted"]}
	raw, _ := json.Marshal(proof)
	_, err := tx.Exec(ctx, "UPDATE transport_fleet_jobs SET "+kind+"=COALESCE("+kind+",$1::jsonb) WHERE id=$2 AND run_id=$3 AND epoch=$4", raw, request["id"], r["id"], r["epoch"])
	return err
}
func fleetDefer(ctx context.Context, tx pgx.Tx, r, j row, quantum float64) error {
	_, err := tx.Exec(ctx, "UPDATE jobs SET status='pending',due_at=$1,error=$2 WHERE id=$3", num(r, "granted")+quantum, fleetWait{}.Error(), j["id"])
	if err == nil {
		_, err = tx.Exec(ctx, "UPDATE transport_commands SET reason=$1 WHERE id=$2", fleetWait{}.Error(), j["id"])
	}
	if err == nil {
		_, err = tx.Exec(ctx, "UPDATE outbox SET retry_after=clock_timestamp() WHERE job_id=$1", j["id"])
	}
	return err
}
func fleetHTTP(ctx context.Context, path string, body any) (row, error) {
	method := "GET"
	var raw []byte
	if body != nil {
		method = "POST"
		raw, _ = json.Marshal(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(os.Getenv("FLEET_URL"), "/")+path, bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+os.Getenv("FLEET_TOKEN"))
	req.Header.Set("Content-Type", "application/json")
	res, err := (&http.Client{Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, fmt.Errorf("fleet HTTP %d", res.StatusCode)
	}
	var value row
	err = json.NewDecoder(http.MaxBytesReader(nil, res.Body, 4<<20)).Decode(&value)
	return value, err
}
func (s *Store) relayFleet(ctx context.Context) error {
	if !fleetEnabled() {
		return nil
	}
	var jobs []row
	err := s.transaction(ctx, func(tx pgx.Tx) error {
		var e error
		jobs, e = objects(ctx, tx, "SELECT f.* FROM transport_fleet_jobs f JOIN runs r ON r.id=f.run_id AND r.epoch=f.epoch AND r.current WHERE r.state IN ('running','held') AND NOT (COALESCE(f.snapshot->>'state'='completed',false) AND (f.departure IS NULL OR f.departure_sent) AND (f.receipt IS NULL OR f.receipt_sent)) ORDER BY f.updated_at,f.id LIMIT 16")
		return e
	})
	if err != nil {
		return err
	}
	for _, j := range jobs {
		id := j["id"].(string)
		path := "/v1/jobs/" + id
		if j["admitted"] != true {
			_, err = fleetHTTP(ctx, "/v1/jobs", j["request"])
			if err == nil {
				_, err = s.DB.Exec(ctx, "UPDATE transport_fleet_jobs SET admitted=true WHERE id=$1 AND run_id=$2 AND epoch=$3", id, j["run_id"], j["epoch"])
			}
		}
		if err == nil {
			for _, kind := range []string{"departure", "receipt"} {
				if j[kind] != nil && j[kind+"_sent"] != true {
					_, err = fleetHTTP(ctx, path+"/proofs/"+kind, j[kind])
					if err != nil {
						break
					}
					_, err = s.DB.Exec(ctx, "UPDATE transport_fleet_jobs SET "+kind+"_sent=true WHERE id=$1 AND run_id=$2 AND epoch=$3", id, j["run_id"], j["epoch"])
				}
			}
		}
		if err == nil {
			var snapshot row
			snapshot, err = fleetHTTP(ctx, path, nil)
			if err == nil {
				scope, _ := snapshot["fleet_scope"].(map[string]any)
				if scope["run_id"] != j["run_id"] || scope["epoch"] != j["epoch"] || num(scope, "offset") != fleetOffset() {
					_, writeErr := s.DB.Exec(ctx, "UPDATE transport_fleet_jobs SET error=$1,updated_at=clock_timestamp() WHERE id=$2", "fleet scope mapping mismatch", id)
					if writeErr != nil {
						return writeErr
					}
					return nil
				}
				remote, _ := snapshot["request"].(map[string]any)
				expected := j["request"].(map[string]any)
				valid := true
				for k, v := range expected {
					if k != "effective_time" && fmt.Sprint(v) != fmt.Sprint(remote[k]) {
						valid = false
					}
				}
				if !valid {
					err = errors.New("fleet snapshot scope mismatch")
				} else {
					raw, _ := json.Marshal(snapshot)
					_, err = s.DB.Exec(ctx, "UPDATE transport_fleet_jobs SET snapshot=$1,error=NULL,updated_at=clock_timestamp() WHERE id=$2 AND run_id=$3 AND epoch=$4", raw, id, j["run_id"], j["epoch"])
				}
			}
		}
		if err != nil {
			_, writeErr := s.DB.Exec(ctx, "UPDATE transport_fleet_jobs SET error=$1,updated_at=clock_timestamp() WHERE id=$2", err.Error(), id)
			if writeErr != nil {
				return writeErr
			}
			return nil
		}
	}
	return nil
}

// A local command owns a durable movement identity. Destination capacity remains
// reserved while the unit is nonallocatable and has no confirmed placement.
func fleetLocalMove(ctx context.Context, tx pgx.Tx, r, j, unit row, destination, action, correlation string, transfer any) error {
	request := fleetRequest(r, unit["id"].(string), j["id"].(string), "", destination, "logistics", int(num(unit, "custody_generation")))
	old, err := object(ctx, tx, "SELECT * FROM transport_fleet_jobs WHERE id=$1 AND run_id=$2 AND epoch=$3", request["id"], r["id"], r["epoch"])
	if err == nil {
		request = old["request"].(map[string]any)
		if old["receipt"] != nil {
			return nil
		}
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return err
	} else {
		if unit["position"] == nil {
			request["origin"] = unit["origin"]
		} else {
			request["origin"] = unit["position"]
		}
	}
	destination = request["destination"].(string)
	if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET destination=$1 WHERE id=$2", destination, unit["id"]); err != nil {
		return err
	}
	if err = fleetGate(ctx, tx, r, request, "pickup_ready", false); err != nil {
		return err
	}
	old, err = object(ctx, tx, "SELECT * FROM transport_fleet_jobs WHERE id=$1", request["id"])
	if err != nil {
		return err
	}
	if old["departure"] == nil {
		if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='in_transit',origin=$1,position=NULL,destination=$2,handoff_id=$4 WHERE id=$3", request["origin"], destination, unit["id"], j["id"]); err != nil {
			return err
		}
		if err = fleetProof(ctx, tx, r, request, "departure"); err != nil {
			return err
		}
	}
	if err = fleetGate(ctx, tx, r, request, "arrival", false); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "UPDATE transport_handling_units SET state='reserved',position=$1,origin=NULL,destination=NULL,handoff_id=NULL WHERE id=$2", destination, unit["id"]); err != nil {
		return err
	}
	if err = handlingMovement(ctx, tx, r, j, unit, action, request["origin"], destination, correlation, transfer); err != nil {
		return err
	}
	return fleetProof(ctx, tx, r, request, "receipt")
}
