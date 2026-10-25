# SIMU-54 Manufacturing OT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver an optional, PLC-driven pump-assembly cell with real equipment feedback, FUXA controls and exactly-once Java production accounting.

**Architecture:** The existing Java controller owns gateway orchestration under its SQL lease. A separate equipment process supplies sensors and applies acknowledged PLC actuator outputs once per authorised logical step. OpenPLC executes cell control; FUXA observes feedback and submits gateway commands. Neither equipment nor PLC/FUXA writes manufacturing tables.

**Tech Stack:** Existing Java 21/Spring Boot/PostgreSQL manufacturing stack, containerised OpenPLC v4, IEC Structured Text, Modbus TCP, FUXA, Docker Compose. Exact runtime, editor/compiler and image digests must pass Task 1 before selection.

**Spec:** `docs/superpowers/specs/2026-10-25-simu-54-manufacturing-ot-design.md` (approved 2026-10-25).

## Global Constraints

- Branch: `feat/SIMU-54-manufacturing-ot`; preserve unrelated untracked files.
- Default `OT_MODE=disabled`; preserve existing production behaviour.
- Build and test only in Docker through `scripts/docker_guard.py`, retaining its default 20 GiB reserve.
- Preserve existing volumes, applied migration checksums and cross-department contracts.
- Native HELICS remains exclusively in the existing private adapter. Twin remains optional and observational.
- One representative cell admits one batch at a time; fixed logical steps may never exceed actual granted simulation time.
- No product implementation before the real OpenPLC protocol/step-handshake compatibility gate passes.

## Review Focus

- Hold racing step admission: the run lock prevents authorising a new step after hold.
- Lost Modbus responses: write echo is not scan acknowledgement; an uncertain write cannot advance equipment.
- Output capacity exhaustion: completed equipment stays completed while Java accounting waits.
- Faulted/stopped cell: paused steps settle without progress so federation time does not deadlock.
- Restart with surviving SQL and lost physical state: reconciliation is required, never automatic production continuation.

### Task 1: Prove runtime, program and protocol compatibility

**Files:** Create `apps/manufacturing/ot/compatibility/compose.yaml`, `apps/manufacturing/ot/compatibility/probe.py`, `apps/manufacturing/ot/plc/cell.st`, `apps/manufacturing/ot/plc/` editor project and `docs/manufacturing-ot-compatibility.md`.

**Interfaces:** Prove Modbus TCP request registers and acknowledgement/output registers for an IEC program. The executable probe exits nonzero unless the actual PLC evaluates the program and acknowledges each logical step once.

- [x] Add a probe that rejects a missing acknowledgement, wrong sequence and duplicate-step counter increment. Execute against an empty/unloaded PLC and observe failure.
- [x] Select an immutable runtime revision and matching editor/compiler. Candidate OpenPLC v4.3.1 resolves to `8d69d935a7915bef9b67bbea46cf87c68d112246`; candidate FUXA v1.3.0 resolves to `029c42a41e85dc78def81682c5aac490a88ef223`. These are source candidates, not validated deployment pins. Resolve platform image digests and dependency locks inside guarded Docker work.
- [x] Build/upload the editor-compatible program. Write an input snapshot, then commit its sequence; read outputs with an echoed sequence before and after to reject torn snapshots. Require program-level acknowledgement, not FC6/FC16 success.
- [x] Prove 100 distinct steps plus repeated identical writes produce exactly 100 logical transitions regardless of extra scans. Demonstrate hold with no new sequence, paused-step acknowledgement, and reconnect with an unresolved write.
- [x] Record exact register addresses, units, word ordering, sequence wrap policy, scan configuration, timings, versions and commands. Reject unsupported fractional quantum settings explicitly or prove their deterministic subdivision.
- [x] Run baseline `make stack-unit APP=manufacturing` with the default guard reserve. Commit only task-owned files after the gate passes.

### Task 2: Equipment model and fenced step protocol

