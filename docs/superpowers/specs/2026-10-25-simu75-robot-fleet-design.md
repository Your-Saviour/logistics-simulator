# SIMU-75: coordinated robot fleet

Status: approved by the user on 2026-10-25; implementation in progress.
Subsequent steering: planner latency may exceed the proposed 100 ms target by
a modest amount; report measured latency. The user requested preparation of
layout corrections after the fixed-floor audit found existing physical overlaps.
Those corrections are a separate reviewable proposal before application.

## Intent and agreed direction

Robots carry whole handling units through the fixed facility without overlapping
one another or their loads. Departments keep authority over inventory, production,
shipping and custody. Twin displays reported operations and remains optional.

The user accepted developing a Python/PostgreSQL service approach and then
requested multiple traffic lanes and a floor grid for routing. This document
incorporates both. Numerical settings below are proposed engineering defaults,
not previously approved requirements or measured results.

## Existing foundations and constraints

- `contracts/handling/v1/facility.json` records physical endpoints in metres,
  shelf elevations, access points and five lane centre lines. It does not define
  traversable floor polygons or robot clearance.
- `apps/twin/web/src/journeys.ts` invents visual trips after business movement
  observations. Its shortest north/south path is not an operational route proof.
- `Facility3D.tsx` defines rack, truck, machine and wall geometry. Those obstacle
  footprints must become shared contract data before navigation uses the floor.
- The existing offer/accept/depart/receive/acknowledge protocol persists custody
  across independent databases. Robot arrival must become an additional receipt
  prerequisite in coordinated mode, never a replacement for departure proof.
- Native HELICS remains in departmental adapters. The fleet has no native handles
  and Twin does not control simulation time.
- Preserve all five websites, existing volumes, applied migration checksums and
  standalone departmental operation when coordinated mode is disabled.
- Run application builds and tests only in Docker through `docker_guard.py`,
  retaining its 20 GiB reserve. No deployment or volume cutover is authorized.

## Approaches

1. Reserve existing visual polylines for entire trips. Simple, but inherits
   unvalidated geometry and prevents useful parallel lane traffic.
2. **Selected direction: grid routing with multiple directed lanes and durable
   reservations.** Share obstacle geometry between scheduler and Twin, use A*
   on valid grid states, and reserve conflicting physical space. More geometry
   work initially; supports explainable detours and simultaneous movements.
3. Time-expanded multi-agent routing with future reservation slots. Higher
   potential throughput, but delays, clock holds and receipt waits require
   replanning future claims safely. Defer this optimization until measured demand
   justifies it.

For the initial implementation of option 2, acquire a complete movement plan's
resources atomically, rather than holding a partial path while requesting more.
Separate directed lanes and disjoint routes can run concurrently. Shared narrow
sections queue. This is intentionally conservative and its throughput is an
acceptance measurement, not a promised result.

## Service and deployment

Add `apps/fleet`, a Python service with Flask HTTP API, a dedicated worker and its
own PostgreSQL database. Reuse established dependency versions where compatible
and preserve locks. The API admits idempotent departmental requests and exposes
read-only fleet snapshots; the worker alone assigns robots, plans and executes.
Use a PostgreSQL advisory lock plus a monotonically increasing worker generation
to fence concurrent workers and stale HTTP callbacks. Transactions check current
run/epoch and worker generation.

Fleet is independently deployable and optional. Coordinated mode is an explicit
run configuration shared by participating departments. Missing fleet in that
mode produces a visible wait; it cannot silently revert to immediate completion.
Historical/default mode keeps its existing behavior. Twin can be absent in either
mode. No sixth website is required.

## Grid, geometry and lanes

Add a versioned navigation contract alongside the existing facility catalog.
Keep existing endpoint identifiers and coordinates. Start with 0.25 m square
cells, a fixed world origin and floor bounds matching the rendered facility.
Store obstacles, directed lane corridors, intersections, endpoint approach poses,
service zones and dedicated parking cells in shared data. Twin renders the same
geometry. The grid overlay is optional, with separate styling for blocked,
available and reserved cells and arrows for lane direction.

Wide corridors support separate opposing lanes where measured free width permits;
narrow aisles remain exclusive single-lane resources. Do not paint two lanes into
space that cannot accommodate two loaded robots. Existing lane centre lines are
inputs to validation, not permission to cross racks, machine bases or truck beds.
Loading from a truck uses a floor service pose and bounded fork reach.

Proposed robot body is 0.85 m wide by 1.05 m long; current load visuals are
0.80 by 0.86 m in plan. Use 0.15 m minimum clearance to obstacles and other moving
envelopes. Validate wheels, forks, carried load, heading changes and extended
pickup/placement sweeps; cell-centre separation alone is insufficient. A narrow
aisle may require a smaller validated vehicle model or an explicit unsupported
route. Never shrink collision bounds just to make a test pass.

