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
- Frontend model checks passed 21 tests, including fourteen journey tests and five
  catalog/placement tests. Two retained tests cover the previous legacy ETA
  helper and do not prove the replacement renderer.
- Departure and receipt observations for the same custody generation replay as
  one physical trip. Recipient confirmation takes over an in-progress estimate
  without restarting it; the complete recorded history remains inspectable.
  Native Shipping's `load` departure is included: carrier receipt takes over
  the same trip, including receipt-first and already-completed deliveries.
- The Docker Chromium pixel check verified real WebGL2 output with SwiftShader.
- The replacement scene replayed 500 synthetic recorded units with 64 robots,
  bounded its queue, avoided duplicate static/replay placements, froze on source
  hold, honored reduced motion, expired trails and made no business writes.
- GPU-buffer inspection verifies manufacturing machine bases at their catalog
  cell positions. Static batches preserve inherited group transforms; the full
  two-test scene suite passed after correcting this placement bug.
- `sh scripts/check_handling_upgrade.sh` passed native API startup and restart
  against pre-handling-unit schemas for all four business departments. Old
  migration checksums, held run/epoch and seeded Storage/Manufacturing aggregate
  quantities survived. No handling units were implicitly created. Native
  Storage and Manufacturing workers then rejected quantity-losing conversion
  manifests and accepted explicit 4+6 manifests for the ten legacy units of
  quantity. Identical command retries returned the original identity; changed
  retries conflicted. A subsequent API/worker restart preserved exact unit IDs,
  barcodes, positions, aggregate quantities and conversion provenance, with no
  fictional movement history. This does not prove recovery during an active
  custody exchange. Its disposable volumes were removed afterward.
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
- The opt-in native factory restart scenario restarted both Logistics and
  Storage workers at raw capacity acceptance, physical receipt and final
  acknowledgement. Both complete factory cycles, all fifteen publication-loss
  gates and contradictory-receipt checks passed afterward. This mode lets the
  first waiting manufacturing request retrieve its raw input from the receipt
  dock; the second cycle still requires raw and finished shelf traversal.
  Run `HANDLING_FACTORY_RESTART_WORKERS=1 HANDLING_FACTORY_REUSE_IMAGES=1 sh scripts/check_handling_factory.sh`
  against already built factory images. Docker inspection records distinct
  before/after process start times for each worker at every checkpoint.
- All four real `/api/projection` responses from that scenario passed Twin's
  projection validator. Receipt-based reconciliation confirmed all four units
  with no remaining physical placement after consumption or customer delivery.
- `make stack-check APP=all` passed production builds, HTTP roles and auditing,
  broker/worker/database recovery, Twin absence, website isolation and each
  application's independent dependency graph. Browser checks passed 27 cases
  in the combined stack, four for each business application alone, and nineteen
  for Twin alone. The opt-in performance test remained skipped in this command.
- `make mixed-check` passed the orderly and native-loss scenarios, delayed and
  held grants, external power, stable event identities, optional Twin sources
  and durable finalization. Its adapter suite passed 38 tests plus native smoke.
- Docker browser targets now use real loopback HTTP forwarding. Chromium's
  native UUID API works without a shim. Two tests verify request forwarding and
  cleanup of an unanswered upstream request when the browser disconnects.
  Initial combined browser checks exposed a leaked forwarding socket after all
  tests had passed; it was closed during diagnosis. The cleanup fix passed its
  regression, and subsequent independent-deployment runs exited normally.
- A separate Chromium recording replayed the captured native projections with
  four concurrent unit journeys, optional inspection and no business writes or
  page errors. See `screenshots/twin-captured-native-replay.png` and
  `screenshots/twin-captured-native-inspection.png`. The local video is retained
  under `.superpowers/sdd/2026-10-25-simu64-implementation/native-replay/results/`.

The busy 500-unit browser workload is explicitly synthetic. The captured
native handling fixture in `apps/twin/tests/fixtures/handling-factory.json`
comes from the four-department factory scenario; it is separate evidence from
browser workload generation. The new native replay uses captured HTTP data in a
mocked read-model transport, not a live backend connection. Its connectivity
labels and missing observation timestamps are fixture metadata, not evidence
of live source availability or a hosted deployment.

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
| Measurement | 30.025 seconds, 468 actual draw frames |
| Browser animation frames | 468 |
| Active journeys | Minimum 64, maximum 64 |
| Units | Minimum 500, maximum 500 |
| Maximum queue | 192 |
| Maximum draw calls per frame | 9 |
| p95 frame interval | **82.0 ms — fails the 33.4 ms target** |

Batching static geometry and robot-child load transforms reduced maximum draw
calls from 434 to 9. Isolating
software WebGL from Chromium's compositor and disabling multisampling improved
the measured interval, but the target remains unmet. The latest diagnostic
recorded a maximum 10.2 ms before submission and 0.5 ms across draw submission;
these are main-thread measurements, not GPU timings. Browser animation frames
and drawn frames matched, ruling out idle animation frames as the missing work.
A separate fullscreen-triangle control at the same 831 × 538 drawing-buffer
size reached 1,801 frames with p95 19.9 ms in the same SwiftShader runtime. That
control is diagnostic evidence, not a substitute for the 500-unit scene gate.
Replacing both shaders with minimal transforms and a constant color still
measured p95 76.2 ms. With rasterization disabled, the same geometry processing
reached 1,779 frames and p95 21.0 ms. These private-browser diagnostics suggest
the remaining cost lies in rasterization rather than draw submission or shader
complexity. Raster discard produces no visible scene and is not acceptance
evidence or a production setting.
Do not treat static screenshots or model tests as passing performance evidence.

JSON results and intermediate baselines are retained locally under
`.superpowers/sdd/2026-10-25-simu64-implementation/performance/`. The benchmark
fails with a nonzero exit status when the target is missed. It is opt-in during
ordinary browser suites to avoid repeating a 30-second measurement in every
application check.

## Review and follow-on work

A fresh read-only whole-branch review found one Important defect: native
Shipping `load` and Logistics `receive` observations could replay the same trip
twice. The fix passed the full 21-test frontend model suite, covering recipient
takeover, receipt-first delivery and late receipt after completed replay. No
Critical defects were established.
The final production frontend also passed the captured-native Chromium replay
again after the batching and coalescing fixes (one test, 20.7 seconds).

Coordinated operational robot traffic is tracked separately in
[SIMU-75](https://ctfittwo.atlassian.net/browse/SIMU-75), created at the user’s
request. SIMU-64 generates visual estimates; it does not prevent robot-to-robot
route overlap.

## Remaining acceptance gates

- Final renderer budget verification. The native truck/shelf recording is
  functional evidence and does not establish the busy-scene frame budget.


The five websites remain separate. No push, PR, hosted deployment, Jira write or
live data-volume cutover has been performed by these local checks.
