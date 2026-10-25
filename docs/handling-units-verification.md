# Handling units: local verification

Status: **local acceptance verified**. These checks establish local behavior;
they are not evidence of a hosted deployment.

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
- Frontend model checks passed 22 tests, including fifteen journey tests and five
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
  five-test scene suite passed after correcting this placement bug.
- `sh scripts/check_handling_upgrade.sh` passed native API startup and restart
  against pre-handling-unit schemas for all four business departments. Old
  migration checksums, held run/epoch and seeded Storage/Manufacturing aggregate
  quantities survived. Historical Shipping orders/lines and Logistics commands/receipts also retained their identities, states and quantities. No handling units were implicitly created. Native
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
  under `.superpowers/sdd/2026-10-25-simu64-implementation/mesa-validation/results/`.

The busy 500-unit browser workload is explicitly synthetic. The captured
native handling fixture in `apps/twin/tests/fixtures/handling-factory.json`
comes from the four-department factory scenario; it is separate evidence from
browser workload generation. The new native replay uses captured HTTP data in a
mocked read-model transport, not a live backend connection. Its connectivity
labels and missing observation timestamps are fixture metadata, not evidence
of live source availability or a hosted deployment.

## Rendering budget: passed locally

Run `make handling-performance-check`. The guarded build uses the production
frontend and a pinned Chromium image with Mesa EGL software rendering. Set
`HANDLING_PERFORMANCE_RENDERER=swiftshader` to reproduce the alternate backend.
The benchmark warms up for five seconds, then measures actual WebGL draw frames
for 30 seconds. Tracing and video are disabled during measurement.

| Item | Result |
| --- | --- |
| Host | Apple M1 Pro, 10 logical CPUs, 16 GiB RAM |
| Container | ARM64, 10 logical CPUs, approximately 8 GiB VM memory |
| Browser | Chromium 156.0.8078.4 |
| Renderer | ANGLE / Mesa llvmpipe LLVM 15.0.6; CPU software rendering, two raster threads |
| Mesa package | 22.3.6-1+deb12u2 |
| Browser viewport | 1440 × 900 |
| Drawing buffer | 831 × 538, DPR 1, single sample |
| Measurement | 30.021 seconds, 1,797 actual draw frames |
| Active journeys | Minimum 64, maximum 64 |
| Units | Minimum 500, maximum 500 |
| Maximum queue | 256 |
| Maximum draw calls per frame | 7 |
| p95 frame interval | **19.1 ms — passes the 33.4 ms target** |

The synthetic workload uses mixed-height trips between distinct raw and finished
rack bays. It is separate from native custody acceptance. Stationary floor pixels
are checked before and after timing, preventing a missing facility from passing.
The result is specific to this software renderer and machine; it does not prove
hardware GPU or hosted performance. Raw measurements, including exact driver
packages, are in [handling-performance-local.json](handling-performance-local.json).

Static facility pixels and depth are cached between changes. Camera, placement,
selection, resize and context changes invalidate the cache; unsupported depth
buffers use direct rendering. Robot parts share instanced geometry. A regression
caught Chromium clearing cached geometry on the first animated draw. Explicitly
clearing before restoring the cache fixed it; held and moving pixel checks pass.
Earlier 20.5/21.1 ms measurements preceded that fix and are superseded. Earlier
SwiftShader measurements missed the target; they are diagnostic history, not the
passing result. No budget, unit count, journey count or measurement duration was
relaxed.

## Review and follow-on work

A fresh read-only whole-branch review found one Important defect: native
Shipping `load` and Logistics `receive` observations could replay the same trip
twice. The fix passed the full 22-test frontend model suite, covering recipient
takeover, receipt-first delivery and late receipt after completed replay. No
Critical defects were established.
The final production frontend passed captured-native replay and comparison with
the uncached facility reference after the animated cache fix (two tests, 24.0
seconds). Both native screenshots were inspected: racks, trucks, floor and
manufacturing cells remain visible during robot movement. All five permanent
scene checks passed separately (29.8 seconds).

Coordinated operational robot traffic is tracked separately in
[SIMU-75](https://ctfittwo.atlassian.net/browse/SIMU-75), created at the user’s
request. SIMU-64 generates visual estimates; it does not prevent robot-to-robot
route overlap.

## Acceptance audit

| Criterion | Local evidence |
| --- | --- |
| Complete unit lifecycle | Two native four-department factory cycles, including raw unload, raw/finished shelves and confirmed delivery |
| Immutable identity and single custody | Native transactional ledgers, fifteen publication-loss gates, five contradictory-receipt cases |
| Finite endpoint agreement | 800-endpoint catalog/model checks, four real projections validated by Twin, GPU machine placement regression |
| Duplicate/concurrent/restart recovery | Five native framework suites, stack recovery, both raw-custody workers restarted at three protocol stages |
| Recipe accounting and lineage | Native Manufacturing tests and two factory cycles with conserved contents and new output identities |
| Exact whole-unit allocation | Native allocation/capacity regressions and explicit legacy 4+6 conversion checks |
| Concurrent 3D handling | Five scene browser checks, shelf-clearance model regression and captured-native replay |
| Fading trails | Scene/model checks for three-second expiry, reduced motion and no business writes |
| Observational Twin | Factory with Twin absent, optional-source mixed checks, read-only inspector |
| Source/epoch failure behavior | 52 Twin database tests, 22 frontend models, inspector and scene browser cases |
| Rendering budget | 500 units/64 journeys, 30 seconds, 19.1 ms p95, visible-world pixel guards |
| Accessible inspection and fallback | Keyboard inspector, WebGL fallback, reduced motion, desktop/mobile screenshots |
| Resource and upgrade safety | Guarded Docker checks, 20 GiB reserve, four native old-schema upgrades/restarts, preserved checksums/history |

Robot-to-robot collision avoidance is the separate SIMU-75 scope.


The five websites remain separate. No push, PR, hosted deployment or live data-volume cutover has been performed.
SIMU-75 was created in Jira at the user’s explicit request.
