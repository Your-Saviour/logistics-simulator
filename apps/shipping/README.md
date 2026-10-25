# Shipping V1 (SIMU-5)

Shipping owns its Laravel 13 API, Blade/Livewire 4 website, PostgreSQL transaction
ledger, RabbitMQ worker and simulation-time controller. PHP owns all business
execution and durable scheduling. It implements complete customer orders, stock/production fulfilment, physical
receipts, packing, dispatch and confirmed delivery. See
[Shipping V1 operations](../../docs/shipping-v1.md) for domain commands, standalone
packaging and connected provider contracts. The sample quantity API remains for
foundation compatibility.
The connected clock is the separately deployed department-local HTTP
HELICS adapter described in `docs/adapter-protocol.md`.

The website uses the existing Industrial direction: warm black `#0B0C0A`, amber
`#FFB800`, monospace type, tabular clock numerals and flat rules. The clock and
committed/granted/requested strip display persisted watermarks. Providers,
process health, sample work and audit rows come from this deployment's database.
No sample telemetry is invented to populate an empty screen.

## Build and isolated tests

Run from the repository root. Every Docker workload uses the repository guard,
which serializes work and stops before free host space drops below 20 GiB. Do
not run service tests or PHP/Composer on the base host. The test compose project
has no published host ports and uses its own database, broker and sessions.

```sh
python3 scripts/docker_guard.py --label shipping-deps -- docker build --target dependencies -f apps/shipping/Dockerfile -t logistics-simulator:shipping-dependencies .
python3 scripts/docker_guard.py --label shipping-build -- docker build -f apps/shipping/Dockerfile -t logistics-simulator:shipping .
python3 scripts/docker_guard.py --label shipping-test-dependencies -- docker compose -f apps/shipping/compose.smoke.yml up -d --wait shipping-db shipping-broker
```

Run the native suite with worker/controller stopped. The ledger harness confirms
and resets its disposable test run, retains old runs, and briefly alters/restores
one migration checksum and its own native-state fixtures. The HTTP API may remain
up, but no other test should mutate this test database concurrently.

```sh
python3 scripts/docker_guard.py --label shipping-native-suite -- docker run --rm --memory=384m --network shipping-foundation-smoke_default --entrypoint sh --env-file apps/shipping/tests/smoke.env -v "$PWD/apps/shipping/src:/app/src:ro" -v "$PWD/apps/shipping/tests:/app/tests:ro" -v "$PWD/apps/shipping/migrations:/app/migrations:ro" -v "$PWD/apps/shipping/bootstrap:/app/bootstrap" -v "$PWD/apps/shipping/config:/app/config:ro" -v "$PWD/apps/shipping/routes:/app/routes:ro" -v "$PWD/apps/shipping/storage:/app/storage" -v "$PWD/apps/shipping/resources:/app/resources:ro" logistics-simulator:shipping-dependencies /app/tests/all.sh
python3 scripts/docker_guard.py --label shipping-start -- docker compose -f apps/shipping/compose.smoke.yml up -d --no-build shipping-api shipping-worker shipping-controller
python3 scripts/docker_guard.py --label shipping-http -- docker run --rm --memory=192m --network shipping-foundation-smoke_default --entrypoint php -v "$PWD/apps/shipping/tests:/app/tests:ro" -v "$PWD/contracts:/contracts:ro" logistics-simulator:shipping-dependencies /app/tests/http.php
python3 scripts/docker_guard.py --label shipping-session-http -- docker run --rm --memory=192m --network shipping-foundation-smoke_default --entrypoint php -v "$PWD/apps/shipping/tests:/app/tests:ro" logistics-simulator:shipping-dependencies /app/tests/web_http.php
```

`tests/run.php` covers strict quantities, unknown fields, finite times, timezone,
DST and seeded quantity/UUID compatibility. `security.php` covers independent
role scopes and server-session identity binding. `ledger.php` uses real PostgreSQL
and RabbitMQ, six concurrent delivery processes, earlier grants, barriers,
reset fencing, bounded retries, migration-checksum rejection, mandatory returned
publication and unacknowledged database-outage redelivery. `adapter.php` runs a
local HTTP transport fixture to verify committed intents, exact request replay
on a lost reply, poll fencing and refusal to restore native sessions from SQL.
That fixture does not claim to simulate native HELICS. `controller_outage.php`
terminates only the disposable controller SQL session and verifies that transient
connection loss retains its standalone run for restart.

