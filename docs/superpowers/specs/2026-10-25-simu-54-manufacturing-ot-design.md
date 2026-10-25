# SIMU-54: Optional manufacturing OT cell

## Intent and scope

Deliver the SIMU-54 operator-command → OpenPLC → simulated equipment → feedback → FUXA loop for one pump-assembly cell. Manufacturing remains the authority for work orders, input consumption, capacity, good output, scrap and completion facts. OT is opt-in; existing deployments retain their scheduler-driven production behaviour.

The implementation belongs on `feat/SIMU-54-manufacturing-ot`. Preserve unrelated untracked files, existing volumes, applied migration checksums and all cross-department contracts. Build and test only in Docker through `scripts/docker_guard.py`, retaining its default 20 GiB reserve.

## Approach

The user selected optional OT execution rather than making OT mandatory for pump assembly. Add a manufacturing-owned Java gateway and an explicit equipment model. Use a PLC step-request/acknowledgement handshake rather than equating wall-clock PLC scans with simulation time. A free-running equipment simulator would violate hold and grant barriers; replacing OpenPLC with an in-process control emulator would not deliver the requested equipment loop.

Default `OT_MODE=disabled` preserves existing behaviour. Enabled mode is validated at startup and persisted with the run; changing execution mode on an existing run requires reset/new epoch. One representative physical cell admits one batch at a time, even when configured business line capacity is higher. That additional resource constraint is visible in production status.

## Compatibility gate

Before product implementation, pin an OpenPLC runtime source revision and matching program format, pin FUXA and all new dependencies, and demonstrate a real containerised round trip. Prefer Modbus TCP as the initial industrial protocol, subject to proof against the selected runtime. Record supported addresses, word ordering, counter widths, writes and readback. Do not claim deterministic PLC scan scheduling: prove deterministic logical step acknowledgement instead. If the runtime cannot support the handshake, report that result before revising the design.

## Components and authority

- Java owns durable batch dispatch, operator-command admission, telemetry correlation, step intents, event deduplication and all business SQL. Add numbered migrations and explicit versioned command/event contracts.
- OpenPLC executes a version-controlled IEC control program for conveyor, clamp, cycle enable, interlocks and good/scrap feedback. Include the editor-compatible project and deployment instructions.
- A separate equipment process reads PLC actuator outputs and supplies presence/position, guard, power, progress and fault feedback. It never accesses manufacturing SQL or native HELICS.
- FUXA uses a checked-in project with a cell schematic, live sensor/actuator indicators, counters, active batch, progress, start/stop/reset, fault injection/diagnosis and stale/disconnected indications. Writes enter the gateway's command interface, rather than bypassing authority to actuators.
- Employee release authorises production eligibility. Operator start enables the admitted batch; stop pauses equipment without reversing consumed material. Reset/acknowledgement cannot clear an active unsafe condition or invent completion. PLC interlocks always override a requested actuator state.
- Native HELICS remains exclusively in the existing private adapter. Twin remains optional and observational.

## Durable lifecycle and contracts

Every batch/step/command/event carries version, run_id, epoch, work-order ID, correlation ID and stable identity. Identical retries return the stored outcome; conflicting identities/bodies and old scopes are rejected. Modbus register values alone are never sufficient authority to commit production.

At the existing start transaction, check OT resource availability, consume materials once and persist batch dispatch atomically. In enabled mode, timer expiry alone cannot finish the batch. A validated completion event must match the dispatched batch, admitted step, quantities and current scope. Reuse the existing output-position, provenance, completion-event and custody transaction paths so good output and scrap commit once. Counters describe the complete batch and preserve the configured scrap rule; faults pause progress rather than silently changing the recipe or scrap policy.

The Java gateway runs within the existing controller ownership lease, with durable epoch/session fencing; network calls occur outside SQL transactions. The equipment process persists step deduplication, and any restart whose state cannot be proven enters reconciliation. Gateway commands require scoped credentials, actor attribution and durable accepted/rejected receipts. Telemetry freshness uses wall-clock thresholds independently of simulation progress.

Equipment batch-done is durable independently of business completion: waiting for an output position must never rerun equipment or increment counters again. Separate operator command acknowledgement from equipment acknowledgement and business completion. Expose rejection/recovery reasons and observation timestamps without exposing service credentials.

## Simulation time and scan handshake

Use bounded fixed logical equipment steps authorised only by persisted manufacturing grants. Start with one simulation-second steps and validate quantum compatibility. A step freezes its input snapshot and command sequence; the PLC echoes its sequence after evaluating the program, and the equipment model applies that acknowledged result once. PLC state transitions and counters are gated by the step sequence, not the number of wall-clock scans. Retries reuse the same step identity and inputs.

Equipment catches up only to actual granted time. Grant settlement atomically persists the required equipment watermark so grant preparation cannot race ahead before a step intent exists. Outstanding unresolved steps and due completion settlement prevent the next time request. A stopped or faulted cell acknowledges each step as paused, allowing simulation time to advance without production progress; uncertain I/O acknowledgements block further grants. Requested time is never permission to step. Hold prevents admitting further steps; a previously authorised in-flight step may settle and is reported explicitly. Speed changes increase step throughput without skipping transitions; achievable acceleration is limited by handshake latency. Finalisation waits for settlement and records equipment stopped. FUXA cell reset clears only acknowledged equipment faults. Application reset archives prior-run work and fences it with a new epoch, retaining the existing consumed-material history; it requires a clean cell handshake before admitting new work. Connected live reset remains forbidden and requires coordinated federation recovery. Hold admission and step admission share the run lock so no new step is authorised after hold; acceptance tests cover this race.

## Faults and recovery

Demonstrate conveyor jam, failed presence/position sensor, guard open and lost power. Each has explicit feedback, an operator-visible reason, inhibited outputs and a controlled recovery sequence. Restore the condition, acknowledge/reset when required, and explicitly resume. Safety trips do not lose consumed-material lineage or free the active batch's capacity.

Gateway/equipment/PLC disconnects stop admission and expose stale state. An ambiguous actuator write, missing acknowledgement or process restart must not silently resume. Retain durable intent and require reconciliation; if the selected PLC/model cannot prove its prior state, require controlled reset/new epoch. Never reconstruct physical state from SQL alone. FUXA disconnection does not fabricate telemetry or completion.

## Deployment and validation

Provide an independent optional Compose configuration for manufacturing, gateway/equipment, OpenPLC and FUXA, persistent PLC/FUXA configuration and documented CyberLab role placement. Use private service networking, localhost-bound operator ports by default, explicit credentials and no automatic live cutover.

Automated guarded acceptance covers disabled-mode regression; real PLC/program/protocol round trip; pump batch material/capacity/output/scrap accounting; duplicate commands/events; stale epoch rejection; every fault/recovery; disconnect/restart ambiguity; hold/resume/speed/reset/finalisation; and delayed HELICS grants. Use actual runtime/FUXA containers for integration evidence, not only protocol fixtures. Capture FUXA screenshots and exact commands/results. Hosted CyberLab evidence is reported separately from local Docker evidence.

## Implementation decisions and limits

The builder chooses exact pinned versions after compatibility testing, register allocation, internal Java classes and the smallest reliable equipment implementation. The initial protocol preference and one-second logical step are proposals to validate, not established compatibility facts. This is discrete lab equipment simulation, not continuous physics or physical safety certification. No unrelated department OT, new business workflow or 3D factory is included.
