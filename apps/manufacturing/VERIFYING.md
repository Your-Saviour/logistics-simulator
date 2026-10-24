# Manufacturing verification record — 2026-10-24

All backend/frontend builds and tests in this record ran inside Docker. The host
was used for editing and orchestration. Existing deployment containers,
credentials, journals and database volumes were not changed.

## Current backend verification

Root ran the canonical guarded command after the Java review fixes:

```sh
sh scripts/check_stack_unit.sh manufacturing
```

**24 tests passed**, with an exact match between the resolved Maven dependency
tree and `backend/dependencies.lock`. The evidence is
[manufacturing-review-green.log](../../.superpowers/sdd/simu-framework-migration/manufacturing-review-green.log).
This run used Maven 3.9.11/Java 21, Spring Boot 4.1.2 and RabbitMQ Java client
5.36.0 with isolated PostgreSQL/RabbitMQ services. The guarded script enforces
serialized Docker work and the default 20 GiB free-space reserve.

The suite covers strict quantities/times, unknown fields and trailing JSON;
independent roles; idempotency replay/conflict; atomic accepted audit rollback and
rejected actor attribution; concurrent duplicate delivery; current-run/epoch
fences; earlier grants and requested-time bounds; power deferral; mandatory
unroutable publication; dead letters; unacknowledged delivery recovery; persisted
adapter operation retries and session ownership; and native completion barriers.

Review regressions were observed failing before their fixes. The green run
includes these behaviors:

- Connected `finalize` persists `finalizing` and a pending native intent. The run
  remains eligible to stall if native finalization fails.
- A connected grant cannot exceed its persisted requested watermark.
- JSON parsing rejects a second document or trailing garbage.
- Actual `pg_terminate_backend` termination of the standalone controller's lease
  causes reacquisition while preserving the held run ID, epoch and state.
  Graceful standalone interruption also preserves state; a reset between prepare
  and grant fences the old epoch and leaves the new run usable.

The reviewed controller finalization path uses a stable operation ID and
validates native acknowledgement before atomically finalizing the session/run
under the owning run, epoch and session. Grants are disabled while finalizing.
End-to-end native acknowledgement is outside the unit evidence above.

Adapter HTTP fixtures establish same-ID retry after a 503 response, replay
without another HTTP send, conflicting-operation rejection and persisted session
restart fencing. They are not native HELICS recovery evidence.

## Frontend and production evidence

Three containerized frontend transport tests and the Angular production build
passed (`manufacturing-browser-green.log`). The added regression verifies the
default fetch transport retains its browser global receiver; actual browser login
also passed after that fix. The locked build reported zero npm vulnerabilities.

Production common HTTP/identity/audit/idempotency checks, terminal reset followed
by successful new-epoch work, broker/database outages and duplicate delivery passed.
Manufacturing also started with only its own dependencies and passed operator and
employee browser flows at desktop and 390px mobile width. The final browser log is
`independent-browser-green.log` in the same evidence directory.

The mixed C#/Java/Go/PHP native federation passed grant-gated correlated handoffs,
external power, optional Twin source recovery and actual native acknowledgement
before SQL finalization (`mixed-stacks-green.log`).

## Limits

See [shared verification](../../docs/verification.md) for complete commands and
platforms. Hosted CI, production ingress and separate physical hosts were not
executed locally. Native state loss requires externally coordinated recovery and
a new epoch. The guarded scripts stop only their own disposable projects.
