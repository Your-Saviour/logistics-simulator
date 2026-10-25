# Coordinated robot fleet

Fleet is an optional Python/Flask/PostgreSQL service for whole-unit transport.
Departments own inventory, production, shipping and custody transactions. Fleet
never connects to or writes departmental databases. The private departmental
adapters remain the only native HELICS owners; Twin is an optional observer.

Default departmental `FLEET_MODE=disabled` preserves existing operation. Explicit
`coordinated` mode waits on missing fleet service or physical proof and never
falls back to immediate movement. Synthetic carrier operations without a native
whole-unit transport path remain an explicit unsupported wait.

Production deployment assumption: each system runs separately with four
dedicated CPU cores. Local acceptance shares one Docker host and does not
establish production latency or rendering performance. Fleet currently has one
fenced scheduling worker; extra cores provide service/database capacity, while
route reservation waits must be assessed separately.

## Configuration

Use a private PostgreSQL database and private HTTP network. Keep environment
files, tokens and generated manifests untracked and readable only by their owner.
The fleet image is `logistics-simulator:fleet-v1`.

| Fleet environment | Meaning |
| --- | --- |
| `DATABASE_URL` | Fleet-owned PostgreSQL connection; no departmental SQL credentials. |
| `ROLE` | `initialize`, `api` or `worker`, selected by the image entrypoint. |
| `FLEET_RUN_ID`, `FLEET_EPOCH` | Explicit fleet UUID scope, independent of departmental UUIDs. |
| `FLEET_SCOPE` | JSON object mapping each participating department to its actual `run_id`, `epoch` and finite nonnegative `offset`. |
| `FLEET_SOURCES` | JSON array of `{name,url,username,password}` for authenticated departmental `/api/projection` polling. |
| `FLEET_TOKENS` | JSON map of distinct nonempty private tokens for department names and `observer`. A department token cannot impersonate another writer; observer access is read only. |
| `FLEET_SIZE` | Initialization count: default 8, supported range 1–16, using validated dedicated parking positions. |

For example, a source mapping has the shape
`{"storage":{"run_id":"<native UUID>","epoch":"<native UUID>","offset":0}}`.
The factory harness configures all four departments explicitly. A source URL is
the departmental API base URL; polling appends `/api/projection`. Use an identity
with `status:read` permission.

Every participating native department's **API, worker and controller** must share:

```dotenv
FLEET_MODE=coordinated
FLEET_URL=http://fleet-api:8000
FLEET_TOKEN=<this department's private token>
FLEET_RUN_ID=<fleet UUID>
FLEET_EPOCH=<fleet epoch UUID>
FLEET_TIME_OFFSET=0
```

The offset must match that department's `FLEET_SCOPE` entry. Requests and proofs
retain native effective times; a native grant is eligible for a fleet physical
fact only when `granted + offset >= effective_time`. GET job responses expose
the requesting department's mapped scope so clients can reject mismatches.
Credentials are absent from public fleet and departmental projections.

## Start and verify inside Docker

Run from the repository root. Build and test only in Docker, serialized through
`scripts/docker_guard.py --wait`; retain its default **20 GiB** free-space reserve.

```sh
make fleet-check
make stack-unit APP=storage
make stack-unit APP=manufacturing
make stack-unit APP=logistics
make stack-unit APP=shipping
make stack-unit APP=twin
```

The fleet check uses an isolated disposable PostgreSQL database and cleans up its
own deployment. The mixed native harness builds all four native backends and
adapters and adds an independent fleet database, initializer, API and worker:

```sh
make fleet-factory-check
FLEET_FACTORY_WITH_TWIN=1 make fleet-factory-check
```

The isolated factory fixture defaults to a 10-second native handoff quantum
and a 30-minute wall deadline. `FLEET_FACTORY_QUANTUM=20` accelerates its native
clock while preserving physical speeds, clearance and proof gates. Override the
deadline with `FLEET_FACTORY_TIMEOUT`; this changes the verifier wall budget, not
production motion. Production departments retain their normal configuration.

`FLEET_FACTORY_FAULT_ONLY=1` runs a separate short fault fixture: an actual
whole-unit load is carried, the disposable Storage adapter is killed, and Fleet
must retain its load and route claims without creating an arrival or receipt.

`FLEET_FACTORY_REUSE_IMAGES=1` skips explicit image builds when current images
already exist. Generated manifests, credentials and evidence use unique ignored
paths with private file permissions. The harness removes only its own disposable
containers and volumes. It does not attach existing deployment volumes.

