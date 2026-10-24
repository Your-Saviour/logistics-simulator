package main

import (
	"context"
	"github.com/google/uuid"
	"os"
	"testing"
	"time"
)

func TestBrokerMandatoryConfirmAndManualCommitDedup(t *testing.T) {
	url := os.Getenv("TEST_AMQP_URL")
	if url == "" {
		t.Skip("requires real isolated RabbitMQ")
	}
	s := testStore(t)
	ctx := context.Background()
	b, e := openBroker(url)
	if e != nil {
		t.Fatal(e)
	}
	defer b.Close()
	if e = b.Publish(ctx, "missing-"+uuid.NewString(), uuid.NewString(), []byte(`{}`)); e == nil {
		t.Fatal("unroutable mandatory publication incorrectly confirmed")
	}
	_, _ = b.Channel.QueuePurge(jobQueue, false)
	_, _ = b.Channel.QueuePurge(deadQueue, false)
	j, e := s.Schedule(ctx, "broker", JobCommand{1, 2}, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	r, _ := s.Run(ctx)
	epoch := r["epoch"].(string)
	s.Prepare(ctx, 1, epoch)
	s.Grant(ctx, 1, epoch)
	s.Heartbeat(ctx, "controller", "")
	if e = b.Relay(ctx, s); e != nil {
		t.Fatal(e)
	}
	d, ok, e := b.Channel.Get(jobQueue, false)
	if e != nil || !ok {
		t.Fatalf("durable relay missing: %v", e)
	}
	// Delivery remains unacknowledged when a database connection cannot begin a transaction.
	// A real database outage is exercised by recovery.sh.
	// Simulate crash after transaction commit and before ACK: broker must redeliver.
	if _, e = s.Execute(ctx, j["id"].(string)); e != nil {
		t.Fatal(e)
	}
	b.Close()
	b, e = openBroker(url)
	if e != nil {
		t.Fatal(e)
	}
	defer b.Close()
	for i := 0; i < 20; i++ {
		d, ok, e = b.Channel.Get(jobQueue, false)
		if ok || e != nil {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if e != nil || !ok || !d.Redelivered {
		t.Fatalf("unacked delivery not recovered: %v", e)
	}
	if e = processDelivery(ctx, s, d); e != nil {
		t.Fatal(e)
	}
	var effects int
	s.DB.QueryRow(ctx, "SELECT sum(quantity) FROM effects").Scan(&effects)
	if effects != 2 {
		t.Fatalf("redelivery duplicated effect %d", effects)
	}
	if e = b.Publish(ctx, jobQueue, uuid.NewString(), []byte(`{"job_id":"invalid"}`)); e != nil {
		t.Fatal(e)
	}
	d, ok, e = b.Channel.Get(jobQueue, false)
	if e != nil || !ok {
		t.Fatal("missing poison message")
	}
	if e = processDelivery(ctx, s, d); e != nil {
		t.Fatal(e)
	}
	found := false
	for i := 0; i < 20; i++ {
		d, ok, e = b.Channel.Get(deadQueue, false)
		if ok {
			found = true
			d.Ack(false)
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !found {
		t.Fatal("poison delivery missing from DLQ")
	}
}
