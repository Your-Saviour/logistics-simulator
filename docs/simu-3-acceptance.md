# SIMU-3 manufacturing V1 acceptance — 2026-10-24

Implementation is isolated on `feat/simu-3-manufacturing-v1`, based on `8012858`.
It completes the Spring Boot/Angular manufacturing domain described by SIMU-3
and its SIMU-21–26 workflows. No existing deployment was cut over or reset.

## Delivered behavior

- Persisted products/BOMs, line batch-slot capacities, processing durations,
  optional scrap, and the seeded pump-assembly preset.
- Queued → ready → running → completed work, with employee holds before start,
  visible material/capacity/power waiting, and durable start/finish jobs.
- Atomic, deduplicated material consumption, good output, scrap, audit history
  and completion facts. RabbitMQ completion publication and HELICS outputs
  participate in the outstanding-work barrier.
- Dedicated Angular employee board, search/filter, order details/BOM/shortages,
  line occupancy, history, role-scoped controls and exact uncertain-command retry.
- Synthetic calendar/seed providers and typed HELICS demand, storage issues,
  informational storage lifecycle observations, and external power availability.
- Persistent independent Compose packaging and explicit external worker/database/
  broker configuration; no Storage, Logistics, Shipping or Twin is required.

## Local verification

All framework builds and service tests ran inside Docker. The host performed
editing, manifest generation and read-only configuration/diagnostic inspection.
Workloads used the repository-wide Docker guard and retained its 20 GiB default
reserve. Linked worktrees now share that guard; optional waiting uses a queued
kernel lock rather than competing polls.

| Check | Evidence |
| --- | --- |
| `COMPOSE_PROJECT_NAME=simu3-manufacturing-unit make stack-unit APP=manufacturing` | 40 backend tests passed, exact Maven dependency-lock match, four frontend transport/retry tests passed, Angular production build passed. |
| Guarded schema/adapter check | Adapter and boundary schemas match their runtime models; completion output/scrap fixture validates and negative scrap rejects; 18 adapter tests passed. |
| `STACK_REUSE_IMAGES=1 make manufacturing-connected-check` | Actual native HELICS demand, reservation observations, duplicate demand/reservation/issue deliveries, power off/on, finite duration, material/output accounting and correlated storage request/receipt passed. |
| Common production recovery probes | HTTP roles/strict validation/audit/replay and terminal/failed/stalled reset passed. Broker outage/recovery, duplicate delivery, worker restart and database outage/recovery probes all passed during the initial production check. |
| `STACK_REUSE_IMAGES=1 STACK_STARTUP_ONLY=1 make stack-check APP=manufacturing` | Employee shortage/hold/supply/release/output passed; two actual worker replicas, stopped-worker barrier, restart and duplicate deliveries passed; broker outage/recovery applied receipt once; all three Chromium tests passed, including full employee lifecycle, roles, search and 390px layout. |
| `make manufacturing-deployment-check` | Fresh persistent packaging completed autonomous pump production with zero backend restarts; a separately launched worker executed durable work through explicit owned DB/broker addresses; external profile configuration passed. |

`DOCKER_GUARD_WAIT_SECONDS=900` was used during concurrent feature verification.
The final production check uses `STACK_STARTUP_ONLY=1` to avoid repeating the
already-passed generic dependency probes; all manufacturing V1 lifecycle,
worker-stop/restart, broker-stop/restart and browser phases still execute.
The normal `make stack-check APP=manufacturing` includes both sets of probes.

Logs are untracked under `.superpowers/sdd/simu-3/`: `unit-green-final.log`,
`contracts-final.log`, `native-verified.log`, `stack-final.log` (the earlier
common recovery probes and regression), `stack-green-final.log` and
`deployment-final.log`. The successful final V1/browser rerun is `stack-verified.log`. Browser screenshots are under
`.superpowers/sdd/simu-framework-migration/browser-artifacts/`.

Observed regressions were fixed before the final checks: cross-command
idempotency keys returned 503 instead of conflict; automatic release could
supersede an employee hold; storage reservation notifications were unsupported;
and prerequisite deferral inherited a five-second wall-clock broker resend
backoff. The retry regression covers publication confirmation racing deferral.

## Decisions and limits

Line capacity counts simultaneous batches; duration applies to a whole batch.
Power gates start/finish transitions, without continuous energy integration.
Configured scrap uses floor(batch quantity × percent / 100).

A confirmed reset archives old-run completion facts and fences their relay into
the new epoch. SQL retains unsent archived facts for diagnosis/export; reset is
an explicit abandonment of the prior scenario, rather than an instruction to
publish its old messages into the new run. A regression verifies that boundary.
The review concern about escaped deployment JSON was disproven by parsing the
actual Compose defaults and example identity values successfully with json.loads.

Storage reservation rejections are visible at the owning Storage application;
Manufacturing does not invent issue confirmation or automatically create new
procurement identities after an uncertain/rejected reservation. Resolve supply
through the owning Storage workflow. HELICS publication ACK is transport evidence,
not destination SQL commit. Native loss still requires coordinated new-epoch
recovery, preserving the earlier baseline policy.

Hosted CI, live CyberLab provisioning, TLS ingress, and separate physical hosts
were not exercised locally. External role placement is tested with explicit
owned DB/broker addresses and a separately launched worker container on the
same Docker host. CI includes the independent deployment and native checks.

Captured production website: [desktop](screenshots/manufacturing-v1-desktop.png)
and [mobile](screenshots/manufacturing-v1-mobile.png). Screenshots were visually
inspected after the passing Chromium lifecycle.

All local disposable verification deployments were stopped. Persistent user
volumes and live deployments were preserved. There are no deferred important
review findings; the reset archival policy and power model above are explicit
V1 decisions.

## Integration with updated main

Merged Shipping V1 main revision `e7cc6bd` with Manufacturing V1. Shared adapter
wiring uses the Shipping transport union, which already contains the identical
Manufacturing demand contract and the common Storage/sample contracts. Both
department schemas, CI steps, Make targets and unit/acceptance checks are retained.
The Docker guard accepts both `--wait` and timed environment-based waiting.

Fresh checks on the combined tree passed:

- `make stack-unit APP=manufacturing`: 40 backend tests, dependency-lock match,
  four frontend tests and Angular production build.
- `make stack-unit APP=shipping`: complete application-owned PHP assertion suite.
- Published schema/runtime parity and all 28 adapter tests, including four new
  shared-adapter ingress/publication composition cases.
- The packaged adapter image independently passes all 28 tests; public fixtures
  are included with its packaged test suite.
- `make manufacturing-connected-check`: actual native material/demand/power,
  duplicate delivery, duration and correlated output acceptance.
- `make shipping-connected-check`: native multiline fulfilment, future-grant and
  actual-endpoint fencing, physical receipt/delivery and adapter restart fencing.

Independent read-only review found no merge-resolution defects. Logs for these
integration checks are local under `.superpowers/sdd/simu-3-merge/`.