Use orthogonal grid moves and cardinal headings. Turning occupies the swept
envelope; no diagonal corner cutting. Exact off-grid endpoint approaches are
validated connectors with their full swept envelopes. Shelf bays at different
heights share the same floor service exclusion zone. Height affects fork travel,
not permission for robots to overlap beneath different shelves.

## Routing, reservations and fairness

Each robot has a persistent identity, pose and dedicated parking position.
Parking lies outside through lanes and service zones and remains occupied when
idle. Plan empty travel from the actual robot pose to pickup, loaded travel to
placement, and empty return to its reserved parking position. Robots never appear
at pickup or disappear after placement.

Deterministic A* uses lane direction, obstacle clearance and occupied envelopes.
Stable cell/heading ordering breaks equal-cost ties. Reserve the complete swept
cell set and pickup/drop service zones for the round trip in one transaction.
An exclusion table with a unique active resource key prevents double grants.
Opposite movement over an edge and turns through shared intersections conflict
even when their endpoint cells differ. The initial policy reserves whole paths
until the robot has returned to parking; it therefore provides conservative
headway and does not support same-lane following within a reserved path.

Waiting jobs hold no route resources. Retry a valid alternate lane/path before
waiting. Queue by durable admission sequence with stable identity tie breaking.
After 30 simulation seconds waiting, protect the oldest feasible job's required
resources from new conflicting grants while already moving robots finish. Other
disjoint jobs may continue. Expose blockers and oldest wait age. No starvation
claim applies while a required department is unavailable or an endpoint is held
indefinitely by business state; report that condition distinctly.

Atomic complete-path acquisition prevents ordinary hold-and-wait cycles.
Detect inconsistent reservations, unreachable return paths and unexpected blocked
poses; hold affected traffic and expose an actionable fault. Never expire a
physical occupancy lock or teleport a robot to resolve a conflict. Replan only
from the last committed pose, with a safe replacement acquired atomically.

## Jobs and persistence

Persist runs, robot configuration and pose, jobs, assignments, immutable route
plans, active reservations, clock observations, inbox deduplication, transactional
outbox, departmental proofs and audit events. Job identity derives from producer,
producer run/epoch, command/handoff identity, custody generation and movement leg.
Identical retries return the same job; conflicting immutable fields return 409.

Lifecycle: queued, assigned, approaching, awaiting_departure, picking_up,
carrying, placing, awaiting_receipt, returning, completed; held/quarantined
records preserve the prior phase and reason. Assignment always binds one robot
and one whole unit. Partial unique indexes enforce at most one live job per robot
and unit within the fleet scope. Admission also checks participating source scopes
and their explicit mapping to the fleet run; equal UUIDs across departments are
not assumed.

Progress and pose change in the same transaction as phase and reservation state.
The stable plan contains distances, headings, fork stages and phase durations.
Proposed speeds are 1 m/s translation and 0.5 m/s lift, with explicit turn and
attachment stages. Record time in simulation seconds; no browser timer executes
work. A load attaches once after valid departure and remains attached throughout
travel and receipt wait until validated placement/receipt reconciliation permits
release. The exact placement/receipt display transition must never draw both a
carried and a static copy of the same unit.

## Departmental integration

Add authenticated, versioned fleet job/proof contracts and integration in all four
business backends, including local shelving/retrieval and manufacturing transfers.
Do not derive operational requests from Twin's historical movement feed.

Departments reserve source units and destination capacity before requesting
transport. The fleet reserves a robot and safe route and approaches pickup.
Pickup readiness allows the owning department to commit departure/in-transit
state with its existing version/custody checks. Fleet pickup requires that durable
proof; an unavailable source leaves the robot waiting safely at the reserved bay.

After physical placement readiness, fleet emits an idempotent arrival proof bound
to job, unit, endpoint, producer scopes, custody generation and route version.
The department validates that proof together with existing accepted manifest and
departure token, then commits receipt and publishes its ordinary acknowledgement.
Fleet never updates departmental SQL. Lost responses replay stable inbox/outbox
identities. An arrival proof alone cannot allocate stock or create receipt.

For moves within one department, add the same reserve/depart/arrive/commit stages
under its local transaction conventions. Manufacturing consumption waits for its
input placement; output creation retains existing recipe/lineage ownership.
Outbound truck loading and inbound unloading use the same physical gate.

## Simulation clock, pause and fencing

The worker consumes authenticated departmental snapshots containing committed
simulation time, execution state, monotonic cursor and run/epoch. Define fleet
time as the minimum committed time of all configured participating departments,
mapped to a common simulation origin. Nonparticipants are excluded explicitly.
Only healthy executing observations authorize advancement. Duplicate or lower
observations never advance the fleet. In standalone coordinated mode, use the
same common origin and committed-time contract, without native HELICS.

Every request and proof includes its producer's committed effective time and
the configured mapping to fleet time. Job approach cannot start before the
request's mapped release time; pickup cannot start before both departure proof
time and committed approach completion. Arrival follows all physical phase
durations and prerequisites. A future producer event is persisted but ineligible
while the fleet minimum clock is behind it. Receipt executes only at a receiving
department's eligible grant at or after the mapped arrival time and its own
prerequisites; a delayed proof is applied at a current/future eligible boundary,
never backdated into committed history. Phase updates expose these causal times
for audit and replay. Include them in boundary calculations and skewed-clock tests.

