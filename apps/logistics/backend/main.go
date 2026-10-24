package main

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func pause(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
func logDependency(label string, e error) { log.Printf("%s: %v", label, e) }
func main() {
	c, e := loadConfig()
	if e != nil {
		log.Fatal(e)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	p, e := pgxpool.New(ctx, c.DatabaseURL)
	if e != nil {
		log.Fatal(e)
	}
	defer p.Close()
	s := &Store{p, c}
	for {
		if e = s.Migrate(ctx); e == nil {
			break
		}
		var conflict Conflict
		if errors.As(e, &conflict) {
			log.Fatal(e)
		}
		logDependency("database unavailable at startup", e)
		if !pause(ctx, 2*time.Second) {
			return
		}
	}
	switch c.Role {
	case "api":
		server := &http.Server{Addr: ":8000", Handler: api(s, func() bool {
			b, e := openBroker(c.AMQPURL)
			if e != nil {
				return false
			}
			b.Close()
			return true
		}), ReadHeaderTimeout: 5 * time.Second}
		go func() {
			<-ctx.Done()
			stop, done := context.WithTimeout(context.Background(), 5*time.Second)
			defer done()
			server.Shutdown(stop)
		}()
		e = server.ListenAndServe()
		if e != nil && !errors.Is(e, http.ErrServerClosed) {
			log.Fatal(e)
		}
	case "worker":
		e = worker(ctx, s)
	case "controller":
		e = controller(ctx, s)
	default:
		log.Fatal("ROLE must be api, worker or controller")
	}
	if e != nil {
		log.Fatal(e)
	}
}
