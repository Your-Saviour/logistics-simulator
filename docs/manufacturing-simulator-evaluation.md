# Simulator evaluation and decision — SIMU-77

Decision, 26 October 2026: **retain OpenPLC and the existing equipment model as
production authority; adopt no external simulator in this increment.** Ship the
Manufacturing workspace and deterministic observational profiles independently.
A maintained protocol component passed a bounded local spike but did not satisfy
persistence, complete operator-product or federation-clock gates. It is not a
replacement manufacturing simulator.

## Evidence and scoring

Primary repositories and exact inspected revisions are recorded in
[`candidates.json`](../apps/manufacturing/ot/evaluation/candidates.json). Commit
dates below come from repository API metadata fetched during this task, not from
an inferred release cadence. Package provenance for the deployed spike is in
[`package-provenance.json`](../apps/manufacturing/ot/evaluation/package-provenance.json).
Scores are this project's assessment, not vendor claims: 0 absent/unproven,
1 partial/requires adaptation, 2 documented fit. Categories: telemetry/scenarios,
maintenance/dependency baseline, browser operation, isolated Docker/Linux,
authoritative clock control, persistence/recovery. Maximum 12. Mandatory gates
outweigh the total score.

| Candidate / primary source | Licence; latest inspected commit | Scores (in category order) | Gate / decision |
| --- | --- | --- | --- |
| [IBA IoT Data Simulator](https://github.com/IBA-Group-IT/IoT-data-simulator/tree/c392047d95791979aa6ede4b54dce9fde949ad8d) | Apache-2.0; 2020-02-21 | 2/0/2/0/0/1 = **5** | Broad MQTT/REST/AMQP/Kafka/WebSocket generation/replay and UI are documented. Supplied stack uses Mongo 3.5, Node 8 and unpinned MinIO; API JVM heap alone defaults to 3500 MB. Dependency baseline fails current deployment gate; no step/grant evidence. Not deployed. |
| [massimocallisto/iot-simulator](https://github.com/massimocallisto/iot-simulator/tree/d7b7d075b87fb775ec1cd9cca1dde722e63868ff) | Apache-2.0; 2023-11-14 | 2/0/0/1/0/1 = **4** | Scripted JSON/MQTT and ARM64 Dockerfile documented. Source POM uses Spring Boot 2.2.1; default Dockerfile uses Java 8 Alpine. Browser frontend is a prototype. Requires dependency remediation/private MQTT and recovery validation. Not deployed. |
| [Open Industry Project](https://github.com/Open-Industry-Project/Open-Industry-Project/tree/c4d9ba3a1a369e3faeb2698433932c768fde0dc0) | MIT; 2026-10-26 | 1/2/2/0/0/0 = **5** | Active browser factory exploration; external Modbus/OPC UA connections require its desktop app. Headless Docker operation and durable command/HELICS semantics are unproven. Keep as a separate visual investigation. Not deployed. |
| [FreeOpcUa opcua-asyncio](https://github.com/FreeOpcUa/opcua-asyncio/tree/c321a240e53d083fd6e167c67f795915d8f236fd) | LGPL-3.0; 2026-10-10 | 1/2/0/2/0/0 = **5** | Maintained protocol library, not an operator application. Deployed asyncua 2.1.0 in a custom bounded container, with pinned transitive versions. Normal/degraded signals and session recovery pass; value persistence and authoritative clock gates fail. No adoption. |
| [CEA-Leti HENDRICS](https://github.com/CEA-Leti/HENDRICS/tree/d43a4c106bd5326fd96d03e480fd6918a595bd8a) | GPL-3.0; 2025-09-04 | 1/1/1/0/0/0 = **3** | Hardware-in-the-loop reference using STM32MP157F-DK2 and Sense HAT. Fails software-only deployment gate without substantial adaptation. No hardware purchase or deployment. |

These checks establish dependency age and packaging constraints, not a complete
CVE audit or licence-compatibility opinion. No unsupported image was silently
substituted to make a candidate pass. CPU architecture support for IBA/OIP/HENDRICS
remains untested. The massimocallisto ARM64 file is documentation evidence only.

## Isolated deployed spike

The viable component-level candidate was asyncua 2.1.0. The exact Python base
image is pinned by digest in the Dockerfile and transitive dependencies are pinned
in `requirements.txt`. The one-shot Compose service has **no network interface
other than loopback**, no published port, no Manufacturing route or credentials,
no PLC/actuator node, read-only filesystem, 32 MiB scratch, all capabilities
dropped, unprivileged UID, one CPU and 384 MiB memory limit. There is no production
integration or persistent deployment to accidentally cut over.

Reproduce from repository root:

```sh
python3 scripts/docker_guard.py --wait --label simu77-evaluation-build -- docker compose -p simu77-evaluation -f apps/manufacturing/ot/evaluation/compose.yaml build
python3 scripts/docker_guard.py --wait --label simu77-evaluation -- docker compose -p simu77-evaluation -f apps/manufacturing/ot/evaluation/compose.yaml run --rm spike
```

The test exercises a real OPC UA server and client: 100 changing temperature
samples, explicit BadSensorFailure quality, denial of observer writes, closing
and reopening a client session, then recreating the server. Node identity remains
stable. Values reset to 25 °C after server restart, explicitly failing persistence.
This proves session disconnect/reconnect, not every network partition behavior.
The normal stream targets one device at 10 Hz; it does not measure a factory-sized
deployment or promise accelerated production. Measurements appear in the
[acceptance record](simu-77-acceptance.md).

| Gate | Result |
| --- | --- |
| Real normal sensor stream / degraded quality | Pass, local container |
| Observer cannot write the node | Pass |
| Session disconnect/reconnect | Pass |
| Recreated-server node identity | Pass |
| Values persist through server restart | **Fail**: reset to model default |
| Browser operator UI / built-in scenario management | **Fail**: library requires custom product |
| Durable authenticated production command outcomes | **Unproven**; observer writes are intentionally denied |
| Persisted actual HELICS grants; hold/reset semantics | **Fail**: not implemented |
| Manufacturing telemetry path | **Not adopted** |
| Hosted deployment / other architectures | **Not tested** |

No candidate meets all adoption gates. Consequently there is no optional
production simulator service, database credential, external ingestion route or
new live dependency. The scoped alternative is the two explicitly synthetic,
grant-correlated signals and recorded scenarios described in the
[operator runbook](manufacturing-ot-v2.md). A future integration needs a persistent
observation adapter, authenticated/private protocol access, bounded ingestion,
source clock/quality mapping and restart tests before enabling its telemetry path.
