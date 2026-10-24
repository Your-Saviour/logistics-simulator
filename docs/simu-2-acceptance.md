# SIMU-2 local acceptance

Issue: [Storage V1 — independent inventory and warehouse simulator](https://ctfittwo.atlassian.net/browse/SIMU-2).
Implementation: C# / ASP.NET Core backend, Vue / TypeScript website, owned
PostgreSQL/RabbitMQ/controller and department-private native HELICS adapter.

## Verified behavior

- Employee receipt, location inventory, on-hand/reserved/available quantities,
  complete-quantity reservations, material issue, release, picking, departure
  and destination receipt are implemented and visible in the independent website.
- Capacity checks, stock/reservation changes, movement history and command
  outcomes commit atomically. Concurrent reservations cannot over-allocate;
  duplicate commands/deliveries cannot apply a receipt twice. Invalid transitions
  and full locations leave the original stock/workflow state intact.
- Transfers conserve goods in transit until receipt; correlated order/batch IDs
  and immutable movement history follow the full lifecycle.
- Standalone seeded suppliers, production/customer demand and transfer outcomes
  operate without other departments. HELICS-owned boundaries disable synthetic
  inputs. Provider-owned capacity failures can retry in later scenario slots.
- Two actual worker replicas process warehouse work and duplicate receipts with
  one stock effect. Broker outage leaves physical stock unchanged; recovery
  receives the pending quantity once. Workers resume durable commands after real
  stop/start. Broker/database outages,
  lost controller leases, time-grant barriers, held/finalized runs and new-epoch
  resets retain the existing foundation's recovery behavior.
- Employee/observer permissions exclude simulation administration. Security
  audits remain operator-only; warehouse movements and command outcomes remain
  available to warehouse users. The UI preserves an exact request/key when a
  submission outcome is uncertain and refreshes clock state before new commands.

## Commands and results

All builds and service tests ran in Docker through `scripts/docker_guard.py`,
with the default 20 GiB free-space reserve retained. Checks ran serially.

| Verification | Result | Local log |
| --- | --- | --- |
| `make stack-unit APP=storage` | 126 native checks passed against real PostgreSQL/RabbitMQ | `.superpowers/sdd/simu-2-storage/merge-unit.log` |
| `make stack-check APP=storage` | Production builds, 5 Vue tests/type check, HTTP fixtures, terminal reset, broker/database recovery, warehouse employee lifecycle with two worker replicas, physical stock invariants during broker outage, actual worker restart/redelivery and 3 Chromium checks passed | `.superpowers/sdd/simu-2-storage/merge-stack.log` |
| `make storage-connected-check` | Real two-federate HELICS warehouse lifecycle passed, including duplicate native inputs and correlated/versioned facts | `.superpowers/sdd/simu-2-storage/merge-native.log` |
| `sh .superpowers/sdd/simu-2-storage/check-python.sh` | Complete shared Python suite: 70 passed; sample/seeded/storage/adapter schema parity passed | `.superpowers/sdd/simu-2-storage/merge-python.log` |
| `make storage-deployment-check` | Fresh persistent packaging ready without manual restarts; all three backend restart counts zero; external profile configuration valid | `.superpowers/sdd/simu-2-storage/merge-deployment.log` |
| `git diff --check` | No whitespace errors | Session command output |

The local Python script creates a uniquely named disposable project using
`deploy/test.compose.yml`, starts PostgreSQL, and runs the existing bootstrap
image with current `src`, `tests`, `scripts` and `contracts` mounted read-only and
`PYTHONPATH=/app/src`. It invokes `pytest -q -p no:cacheprovider` and
`python scripts/check_contracts.py`, then removes only that disposable project.
The suite reported one existing upstream Starlette deprecation warning.

Chromium exercised the real employee website through receipt → reserve → pick →
transfer → confirmed arrival, checked the physical/reserved quantities, searched
inventory, and verified desktop/mobile layout. Screenshots were rendered and
visually inspected:

- `.superpowers/sdd/simu-framework-migration/browser-artifacts/storage-v1-employee-desktop.png`
- `.superpowers/sdd/simu-framework-migration/browser-artifacts/storage-v1-employee-mobile.png`

These logs/screenshots are local ignored evidence, not hosted CI artifacts.
The native check starts Storage's owned dependencies, C# roles, private adapter,
a HELICS broker and a small external peer. No other department or Twin runs.
It proves 8 components received, 5 issued, 8 products received, 5 transferred to
Dispatch, and 3 products retained at origin, with zero remaining reservations.

## Review and compatibility

A fresh reviewer identified and verified fixes for transport-schema integration,
automatic capacity retries and reserved scheduler-key enforcement. A follow-up
found the legacy sample envelope's optional `type`; regression tests confirmed
the failure, and the adapter now preserves that default on publication/receive.
The original sample envelope schema and API remain compatible. Numbered additive
migrations 006–007 preserve previous SQL/checksums and archive inventory by run.

## Operational limits

This is local Docker evidence. No hosted environment, multi-host deployment,
CyberLab provisioning or adjacent CyberLab module was changed. The persistent
Compose file and external-address/role configuration are documented in
[the deployment guide](storage-v1.md); a hosted cutover still needs its own
operational validation. Native interoperability is proved with the documented
peer contract, not with unknown external simulator contracts or future domain
implementations in the other departmental applications. Twin remains optional.