`http.php` exercises `contracts/http/v1/jobs.fixtures.json`, role denials, audits,
hold, native PHP controller/worker execution, idempotency replay/body conflict and
new-epoch reset. `web_http.php` signs in through actual CSRF-protected forms,
checks the signed Livewire snapshot and sends an employee-forged operator action
to the real update route; server-side authorization denies it. `ui_scope.php`
ensures a service with no status scope cannot read Livewire data.

For the concurrent native finalize API fixture, first stop worker/controller,
then execute `tests/finalize.php` in the same test container environment/network
used for the native suite. It holds the PostgreSQL run lock while an API finalize
request waits, commits a pending native intent and verifies HTTP 409; initializing
and unsettled receives also block. A settled native finalization records a durable
`finalizing` intent and remains fenced until transport completion.

Stopping `docker compose ... stop` affects only this test project and retains its
volumes. Coordinate cleanup of these test images/caches/volumes with the root
agent; do not prune unrelated deployments or databases.

## Runtime and identities

The production image runs patched PHP 8.4.27 under FrankenPHP/Caddy on port 8000.
It uses two PHP threads and bounded Go runtime defaults. `ROLE=api|worker|controller`
selects the main entry point. `SIMULATOR=shipping` is required. Worker/controller
roles are PHP Artisan processes; Laravel wall-clock queue delays are not used to
represent simulation-time jobs. All roles migrate/check the same department-local
ledger before entering their respective process.

Supply `DATABASE_URL`, `AMQP_URL`, `APP_USERNAME` (default `operator`),
`APP_PASSWORD` and an independent, strong `APP_KEY=base64:<32 random bytes>`.
Generate and retain APP_KEY as a deployment secret, for example with Laravel's
key generator inside the guarded toolchain. Startup never generates/replaces it.
`APP_URL` should match the website origin. Set `SESSION_SECURE_COOKIE=true` behind
an HTTPS ingress; same-site Strict and HttpOnly are always enabled. Sessions use
private department-local files, never a central identity service. Preserve/share
the session directory only among this deployment's API replicas when required.

`APP_IDENTITIES` is an array of username/password/role objects. Employee defaults
are status:read/jobs:write; operator also has runs:control/audit:read. Service
scopes default to none and must be explicitly narrowed from status:read/jobs:write.
Duplicate usernames, empty credentials and scopes beyond a role fail startup.
Basic authentication protects the existing API. Browser forms establish a private
server session containing username and a keyed credential/version binding. No
password is stored in browser storage or public Livewire state. Every Livewire
request resolves the configured identity again, requires status:read, and checks
the required scope for each public command. Client-supplied roles are never used.

Existing routes remain `/api/health/live`, `/api/health/ready`, `/api/status`,
`/api/jobs`, `/api/control/{action}`, `/api/sources`, `/api/audit`. The website and
API share the same origin/image; there is no separate JavaScript build or proxy
backend. API Basic credentials and web sessions are independently authenticated.

## Clock, providers and connected recovery

`CLOCK_MODE=standalone` uses synthetic `orders`, `goods` and `carrier` boundaries.
`BOUNDARY_PROVIDERS` must name exactly those boundaries. `HANDOFF_QUANTUM` defaults
to one finite second and must be at least one. `SCENARIO` preserves seed, IANA
timezone, offset-bearing start, local business hours, weekdays (Monday=0) and
interval. Elapsed simulation seconds are UTC seconds; openings account for DST
gaps/repeated hours. `AUTONOMOUS_SAMPLE=true` seeds stable input IDs and quantities
through the same validated ledger as employee samples. The test fixture disables
it to isolate employee effects. Local hold stops new grants; standalone speed is
1/5/20/60. Reset confirms the current run ID, archives it and creates a new epoch.

