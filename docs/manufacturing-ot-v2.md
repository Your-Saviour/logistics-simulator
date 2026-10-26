# Manufacturing equipment workspace (SIMU-77)

Open **Equipment and diagnostics** after signing in to Manufacturing. The
Assembly cell workspace is part of the existing Angular application. Editable
FUXA remains available and authoritative equipment feedback still comes from
OpenPLC through the existing authenticated Java gateway. Set `FUXA_PUBLIC_URL`
to the operator-accessible FUXA URL to show its link; an empty value hides it.
The link does not grant a FUXA session or editor permissions. Bootstrap continues
to preserve operator-edited FUXA projects.

## Operator journey

1. Supply the recipe's whole handling units, create a work order and release it.
   Follow the active work-order identity from the equipment workspace back to
   its details. One batch carrier occupies the cell at a time.
2. Check connection age, run state and **Next action**. Start is available only
   for a dispatched unfinished batch in a running run, with fresh equipment
   feedback, no unsafe conditions and no latched fault. Stop pauses equipment;
   it does not return consumed materials or rewind time.
3. On a fault, inspect the active alarm and production impact. Acknowledge the
   alarm to record who has seen it. This does **not** clear the unsafe condition,
   reset the PLC latch or resume equipment.
4. Restore the condition (for an injected named scenario, **Stop active scenario**),
   wait for confirmed feedback, select **Reset latch**, then explicitly **Start
   cell**. Batch progress, material consumption and lineage remain intact.
5. Use the device inspector for units, source/protocol, synthetic labels and the
   sample's own observation time. The trend uses simulation seconds. The age is
   wall-clock freshness. Gaps and source continuity changes break trend lines;
   values are never interpolated through missing observations.

The carrier diagram moves only when the gateway confirms equipment position.
Stale diagrams are labelled last-known and dimmed; actuator status becomes
Unknown. A successful API request does not imply physical command completion.
The timeline distinguishes command acceptance/pending/completed/rejected records.

## Permissions and command recovery

| Capability | Required identity / scope |
| --- | --- |
| Observe equipment, history and alarms | `status:read` |
| Start, Stop, Reset latch, acknowledge an alarm | operator role and `runs:control` |
| Start/stop sensor or physical fault scenarios; direct fault injection (including FUXA mailbox) | operator role, `runs:control`, `scenarios:manage` |

The default operator has all these scopes. Existing explicitly scoped identities
do not automatically gain `scenarios:manage`: add it only to scenario managers.
The OT example and disposable test FUXA identity include it to exercise fault
controls. Remove it from a routine-operation FUXA identity when fault injection
should be unavailable. This is a deliberate authorization change.

A command with an uncertain HTTP outcome is retained in session storage under
the authenticated actor. Retry uses the exact endpoint, body, run, epoch and
idempotency key, including after a reload. Another run never retargets the retry.
Discarding the local retry does not cancel an accepted command. If session
storage cannot retain the command, submission stops before sending it.

## Signals and models

Stable synthetic devices are `assembly.motor.temperature` and
`assembly.motor.current`. Both are **observation-only**, labelled synthetic,
and generated from acknowledged simulation time. They cannot produce a business
completion, change equipment motion or grant time. Their retained sample time
is independent of the gateway heartbeat; a held run does not keep their age fresh.
Boolean conveyor/clamp/cycle/position/guard/power signals expose confirmed model
or actuator values. Unknown values remain absent.

Synthetic model v1 uses 25 °C / 0.2 A while stopped; enabled equipment uses
`35 + min(30, progress_seconds × 0.2)` °C and 4.5 A. These are transparent test
signals, not a validated thermal/electrical model. Supported ranges are 23–85 °C
and 0–8 A. A profile's version, seed, actor, start/stop simulation time and wall
time are recorded with run/epoch; each retained observation identifies its scenario.

