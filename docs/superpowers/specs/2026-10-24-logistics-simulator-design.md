# Logistics and manufacturing simulator

Status: proposed design for approval. No production simulator has been implemented.

## Intent and agreed requirements

Create an autonomous small-to-medium business for CyberLab exercises. The priority is realistic business activity and resulting application, messaging, and database traffic. The user requested manufacturing, storage, logistics, and shipping; separately deployable Docker containers; background processing servers; database nodes; employee-facing frontends; and a combined digital twin showing simulation time, stock movements, dispatch, and delivery.

The user selected event-driven services using RabbitMQ and PostgreSQL. Worker nodes mean background processing servers, not employee workstations. Employee frontends are nevertheless required so a person can participate in business operations. Subsequent explicit requirements: integration with HELICS as part of a series of simulators, and FIVE SEPARATE WEBSITES. Manufacturing, storage, logistics and shipping must each stand alone as their own simulator; the fifth website is the combined digital twin. The user selected a dark control-room visual direction after rejecting the initial sparse light preview. A single application with departmental tabs does not meet this requirement.

## Approaches

1. Event-driven departmental APIs, queued background workers, and department-owned PostgreSQL databases. Selected by the user. Supports independent worker scaling, persistent work, and meaningful service dependencies, with more infrastructure to operate.
2. HTTP services with workers polling for jobs. Considered but not selected. Simpler infrastructure but more polling and weaker representation of distributed processing.

## Scope and proposed defaults

The remaining choices in this document are builder proposals, not additional user requirements. First release: one synthetic business, one factory, two warehouse locations, a dispatch depot, supplier and customer destinations, a small configurable product catalog with bills of materials, and a finite fleet. Supplier/customer destinations are simulated records and network clients, not integrations with real businesses. Products and staff are explicitly synthetic.

Autonomous activity uses the same APIs and authorization rules as employee actions. It creates orders, receipts, production jobs, picking tasks, transfers, and shipments, with business hours, processing durations, resource capacity, and configurable demand. Include an order desk in the shipping frontend rather than adding a fifth business department for the first release.

Non-goals: industrial control protocols, ERP integration, accounting/payroll, geographically accurate routing, 3D physics, optimization research, multi-tenant SaaS, and production high availability. A process failure must not silently lose or duplicate inventory or complete the same job twice. A digital twin must never show decorative movement as if it were authoritative business progress.

## Services and data ownership

| Component | API/frontend | Background workers | Persistent state |
| --- | --- | --- | --- |
| Manufacturing | Work orders, materials availability, production lines, release/hold actions | Schedule jobs, start batches, finish batches, record consumption and output | Production PostgreSQL |
| Storage | Inventory by location, receipts, reservations, picking, movement history | Receive supplies, allocate materials, reserve stock, pick, put away | Inventory PostgreSQL |
| Logistics | Transfer requests, vehicles, loading, journey status | Allocate vehicles, load, depart, arrive, unload | Transport PostgreSQL |
| Shipping | Customer order entry, order progress, packing, dispatch, tracking | Coordinate fulfilment, pack, request transport, mark delivered from transport events | Shipping PostgreSQL |
| Per-simulator control | Each simulator's scenario configuration, clock, run/pause/speed/reset | One active clock/scheduler and activity generator per simulator | Its own departmental PostgreSQL |
| Digital twin | Combined schematic, event feed, order drilldown, current simulation time | Dedicated event projection consumer | Read-model PostgreSQL |

Use Python/FastAPI for APIs, Python workers, React/TypeScript for frontends, RabbitMQ for messaging, PostgreSQL for storage. Exact supported versions and dependency pins are implementation choices to verify before coding.

Each departmental frontend is a separate website with its own base URL, app shell, login and navigation, independently served and talking only to its own API. Shared build-time UI components are allowed; runtime sharing of one frontend server, central login server, business-state engine or clock service is not required. Its API accepts authenticated commands and commits domain state plus an outbox entry in one database transaction; workers execute durable jobs and integrations. The combined frontend is a fifth independently deployed website using a projection API, never direct database access or direct browser connections to RabbitMQ. Optional links to other websites use configured external URLs and are not client-side workspace tabs.

Each of the four business simulators owns its run controller, local scheduler/clock driver, HELICS adapter and boundary inputs. The suite console aggregates these controllers; it is not required for their execution. Ship a separate Compose entry point and CyberLab module role/configuration for each business simulator and the twin, plus an umbrella configuration to deploy the connected suite. A shared source repository is acceptable; each application must have its own deployment/health checks and be able to start without the others.