**Files:** Create `apps/manufacturing/ot/equipment/model.py`, `server.py`, `journal.py`, `modbus.py`, `Dockerfile`, pinned dependency lock, `tests/test_model.py`, `tests/test_protocol.py`; create `contracts/ot/v1/` schemas and fixtures.

**Interfaces:** Authenticated private `POST /v1/commands` accepts a versioned stable command ID, run_id, epoch, controller session, order/correlation and operation (`initialize`, `dispatch`, `step`, `stop`, `reset`, `finalize`). `GET /v1/status` reports durable outcome, last acknowledged step, observation time, sensors, actuators, counters and recovery state. An equipment step cannot select its own simulation time.

- [x] Write failing tests for duplicate identical step replay, conflicting body rejection, stale epoch/session, timeout ambiguity, restart reconciliation, unsafe reset, all four faults and progress derived from actual actuator outputs.
- [x] Implement explicit discrete conveyor position, part-presence/position sensors, clamp state, processing progress and good/scrap batch counters. Gate progress on acknowledged PLC outputs; represent jam, sensor failure, guard open and power loss with visible diagnosis and recovery prerequisites.
- [x] Persist command bodies/results and step application atomically in the equipment journal. Crash between actuator acknowledgement and durable application requires reconciliation unless the prior step is provably replayable. No host-time equipment progression.
- [x] Run guarded model tests and real-PLC integration tests, including PLC/equipment restarts, extra scans and duplicate network requests. Commit task-owned files.

### Task 3: Java durable OT lifecycle and accounting

**Files:** Create `apps/manufacturing/backend/src/main/java/simu/manufacturing/Ot.java`, `OtGateway.java`, `src/main/resources/migrations/016_manufacturing_ot.sql`, `src/test/java/simu/manufacturing/OtTest.java`; modify migration index, `Settings.java`, `Production.java`, `Store.java`, `Controller.java`, `Api.java`, and Compose environment settings.

**Interfaces:** `Ot` owns SQL admission, command receipts, batch/step correlation and watermark checks; `OtGateway` performs HTTP outside SQL transactions. Controller calls `OtGateway.settle()` before preparing time. `Ot.outstanding(Connection, run)` extends the existing completion barrier; `Ot.dispatch(...)` participates in the existing start transaction; `Ot.completion(...)` gates the existing finish transaction.

- [x] Cover mode/settings, persisted-mode/reset safety, identity replay and stale scope in JUnit; use existing business-domain tests plus the equipment capacity tests and real batch acceptance for material/output accounting and completion correlation.
- [x] Add numbered migration for run execution mode, cell session, batch dispatch, step intents/receipts, equipment watermark and attributed operator receipts. Enforce unique batch completion and command identity/body consistency.
- [x] In enabled mode, atomically reserve the cell and dispatch when existing material/capacity checks pass; timer expiry cannot complete a batch. Equipment completion remains durable while `HandlingUnits.outputPosition` is unavailable; use existing output/scrap/provenance/custody transactions exactly once.
- [x] Add authenticated `GET /api/ot` and operator-only `POST /api/ot/commands` with strict validation, scope, actor attribution, durable accepted/rejected receipts and retained idempotency. Employee release controls eligibility; operator enable and PLC interlocks control equipment.
- [x] Run guarded backend suite and dependency lock comparison; commit task-owned files.

### Task 4: Clock barriers and recovery

**Files:** Modify `Ot.java`, `OtGateway.java`, `Store.java`, `Controller.java`; create `OtClockTest.java` and `OtRecoveryTest.java` alongside existing JUnit tests.

**Interfaces:** Grant transactions persist required equipment watermarks before releasing the run lock. Preparation refuses advancement while acknowledged equipment time is behind the grant. Paused/faulted steps settle with no production progress. Held runs settle only previously admitted steps. Gateway owner/session is fenced alongside run/epoch.