For a persistent installation, first provision the private database/network and
an untracked owner-only environment file. Build the image through the guard:

```sh
python3 scripts/docker_guard.py --wait --label fleet-build -- \
  docker build -t logistics-simulator:fleet-v1 -f apps/fleet/Dockerfile .
```

Run `ROLE=initialize` once with the explicit run/epoch, source mappings and fleet
size before starting `ROLE=api` and `ROLE=worker` against the same database.
Initialization applies fleet migrations `001`–`005` with checksum checks. An
identical configuration can be revalidated; initialization does not replace an
existing physical scope, reset poses or clear reservations. Changed scope,
parking, size or layout requires explicit physical reconciliation. Preserve
persistent volumes and applied native migration checksums; no live cutover is
part of these commands.

## Physical and custody rules

Navigation uses the shared 0.25 m grid, directed lanes, obstacles, validated
endpoint service poses and dedicated parking. The robot body is 0.85 × 1.05 m;
loads are 0.80 × 0.86 m in plan. Planning expands envelopes by 0.15 m clearance,
includes turning and fork/load service sweeps, and excludes other static loads.
Pallet pockets and bounded lifting stages preserve shelf support contact without
permitting beam crossings. Translation uses simulation time; lift stages respect
0.5 m/s travel.

The worker atomically reserves a complete empty approach, loaded leg and empty
return, including service zones. Reservations remain until return to parking.
Disjoint routes may proceed together; overlapping lanes, intersections and shelf
levels sharing a service bay queue. This conservative policy provides no
same-lane following throughput guarantee. Idle parking remains occupied.

A durable native request is intent, not departure. The source waits for
`pickup_ready`, then commits its ordinary departure/in-transit state and a fleet
proof in the same native transaction. HTTP delivery follows commit through an
outbox. Receipt requires physical `arrival` **and** the existing accepted manifest
and departure token. Only the receiving department can commit business receipt.
Local moves reserve destination capacity, remain nonallocatable in transit and
confirm placement only after arrival. Batches commit each eligible unit
independently so an arrived unit can release its physical job while a sibling
waits for the shared route; aggregate completion does not withhold those proofs. Deferred waits move beyond the current
grant so native time requests can continue. Exact request/proof retries preserve
identity and effective time; conflicting immutable facts are rejected.

The HTTP shapes, stable UUIDv5 job identity and error codes are specified in
[`contracts/fleet/v1/README.md`](../../contracts/fleet/v1/README.md).

## Clock, outage and recovery

Fleet time is the minimum mapped **committed** time of configured participants.
A healthy executing observation with matching run/epoch, valid monotonic cursor
and at most five seconds of wall-age is required from every participant. Wall
time detects unavailability; it never moves a robot. Held, stale, reversed or
missing source observations hold the fleet with its loads and locks intact.
Future requests and proofs persist but wait for eligible fleet time.

On reconnect or recovery, the first authorized tick rebases timed phases across
the held interval and consumes no movement from that gap. Native late receipts
execute at an eligible current/future grant, never by rewriting history.

A process advisory lease and increasing worker generation fence competing or
stale workers. Recovery checks stored poses, layout digest and complete route
reservations. Inconsistent physical state is quarantined for reconciliation.
Epoch/layout replacement does not release occupied resources. No lock TTL,
automatic pruning, teleport or automatic live-state cutover resolves a fault.

The approved layout update retained all 800 endpoint IDs, heights and contract
version 1 while changing 93 coordinates in the shared catalog and four native
copies. Navigation carries `layout_revision=simu75-layout-2026-10-25`; a digest of
physical configuration fences existing fleet state. Rebuilding against changed
geometry does not authorize reusing an old physical database without validation.

## Optional Twin and evidence

Configure Twin API/projection with:

```dotenv
TWIN_FLEET_SOURCE={"url":"http://fleet-api:8000","token":"<observer token>"}
```

Twin renders reported robot/load poses and an optional reservation grid.
Coordinated source scopes disable historical invented journeys. Fleet loss keeps
the last report visibly stale; it does not enable replay fallback. Reduced motion
uses reported poses without tweening. Twin never schedules robots or simulation
time.

See [`docs/fleet-verification.md`](../../docs/fleet-verification.md) for observed
checks, the failed rendering budget and remaining acceptance work. Passing unit
checks does not establish mixed native acceptance or the throughput targets.