In standalone mode, replace absent suppliers/customers/departments with explicitly configured synthetic boundary adapters: manufacturing can receive modeled components and output demand, storage can receive modeled receipts and pick/transfer requests, logistics can receive modeled transport requests and destinations, shipping can receive modeled orders, goods-ready notifications and carrier results. These are visible scenario choices, not hidden fallback after a connected real simulator fails. In connected mode, the paired simulator owns that boundary and synthetic sources for it are disabled to prevent duplicate activity.

## Container and machine topology

Distributed suite profile: four department application endpoints, four department worker endpoints, four departmental database endpoints, one optional shared RabbitMQ endpoint, one twin application endpoint and one twin database endpoint: 15 endpoint roles, plus a HELICS broker when not supplied by the surrounding federation. Each department runs its own controller/scheduler/HELICS-adapter containers alongside its API/worker roles. These are configurable role assignments, not a requirement to provision a fixed number of VMs every time. A standalone department can deploy its own RabbitMQ/PostgreSQL containers and has no dependency on shared suite infrastructure.

On each department application endpoint run separate frontend, API and controller containers. Run each department's worker pool on its worker endpoint and its PostgreSQL container on its database endpoint. Each department database contains its own domain, run-control, clock and outbox/inbox state under that department's ownership. RabbitMQ can be shared using isolated virtual hosts and identities or deployed separately per simulator. The twin endpoint runs frontend, projection API, and projection consumer containers with its own read-model database. The compact local Compose profile runs the same components on one Docker host; it may put the five logical databases on a single PostgreSQL instance with distinct users. Database sharing never permits cross-department table access. Separate website origins/ports are retained in local mode.

Worker replicas are configurable by department. A worker consumes only its own role's queues. Distributed deployments use explicit reachable hostnames/IPs for APIs, broker, and databases; Compose service names work only in the local profile. Do not assume a Docker bridge spans machines. APIs, broker, and database ports are restricted to the required lab peers; browser-facing frontends expose HTTP endpoints.

## Business lifecycle and invariants

1. A person or activity generator creates a customer order through shipping. Shipping records its lines and asks storage to reserve finished goods.
2. Storage reserves available quantities atomically. A shortage requests manufacturing for the missing quantity. Repeated reservation requests with the same key return the prior result.
3. Manufacturing requests storage reservations for the bill of materials. Missing inputs trigger a modeled supplier receipt after a configured lead time. Production starts only after materials have been issued.
4. Storage issues inputs once; manufacturing starts its timed batch. Completion creates an output receipt in storage. The simulator tracks materials issued, work in progress, output, and optional configured scrap.
5. Storage reserves and picks finished goods for the order. Logistics moves goods to the dispatch depot when needed, consuming vehicle capacity and journey time.
6. Shipping packs goods actually received at the depot and requests delivery. Logistics loads, departs, arrives, and unloads. Shipping marks delivery only after the corresponding transport completion event.

For first release, fulfil one complete order without partial shipments; backorders wait until all lines are available. No cancellation after materials are issued or goods are loaded; show the reason in employee UIs. Earlier cancellation releases reservations through explicit compensating commands. Inventory cannot be negative or double-reserved. Transfers and deliveries retain goods as in-transit stock until receipt; dispatch is not delivery. Production, vehicles, and storage capacity are finite. Generic defaults are editable in scenario configuration.

Employee actions include releasing/holding production, receiving supplies, reserving/picking stock, assigning a vehicle, dispatching a ready shipment, and entering/viewing an order. Automation and employee actions race through the same transactional preconditions: an already completed task returns its existing outcome or a clear conflict, never a duplicate side effect. Every screen shows operation progress and actionable failures rather than assuming a submitted command finished immediately.

## Messaging and recovery

Use durable exchanges and queues with persistent messages, publisher confirmations, manual acknowledgements, bounded retry queues, and dead-letter queues. RabbitMQ carries each simulator's internal commands, background jobs and domain events. HELICS carries the cross-simulator boundary exchanges in connected mode; avoid sending the same business action over both paths. Internal subscribers receive their own queues. Separate commands from immutable facts. Keep a transport-neutral boundary envelope so an explicit non-HELICS integration profile can be added later without changing domain ownership.

