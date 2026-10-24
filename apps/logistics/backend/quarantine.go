package main

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func custodyQuarantineSeen(ctx context.Context, tx pgx.Tx, r row, raw []byte, event string) (bool, error) {
	_, err := object(ctx, tx, "SELECT id FROM transport_custody_quarantine WHERE run_id=$1 AND epoch=$2 AND event_id=$3 AND envelope=$4::jsonb LIMIT 1", r["id"], r["epoch"], event, raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}
func recordCustodyQuarantine(ctx context.Context, tx pgx.Tx, r row, raw []byte, event, endpoint, phase, reason string, command any) error {
	_, err := tx.Exec(ctx, "INSERT INTO transport_custody_quarantine(id,run_id,epoch,event_id,envelope,endpoint,phase,reason,command_id,simulation_time) SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10 WHERE NOT EXISTS(SELECT 1 FROM transport_custody_quarantine WHERE run_id=$2 AND epoch=$3 AND event_id=$4 AND envelope=$5::jsonb AND phase=$7 AND reason=$8)", uuid.NewString(), r["id"], r["epoch"], event, raw, endpoint, phase, reason, command, r["granted"])
	return err
}
