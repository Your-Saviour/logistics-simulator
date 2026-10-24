# SIMU-1 remaining application acceptance

Execute inline using the established executing-plans/TDD workflow. User authorized completion of SIMU-1 except SIMU-13. Do not implement CyberLab or distributed packaging work.

1. SIMU-12: independent employee/operator/service identities, scoped authorization, transactional accepted-command audits and rejected-command context, operator audit UI. Regression tests deny employee/service controls and verify no secret disclosure.
2. SIMU-11: deterministic demand/supply/receiving/carrier adapters for explicit synthetic boundaries; persisted scenario seed, timezone, business-day start/hours. Controller generates only selected synthetic boundary inputs. Restart and reset preserve scenario configuration; connected boundaries generate no synthetic inputs.
3. SIMU-8/SIMU-7: validate published JSON Schemas and sample fixtures in CI; reject analytics envelopes at business input. Add provider and clock/status schema coverage.
4. SIMU-10: extend native federation demonstration to request a later time and receive an earlier grant; preserve future-job gating.
5. SIMU-9: demonstrate an actual PostgreSQL outage, recovery and committed-work preservation alongside existing RabbitMQ/worker checks.
6. SIMU-14: run the smallest relevant upstream OFacT example at the pinned source revision inside an isolated evaluation container; record dependencies, runtime result and adopt/reject decision.
7. Run local checks, browser checks, an independent code review and hosted CI against the feature branch. Reconcile each included task against its own acceptance criteria; leave SIMU-13 untouched and report epic exclusion clearly.

Review focus: role escalation, accepted audit atomicity, rejection secret leakage, DST/business-time boundaries, reset/config races, duplicate synthetic seeding and peer/synthetic double delivery.
