# SIMU framework migration implementation plan

> **For agentic workers:** Use superpowers:executing-plans for integration and superpowers:dispatching-parallel-agents for independent application migrations. Track evidence here and in `.superpowers/sdd/simu-framework-migration/progress.md`.

**Goal:** Complete SIMU-45–47 and prerequisite foundations SIMU-48–52, excluding SIMU-13.

**Architecture:** Keep the published HTTP and PostgreSQL contracts while replacing each application's runtime. A private per-application Python adapter owns native HELICS; each business backend owns scheduling and effects. Shared material is language-neutral contracts and fixtures.

**Tech stack:** ASP.NET Core/Vue, Spring Boot/Angular, Gin/Svelte, Laravel/Livewire, Flask/React; PostgreSQL, RabbitMQ, HELICS 3.6.1.

**Spec:** `docs/superpowers/specs/2026-10-24-simu-1-framework-migration-design.md`, approved by the user.

## Global constraints

- Exclude SIMU-13 and CyberLab/distributed packaging changes.
- Preserve persisted data, migration checksums, independent credentials and epochs; no automatic cutover/reset.
- Business execution belongs to the selected backend, not a Python proxy.
- Standalone execution must not require the adapter or another department.
- Use a feature branch in the current workspace; no changes to live deployment data.
- Parallel department tasks own disjoint application paths. Root owns shared contracts, adapter, verification and documentation.
- User constraint: service builds and tests run inside their respective Docker containers, never on the base host. Host commands only edit files or orchestrate containers.

## Review focus

- Same idempotency key with a different body must conflict even after time advances.
- A database outage before commit must leave deliveries unacknowledged and retry budgets unchanged.
- Stale adapter sessions and ambiguous native publication must fail closed.
- Concurrent reset, grant and worker replicas must fence old work and preserve atomic audit records.
- DST folds/gaps must use elapsed UTC seconds and deterministic seeded input IDs.

## Task 1: Adapter and common fixtures

Files: `src/simulator/adapter.py`, `src/simulator/adapter_protocol.py`, `tests/test_adapter.py`, `contracts/adapter/v1/*`, `docs/adapter-protocol.md`.

Interfaces: authenticated `POST /v1/commands` accepts `version`, `request_id`, `run_id`, `epoch`, `session_id`, `operation`, `payload`; `GET /v1/health` reports process/native state. See protocol document for exact operations. No database access.

- [ ] Write and run failing protocol tests for delayed/earlier grants, persisted receive ACK, idempotency/body conflicts, unsettled barriers, publication retry and native-loss fencing.
- [ ] Implement serialized adapter state and durable operation journal. Reject native rejoin after process loss for the same epoch. Publish strict schemas and fixtures.
- [ ] Run adapter unit tests and a real native reference federation using HTTP clients.

## Tasks 2–5: Independent business migrations

Files by task: `apps/storage/**` (SIMU-48), `apps/manufacturing/**` (SIMU-49), `apps/logistics/**` (SIMU-50), `apps/shipping/**` (SIMU-51).

Interfaces: preserve existing `/api/health/live`, `/api/health/ready`, `/api/status`, `/api/jobs`, `/api/control/{action}`, `/api/audit`, `/api/sources` and root migrations. Use the adapter protocol from task 1. Commands/env retain existing names.

- [ ] Write failing backend acceptance checks for role restrictions, validation, replay/conflict and durable grant-gated execution.
- [ ] Implement application-owned API, SQL transactions, worker, controller, seeded calendar/providers and adapter client in each selected backend.
- [ ] Build the selected frontend with independent login/status/jobs/control/audit flows.
- [ ] Pin dependencies/toolchains; supply application-owned Dockerfiles and isolated build/smoke configuration.
- [ ] Run backend/frontend builds, contract checks and recovery checks. Record actual evidence and limitations.

## Task 6: Flask twin (SIMU-52)

Files: `apps/twin/**`, `tests/test_twin_flask.py`.

Interfaces: preserve twin routes/read model and projection process, prohibit business mutations. Reuse Python read-model utilities at build time; no FastAPI request handling.

- [ ] Write failing Flask tests for identities, readiness, zero sources and mutation denial.
- [ ] Implement Flask authentication/errors and production Gunicorn entry point; retain application-owned React build.
- [ ] Run tests/build and isolated startup/projection recovery checks.

## Task 7: Cross-language checks and CI (SIMU-46)

Files: `scripts/check_stacks.py`, `scripts/stack_acceptance.py`, `contracts/http/v1/*`, `.github/workflows/stacks.yml`, application-local test configurations.

- [ ] Publish common positive/negative HTTP and JSON fixtures for quantities, UUIDs, time, unknown fields, conflicts and permissions.
- [ ] Execute fixtures against each actual backend and exercise durable jobs through real PostgreSQL/RabbitMQ.
- [ ] Add isolated per-app CI builds, frontend builds and dependency lock checks.
- [ ] Run mixed-language native federation and optional-twin source checks. Do not claim acceptance for skipped/failing paths.

## Task 8: Documentation and final review (SIMU-47)

Files: `README.md`, `docs/bootstrap.md`, `docs/contracts.md`, `docs/operations.md`, `docs/verification.md`, `docs/simu-1-acceptance.md`, original design baseline.

- [ ] Document intended versus verified architecture, exact commands/toolchains, adapter recovery, Laravel AMQP choice and preserved-state cutover.
- [ ] Run all applicable existing and new checks, distinguish local from hosted evidence.
- [ ] Obtain independent whole-change review; resolve material findings and rerun affected checks.
- [ ] Report remaining failures/limitations honestly; leave SIMU-13 and epic completion untouched.
