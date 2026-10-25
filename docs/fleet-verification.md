# Fleet verification record — SIMU-75

This records local Docker evidence available on 2026-10-25. It separates observed
results from acceptance still in progress. The source work ledger is
`.superpowers/sdd/2026-10-25-simu75-implementation/progress.md`; its adjacent logs
and screenshots are ignored local artifacts, not hosted CI evidence.
Selected public metrics are retained in [the local results record](verification/simu75-local-results.json).

The complete four-department HELICS fleet factory check **passed with Twin
absent**: two conserved native recipe/order cycles, all fifteen publication-loss
checks, a loaded-worker restart, same-bay contention and all 23 physical jobs
including empty parking returns. It finished in **813.24 wall seconds** with
5391 online samples; the verifier exited 0 with `OOMKilled=false`. The fixture
used a 20-second native handoff quantum and 1800-second wall deadline. Its log is
`factory-native-q20.log`, evidence directory `simu75-fleet-factory/050d990f96`.
The corresponding **Twin-enabled run also passed**, in **836.31 wall seconds**,
with all 23 jobs complete, the same functional assertions, and a fresh Twin
fleet snapshot. Its verifier exited 0 with `OOMKilled=false`; log
`factory-with-twin-q20.log`, evidence directory `simu75-fleet-factory/06ae3f656c`.

## Observed results

| Area | Observed evidence | Limit |
| --- | --- | --- |
| Native fleet, Twin absent | Full factory check passed; 23 completed jobs, all four workflow categories, one observed traffic wait. | Local disposable HELICS deployment; sequential native cycles plus contended shelf jobs. |
| Native fleet, Twin present | Full factory check passed in 836.31 s; 23 jobs complete and fresh observer snapshot. | Local disposable HELICS deployment; Twin adds no native federate. |
| Native adapter loss | SIGKILL of Storage adapter with a carried native unit passed in 21.46 s. | Storage stalled; the other three departments remained running. Fleet retained load/claims and emitted no arrival. |
| Fleet backend | 78 tests passed in 28.88 s, `final-phase-recovery-suite.log`. | Isolated Docker/PostgreSQL checks, not a completed native factory run. |
| Twin backend | 66 backend tests passed. | Rendering performance is measured separately below. |
| Storage | Earlier 455 checks passed; the latest per-unit batch/delivery and counter-limit regression run passed **503** PostgreSQL/RabbitMQ checks. | Native backend regression evidence, not cross-stack physical acceptance. |
| Manufacturing | 80 Java tests and 7 frontend tests/build passed. | Local guarded evidence. |
| Logistics | Full Go suite and vet passed; suite reported 9.915 s. | Local guarded evidence. |
| Shipping | Full PHP suite passed. | Local guarded evidence; no invented test count. |
| Twin frontend | Production TypeScript/Vite build and 24 frontend model tests passed. | Build/model evidence does not prove rendering performance. |
| Browser | Three final operational fleet acceptance checks passed in 10.5 s; desktop/mobile screenshots captured. | Includes approved geometry, pallet transforms and final grid alignment. |
| Approved geometry | 800 endpoint service poses validated; geometry acceptance five tests passed. | Geometric support does not establish 600 s traffic throughput. |

Fleet regressions cover clock/proof causality, pause/reconnect gap rebasing,
source polling, malformed inputs, reported load transforms, immutable retries,
lease/generation fencing, static load exclusion, empty return routing and
quarantine when recovery reservations are missing. Worker replacement preserves
physical state, proofs and claims in all seven active phases. Actual loaded
process restart and native adapter loss are verified by separate Docker fixtures. Storage evidence includes
source-group pickup gates, inbound receipt gates, local putaway/pick/transfer,
future/offset/epoch eligibility, grant-safe waiting and HTTP retry after commit.

A separate SQL/worker fixture carries inbound, shelf, manufacturing and outbound
loads simultaneously using custom validated parking positions and synthetic
departmental proofs. It establishes physical concurrency, not default eight-robot
native throughput.

Final browser screenshots show the synthetic acceptance fixture with 500 units
and 16 reported loaded robots: [desktop](images/simu75/fleet-desktop.png) and
[mobile held/stale state](images/simu75/fleet-mobile.png). These are UI evidence,
not screenshots of the native factory acceptance deployment.

Final native review exposed three liveness/contract gaps after the earlier
Storage run: actual stable robot IDs such as `robot-01` were rejected, batch
receipts/departures waited for all sibling physical facts, and a conflicting new
request could block delivery of the preceding receipt. Failing regressions were
observed before correction. The final guarded `make stack-unit APP=storage`
completed with 503 checks and exit 0. Two-unit shared-route cases introduce facts
one unit at a time, require its native receipt or departure proof before the
sibling can proceed, and check exact per-unit stock conservation. Delivery tests
cover the old-receipt/new-request cycle and independent-item continuation after a
409. Whole-trip physical reservations remain unchanged.

