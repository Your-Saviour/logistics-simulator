# Logistics V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Complete SIMU-4 with finite fleet transport and separate destination receipt.

**Architecture:** Extend the existing Go SQL transaction and job runtime. Domain
commands share grants, RabbitMQ delivery and boundary output barriers. Svelte
provides the employee transport workflow.

**Tech Stack:** Go/Gin, PostgreSQL, RabbitMQ, Svelte/TypeScript, private HELICS adapter.

**Spec:** docs/superpowers/specs/2026-10-24-simu-4-logistics-v1-design.md

## Global Constraints

- Build and test services only inside Docker through scripts/docker_guard.py.
- Keep the default 20 GiB disk reserve and share the guard lock across worktrees.
- Preserve published run_id, epoch and due_at fields and migration checksums.
- Do not modify other worktrees, prune volumes or perform a live cutover.

## Review Focus

- Concurrent assignments must reserve a vehicle exactly once.
- Failed arrival and unloading must retain custody and reservations.
- Duplicate arrival jobs and peer events must not repeat physical effects.
- A delayed ACK must not turn ETA or unloading into destination receipt.
- Old browser commands and worker deliveries must be fenced after reset.

### Task 1: Domain commands and durable fleet

**Files:** backend transport.go, transport_store.go, transport_test.go and migration
006 under apps/logistics; modify domain.go, api.go and store.go.

**Interfaces:** parseTransport(io.Reader) (TransportCommand,error),
Store.ScheduleTransport(ctx,key,command,audit), Store.Transport(ctx), and
executeTransport(ctx,tx,run,job) used by Store.Execute.

- [ ] Write real SQL/API regressions for complete lifecycle, capacity, competing
  assignment, early/duplicate arrival, grant barrier, stale epoch and audit rollback.
- [ ] Run make stack-unit APP=logistics; observe missing endpoint/domain failures.
- [ ] Add validated scenario configuration, additive schema and domain transactions.
- [ ] Run the full Go suite and vet; require all passing.
- [ ] Commit feat: implement durable fleet transport (SIMU-4).

### Task 2: Providers and HELICS domain handoffs

**Files:** transport_provider.go, transport_boundary.go, controller.go, adapter.go,
contracts/v1/logistics-boundary.schema.json, adapter envelope validation.

**Interfaces:** SeedTransport(ctx) error; IngestTransport(ctx,raw,source);
versioned requests, receipts and facts use existing adapter v1 operations.

- [ ] Add deterministic provider and peer identity/deduplication regressions first.
- [ ] Observe failures in the containerized Go suite.
- [ ] Implement demand, provider-owned workflow and receipt automation; domain
  inputs/outputs retain the existing native journals and grant barriers.
- [ ] Verify the full Go suite and an actual native HELICS peer exchanging domain events.
- [ ] Commit feat: connect transport providers and boundary facts (SIMU-4).

### Task 3: Employee website

**Files:** frontend/src/Transport.svelte, App.svelte, client.ts and tests/ui.mjs.

**Interfaces:** GET /api/transport and POST /api/transport/commands from Task 1.

- [ ] Add browser lifecycle checks for fleet/route display, assignments, valid
  actions and separate ETA/arrival/receipt; retain uncertain command retry coverage.
- [ ] Observe missing transport UI failure in Docker.
- [ ] Implement the queue, fleet, transfer form and state actions using existing styling.
- [ ] Run Svelte type checks, production build and desktop/mobile browser acceptance.
- [ ] Commit feat: add employee fleet workspace (SIMU-4).

### Task 4: Deployment and recovery acceptance

**Files:** apps/logistics/compose.v1.yaml, logistics.env.example, scripts/logistics*
acceptance, deployment and connected checks; docs/logistics-v1.md and acceptance.

**Interfaces:** External DATABASE_URL, AMQP_URL, API_UPSTREAM and adapter settings;
same binary with ROLE=api|worker|controller, independent workers.

- [ ] Add end-to-end lifecycle/restart/duplicate-arrival assertions.
- [ ] Run them to establish the missing deployment/acceptance behavior.
- [ ] Add persistent packaging and guarded disposable checks without volume deletion.
- [ ] Run make stack-unit APP=logistics, make stack-check APP=logistics, connected
  and deployment checks. Record exact local results and hosted limits.
- [ ] Review the whole branch, fix material findings with regressions, and commit.
