# SIMU-77 local acceptance and remaining limits

Evidence date: 26 October 2026. All service execution is local Docker Desktop
through `scripts/docker_guard.py` with its unchanged **20 GiB** free-space reserve.
No hosted deployment or representative-human usability study was performed.
Unrelated running services and data volumes were preserved.

## Reproduce

```sh
make stack-unit APP=manufacturing
make stack-check APP=manufacturing
make manufacturing-connected-check
OT_ARTIFACTS=.superpowers/sdd/simu77-after make manufacturing-ot-check
```

The OT target now includes `dashboard.mjs` after the existing FUXA walkthrough.
Every deployment is disposable and uses scoped credentials. Cleanup removes only
that target's own project/volumes. Current production and operator-edited FUXA
projects are not migrated or replaced automatically.

## Baseline and regression evidence

The pre-change run used existing OT images with
`STACK_REUSE_IMAGES=1 OT_ARTIFACTS=.superpowers/sdd/simu77-before make manufacturing-ot-check`.
It passed the established real PLC/FUXA workflow and recovery checks and captured
[this guard-open baseline](screenshots/simu77/before-guard-open.png). The baseline
has no integrated Manufacturing equipment route, signal inspector, history or
independent alarm acknowledgement. Start remains enabled while faulted; fault
injection appears beside routine controls.

New regressions were observed failing before their implementations:

- Missing durable insight implementation, then sample deduplication/retention,
  alarm lifecycle and scenario identity tests passing.
- Physical named scenario unsupported, then durable inject/restore operations
  passing without automatic reset/start.
- Routine operator fault request returned 200 instead of 403, then both direct
  command and FUXA-mailbox permission tests passing.
- Missing synthetic-sample freshness helper, then old signal samples remaining
  stale despite fresh gateway responses.
- Missing source-discontinuity recording, then consecutive simulation seconds
  separated by source loss producing distinct continuity generations.
- Actual HTTP-host dashboard command failed because `crypto.randomUUID` was
  unavailable; a regression exercises command identity without that API.

The independent code review's important findings were addressed: scenario
permission bypass, synthetic timestamp truthfulness, duplicate timeline keys,
and retained-command instance replacement during a run-scope change. A follow-up
review reported no remaining important finding. It was read-only; execution
results below remain the evidence for runtime behavior.

## Checks

| Exact command | Result |
| --- | --- |
| `make stack-unit APP=manufacturing` | Passed: 99 backend tests, 14 frontend tests, Angular production build and dependency-lock comparison. |
| `make stack-check APP=manufacturing` (build), then `STACK_REUSE_IMAGES=1 make stack-check APP=manufacturing` after correcting the Manufacturing scope assertion | Passed: HTTP/roles/audit, terminal/reset recovery, broker/SQL/worker recovery, duplicate two-worker execution and 4 Chromium tests (24 other-app tests skipped). |
| `make manufacturing-connected-check` | Passed: actual native HELICS and correlated business loop; disposable cleanup passed. |
| `STACK_REUSE_IMAGES=1 OT_ARTIFACTS=.superpowers/sdd/simu77-final make manufacturing-ot-check` | Passed in full: real PLC/FUXA, all four faults, the new dashboard walkthrough, seeded dropout, desktop/tablet/keyboard/reduced motion, actual-grant interval SQL assertion, duplicate replay/conflict, stale disabled controls, equipment/PLC/controller restarts, old-scope fencing, physical finalization and terminal reset. Disposable cleanup passed. |

The scope assertion was updated specifically for Manufacturing's new permission;
other applications still require their original exact scope set. The final OT images were rebuilt before reuse. The stack recovery check
preceded the final HTTP command-ID and timeline fixes; final source subsequently
passed the full unit/build checks and full real-PLC/dashboard acceptance.

The native HELICS check passed typed demand, actual duplicate delivery,
whole-unit material/output custody, power gating, finite processing duration and
completion correlation. The focused backend suite passed eight new tests.

## Browser evidence and performance

- [Before: original FUXA guard fault](screenshots/simu77/before-guard-open.png).
- [After: Manufacturing desktop fault, guidance and independent acknowledgement](screenshots/simu77/after-desktop-fault.png).
- [After: responsive tablet operation](screenshots/simu77/after-tablet.png).

The new browser walkthrough completed active-order identification, keyboard Start,
named guard-fault injection, independent alarm acknowledgement while the fault
remained active, restore → Reset → explicit Start, and seeded dropout. It checked
820 px page overflow, keyboard focus, reduced-motion preference and zero active
workspace animations. This is a focused accessibility check, not a complete
screen-reader or WCAG certification.