Connected mode also requires `FEDERATION_ID`, `FEDERATION_RUN_ID`,
`FEDERATION_EPOCH`, `HELICS_ADAPTER_URL`, `HELICS_ADAPTER_TOKEN`, explicit providers,
`HELICS_PEERS` and nonempty `HELICS_OUTPUTS` using the documented routing shapes.
The separate adapter owns `HELICS_CONFIG` and native HELICS. `HELICS_TIMEOUT_SECONDS`
defaults to 60. No synthetic fallback or unilateral live rejoin is permitted.

Native Storage reservations declare one to eight canonical units per line.
Shipping retains those identities as promises, then admits the complete order
to finite receiving positions before requesting picks. Other receipts and
intakes respect these promised positions. Capacity waits remain durable jobs;
an order exceeding the facility's complete footprint becomes blocked with its
source reservations retained. Cancellation remains available before any pick
intent begins, including while admission waits for capacity.

Transfer requests include the receiver-assigned `unit_destinations` map. Only
matching departure proofs import those units and continue their counters.
Complete local custody receipts make the order ready; delayed source receipt
confirmations settle intent history while preserving onward shipment state.
The website and command handler share cancellation eligibility.

The controller holds a PostgreSQL session lease. It persists its native session
and each operation's request ID/body before HTTP; retries use the original
request. Poll intents fence finalization before receiving messages. Only committed
grants and inbox transactions, followed by confirmed native receive acknowledgement,
clear that fence. SQL completion and output barriers authorize the next request;
preparing requested time and marking native pending are one locked transaction.
Earlier native grants authorize only their actual time. A standalone controller
database connection failure releases its lease and exits while retaining the
held/running run, scenario, epoch and watermarks; restart it after database recovery
without a reset. Connected native loss remains a stalled-epoch recovery case. Outgoing retries retain
stable event identity, with receiver inbox deduplication mandatory.

Connected finalize rejects initialization, pending native requests, unsettled
receives and due work/outputs. It records `finalizing` before native finalization,
then becomes `finalized` only after confirmed completion. Native loss or ambiguous
transport failure stalls the epoch. A replacement controller cannot reconstruct
or resume a native session from SQL. Recovery requires federation-owner coordination
and a new epoch, retaining old data/journals for diagnosis.

## Dependencies and preserved-state cutover

`composer.lock` is application-owned and pins Laravel 13.38.0, Livewire 4.4.8,
php-amqplib 3.7.5 and their complete dependency graph. Docker installs it with
platform checks enabled. The patched FrankenPHP base is pinned by digest in both
Dockerfiles. Required sockets are installed explicitly; no platform requirement
is ignored. Composer cache is cleared in the dependency stage. No host vendor or
node_modules tree is required in the build context.