Envelope fields: event ID, schema version, type, run ID, correlation ID, causation ID, aggregate ID/version, originating service, simulation timestamp, wall-clock timestamp, and payload. Correlation follows an order through all four departments. Consumers deduplicate inside the same transaction as their state update. All API commands carry an idempotency key. Per-aggregate versions and expected state transitions reject stale/out-of-order updates; missing prerequisites defer/retry instead of applying invalid transitions.

PostgreSQL transactional outboxes avoid the database/message dual-write gap. Acknowledgement occurs after commit; publish-confirm plus consumer deduplication tolerates relay redelivery. Reconnect and retry use real time, not accelerated business time. Terminal failures are visible to operators. Restarting workers must resume durable work. Database outages hold work; broker outages accumulate unsent outbox entries; neither should fabricate completed operations.

## Simulation clock and run isolation

Standalone clock defaults per simulator: starts at 08:00 local business time, 1x speed, configurable timezone (Australia/Adelaide initially); operator can pause/resume and select 1x/5x/20x/60x. Persist the simulation-time anchor, wall-time anchor, speed, run ID, and pause state. Each simulator has one active scheduler under a database lease to avoid duplicate job scheduling. Long business operations use durable due-at jobs instead of sleeping workers or broker message TTLs. In HELICS mode the federation's time grants replace local clock advancement; wall-clock speed is an optional coordinated pacing policy, not a unilateral local time multiplier.

Standalone pause freezes that simulator's business time and prevents new business state transitions. Commands may be accepted as pending; queries, infrastructure health, outbox publication, and projection catch-up continue. A transition already committed before pause remains valid. A clock outage fails business processing closed; it must not advance business time based on each worker's private clock. Workers use their simulator's run/clock version and authoritative clock check at transition boundaries. In federated mode, a local hold does not imply that other simulators paused; a global pause requires coordination with the federation controller at an agreed boundary.

Reset is an explicit confirmed operator action. Quiesce generators and workers, allocate a new run ID, seed the new scenario, reset clock anchors, then resume. Every message, job, and domain row is scoped to a run; reject old-run messages so broker backlog cannot contaminate the new run. Old runs can remain read-only for inspection. In a federation, reset requires ending/recreating the affected federation run under its owner, not rewinding one live federate. Exact archival policy is left to implementation.

## HELICS integration

