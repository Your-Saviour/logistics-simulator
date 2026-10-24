# Digital Twin V1 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or focused parallel workers. Track steps with checkboxes.

**Goal:** Deliver SIMU-39 through SIMU-44 as the independently deployed Flask/React Twin described by SIMU-6.
**Architecture:** Department-owned authenticated HTTP projection snapshots expose durable history. A separate Python consumer persists validated source snapshots, deduplicated events and cursors transactionally. The React site reads the Twin only; SSE/poll reconnect uses a durable Twin revision cursor.
**Tech Stack:** Existing Python/Flask/PostgreSQL, React/TypeScript, Docker and Playwright; no dependency upgrades.
**Spec:** SIMU-6 and children; docs/superpowers/specs/2026-10-24-logistics-simulator-design.md, with the approved Flask stack override. User explicitly requested direct implementation on 24 October 2026.

## Global Constraints

- Twin never regulates HELICS time or becomes a business dependency.
- Build and test only inside Docker through scripts/docker_guard.py, retaining 20 GiB reserve.
- Preserve migrations/checksums, volumes, identities, published fields and existing contracts.
- Unknown/stale data must not appear as zero stock or confirmed delivery. No atomic federation snapshot claim.
- Read-only default; explicitly configured authorized control routes only. Preview is visibly labeled.

## Review Focus

- Removed sources and old epochs must not remain apparently live.
- Credential-bearing URLs and upstream errors must never leak secrets.
- Concurrent consumers and reconnects cannot regress cursors or duplicate history.
- Independent run timelines must not be aligned solely by a numeric watermark.
- ETA, stale data and local hold must never imply delivery or global pause.

### Task 1: Source projection HTTP contract
**Files:** Four departmental backends and their existing native tests; contracts/http/v1.
**Interfaces:** GET /api/projection authenticated status:read. JSON {version:1,source,run:{id,epoch,granted,requested,committed,state,speed,anchor,scenario,...},cursor:string,snapshot:object,events:array}. Snapshot contains existing domain snapshot fields; events contain durable domain history with stable id, correlation_id where available and simulation_time. Complete snapshot and complete active-run history support reconnect with no missing records; source cursor identifies snapshot content, not a fabricated business event. Never truncate history silently.
- [ ] Write/run source contract authorization and history tests (RED).
- [ ] Implement additive read-only endpoint in each native backend, transactionally reading domain/run state; preserve framework ownership.
- [ ] Run guarded native suites and document evidence.

### Task 2: Twin durable consumer/API
**Files:** apps/twin/backend/projection.py, apps/twin/backend/api.py, src/simulator/projection.py, additive migrations and apps/twin/tests.
**Interfaces:** Consumer accepts Task 1 contract, writes per-source snapshot/cursor/events atomically. GET /api/twin returns {revision:number,sources:array,events:array,aligned:object|null,mode:'live',controls:array}; each source {name,connected,stale,observed_at,last_success_at,error,status:{run},snapshot:object|null,cursor,website_url}. GET /api/twin/events?after=N supports durable revision catch-up, SSE optionally. Existing /api/sources preserved. No secrets returned. Config TWIN_SOURCES keeps existing URL/user/password and optional website_url; explicit control identities use separate config.
- [ ] Write/run tests for cursor dedupe, transaction rollback, out-of-order/epoch handling, zero/subset sources, stale/restart and read permissions (RED).
- [ ] Implement validated snapshots/history, durable revisions and safe read API. Align only compatible run/epoch/time origins; show per-source times always.
- [ ] Add explicit optional control routes with operator permission, fixed configured targets and truthful acknowledgements; default no routes.
- [ ] Run guarded Twin test suite (GREEN).

### Task 3: Facility website
**Files:** apps/twin/web/src and apps/browser-check/twin.spec.ts.
**Interfaces:** Consumes Task 2 /api/twin, existing /api/status identity and Basic login. Browser requests Twin API only. No source credentials in client. Read-only source snapshots are the facility authority.
- [ ] Add browser checks for zero/subset sources, drilldown, stale state, estimated vehicle travel and mobile keyboard selection (RED).
- [ ] Replace foundation shell with industrial facility SVG, source watermarks, correlated drilldown/history, infrastructure view and configured external links. Use explicit unavailable states.
- [ ] Verify production TypeScript build and browser checks; capture desktop/mobile screenshots.

### Task 4: Packaging and acceptance
**Files:** apps/twin/README.md, scripts Twin acceptance, deployment configuration and docs/simu-6-acceptance.md.
- [ ] Verify independently supervised consumer, zero sources, any subset and restart using production containers.
- [ ] Exercise five distinct URLs and Twin shutdown without business/time effects, connected domain lifecycle and recovery.
- [ ] Record exact commands/results and evidence limitations, including CyberLab configuration scope.
- [ ] Review whole change and run affected suites. Leave reviewable branch; no live cutover or automatic merge.

## Execution record

Implementation proceeded directly from approved requirements at the user's request.
The feature branch is `feat/simu-6-digital-twin-v1`; user-owned untracked files are excluded.

- Source contracts: native storage179 checks, manufacturing44 JVM plus4 frontend tests/build,
  Go vet/native tests and full PHP suite pass after review fixes.
- Twin core:26 PostgreSQL/API/consumer tests pass, including equivalent timestamp encodings
  across native stacks, reconfiguration overlap, current health and safe source probes.
- Website: production TypeScript/Vite build and10 Playwright fixture checks pass.
- Review fixed lost-response control replay through durable native receipts, live operational
  health/freshness, overdue arrival confirmation labels, and overlapping reconfiguration.
- Five-site/native HELICS evidence and resource-related verification limits are recorded in
  docs/simu-6-acceptance.md. Full acceptance commands did not finish all later phases.
- Final Three.js/React Three Fiber facility uses local CC0 GLB models; two scene tests,
  TypeScript and production build passed. Final 3D browser QA was blocked by disk reserve.

Decisions: retain default read-only operation with opt-in fixed control routes; external
federation owners must implement their own idempotency and explicit global acknowledgements.
Complete active-run source history is transferred as replacement snapshots (32 MiB per-source
HTTP response bound, rejection rather than silent truncation); SSE sends atomic snapshot/cursor
frames with polling fallback. Twin remains optional and never owns native time advancement.
CyberLab/hosted cutover is outside this local implementation; deployment inputs are documented.
