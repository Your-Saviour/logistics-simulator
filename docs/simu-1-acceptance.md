# SIMU-1 application acceptance, excluding SIMU-13

The user explicitly excluded SIMU-13. Its CyberLab/distributed-packaging task remains outside this delivery; the parent epic must not be described as fully closed while that child remains open.

| Included task | Implementation and verification |
| --- | --- |
| SIMU-7: five independent applications / CI | Separate website builds/origins and API/worker/controller/database state; CI runs schema parity/fixtures, Python tests, frontend builds/audit, five-site smoke/browser checks and independent startup. |
| SIMU-8: contracts | Published runtime-matched boundary and seeded-input JSON Schemas, units/ownership/routes and positive handoff policy; analytics ingestion regression verifies no inbox/job/effect is written. |
| SIMU-9: reliable background execution | Transactional jobs/inbox/outbox, confirmed durable RabbitMQ publication, manual ACK, retries/DLQ. Recovery script exercises duplicate delivery across worker restart, real PostgreSQL outage, broker outage, committed-work preservation and old epochs. |
| SIMU-10: local/HELICS time | Persisted clock/run/jobs, singleton lease, current-time ledger, hold/speed/reset/finalization. Native federation proves delayed grants and explicitly requests 5 / receives 2 from peer messages while a due-at-8 job remains untouched. |
| SIMU-11: standalone providers | Deterministic demand/supply/receiving/carrier inputs per selected synthetic boundary; connected peers never cause fallback. Scenario seed, start time, timezone, business hours/weekdays and cadence persist through restart/reset; DST gap/fold and old-epoch regressions pass. |
| SIMU-12: identities and audits | Independent employee/operator identities; service credentials with explicit scopes. Employees/services cannot control/reset runs or read audits. Accepted command/audit are one transaction; rejected context retains request-time run. Operator audit UI and employee UI/API regressions cover all five apps. |
| SIMU-14: OFacT assessment | Pinned source/license/dependency inspection and actual isolated upstream sales-generation example: 20 orders, 8 customers. Runtime reuse rejected for this bootstrap; no upstream code imported into app runtime. |

This is bootstrap acceptance, not completion of departmental V1 workflows under SIMU-2 through SIMU-6. Role authentication uses deployment-provided secrets and HTTP Basic at the API; use TLS outside loopback development. Federation-wide pause/checkpoint recovery remains owned by an external federation controller as documented, not silently implemented by local controls.

Hosted checks are defined in [.github/workflows/ci.yml](../.github/workflows/ci.yml). The delivery report links the verified feature-branch run; [workflow history](https://github.com/Your-Saviour/logistics-simulator/actions/workflows/ci.yml) remains the authoritative hosted result.