Publisher confirms and mandatory returns are both handled before SQL marks an
outbox send. Consumers use manual ACK after committed execution/failure state;
null/scalar/array/malformed JSON bodies go to the DLQ. Database outages leave the
delivery unacknowledged without burning domain retry attempts. Bounded domain
failures persist retry_after, then fail/dead-letter after three attempts.
Primary references checked: [Laravel 13 requirements](https://laravel.com/framework/docs/deployment),
[Livewire installation](https://livewire.laravel.com/docs/4.x/installation),
[FrankenPHP runtime configuration](https://serversideup.net/open-source/docker-php/docs/image-variations/frankenphp),
[RabbitMQ PHP confirms](https://www.rabbitmq.com/tutorials/tutorial-seven-php), and
[the locked client's ACK/return handling](https://github.com/php-amqplib/php-amqplib/blob/v3.7.5/PhpAmqpLib/Channel/AMQPChannel.php).

SQL migrations 001–003 are byte-identical copies of the historical migrations;
applied SHA-256 checksums are checked before any pending SQL runs. Migration 004
only adds shipping-owned session/operation/native-barrier tables. Runtime
transactions take the shared schema advisory gate then current-run row lock;
migrations take the exclusive gate. Jobs/inbox/effects/outboxes and audits retain
the existing schema and identifiers.

For production cutover, quiesce the old API, controller and workers, retain the
database/credentials, verify checksums and preserve the standalone run. Do not run
old/new controllers concurrently. A connected legacy run requires owner-coordinated
finalization and new run/epoch deployment; it cannot be taken over live. Retain the
old database and adapter journal. This source change performs no live deployment,
credential rotation, destructive schema operation or production reset.

Local verification covers the PHP/framework/real SQL/broker and HTTP/session
contracts above. Native mixed-language federation and shared browser screenshot
checks belong to the root integration run; no hosted CI or physical multi-host
result is implied here.

## Standalone terminal recovery

The standalone controller retains its SQL lease and waits while the current run
is `failed`, `stalled` or `finalized`, including when started against that state.
It advances no work in that state. A confirmed reset creates a fresh epoch that
the same controller observes and schedules; resetting does not require a process
restart. Connected terminal runs retain their coordinated new-epoch recovery rule.
The shared production-container acceptance checks finalize/reset and failed/stalled
SQL fixtures followed by reset and successful new-epoch execution.

The inherited Caddy-only Docker healthcheck is disabled because the same image
also runs non-HTTP worker/controller processes. Use `/api/health/ready` and the
reported SQL heartbeats to check application and role readiness, as for the
other department images.

## Shared migration acceptance

Production HTTP/identity checks and independent-only-dependency startup/browser
checks passed. The mixed C#/Java/Go/PHP HELICS federation passed delayed/held
grants, correlated durable handoffs, external power, optional Flask Twin source
recovery, native acknowledgement/finalization and adapter-loss fencing. Business
runtimes also passed real broker/database recovery and terminal-run reset checks.
See [the shared verification record](../../docs/verification.md) for commands,
actual evidence and the untested hosted/physical-host limits.

Production build contexts exclude generated Laravel sessions, views, logs and
bootstrap caches. The image creates fresh writable runtime directories; no local
test session or compiled configuration is copied into a clean deployment.

## V1 state migrations

Numbered migrations 005–008 add shipping orders/lines/shipments, durable domain
commands and provider intents/history, exact incoming-event bodies, external
customer aggregate identity, persistent cancellation intent and prepared browser
operations. Existing applied SQL and migration checksums remain unchanged. New
roles apply these additive migrations under the existing schema/run gates. Keep
owned volumes and application keys; this source update does not perform live
cutover, data reset or credential replacement.

### Coordinated robot custody (SIMU-75)

Default `FLEET_MODE=disabled` preserves existing behavior. For coordinated native
custody configure API, worker and controller with `FLEET_MODE=coordinated`,
`FLEET_URL`, private Shipping `FLEET_TOKEN`, `FLEET_RUN_ID`, `FLEET_EPOCH` and
optional finite nonnegative `FLEET_TIME_OFFSET` (default `0`). Map the actual
Shipping native run/epoch and offset in the fleet source configuration.

Migration `017_fleet.sql` stores immutable fleet requests, physical observations
and departmental proofs. Worker HTTP happens after native SQL commits. Pickup
readiness gates source loading/departure; physical arrival is required in addition
to the accepted manifest and source departure token before Shipping imports stock.
Proofs preserve their original native effective time across lost replies. Future
physical arrivals wait until an eligible native grant plus the configured offset.
Durable waits defer the command beyond the current grant, allowing native HELICS
time requests to continue. Unavailable fleet never enables a fallback receipt.

`handling.fleet` exposes mode and fleet run/epoch without credentials. Deferred
commands show their wait in job errors; detailed HTTP failures remain in
`shipping_fleet_jobs.error`. Old native scopes remain archived and are excluded
from delivery. Keep existing volumes and applied migration checksums. Run native
regressions with `make stack-unit APP=shipping`.

Coordinated carrier operation requires native Logistics destination custody. A
synthetic carrier has no authorized receiver for Logistics truck endpoints, so
coordinated mode defers that work with an actionable native-custody wait. It
never fabricates completion. Disabled mode keeps synthetic standalone workflows.

Canonical Storage customer picks require exactly two source version increments
in coordinated mode (unplaced departure and confirmed arrival), and one in
disabled mode. Both advance one movement sequence and retain the existing custody
generation until custody departure. Shipping keeps immutable manifest checks and
reserves enough counter headroom for pick stages, departure and receiver receipt.
