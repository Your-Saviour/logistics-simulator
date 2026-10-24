# SIMU-4 transport design

The user approved this design and execution on 24 October 2026. Extend the
existing independent Go/Gin and Svelte deployment with finite fleet transport.
The employee assigns goods and follows loading, departure, confirmed arrival,
unloading and destination receipt. ETA alone never confirms delivery.

## Approach

Extend the existing PostgreSQL jobs, RabbitMQ worker and granted-time controller.
A separate scheduler would duplicate the existing barriers and recovery logic;
replacing the runtime would discard the verified SIMU-50 foundation. Python
continues to own only native HELICS in the private adapter.

## State and transactions

Each run has immutable configured locations, routes (origin, destination,
journey seconds), and vehicles (capacity, starting location). Defaults provide
two warehouses, dispatch and customer destinations with a small finite fleet.
Configuration changes require a confirmed new standalone run; connected changes
require coordinated new epoch deployment. Existing SQL checksums remain intact.

Transfers carry SKU, integer item quantity, route, correlation UUID, vehicle,
version, planned ETA and separate departure, arrival, unloading and receipt
timestamps. Workflow: requested → assigned → loaded → in_transit → arrived →
unloaded → received. Assignment reserves one vehicle exclusively, checks location
and capacity, and rejects competing assignments atomically. Unload releases the
vehicle at its destination. Receipt acknowledges goods at the destination.
Automatic arrival is a durable job scheduled at departure plus route duration;
an employee arrival command may confirm only after that time. Duplicate automatic
and employee arrivals cannot repeat effects. Until unloading, transport retains
custody; unloaded goods remain awaiting receipt until an explicit destination ACK.

Every command requires run_id, epoch, due_at and idempotency key. Workers process
commands only at granted time with a healthy controller. Expected business
rejections settle their job without spending infrastructure retries. Command,
audit, custody ledger, state and boundary outbox commit together under the current
run row lock. Outstanding eligible jobs and unsent outputs retain the barrier.
Identical replays return current outcomes, changed bodies conflict, and stale
epochs are fenced. Historical run records remain available in PostgreSQL.

## Website and boundaries

Replace the sample focus with transfer queue, fleet availability, route capacities,
custody and ETA/arrival/receipt details. Show valid employee actions and preserve
the same body/key for uncertain retries. Keep operator controls and audit access.

Explicit seeded transport-demand and receiving-destination providers use the same
domain commands. Automation acts only on provider-owned records. Connected mode
disables the corresponding synthetic provider. Versioned HELICS domain requests,
receipts and transport facts preserve peer authentication, federation/run/epoch,
correlation/causation, deduplication and effective-time validation. Storage arrival
handoffs use its existing storage.transfer.arrived.v1 contract; other peers consume
documented transport facts. No HTTP or RabbitMQ cross-department business path.

## Verification and delivery

Real PostgreSQL/RabbitMQ tests prove state transitions, competing assignments,
capacity, no early arrival, grant barriers, atomic audit/outbox, duplicate arrival,
reset fencing and providers. Production acceptance covers employee workflows,
multiple workers, dependency/worker recovery and Svelte browser behavior. A native
HELICS peer verifies domain handoffs without other department applications.
Persistent Compose and example external endpoint configuration support independent
role placement. Hosted/physical multi-host verification must be reported separately.
All builds and tests run in Docker through the shared guard with 20 GiB reserve.