| Version 1 profile | Parameters and expected result | Production effect |
| --- | --- | --- |
| normal | Seed recorded; default model | None |
| noise | Seed controls deterministic ±2 °C / ±0.2 A per simulation second | Observation only |
| drift | +0.05 °C / +0.005 A per elapsed simulated second, capped at +20 °C / +2 A | Observation only |
| stuck | Constant 35 °C / 4.5 A | Observation only |
| dropout | First three seconds of each ten-second interval have null values and missing quality | Observation only |
| conveyor_jam | Inject then stop scenario to restore conveyor | Inhibits/latches equipment |
| sensor_failure | Inject then stop scenario to restore position sensor | Inhibits/latches equipment |
| guard_open | Open then stop scenario to restore guard | Inhibits/latches equipment |
| power_loss | Remove then stop scenario to restore power | Inhibits/latches equipment |

Only one named scenario is active per run/epoch. Starting another requires
stopping it. Stopping a fault scenario restores its condition through a durable
PLC gateway command; Reset and Start remain explicit. Profile changes never
retroactively alter already-authorized earlier intervals. Historical views are
read-only: rerunning starts at the current grant and cannot rewind the federation.
Amplitudes/rates and these two device definitions are fixed versioned profiles;
a general device editor and arbitrary profile scripting are not provided.

## API and persistence

- `GET /api/ot` remains the live gateway snapshot and latest 50 command receipts;
  command rows now include correlated `order_id`.
- `GET /api/ot/insights` returns the current run/epoch's retained observations,
  device metadata/profiles, latest 200 alarm episodes, latest 50 scenarios,
  latest 200 insight receipts and latest 200 source events.
- `POST /api/ot/insights` requires `Idempotency-Key`, `run_id`, `epoch` and one
  action: `alarm_ack` with `alarm_id`; `scenario_start` with `profile` and integer
  `seed` (0–2147483647); or `scenario_stop`. Unknown fields are rejected.
  Exact retries return the recorded receipt; changed bodies conflict.
- Existing `POST /api/ot/commands` retains Start/Stop/Reset/fault semantics.

Migrations **017** and **018** add insight tables and source continuity; applied
migration checksums are preserved. Observations are retained at most 600 per run,
inserted atomically with the acknowledged operation, deduplicated by operation ID.
Cleared alarm episodes and source events are bounded to 200 per run (active alarms
are retained). Responses limit scenarios to 50 and insight receipts to 200;
scenario and receipt rows remain durable for idempotency/audit. The existing
`ot_operations` journal also retains responses for exact replay; the 600-sample
limit does not cap total database storage. Old runs are
archived, not automatically deleted. Budget/archive their database storage using
existing operational procedures; do not prune volumes.

Gateway failure persists an event and advances a continuity generation without
advancing simulation time. Reconnect records a confirmed source event. The current
protocol can identify an explicit PLC observation failure when the equipment
HTTP gateway responds; other transport failures leave PLC state unknown. It does
not provide independent hardware heartbeats for every component. Equipment/PLC
restart or controller ownership mismatch still requires reconciliation and a
controlled new epoch. See the [existing recovery runbook](manufacturing-ot.md).

Source-disconnect/reconnect and process-restart scenarios are infrastructure
acceptance phases in `scripts/check_manufacturing_ot.sh`, with the exact isolated
project, scope and source events recorded. They deliberately remain deployment
operations rather than offering a web control that can stop live services.

## Deployment, evaluation and evidence

OT-disabled operation remains supported; the workspace explains disabled mode.
No new broker, physical simulator or production deployment is required. The
[simulator decision](manufacturing-simulator-evaluation.md) records why no external
candidate was adopted. Its isolated protocol spike has no Manufacturing route,
business credentials or actuator nodes.

[Acceptance and limits](simu-77-acceptance.md) distinguish local Docker evidence
from hosted and representative-human acceptance. Desktop/tablet targets are
1440/820 px; reduced motion disables workspace motion and keyboard focus is visible.
