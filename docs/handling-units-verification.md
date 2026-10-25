# Handling units: local verification

Status: **acceptance is incomplete**. This document distinguishes completed
local checks from remaining gates; it is not evidence of a hosted deployment.

## Completed local evidence

- Final `make stack-unit APP=<app>` checks passed for Storage, Manufacturing,
  Logistics, Shipping and Twin. The five runs were serialized, and their
  disposable containers and data volumes were removed afterward. Storage was
  rechecked after adding raw inbound custody (409 checks); Logistics' full
  PostgreSQL/RabbitMQ suite and `go vet` passed after adding the sender and
  routing regression.
- Twin's PostgreSQL-backed suite passed 52 tests for extension validation,
  immutable identity, event/snapshot agreement, retained history, scope fencing,
  conflicts and receipt-based custody reconciliation.
- Frontend model checks passed 17 tests, including ten journey tests and five
  catalog/placement tests. Two retained tests cover the previous legacy ETA
  helper and do not prove the replacement renderer.
- The Docker Chromium pixel check verified real WebGL2 output with SwiftShader.
- The replacement scene replayed 500 synthetic recorded units with 64 robots,
  bounded its queue, avoided duplicate static/replay placements, froze on source
  hold, honored reduced motion, expired trails and made no business writes.
- Five inspector browser checks cover keyboard navigation through lineage,
  unavailable WebGL, unknown/disputed/unobserved placement, source hold and
  disconnection, epoch replacement and missing handling extensions. Desktop and
  390 px mobile screenshots were inspected. Full barcode headers remain inside
  the inspector, including its Clear control.
- Three orchestration regression tests verify fresh unit-check projects and
  volume teardown for Manufacturing, Logistics and Twin.
- The connected four-department factory check passed two native recipe/order
  cycles with Twin absent. The second output was put away at
  `storage.finished.r01.b01.l04`, retrieved from that same shelf, handed through
  Shipping and loaded for confirmed customer delivery. The first cycle retained
  fifteen publication-loss checks and five contradictory-receipt quarantine
  checks. Two dispatch vehicles were configured for the two deliveries; their
  recorded locations were never reset.
- Both raw inputs were loaded into recorded Logistics inbound truck slots,
  unloaded into Logistics docks, then handed to Storage with unchanged UUIDs,
  barcodes and contents. Two inbound vehicles were configured separately from
  the outbound fleet. The second cycle explicitly verifies the persisted
  truck-to-dock unload movement and Storage receipt from that exact dock.
- All four real `/api/projection` responses from that scenario passed Twin's
  projection validator. Receipt-based reconciliation confirmed all four units
  with no remaining physical placement after consumption or customer delivery.

Fixtures used for browser rendering are explicitly synthetic. The captured
native handling fixture in `apps/twin/tests/fixtures/handling-factory.json`
comes from the four-department factory scenario; it is separate evidence from
browser workload generation.

## Rendering budget: open gate

The explicit benchmark is:

```sh
make handling-performance-check
```

It builds the production frontend and pinned browser image through
`scripts/docker_guard.py`, starts a disposable web container, warms up for five
seconds, then records 30 seconds of actual WebGL draw frames. It checks 500 live
unit representations, exactly 64 concurrent journeys, a queue of at most 256,
and p95 frame intervals no greater than 33.4 ms. It does not manufacture business
receipts. Tracing and video are disabled for the measurement itself; functional
recordings are captured separately.

Latest completed local measurement:

| Item | Result |
| --- | --- |
| Host | Apple M1 Pro, 10 logical CPUs, 16 GiB RAM |
| Container | ARM64, 10 logical CPUs, approximately 8 GiB VM memory |
| Browser | Chromium 156.0.8078.4 |
| Renderer | ANGLE / Vulkan SwiftShader, LLVM 10.0.0; CPU software rendering |
| Browser viewport | 1440 × 900 |
| Drawing buffer | 831 × 538, DPR 1, single sample |
| Measurement | 30.065 seconds, 477 actual draw frames |
| Active journeys | Minimum 64, maximum 64 |
| Units | Minimum 500, maximum 500 |
| Maximum queue | 192 |
| Maximum draw calls per frame | 72 |
| p95 frame interval | **72.7 ms — fails the 33.4 ms target** |

Batching static geometry reduced maximum draw calls from 434 to 72. Isolating
software WebGL from Chromium's compositor and disabling multisampling improved
the measured interval, but the target remains unmet. App preparation and render
submission each measured below 7 ms in these runs; this is not a GPU-time or
hardware-acceleration claim. Do not treat static screenshots or model tests as
passing evidence for this budget.

JSON results and intermediate baselines are retained locally under
`.superpowers/sdd/2026-10-25-simu64-implementation/performance/`. The benchmark
fails with a nonzero exit status when the target is missed. It is opt-in during
ordinary browser suites to avoid repeating a 30-second measurement in every
application check.

## Remaining acceptance gates

- Final upgrade/drain/conversion and recovery evidence against the final branch.
- Final `make stack-check APP=all` and `make mixed-check` results. Earlier narrower
  checks are not substitutes for these final commands.
- Final renderer budget verification and shelf/truck interaction recordings.
- Fresh whole-branch review and resolution of required findings.

The five websites remain separate. No push, PR, hosted deployment, Jira write or
live data-volume cutover has been performed by these local checks.
