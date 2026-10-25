package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	amqp "github.com/rabbitmq/amqp091-go"
	"net"
	"time"
)

const jobQueue = "sample.jobs.v1"
const deadQueue = "sample.jobs.dead.v1"

type Broker struct {
	Connection *amqp.Connection
	Channel    *amqp.Channel
	returns    <-chan amqp.Return
}

func openBroker(url string) (*Broker, error) {
	connection, e := amqp.DialConfig(url, amqp.Config{Heartbeat: 30 * time.Second, Dial: func(network, address string) (net.Conn, error) {
		return net.DialTimeout(network, address, 3*time.Second)
	}})
	if e != nil {
		return nil, e
	}
	ch, e := connection.Channel()
	if e != nil {
		connection.Close()
		return nil, e
	}
	b := &Broker{Connection: connection, Channel: ch}
	fail := func(e error) (*Broker, error) { b.Close(); return nil, e }
	if e = ch.ExchangeDeclare("sample.dead.v1", "direct", true, false, false, false, nil); e != nil {
		return fail(e)
	}
	if _, e = ch.QueueDeclare(deadQueue, true, false, false, false, nil); e != nil {
		return fail(e)
	}
	if e = ch.QueueBind(deadQueue, "dead", "sample.dead.v1", false, nil); e != nil {
		return fail(e)
	}
	if _, e = ch.QueueDeclare(jobQueue, true, false, false, false, amqp.Table{"x-dead-letter-exchange": "sample.dead.v1", "x-dead-letter-routing-key": "dead"}); e != nil {
		return fail(e)
	}
	if e = ch.Qos(1, 0, false); e != nil {
		return fail(e)
	}
	if e = ch.Confirm(false); e != nil {
		return fail(e)
	}
	b.returns = ch.NotifyReturn(make(chan amqp.Return, 1))
	return b, nil
}
func (b *Broker) Close() {
	if b.Channel != nil {
		_ = b.Channel.Close()
	}
	if b.Connection != nil {
		_ = b.Connection.Close()
	}
}
func (b *Broker) Publish(ctx context.Context, routing, id string, body []byte) error {
	confirmation, e := b.Channel.PublishWithDeferredConfirmWithContext(ctx, "", routing, true, false, amqp.Publishing{DeliveryMode: 2, ContentType: "application/json", MessageId: id, Body: body})
	if e != nil {
		return e
	}
	if confirmation == nil {
		return errors.New("publisher confirms disabled")
	}
	ack, e := confirmation.WaitContext(ctx)
	if e != nil {
		return e
	}
	select {
	case returned := <-b.returns:
		return fmt.Errorf("mandatory routing failed: %d %s", returned.ReplyCode, returned.ReplyText)
	default:
	}
	if !ack {
		return errors.New("broker negatively acknowledged publication")
	}
	return nil
}
func (b *Broker) Relay(ctx context.Context, s *Store) error {
	rows, e := s.Dispatchable(ctx)
	if e != nil {
		return e
	}
	for _, r := range rows {
		raw, _ := json.Marshal(row{"job_id": r["job_id"]})
		timeout, cancel := context.WithTimeout(ctx, 5*time.Second)
		e = b.Publish(timeout, jobQueue, r["id"].(string), raw)
		cancel()
		if e != nil {
			return e
		}
		if e = s.Published(ctx, r["id"].(string)); e != nil {
			return e
		}
	}
	return nil
}
func processDelivery(ctx context.Context, s *Store, d amqp.Delivery) error {
	var message struct {
		JobID string `json:"job_id"`
	}
	if json.Unmarshal(d.Body, &message) != nil {
		return d.Nack(false, false)
	}
	if _, e := uuid.Parse(message.JobID); e != nil {
		return d.Nack(false, false)
	}
	result, e := s.Execute(ctx, message.JobID)
	if e != nil {
		var business Conflict
		if !errors.As(e, &business) {
			return e
		}
		result, e = s.Fail(ctx, message.JobID, e.Error())
		if e != nil {
			return e
		}
	}
	if result == "dead" {
		return d.Nack(false, false)
	}
	return d.Ack(false)
}
func worker(ctx context.Context, s *Store) error {
	for ctx.Err() == nil {
		b, e := openBroker(s.C.AMQPURL)
		if e != nil {
			logDependency("worker broker", e)
			if !pause(ctx, 2*time.Second) {
				break
			}
			continue
		}
		for ctx.Err() == nil {
			if e = b.Relay(ctx, s); e != nil {
				break
			}
			var d amqp.Delivery
			var ok bool
			d, ok, e = b.Channel.Get(jobQueue, false)
			if e != nil {
				break
			}
			if ok {
				if e = processDelivery(ctx, s, d); e != nil {
					break
				}
			}
			if !ok {
				if e = s.relayFleet(ctx); e != nil {
					break
				}
			}
			if e = s.Heartbeat(ctx, "worker", ""); e != nil {
				break
			}
			if !ok && !pause(ctx, 150*time.Millisecond) {
				break
			}
		}
		b.Close()
		if e != nil {
			logDependency("worker durable work retained", e)
		}
		if !pause(ctx, 2*time.Second) {
			break
		}
	}
	return nil
}
