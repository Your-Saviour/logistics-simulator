package main

import (
	"errors"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"log"
	"net/http"
	"strings"
)

func respondError(c *gin.Context, e error) {
	var conflict Conflict
	if errors.As(e, &conflict) {
		c.AbortWithStatusJSON(409, gin.H{"detail": e.Error()})
		return
	}
	log.Printf("database operation failed request=%s: %v", c.GetString("request_id"), e)
	c.AbortWithStatusJSON(503, gin.H{"detail": "Database unavailable; retry with the same idempotency key"})
}
func api(s *Store, broker func() bool) http.Handler {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())
	r.Use(func(c *gin.Context) {
		a := &Audit{Actor: "anonymous", Role: "anonymous", RequestID: uuid.NewString(), Action: c.Request.Method + " " + c.Request.URL.Path, Key: c.GetHeader("Idempotency-Key"), Peer: c.ClientIP()}
		c.Header("X-Request-ID", a.RequestID)
		c.Set("request_id", a.RequestID)
		c.Set("audit", a)
		command := c.Request.Method == "POST" && strings.HasPrefix(c.Request.URL.Path, "/api/")
		if command {
			run, e := s.Run(c.Request.Context())
			if e != nil {
				c.AbortWithStatusJSON(503, gin.H{"detail": "Database unavailable; command was not accepted"})
				return
			}
			a.RunID = run["id"].(string)
		}
		c.Next()
		if command && c.Writer.Status() >= 400 {
			if e := s.Reject(c.Request.Context(), a, c.Writer.Status()); e != nil {
				log.Printf("Rejected command audit unavailable request_id=%s status=%d: %v", a.RequestID, c.Writer.Status(), e)
			}
		}
	})
	permit := func(scope string) gin.HandlerFunc {
		return func(c *gin.Context) {
			u, p, ok := c.Request.BasicAuth()
			principal, found := s.C.identify(u, p)
			if !ok || !found {
				c.AbortWithStatusJSON(401, gin.H{"detail": "Invalid username or password"})
				return
			}
			a := c.MustGet("audit").(*Audit)
			a.Actor = principal.Username
			a.Role = principal.Role
			if !principal.Can(scope) {
				c.AbortWithStatusJSON(403, gin.H{"detail": "This identity cannot perform the requested action"})
				return
			}
			c.Set("principal", principal)
			c.Next()
		}
	}
	r.GET("/api/health/live", func(c *gin.Context) { c.JSON(200, gin.H{"application": "logistics", "alive": true}) })
	r.GET("/api/health/ready", func(c *gin.Context) {
		status, e := s.Status(c.Request.Context())
		if e != nil {
			c.JSON(503, gin.H{"application": "logistics", "ready": false})
			return
		}
		b := broker()
		roles := map[string]bool{}
		for _, h := range status["heartbeats"].([]row) {
			if h["healthy"] == true {
				roles[h["role"].(string)] = true
			}
		}
		run := status["run"].(map[string]any)
		ready := b && roles["worker"] && roles["controller"] && run["state"] != "failed" && run["state"] != "stalled"
		code := 200
		if !ready {
			code = 503
		}
		c.JSON(code, gin.H{"application": "logistics", "database": true, "broker": b, "ready": ready})
	})
	r.GET("/api/status", permit("status:read"), func(c *gin.Context) {
		v, e := s.Status(c.Request.Context())
		if e != nil {
			respondError(c, e)
			return
		}
		v["identity"] = c.MustGet("principal")
		v["application"] = "logistics"
		v["providers"] = s.C.Providers
		v["quantum"] = s.C.Quantum
		run := v["run"].(map[string]any)
		scenario := scenarioFrom(run)
		v["simulation_time"] = scenario.instant(num(run, "granted")).Format("2006-01-02T15:04:05.999999999Z07:00")
		c.JSON(200, v)
	})
	r.POST("/api/jobs", permit("jobs:write"), func(c *gin.Context) {
		key := c.GetHeader("Idempotency-Key")
		if key == "" || len(key) > 128 {
			c.JSON(422, gin.H{"detail": "Idempotency-Key must contain 1..128 characters"})
			return
		}
		if strings.HasPrefix(key, "synthetic:") || strings.HasPrefix(key, "boundary:") || strings.HasPrefix(key, "synthetic-sample:") {
			c.JSON(409, gin.H{"detail": "This idempotency key namespace is reserved for internal providers"})
			return
		}
		command, e := parseJob(c.Request.Body)
		if e != nil {
			c.JSON(422, gin.H{"detail": e.Error()})
			return
		}
		job, e := s.Schedule(c.Request.Context(), key, command, c.MustGet("audit").(*Audit), nil)
		if e != nil {
			respondError(c, e)
			return
		}
		c.JSON(200, job)
	})
	r.POST("/api/control/:action", permit("runs:control"), func(c *gin.Context) {
		command := struct {
			Speed        int       `json:"speed"`
			ConfirmRunID *string   `json:"confirm_run_id"`
			Scenario     *Scenario `json:"scenario"`
		}{Speed: 1}
		if e := strictJSON(c.Request.Body, &command); e != nil {
			c.JSON(422, gin.H{"detail": e.Error()})
			return
		}
		confirmation := ""
		if command.ConfirmRunID != nil {
			confirmation = *command.ConfirmRunID
			if _, e := uuid.Parse(confirmation); e != nil {
				c.JSON(422, gin.H{"detail": "confirm_run_id must be a UUID"})
				return
			}
		}
		if command.Scenario != nil {
			if e := command.Scenario.Validate(); e != nil {
				c.JSON(422, gin.H{"detail": e.Error()})
				return
			}
		}
		value, e := s.Control(c.Request.Context(), c.Param("action"), command.Speed, confirmation, c.MustGet("audit").(*Audit), command.Scenario)
		if e != nil {
			respondError(c, e)
			return
		}
		c.JSON(200, value)
	})
	r.GET("/api/sources", permit("status:read"), func(c *gin.Context) { c.JSON(200, []row{}) })
	r.GET("/api/audit", permit("audit:read"), func(c *gin.Context) {
		v, e := s.AuditEvents(c.Request.Context())
		if e != nil {
			respondError(c, e)
			return
		}
		c.JSON(200, v)
	})
	return r
}