- [x] Write failing tests for grant/admission, hold/admission and delayed/partial-grant barriers; verify speeds 1/5/20/60, fault-paused time, uncertain-write blocking, reset fencing and finalisation using equipment regressions and live acceptance.
- [x] Implement bounded step admission at actual grants, reconciliation on unknown process state, stop-before-finalisation acknowledgement and clean-cell handshake following standalone reset. Retain the existing prohibition on connected live reset.
- [x] Verify SQL transactions do not span network calls and session lease loss cannot admit more work. Test lost replies with the same stable identity, then dependency loss and restart. Run guarded backend and native manufacturing acceptance; commit task-owned files.

### Task 5: FUXA project and independent deployment

**Files:** Create `apps/manufacturing/ot/fuxa/project.json`, gateway device/tag configuration, `apps/manufacturing/compose.ot.yaml`, `apps/manufacturing/ot.env.example`, and `docs/manufacturing-ot.md`; modify manufacturing README.

**Interfaces:** FUXA observes gateway telemetry and writes only operator mailbox/command inputs validated by Java. Select the gateway-facing FUXA protocol using the verified pinned version's supported connector; never expose raw actuator registers as operator controls. Existing non-OT Compose invocation remains usable.

- [x] Import the project in the real pinned FUXA container and verify tag reads and command acknowledgements. A protocol fixture alone does not pass.
- [x] Provide editable factory schematic with actual sensors/actuators, batch identity, progress, good/scrap counters, Start/Stop/Reset, fault controls and active/latched fault diagnosis. Stale/disconnected indication uses wall-clock observation age and connection status.
- [x] Persist PLC/FUXA configuration, bind operator ports to localhost by default, keep private services off host ports and document external CyberLab placement and credentials.
- [x] Verify unknown/rejected commands, read-only identities, stale telemetry and fault recovery visibly. Capture real FUXA screenshots through the browser workflow. Commit task-owned files.

### Task 6: End-to-end acceptance and branch review

**Files:** Create `scripts/check_manufacturing_ot.sh`, `apps/manufacturing/ot/acceptance/` integration cases and `docs/simu-54-acceptance.md`; modify Makefile with `manufacturing-ot-check` target.

**Interfaces:** One guarded command creates a disposable independent deployment, exercises real PLC/equipment/FUXA/Java, captures evidence and removes only its own disposable resources. Persistent deployment volumes remain untouched.

- [x] Prove pump work-order release through equipment and completion, checking BOM consumption, cell/business capacity, good output, scrap, event correlation and replay once.
- [x] Exercise each fault, acknowledgement and recovery; PLC/gateway/equipment disconnect/restart; duplicate and old-epoch commands/events; hold, speed, reset, finalisation and delayed native grants.
- [x] Run `make stack-unit APP=manufacturing`, `make stack-check APP=manufacturing`, `make manufacturing-connected-check` and `make manufacturing-ot-check`. Record exact results and distinguish local Docker evidence from hosted CyberLab evidence.
- [x] Request a fresh whole-branch code review, resolve substantive findings with regressions, verify the diff and report remaining limitations. Leave the feature branch unmerged unless separately instructed.

## Execution state — 2026-10-26

Implementation is on `feat/SIMU-54-manufacturing-ot`. The disk reserve is unchanged;
user-authorised cache/SDK cleanup restored sufficient space. Existing user data
volumes were preserved and the fleet preview was stopped with permission.

The real OpenPLC compatibility gate, equipment/live-PLC suites, integrated Java
batch, editable FUXA operator/fault workflow and fresh 91-test backend suite have
passed. A fresh whole-branch review found two substantive issues; regression tests
reproduced both, and the fixes passed the full fresh backend suite. Final full
packaging/native/disposable OT acceptance passed; authoritative command
results and operational limits are recorded in `docs/simu-54-acceptance.md`.

The native reference peer required an update for the current whole-unit custody
contract: historical quantity-only facts correctly do not create material stock.
The fixture now exercises manifest reservation and accepted/departed custody.
No production ownership or cross-department contract was weakened.
