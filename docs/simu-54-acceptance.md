# SIMU-54 local acceptance

Feature branch: `feat/SIMU-54-manufacturing-ot`. All service execution uses Docker
and `scripts/docker_guard.py` with its unchanged 20 GiB reserve. These are local
Docker Desktop results; hosted CyberLab placement has not been exercised.

## Reproduce

```sh
make stack-unit APP=manufacturing
make stack-check APP=manufacturing
make manufacturing-connected-check
make manufacturing-ot-check
```

The OT command builds pinned OpenPLC/compiler/equipment/FUXA packaging, creates a
unique disposable Compose project and random private credentials, and removes
only that project's volumes on exit. Its screenshots/logs remain in ignored
`.superpowers/sdd/manufacturing-ot-acceptance`. `OT_ARTIFACTS` overrides the output
location; `STACK_REUSE_IMAGES=1` reuses images after a verified build. Do not use
image reuse to test unbuilt source changes.

## Evidence recorded during implementation

- Real OpenPLC protocol gate: 100 distinct step markers, duplicate writes and
  extra scans; guard/power/stop interlocks passed. Explicit segmented mapping
  was necessary to expose `%MW`; default mapping did not provide it.
- Equipment/model suite: 14 passed; three live-only tests skipped in the unit
  invocation. The separate real-PLC invocation passed all three live tests:
  actuator-driven batch/counters, all four faults and journal restart fencing.
- Java backend: full 87-test suite passed, followed by two actual-native-grant
  barrier fixtures. Requests for time10 never authorised steps beyond the actual
  grant3; future-step acknowledgement was rejected.
- Integrated business loop: a Java work order for 20 PUMPs consumed 20 HOUSING,
  20 IMPELLER and 40 SEAL once; real PLC/equipment completion yielded 19 good / 1 scrap
  and exactly one correlated business completion event.
- Real FUXA imported the checked-in editable native project, displayed live
  telemetry/counters and submitted an attributed `fuxa` Start command through
  the scoped Java interface. Browser verification uses containerised Playwright;
  the in-app browser provider reported no connected browsers.
- Regression found by a longer live run: Modbus transport request ID overflow
  after sufficient polling. The 16-bit wrap regression failed with `struct.error`
  before the fix and passed after it. This does not change the separate durable
  PLC logical-sequence exhaustion policy.

## Final command results

| Command | Result |
| --- | --- |
| `make stack-unit APP=manufacturing` | Passed: 91 backend tests, 7 frontend tests, frontend production build and Maven dependency lock comparison. |
| `STACK_REUSE_IMAGES=1 make manufacturing-connected-check` | Passed with current built images: native demand, actual duplicate deliveries, whole-unit input/output custody, power gating, finite processing duration and correlation. Guarded cleanup passed. |
| `make stack-check APP=manufacturing` | Passed: production builds, HTTP/role checks, broker/SQL/worker recovery, two-worker duplicate deliveries, and 4 applicable Chromium tests; 24 other-app tests skipped. Disposable resources removed. |
| `make manufacturing-ot-check` | Passed: cold deployment, correlated batches, all four FUXA faults, speeds 1/5/20/60, hold/resume, replay/conflict, stale/disabled controls, equipment/PLC/controller restart fencing, old scopes, new epochs, physical finalisation and terminal reset. Guarded cleanup passed. |

The native peer fixture was updated to the current whole-unit custody contract;
quantity-only material facts and the historical output receipt event are no
longer authoritative. The failure diagnostics preserve the last run/order state.
No business contract was weakened to make the fixture pass.

Actual FUXA captures from the disposable deployment:

- [Completed batch: 19 good / 1 scrap](screenshots/manufacturing-ot-completed.png)
- [Open guard, paused equipment and recovery controls](screenshots/manufacturing-ot-guard-open.png)
- [Disconnected telemetry and disabled physical controls](screenshots/manufacturing-ot-disconnected.png)


## Operational limits

A 100ms scan runs under ordinary Docker scheduling. Logical sequence acknowledgement
is deterministic; wall-clock scan cadence and guaranteed accelerated throughput
are not. Every logical second must be acknowledged, including accelerated runs.
A scope supports at most 65,535 acknowledged operations, including controls; use a
controlled new epoch before exhaustion. The MBAP transport counter wraps safely.

The schematic models a single batch carrier. The business backend retains its
existing BOM, processing duration, scrap rule, provenance and output-capacity
checks. It does not model individual pump kinematics.

Unknown PLC/journal/controller state requires an archived run and controlled
new epoch; it does not automatically reconstruct live production. A transient
connection interruption retries an unchanged intent. Program changes require
cold provisioning and verified source/binary identity. FUXA starts on localhost;
external deployment requires boundary authentication/TLS and private OT routing.
See [operation and recovery](manufacturing-ot.md).

## Review decisions

- Used the requested feature branch in the existing checkout to preserve user
  work; no additional worktree was created.
- Required whole-second OT quantum and floor(actual native grant). Subsecond
  equipment dynamics are outside this model.
- Staged enabling OT until confirmed reset; refused disabling a persisted enabled
  run. Enabling therefore requires reset; returning to disabled mode requires an
  archived OT deployment and an independent fresh disabled deployment.
- Required a new epoch after unknown process state. Recovering consumed batches
  may require manual reconciliation against the archived business records.
- Selected a 100ms PLC scan after 20ms watchdog failures on this host. Achieved
  acceleration is bounded by acknowledgements and host scheduling.
- Persisted a running grant's authorised interval intents atomically before Hold.
  Hold can drain that grant; large quanta can delay Stop at its boundary.

- Layered verification uses existing business JUnit, new OT/clock regressions,
  equipment tests and real-service/browser acceptance instead of duplicating all
  domain cases in new JUnit methods. Negative OT reply-field combinations are
  validated in code/review but are not exhaustively enumerated as individual tests.

No minor review findings were deferred. The two substantive review findings
were held-control starvation and mutable state-based rejection outcomes; both
have regressions and were fixed before final verification.