Storage migration `015_storage_fleet_unit_audits.sql` adds per-unit immutable
stock/action audit keys and bounded delivery/poll retry cursors. Earlier applied
SQL files remain unchanged. Coordinated local transfers finish their aggregate
only after per-unit native physical receipts; a subsequent explicit `arrive`
replays the completed receipt without adding stock again. Disabled-mode workflow
regressions remain in the full suite.

The native Storage-to-Shipping fixture exposed an exact-version contract gap:
coordinated picking commits departure and arrival, advancing version twice while
Shipping expected the legacy single increment. Shipping now requires exactly two
in coordinated mode and exactly one in disabled mode; movement sequence and
custody generation remain exact. Storage reserves five remaining version
increments for coordinated customer allocation, and Shipping validates four
after reservation. The full Storage suite passed 503 checks, including rejection
without stock mutation and completion exactly at the integer counter limit.

The passing verifier archives each reservation set once and samples compact
digests and robot transforms, with a 512 MB container limit. It retains exit
state and internal-only broker timing diagnostics. Earlier incomplete fixtures
(including an exit 137 and a 20-minute wall deadline during the last putaway)
are excluded from passing evidence. The original exit-137 cause was not captured.

A separate native fault fixture kills the Storage adapter with `SIGKILL` while
an actual Logistics load is held. After deliberate holds are removed, Storage
is stalled and the other three native departments are running. Fleet remains
held, preserving the carried unit and exact claims for six wall seconds
(exceeding the five-second freshness bound), with no physical arrival or native
receipt. The check passed in 21.46 s with verifier exit 0; log
`factory-native-adapter-loss.log`, evidence directory `simu75-fleet-factory/52d9ae1360`.

## Approved physical catalog change

The user approved applying the corrected fixed layout. Shared and four native
catalog copies received **93 coordinate changes**, preserving all **800 endpoint
IDs**, shelf heights and contract version 1. Navigation records
`layout_revision=simu75-layout-2026-10-25`. Validation includes 800 service poses,
four machine offsets and eight truck footprints; the measured minimum loaded
separation in the corrected layout is **0.24 m**.

Routing uses a 0.25 m grid, a 0.85 × 1.05 m robot body, 0.80 × 0.86 m loads and
0.15 m planning clearance. Complete-trip reservations include approach, loaded
travel, fork/load service sweeps and return to persistent parking. Shelf levels
share floor service exclusions. Static load and own-load exclusions distinguish
empty approach/return from carried travel. Pallet-pocket stages use explicit
lifting durations, including the 0.5 m/s lift bound.

Fleet migrations are its own numbered `001_fleet.sql`,
`002_worker_freshness.sql`, `003_reported_robot.sql`, `004_layout_fence.sql` and
`005_planning_diagnostics.sql`.
Applied native SQL was not rewritten for the catalog correction. Existing fleet
physical state is digest-fenced rather than silently reinterpreted against the
new layout. A reconciliation fault retains occupancy and quarantines execution.

Production deployment assumption: each system runs separately with four
dedicated CPU cores. Local acceptance shares one Docker host and does not
establish production latency or rendering performance. Fleet currently has one
fenced scheduling worker; extra cores provide service/database capacity, while
route reservation waits must be assessed separately.

## Performance: failed and unmeasured targets

The recorded 30 s camera-interaction stress fixture used **500 units, 16 reported
loaded robots and the grid overlay**. CPU preparation plus WebGL submission p95
was **1.30 ms**. The final geometry/pallet/grid rerun rendered 839 frames in
30.04 s, with frame interval p95 **39.20 ms**, which **failed the 20 ms target**. These are different measurements: CPU submission is not GPU
completion or frame time. The renderer was Chromium 156 through ANGLE/Mesa
llvmpipe, LLVM 15.0.6, in the recorded local container setup; this was a synthetic
rendering benchmark, not a native acceptance workload. Artifacts are under
`render-performance-final/` beside the work ledger.

The user relaxed the planner 100 ms target to a soft preference. Representative
recorded route timings were approximately 642 ms cold and 232/137 ms warm.
These timings are not a worker scheduling/commit p95 measurement and do not
justify weakening collision clearance.

The corrected four-robot scheduler run completed the full 120 s warmup and
600 s measurement in 238.89 wall seconds. It recorded **0.7 completed round
trips/minute**, 0.5 loaded receipts/minute, 58 queued jobs, 44.6% mean robot
utilization, 652 s assigned queue-wait p95, and 710 s oldest unassigned age.
Worker tick p95 was 1218 ms and maximum 5308 ms. Continuous declared route
primitives and sampled transforms passed the fixture checks; the previous
collision report at simulation second 284 was confirmed to be a false straight
chord across a valid turn. Throughput is substantially below the proposed target.
The eight-robot run reached 671 simulation seconds (551 s measured) before its
300 s wall limit, with 10 completed round trips, 55 queued jobs and worker tick
p95 1313 ms. It passed its route primitive/transform checks but did not complete
the requested measurement window. The sixteen-robot measurement remains pending.