Final full-walkthrough local dashboard measurements:

| Measurement | Local result |
| --- | --- |
| Devices / synthetic analogue signals | 8 / 2 |
| Retained observations at measurement | 542 (600 maximum) |
| Insight JSON response | 829,949 bytes |
| p95 insight API request | 98.930 ms |
| p95 retained-sample age at API read | 324 ms |
| Browser filter interaction | 61.140 ms |
| Browser navigation | 118.600 ms |
| Desktop / tablet | 1440 / 820 px |
| Browser errors / running workspace animations | 0 / 0 |

Sample age is measured at API read, not claimed as an end-to-end sensor-to-pixel
benchmark. The display polls at 1.5 seconds. Machine-readable measurements are in
[dashboard-metrics.json](screenshots/simu77/dashboard-metrics.json).

A separate real-database snapshot at the 600-row bound measured **1,425,408 bytes**
for the observation table and indexes; see [storage evidence](screenshots/simu77/history-storage.json).
This does not include the pre-existing durable operation journal or all database
storage. The cleared-alarm/source-event bounds are checked by implementation and
regressions; sustained multi-device scaling and archive growth were not benchmarked.

A [Docker stats snapshot](screenshots/simu77/resources.json), during local
acceptance with the same built application images, recorded controller
193.4 MiB / 9.40% CPU, API 161.8 MiB / 3.88%, equipment 15.2 MiB / 6.53%,
OpenPLC 139.9 MiB / 7.26%, FUXA 94.87 MiB / 0.77%, and web 8.703 MiB / 0%.
These are point-in-time container values, not peak or sustained budgets.

## Simulator measurements and decision

The fully pinned, isolated asyncua 2.1.0 spike passed a real normal stream,
BadSensorFailure quality, denial of observer writes, session reconnect and stable
node identity after recreated-server restart. It deliberately failed retained
value persistence (reset to 25 °C) and does not implement HELICS grant control.
Consequently no external simulator was adopted. See the
[decision and primary sources](manufacturing-simulator-evaluation.md).

Measured on Linux **aarch64**, limited to one CPU and 384 MiB:

| Measurement | Local result |
| --- | --- |
| Stream | 1 device; 100 samples; target 10 Hz |
| Observed stream rate | 9.758 Hz |
| p95 server-write → client-read latency | 1.782 ms |
| Mean write/read latency | 0.990 ms |
| Process peak RSS | 137,692 KiB (134.5 MiB) |
| Process CPU time / total elapsed | 4.421 s / 15.591 s |
| History storage | No persistent spike history; restart value persistence fails |

Machine-readable measurements are committed in
[`local-result.json`](../apps/manufacturing/ot/evaluation/local-result.json).
These are bounded loopback component measurements, not hosted, MQTT,
Manufacturing-ingestion or factory-scale results.

## Targets and practical limits

Implementation defaults were chosen under the user's instruction to use judgment:
two synthetic analogue devices plus six binary signals; one active scenario;
600 retained acknowledged observations per run; desktop 1440 px and tablet 820 px.
The browser polls every 1.5 seconds; the equipment gateway uses its existing
freshness limits. Target budgets are an insight response below 2 MiB, p95 insight
request below 1 second, interactive filtering below 1 second, and displayed
running observations normally less than 3 seconds old. These are local acceptance
targets, not a throughput or acceleration guarantee.

- Representative operator task times/friction have not been measured. The browser
  walkthrough checks task completion automatically; it cannot substitute for a
  human operator's assessment.
- Source process shutdown/restart remains an isolated deployment scenario rather
  than an application button that stops infrastructure. Explicit PLC observation
  loss is distinguishable; arbitrary transport loss cannot independently prove
  every component's status.
- Profile amplitudes/rates and the two analogue devices are fixed, documented v1
  definitions. Seeds and profile selection are configurable; a general device
  editor, arbitrary model scripting and old-run replay UI are not implemented.
- Observation/cleared-alarm/source-event history is bounded per run. Scenario and
  idempotency records remain durable; archived runs require storage planning.
- Existing OpenPLC scan scheduling, logical sequence exhaustion, output-capacity
  barriers and controlled reconciliation limitations still apply.
- A client can intentionally collide with the reserved-looking `scenario:`
  command-key prefix and make a physical scenario transaction fail. SQL rollback
  prevents partial changes or unauthorized actuator activity; dedicated namespace
  reservation is a minor hardening item.
- Hosted acceptance and multi-architecture validation remain unclaimed.