HELICS is a required integration, not a RabbitMQ substitute or a diagram-only claim. Official [HELICS](https://github.com/GMLC-TDC/HELICS) provides time-coordinated simulator exchange, with [Python bindings](https://python.helics.org/) and a BSD-3-Clause core. Pin a compatible HELICS/Python package version and verify the native binaries in the target Docker platforms before coding.

Use one HELICS combination federate per running business simulator, with its adapter in a dedicated process. All departments remain independently launchable. Each adapter is the sole owner of its HELICS handles; departmental workers do not call HELICS. Expose a common driver interface: initialize, ingest boundary inputs, next-event-time, advance-to-grant, collect outputs, checkpoint and finalize. Implement local and HELICS clock drivers around the same departmental domain model.

Federated execution at granted time T: ingest HELICS inputs, persist received messages with deduplication, execute eligible local commands/jobs, settle required local follow-up work, publish committed outputs, then request the next time. Track outstanding work in a durable ledger; an empty RabbitMQ queue does not prove a time boundary has completed. Never request the next time while workers can still produce current-time outputs. Granted times may be earlier than requested and cannot move backwards. Async time requests keep web/status handling responsive but do not authorize processing future-time jobs. Define a positive minimum time quantum and explicit next-time policy for employee commands and cross-department reactions; do not silently claim zero-delay same-time convergence. The default proposed quantum is one simulation second, configurable to the surrounding federation's contract.

Use typed value publications/subscriptions for boundary conditions where current state matters (for example available power, demanded power, transport capacity). Use HELICS message endpoints for discrete orders, supply requests, transfer requests, departures, arrivals and acknowledgements where every occurrence matters. All external interface names, units and routing are versioned configuration. Proposed common envelope: schema version, federation/run/epoch IDs, event ID, correlation ID, source/destination simulator, effective simulation seconds, aggregate ID/sequence and payload. Reject or explicitly defer late commands; do not apply a past event to already committed history. JSON schemas validate business payloads; HELICS does not do that for us.

Each paired boundary has one documented owner: storage issues/reserves inventory, manufacturing owns batches, logistics owns journeys, shipping owns customer order/shipment state. A per-boundary profile selects either a synthetic adapter or a HELICS peer. First release demonstrates the connected four-department chain plus a small external peer stub (for example power availability limiting factory capacity) to prove compatibility with simulators outside this repository. Exact interfaces of the user's other simulators are not yet supplied; provide a documented sample federation and configurable mappings, and do not claim compatibility with unknown existing contracts until tested against them.

The digital twin observes configured simulator APIs/projection streams and their granted/committed times. It is not required to be a time-regulating HELICS participant. It can run alone with no sources connected and clearly show that state, or monitor any subset of simulators. It must not become a required dependency of a business simulator. HELICS causally coordinates time; it does not make every simulator have identical committed time at each wall-clock instant. Show per-source watermarks and label an aligned view at the minimum compatible committed watermark; never imply a federation-wide atomic database snapshot. Global controls appear only when the twin is configured with the federation controller's authority; local department controls remain in each simulator's operator area.

Networking: prefer explicitly configured tcp_ss cores for the documented cross-host profile; use routable broker and advertised local addresses/ports. Compose DNS is local to its Docker network. Distinguish logical HELICS endpoints from TCP ports and HTTP APIs. Provide a local example broker and support an external broker in CyberLab; the surrounding series may already own it. Docker/Ansible orchestrates processes, HELICS synchronizes models. See official [networking documentation](https://docs.helics.org/en/main/user-guide/advanced_topics/networking.html).

Failure policy: idempotently retry worker failures without advancing the affected simulator past unfinished work. Broker/adapter failure marks the run stalled or failed, never silently switches to standalone time or synthetic peers. HELICS, RabbitMQ and PostgreSQL do not share an atomic transaction; require event deduplication across simulators and use federation abort/restart from an agreed run/checkpoint for unrecoverable publication failures. A time barrier is not a distributed database snapshot. Federation pause/resume/reset must report its actual acknowledged scope and cannot unilaterally rewind peers. Verify pause-barrier semantics against the pinned HELICS version.

## Employee frontends

Four separate websites, each with its own app shell and department navigation, optionally using a shared build-time component library. Each supports login, searchable task lists, status filters, a record detail panel, valid workflow actions, and an audit history. A user sees business language; queues and node health belong in each simulator's operator area or the combined console. Each has a complete standalone seeded scenario and its own start/stop/pause controls as appropriate to the selected clock driver. The first-release look may be consistent across sites; architecture permits independent versions and future legacy-style frontend replacements without migrating all five applications.

- Manufacturing: production board, line capacity, material shortages, work-order detail, release/hold controls.
- Storage: location inventory with on-hand/reserved/available quantities, receipts, pick lists, movement ledger.
- Logistics: vehicle availability, transfer jobs, load quantities, origins/destinations, departure and ETA.
- Shipping: customer order desk, fulfilment status, packing tasks, ready dispatches, delivery tracking.

Proposed access model: locally provisioned employee identities with department roles, automated service identities with scoped permissions, and a simulation-operator role for clock/scenario/reset controls. An employee account may hold multiple department roles, but employee permissions do not include simulation administration. No external identity provider required in the first release. Passwords and service secrets are configured at deployment and are not committed defaults.

## Combined digital twin

An interactive 2D schematic, not a literal geographic map: supplier -> raw-material store -> factory -> finished-goods warehouse -> dispatch depot -> customer. Show stock per location, active production, vehicles and loads in transit, ready-to-dispatch shipments, and deliveries. Select a location, batch, order, or shipment to see quantities, linked records, current activity, and expected completion in simulation time. Link back to the relevant employee frontend through configured base URLs.

A prominent simulation clock displays date/time, timezone, running/paused state, and speed. Operator-only controls change run state. A feed lists business events. A separate infrastructure view lists service readiness, worker availability, queue backlog, dead-letter failures, and projection freshness.

The twin projects the exact events committed by the business services. A vehicle position is an explicitly estimated interpolation between confirmed departure and planned arrival in simulation time, never proof of delivery. Hold it at an awaiting-confirmation state if arrival is overdue; do not animate it into a completed delivery. Pause freezes interpolation. Connection failure/stale projections remain visibly stale, with the last received simulation timestamp; do not keep inventing movement.

Projection consumer updates its read model and deduplication ledger transactionally. Reconnect sends a current snapshot plus a cursor, then live updates through SSE, with polling fallback. Snapshot/cursor handling must not skip events between initial load and subscription. Preserve event history for projection rebuild from the active run; RabbitMQ acknowledgement history alone is not replay storage.

Visual direction selected by user: dark control-room view with detailed facility layout. Use warm-black surfaces, a monospace typeface, one amber signal accent and thin structural borders. The twin has a large isometric facility schematic with production cells, storage racks, loading bays and vehicles. Each of the other four websites has its own task-focused app shell rather than switching departments inside one app. The preview contains clearly labeled illustrative records and only demonstrates navigation/layout; it is not the running simulator. Initial sparse light preview was rejected and is not the design to implement.

## CyberLab integration and repository boundaries

Target integration is a feature branch of ../Cyberlab-main. Existing modules use manifest.yml, machines.yml, values.yml, and Ansible playbooks; follow those contracts for separately selectable manufacturing, storage, logistics, shipping and twin module configurations plus an umbrella suite, Docker dependency, configurable machine roles, source installation, persistence, networking, and readiness checks. Provide opt-in lab configurations rather than changing the default lab deployment. Exact module naming and shared installer structure are planning decisions; standalone deployment is mandatory.

Proposed source arrangement: develop the simulator in this logistics-simulator repository and integrate a pinned source revision into the CyberLab feature branch using its existing GitHub source-install pattern. Resolve the exact supported source-install contract during planning; if it cannot pin this repository cleanly, document the alternative before implementation. Do not silently duplicate maintained source across both repositories. Obtain required filesystem approval before writes to the adjacent repository or its Git metadata, which lie outside this workspace's writable roots.

Use the SIMU Jira project for implementation work items after design approval. Initial breakdown: service/data contracts, RabbitMQ/outbox infrastructure, four departmental workflows, autonomous activity/clock, employee UIs, digital twin, distributed deployment, end-to-end verification. Jira issue creation is not messaging other people; do not post unrelated comments or notifications.

## Delivery and validation

Deliver runnable local Compose deployments for each business simulator and the connected suite, documented distributed configuration, four employee websites, a separate twin website, standalone seeded scenarios, a HELICS sample federation and external-peer stub, CyberLab module/configurations on a feature branch, and SIMU work items linked to delivered work. Implementation plan sequences a complete order lifecycle before broadening UI features; all four employee frontends and the combined twin remain required first-release deliverables. Open-source reuse assessment is recorded in docs/research/2026-10-24-open-source-simulator-assessment.md; bounded reuse is preferred over importing a central ERP that removes the required service independence.

Acceptance checks:

- A seeded order reaches delivery with correlated records across all four departments, correct material accounting, and visible progress in every applicable frontend and the twin.
- An employee command and autonomous command use the same validation and produce the same domain events.
- Duplicate/redelivered work and concurrent reservations cannot consume or reserve stock twice.
- Multiple replicas of at least one worker pool process jobs without duplicate business effects.
- Stop/restart a worker and broker; queued and outbox work recovers. A stopped service causes visible downstream waiting, not impossible progress.
- Pause/speed changes affect due jobs and twin interpolation consistently; reset excludes old-run messages.
- Reload/reconnect the twin without missing state, visibly mark disconnected/stale state, and distinguish planned arrival from confirmed delivery.
- Start each of the four business simulators using only its own containers and explicitly configured synthetic boundary adapters; its employee website remains usable with all other simulators and the twin stopped.
- Expose five independent website URLs. Stop any one frontend and verify the other four remain reachable. No department switches through shared client-side application navigation.
- Run four business HELICS federates plus an external peer stub through the broker; verify grant-gated processing and a cross-simulator condition affecting the business lifecycle. Verify a delayed grant does not advance local jobs, and requested/granted/committed time remain distinct.
- Verify federated local hold versus federation-wide pause, orderly finalization, stalled peer behavior and new-epoch reset. The twin monitors a subset without requiring absent simulators.
- Exercise an independently hosted worker with externally configured broker/database/API addresses; if multiple live machines are unavailable, report that limitation explicitly and verify topology/configuration separately.
- Validate CyberLab module and Ansible configuration with repository checks. Live cloud provisioning is a separate explicitly authorized deployment step, not implied by creating the module.

Builder chooses exact schemas, supported versions, queue names, UI component tooling, replica counts, seed catalog, and test fixtures within these contracts. Any removal of a required department/frontend or change from distributed services to a single central business-state engine requires revisiting the design.