Low utilization with idle robots and queued work supports reservation contention
as a capacity limit. Complete-trip claims remain held across approach, carrying,
service and parking return; dedicated CPU cannot make overlapping claims
compatible. Current blocker lists contain all active reservation job IDs, so
they are candidate blockers rather than proof of one particular corridor. At
eight robots, 12 complete trips/minute would require an average occupied cycle
of at most 40 simulation seconds even at 100% utilization. Distributed parking
and shorter empty trips may help, but this target is not established.

The following remain **pending**, not satisfied:

- The complete deterministic 600 simulation-second, post-warmup balanced
  workload at 8/16 robots (4 robots completed), reporting completions/minute,
  p95/maximum queue wait, utilization, route failures and blockers. The proposed 8-robot target of at
  least 12 loaded legs/minute and no growing queue remains unproven.
- Worker scheduling/commit p95 under 16 robots and 256 queued jobs; the 100 ms
  planner preference does not substitute for this measurement.

## Reproduce in isolated Docker deployments

Run commands at the repository root. Every service build/test runs inside Docker
and is serialized by `scripts/docker_guard.py --wait` with its default **20 GiB**
free-space reserve. Do not reduce that reserve to force a run, prune unrelated
volumes, or attach the harness to persistent deployment volumes.

```sh
make fleet-check
make stack-unit APP=storage
make stack-unit APP=manufacturing
make stack-unit APP=logistics
make stack-unit APP=shipping
make stack-unit APP=twin
FLEET_FACTORY_QUANTUM=20 FLEET_FACTORY_TIMEOUT=1800 make fleet-factory-check
```

For the optional observer variant:

```sh
FLEET_FACTORY_WITH_TWIN=1 FLEET_FACTORY_QUANTUM=20 FLEET_FACTORY_TIMEOUT=1800 make fleet-factory-check
```

For the isolated native adapter-loss variant:

```sh
FLEET_FACTORY_FAULT_ONLY=1 FLEET_FACTORY_QUANTUM=20 FLEET_FACTORY_TIMEOUT=600 make fleet-factory-check
```

`FLEET_FACTORY_REUSE_IMAGES=1` reuses current rebuilt images. The factory check
creates a unique ignored manifest/identity directory and owner-only evidence,
then tears down only its disposable project and volumes. The verifier never
receives a Docker socket. Host-side guarded process control handles its explicit
restart checkpoint. Initialization uses `ROLE=initialize` with explicit fleet
run/epoch and source mapping before API/worker startup.

The harness reuses the existing two-cycle native recipe/order fixture, five
custody legs and fifteen dropped-publication checks. It adds fleet observation,
all four physical workflow categories, simultaneous same-bay shelf contention,
resource/assignment uniqueness, sampled robot envelope separation and a loaded
fleet-worker restart while all native sources are held. Sampled observations are
not a claim of continuous-time collision proof. Completion requires actual
assertions and evidence, not merely a healthy Compose deployment.

## Operational boundaries checked by the implementation

All participating API/worker/controller roles opt into `FLEET_MODE=coordinated`
with their own private token, independent fleet run/epoch and matching
`FLEET_TIME_OFFSET`. Fleet polls authenticated native projections and uses the
minimum mapped committed source clock. Holds, stale sources, scope mismatches and
dependency failures preserve poses, loads and reservations. Reconnect rebases
timed phases without consuming missed movement; future proofs stay ineligible
until the committed clock permits them.

Departure and receipt proofs are native transactional outbox facts sent over
HTTP after commit. Fleet does not write native SQL. Physical arrival adds a gate
to the accepted manifest/departure-token protocol; departmental receipt remains
the sole authority for stock and custody. Synthetic carrier paths without a
native whole-unit implementation wait explicitly.

Optional Twin uses `TWIN_FLEET_SOURCE` with private `url`/observer `token`.
Coordinated scopes disable invented replay and remain visibly stale during fleet
loss. Neither Twin availability nor selection controls fleet time or motion.
Advisory leases, worker generations and layout digests fence recovery; there is
no TTL lock release, automatic physical reset or live-state cutover.

## Pre-merge verification

A fresh guarded Docker rerun on 2026-10-25 passed `make fleet-check` (78 tests),
`make stack-unit APP=storage` (503 checks), and the complete Manufacturing,
Logistics, Shipping and Twin unit targets (Twin: 66 tests). Manufacturing's seven
frontend tests and build passed. Twin's production TypeScript/Vite build and
`npm run test:scene` (24 tests) also passed. Local logs are under
`merge-verification/` beside the work ledger. The previously recorded native
factory, adapter-loss and browser acceptance evidence applies to the same
implementation; these functional checks do not change the performance misses
reported above. Smooth committed-state playback is tracked separately in
[SIMU-76](https://ctfittwo.atlassian.net/browse/SIMU-76).
