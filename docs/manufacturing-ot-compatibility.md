# Manufacturing OT compatibility (SIMU-54)

## Validated industrial protocol

Initial protocol: **Modbus TCP**, unit ID 1, FC3 reads and FC16 writes, big-endian
16-bit unsigned registers. OpenPLC v4.3.1 source revision
`8d69d935a7915bef9b67bbea46cf87c68d112246`, multi-platform image index
`ghcr.io/autonomy-logic/openplc-runtime@sha256:2ca9fc611f25c3ad0471b996a4bf27507ac112612292426ca6d5ca4bf06e97e6`.

STruC++ 0.7.0 matches the compiler pinned by OpenPLC Editor v4.3.2. Its release
archive is verified against SHA-256
`8d78ae92d931b87c06145520222d1491206f424c147ec66ea84653cb8b0e1be5` before compilation.
The runtime compiles the generated upload itself. No PLC control emulator is
used in the live acceptance test. Equipment Python uses the same pinned image's
standard library and introduces no pip dependencies.

FUXA 1.3.0 source revision `029c42a41e85dc78def81682c5aac490a88ef223`, image index
`frangoteam/fuxa@sha256:6e55ac55645a865816e64dca8caf5725f9067548f1b48c17706660eac4609939`.
Its image has been pulled; live HMI acceptance is recorded separately.

## Observed protocol behaviour

The default OpenPLC Modbus configuration uses a legacy layout with **no %MW
registers exposed**. Explicit segmented configuration is required: 1024 %QW
registers followed by 32 %MW registers, with %MD/%ML disabled. Transport addresses
are zero-based; a Modbus client may display address 0 as 40001.

Successful writes are transport acknowledgements: OpenPLC journals writes for a
subsequent scan. The gateway writes the input snapshot without the commit marker,
reads the complete snapshot back, writes the sequence marker, then waits for the
IEC program to echo the sequence and scope cookie. Outputs are read between two
sequence observations to reject a torn snapshot. A timeout never authorises
physical progress or a manufacturing completion.

## Cell I/O

| Zero-based holding register | PLC variable | Units / ownership |
| --- | --- | --- |
| 0 | %QW0 acknowledgement | logical command sequence |
| 1–3 | %QW1–3 conveyor, clamp, cycle | 0/1 PLC actuator outputs |
| 4 | %QW4 fault latch | 0/1 PLC indication |
| 5–6 | %QW5–6 good, scrap | items in the current batch |
| 7 | %QW7 current batch | within-epoch carrier number |
| 8–11 | %QW8–11 scope cookie | four opaque 16-bit words |
| 1024–1026 | %MW0–2 enable, guard, power | 0/1 gateway/model inputs |
| 1027 | %MW3 request sequence | commit marker, written last |
| 1028–1032 | %MW4–8 positioned, clamped, processed, exited, healthy | 0/1 equipment sensor feedback |
| 1033 | %MW9 batch number | within-epoch carrier number |
| 1034–1035 | %MW10–11 target good, scrap | items, supplied by Java-owned batch dispatch |
| 1036–1037 | %MW12–13 fault acknowledgement, active carrier | 0/1 gateway commands |
| 1038–1041 | %MW14–17 scope cookie | new on run/epoch/session change |
| 1042 | %MW18 cell reset | explicit clean-scope initialisation only |

Operators cannot write PLC registers directly through the HMI. The equipment
service is the sole configured Modbus writer. The cookie detects foreign or lost
PLC state; durable Java/HTTP scope and stable identities remain the business
completion authority. Batch quantities remain within the existing 1..10000 range.
Sequences and carrier numbers never wrap silently: reaching 65535 requires a
controlled new epoch. This bounds a one-step-per-second run to less than 18 hours
(and operator commands also consume sequence numbers).

## Simulation-time limits and measured evidence

The PLC scans on wall time. The checked-in task uses a 100 ms interval. A 20 ms
probe was stopped by the runtime scan watchdog on the loaded local Docker Desktop
host; the runtime also reports that real-time scheduling is unavailable. This is
not a claim of hard real-time scan determinism.

Logical progress uses one-second steps. Java authorises only complete steps at or
below the **actual persisted grant**, never requested time. Duplicate markers and
extra scans produce no additional transitions. Nominal speed 1/5/20/60 settings
are upper bounds: actual acceleration is limited by verified input propagation,
scan acknowledgement and journal commits. Steps are never skipped to achieve a
requested wall-time rate. Configured OT requires an integer handoff quantum;
fractional native grants authorise only steps below their floor.

Locally verified on 2026-10-25: 100 distinct markers produced exactly 100 logical
transitions; repeating each marker and waiting through extra scans produced no
extra transitions. Guard-open, power-unavailable and stopped inputs each
acknowledged a paused step without conveyor output or counter increment.

Reproduce in an isolated disposable Compose project:

```sh
sh scripts/check_manufacturing_ot_compatibility.sh
```

The production cell model, HMI and Java accounting acceptance have their own
checks; the minimal handshake probe alone does not prove them. No hosted CyberLab
execution is claimed here.

Primary source references:
[OpenPLC runtime](https://github.com/Autonomy-Logic/openplc-runtime/tree/8d69d935a7915bef9b67bbea46cf87c68d112246),
[compiler pin](https://github.com/Autonomy-Logic/openplc-editor/blob/v4.3.2/binary-versions.json),
[FUXA HTTP device](https://github.com/frangoteam/FUXA/blob/029c42a41e85dc78def81682c5aac490a88ef223/server/runtime/devices/httprequest/index.js).