Department controllers continue their native requests while robot jobs wait;
waiting for transport is durable deferred business work, not unfinished work at
the current grant that would prevent the next request. Time requests must respect
the next eligible physical/business boundary. Tests must prove the federation
can advance while waiting for a robot, and that receipt cannot execute before
the fleet arrival time. No fleet process joins or reconstructs a native session.

Hold/pause stops pose advancement. Missing source data or a heartbeat older than
5 wall seconds freezes the fleet globally, retaining loads and reservations.
Wall time detects unavailability only; it never advances simulation. On reconnect,
validate all scopes and proofs before resuming. Do not animate missed intervals
using wall time or extrapolate beyond a reported pose in Twin.

Epoch replacement retires old jobs and proofs for execution, but retains their
physical occupancy as quarantined state until coordinated reconciliation assigns
an explicit safe new starting state. It must not release locks underneath robots
or silently reuse an old load in a new run.

## Restart and failure recovery

On worker restart, acquire a new fenced generation, read committed poses and
reservations, verify uniqueness/geometry/proofs, then resume from the same phase
only with healthy matching clock scopes. A lost transaction advances nothing;
a committed transaction is replayed as committed. Retain loaded and idle robot
occupancy through database/API/source outages. No TTL releases physical locks.
If the database is unavailable, the worker cannot move. Stale workers cannot
commit after takeover. Native adapter loss follows the existing stalled-epoch
rule rather than an automatic synthetic fallback.

## Twin behavior

Configure an optional fleet source distinct from departmental projection sources.
Snapshots expose mode, run/epoch mappings, monotonic revision, committed time,
robot/job/unit IDs, pose, heading, fork/load transform, route, phase, progress,
waiting reason, blockers and freshness. Validate contract and revision before
display. Coordinated scopes disable JourneyQueue; fleet loss keeps the last
reported poses visibly stale rather than switching to invented replay.

Render loaded robots and idle robots with stable identity, optional selection,
job/load details and the optional grid/reservation overlay. Selection never gates
motion. Reduced motion shows reported poses without tweening. Historical replay
remains explicitly labelled and separate from operational mode. Reuse instancing
and the static geometry cache; draw no duplicate static load during transport.

## Budgets and Docker acceptance

Propose a default fleet of 8 robots; support 16 in stress checks. Before fixing
this default, measure route availability and throughput for 4/8/16 robots.
Use a deterministic balanced mix of inbound unload, shelf putaway/retrieval,
manufacturing input/output transfers and outbound load for 600 simulation seconds
after warmup. Report completions/minute, maximum/p95 queue waits, utilization,
route failures and blocked reasons for each fleet size. Initial target: at least
12 completed loaded legs/minute at 8 robots with healthy sources, with no growing
queue at that offered rate. If topology cannot achieve it, present measured
constraints before changing either reservation policy or target.

Target worker scheduling/commit p95 below 100 ms at 16 robots and 256 queued
jobs, and Twin render p95 at most 20 ms over 30 seconds with 500 units and 16
reported robots on the recorded local GPU/container setup. Report software/GPU
details and distinguish targets from results. Verify overlay-on performance too.

Required checks:

- Geometry validation for every supported endpoint approach, parking, loaded
  clearance, turns, multiple shelf levels, walls, machines and trucks.
- Deterministic same-bay, opposing-lane, intersection, following-distance,
  alternate-route and sustained-contention scenarios; assert continuous swept
  envelope separation, not just disjoint integer cell IDs.
- Simultaneous disjoint movement for all four workflow categories.
- Duplicate/conflicting admission, competing workers, stale worker generations,
  exactly one active robot/unit assignment and atomic audits.
- Process termination before/after each custody/phase/reservation commit and lost
  HTTP replies; safe database/source/fleet outage recovery with no lost loads.
- Pause, stale snapshots, reconnect, unequal early grants, epoch replacement and
  native adapter loss; no fabricated movement or premature receipt.
- Each native backend's coordinated gates and disabled-mode regressions;
  mixed-language HELICS transport scenario with Twin absent and present.
- Browser identity/wait/grid/selection/reduced-motion/fallback checks, load
  attachment and no duplicate placement, with screenshots and measured budgets.

Add numbered migrations only. Provide isolated fleet unit/stack acceptance and
extend mixed checks. Record exact guarded commands and actual results; preserve
existing five-stack checks. Layout editing, splitting/repacking, full physics and
PLC/FUXA integration remain outside this design.

## Decisions still requiring approval

Approve this design's grid/lane model, conservative complete-trip reservations,
Python/Flask/PostgreSQL service, committed-source clock policy, fail-closed behavior,
and proposed geometry/fleet/performance defaults before implementation. The builder
may choose module decomposition, internal indexes and test fixtures within these
contracts; topology or budget failures require evidence and a design revision.
