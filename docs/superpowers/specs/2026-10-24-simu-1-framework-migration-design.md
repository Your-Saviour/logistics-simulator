# SIMU-1 remaining framework migration

Status: approved by the user; implementation and local container acceptance complete on feature/simu-framework-migration. Hosted CI and deployment are separate.

## Scope and evidence

The current Jira SIMU-1 description supersedes the uniform FastAPI/React
bootstrap design. SIMU-7–12 and SIMU-14 are Done. The remaining included
children are SIMU-45, SIMU-46 and SIMU-47. SIMU-13 is explicitly excluded.
SIMU-46 requires the migrated foundations tracked by SIMU-48–52 under the
application epics. This proposal includes those prerequisite foundations,
but does not include their departmental V1 workflows.

The repository currently runs every API through `simulator.api`, every
business controller through `simulator.controller`, and every frontend
through `apps/web`. Its existing tests and acceptance report establish the
historical bootstrap only. No migrated implementation or mixed-language
verification is claimed.

## Required application ownership

| Application | Backend | Website |
| --- | --- | --- |
| Storage | C# / ASP.NET Core | Vue / TypeScript |
| Manufacturing | Java / Spring Boot | Angular / TypeScript |
| Logistics | Go / Gin | Svelte / TypeScript |
| Shipping | PHP / Laravel | Blade / Livewire |
| Digital twin | Python / Flask | React / TypeScript |

Each business backend owns its API, transactions, sample business execution,
workers, durable scheduler, local clock and outstanding-work ledger. Each
owns independent PostgreSQL/RabbitMQ state and credentials. Python supplies
only the department-local HELICS adapter in connected business deployments.
The twin owns its read model and separately supervised projection consumer;
it has no business scheduler or time-regulating federate.

## Approaches

Recommended: incremental replacement preserving the existing HTTP and SQL
contracts, starting with the adapter and reusable external acceptance
fixtures. Integrate one department at a time, then run mixed-stack checks.
This retains recovery evidence and permits explicit compatibility checks at
each cutover, while requiring genuine implementations in four languages.

A simultaneous replacement would make durable-state compatibility and
federation regressions harder to isolate without reducing the required work.
A framework proxy over Python would be smaller but violates the approved
ownership requirements. Neither alternative is recommended. The user has
approved this incremental implementation approach.

## Adapter protocol (SIMU-45)

Proposed builder choice: versioned JSON over a private authenticated HTTP
interface, with asynchronous polling for native initialization/time requests.
The adapter is deployed separately for each business application. One process
owns one native combination federate, serialized native operations, and no
business database credentials. It must reject multiple native owners.

Define schemas and reference fixtures for initialize, receive and persisted
acknowledgement, time request/grant, publish and publication acknowledgement,
health, checkpoint and finalize. Requests identify protocol version,
operation ID, federation/run/epoch and controller session. Business envelopes
retain existing IDs, units and positive handoff quantum. Reject unknown
fields, nonfinite times, stale sessions and conflicting operation replays.

Received envelopes remain available until the backend acknowledges its
transactional inbox commit. The backend durably records grants and effects;
only its durable completion barrier can authorize a further time request.
Publication retries retain stable event IDs; a transport acknowledgement is
not a claim of destination database commit. Receiver deduplication remains
mandatory. Earlier grants authorize only the time actually granted.

Checkpoint reports durable-backend/native-session metadata and recovery
eligibility. It must not imply native HELICS state can be reconstructed from
SQL. Adapter loss marks connected execution stalled, fences old sessions
and requires owner-coordinated federation recovery with a new epoch when
native state is lost. No synthetic fallback or unilateral live rejoin.

## Department migrations (SIMU-48–52)

Create application-owned backend/frontend source, locked dependencies,
toolchain declarations, migrations, container entry points and isolated
development/smoke configurations. Keep the existing sample scope and visual
direction. Preserve health/status/source/audit routes, command validation,
permissions, idempotency conflicts, transactional audits and error semantics.

Port durable execution into each selected business backend: row locking and
epoch fencing; jobs/inbox/internal and boundary outboxes; confirmed mandatory
publication; manual acknowledgement after durable commit; bounded processing
retries and dead letters; explicit seeded providers and business-time rules.
Local drivers do not require the adapter. Connected controllers use the
adapter protocol and own the persisted grant/completion barrier themselves.

For shipping, choose and lock a maintained AMQP client/integration after
checking its current compatibility. Explicitly implement and test publisher
confirms, routing failures and consumer acknowledgement semantics. Laravel
wall-time queue delays do not replace simulation-time due jobs.

Preserve PostgreSQL data and applied migration checksums. Use additive,
versioned migrations and quiesce old controllers/workers at cutover. Never
silently reset data, regenerate credentials or replace active federation
identities. Any incompatible reset requires a concrete operator-approved
cutover procedure before execution.

## Verification and documentation (SIMU-46–47)

Publish shared JSON/HTTP fixtures covering UUIDs, strict quantities, units,
finite simulation seconds, timezone/DST, epochs, unknown fields and errors.
Run them against actual framework implementations, not adapters that forward
business execution to Python. Preserve employee/operator/service boundaries
and assert accepted audit atomicity and durable rejected audit attribution.

Exercise duplicates, concurrent delivery, worker restart and real database,
broker and adapter outages for each relevant implementation. Verify no
acknowledgement precedes commit and no duplicate sample effects occur.
Build all five frontends/backends and start each application independently.
Then run a mixed-language federation with delayed and earlier grants,
external power, correlated handoffs, and an optional twin observing zero,
subset and all sources. Adapter reference tests precede integration checks.

Update README, bootstrap, architecture, contracts, operations and verification
with commands actually exercised, exact supported toolchains, dependency
locks and preserved-state cutover steps. Keep historical evidence labeled.
Report hosted CI separately from local results and physical multi-host work
that has not been exercised. Preserve the OFacT rejection decision.

## Exclusions and completion

No CyberLab modules, Ansible changes or distributed deployment packaging from
SIMU-13. Application-owned build/smoke assets remain necessary for the migration
and CI tasks. No department V1 lifecycle implementation, cloud provisioning,
central business/identity runtime, or federation-wide pause controller.

Completion requires all included acceptance criteria and their prerequisite
migrations to pass against the selected stacks. SIMU-1 remains open while
SIMU-13 is open. No Jira completion changes or external messages have been
made during this assessment.
