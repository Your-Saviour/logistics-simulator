# Run control, failure and distributed operation

## Standalone

One controller holds the per-database PostgreSQL advisory lease. It advances granted time by the positive handoff quantum, paced at the selected speed, only after current-time jobs/output settle. The database records a time anchor; restart preserves the run and jobs and advances without skipping unsettled work. It does not attempt exact wall-time catch-up after a long outage. Workers fail closed after 15 seconds without controller heartbeat.

`hold` freezes local time and transitions. Pending commands remain durable. `resume` resets the wall anchor and proceeds. `reset` is a locked, confirmed operation creating a new run UUID and epoch UUID; previous runs are archived. Old queued IDs cannot affect the new run. Queries and independent projection reads remain usable during hold.

## Selected runtime ownership

Business API/worker/controller roles run in each selected backend image:
ASP.NET Core for storage, Spring Boot for manufacturing, Gin for logistics and
Laravel/Artisan for shipping. Use `ROLE=api`, `worker` or `controller`; Python
is not their business executor. The twin uses its Flask API plus a separately
supervised Python projection consumer. Each application owns its credentials,
PostgreSQL and RabbitMQ; no central business or identity service is required.

The private per-department adapter owns one combination federate and all native
HELICS handles. Give it an independent durable journal and token, plus explicit
run/epoch/federation and routing configuration. It never connects to the business
database. See [adapter protocol](adapter-protocol.md) and the application READMEs.

For isolated mixed-framework verification use `make mixed-check`. It publishes no
host ports and does not change the existing review deployment. Every build/test
runs in Docker under the disk/serialization guard. The following connected
example belongs to the historical uniform Python reference.

## Historical connected HELICS example

```sh
make configure
python3 scripts/federation_compose.py
docker compose -f deploy/generated/federation.json up -d --build --wait
```

Stop standalone/suite deployments first because the website ports are the same. The connected project uses its own volumes. Its identity is retained in `deploy/generated/federation.identity.json`; rerendering does not rewind a live run. The fifth website monitors APIs and is not a time-regulating federate. A separate `external-power` process supplies a typed 25 kW condition and deliberately delays time requests.

For a short self-cleaning test using four temporary application databases plus the external peer, run `make federation-test`. It proves a delayed grant leaves effects untouched, exchanges typed power and sample messages through the production adapter/outbox code, deduplicates input and disconnects cleanly.

Local hold is not federation-wide pause: it may hold peers at a causal boundary, but acknowledges no global pause. The bootstrap provides no federation-wide pause controller. An external federation owner must coordinate a barrier and collect participant acknowledgements; the twin has no global-control authority. Speed changes and live local reset are rejected in connected mode.

Requested, granted and committed times are distinct. An asynchronous pending request never authorizes future work. The durable job/boundary-output ledger, not RabbitMQ queue emptiness, determines when another request may be sent. Input is validated and persisted before the controller requests further time. Sample work at a grant is committed exactly once in its own database; HELICS is not a distributed database transaction.

Finalization stops new scheduling and requires current-time work and native requests/receives to settle. In connected mode, selected backends persist `finalizing` before transport and only persist `finalized` after native acknowledgement. Native finalization failure stalls the run; it must not claim successful completion from SQL alone. A standalone finalized run can be reset. Connected finalization disconnects the participant and does not rewind its peers. For reset/recovery, the federation owner finalizes/aborts the old federation, allocates a new common run/epoch and launches participants with fresh run databases (archive previous databases first). The adapter deliberately refuses to restart into a live persisted HELICS run with granted/requested time; no checkpoint/rejoin protocol is claimed. Connected controllers are not auto-restarted by the sample Compose file.

## Failure behavior

- Database unavailable: transactions stop; no ACK or private-clock advancement. API readiness returns 503; unaccepted POST commands fail closed. If PostgreSQL cannot store a rejected audit, logs retain the request ID without credentials. Accepted command and audit transactions roll back together. The broker redelivers after reconnect.
- RabbitMQ unavailable: jobs and outbox remain in PostgreSQL; the worker reconnects using wall-time delays. Current unfinished work prevents further grants.
- Worker processing error: retry durably after two wall seconds, at most three attempts. Terminal failure marks the job dead and run failed and dead-letters its delivery. Inspect the UI error and `sample.jobs.dead.v1`; standalone recovery uses confirmed reset after investigation.
- Malformed delivery: dead-letter immediately without crashing the worker. A duplicate/fenced delivery is acknowledged without another effect.
- Controller lease contention: the losing process cannot stall the owner. A reset between prepare and grant is fenced without failing the new standalone run.
- HELICS peer or initialization wait exceeding 60 wall seconds: mark stalled. No local time or synthetic fallback. `HELICS_TIMEOUT_SECONDS` is configurable.
- HELICS output publication has no shared transaction with PostgreSQL. A crash after send but before marking sent may replay; consumers deduplicate stable event IDs. Unrecoverable native state loss requires an agreed federation abort/new epoch, not a claim of distributed exactly-once transport.
- Twin source outage: retain its last snapshot and show disconnected/stale. Each source watermark is independent; no atomic federation snapshot is implied.

## Multiple hosts and credentials

Generated manifests use local Compose DNS. It resolves only inside that one Docker network. To move a worker to another host, explicitly supply `DATABASE_URL`, `AMQP_URL`, `SIMULATOR`, `APP_USERNAME`, `APP_PASSWORD`, mode/provider and federation configuration as appropriate. Run that department’s selected backend image with `ROLE=worker`; no API container or shared business server is required on that worker host. The historical Python reference instead uses `python -m simulator.worker`. Deploy only the selected roles; local dependency containers are not required by the process.

For the historical `make configure` generator, `<APP>_DATABASE_URL`, `<APP>_AMQP_URL`, `<APP>_APP_USERNAME`, `<APP>_APP_PASSWORD` and `<APP>_API_UPSTREAM` override addresses/identities (for example `STORAGE_DATABASE_URL`). For the migrated private verification manifests, use a Compose override for environment/addresses; they do not consume those historical prefixed overrides. Use an override for role-specific environment, ports, volumes and `TWIN_SOURCES`. The latter is a JSON array of `{name,url,username,password}` for read-only source API polling; the server never returns those credentials to the browser. If observer credentials are overridden, update the twin's matching source credentials too.

Expose database/broker listener ports only on the intended lab interfaces and configure their service users/virtual hosts consistently with application URLs. Passwords in URLs must be percent-encoded; generated hex secrets require no escaping. Frontends proxy through their own configured API upstream, so source credentials are not embedded in JS bundles.

HELICS uses `tcp_ss`. Set the broker to a routable address and set core/local advertised interfaces and receive ports in `HELICS_CONFIG`/core-init. Ensure peer hosts can reach those ports; do not publish a container-only hostname as a cross-host advertised address. Logical endpoint names such as `storage/events` are not HTTP URLs or TCP ports. See [HELICS networking](https://docs.helics.org/en/main/user-guide/advanced_topics/networking.html).

Local Compose and source configuration are verified; separate physical hosts, TLS ingress, site firewall policy, production authentication and unknown external simulator contracts are not verified by this bootstrap. No cloud resources or adjacent repository changes are included.


## Schema changes and service restarts

`schema_migrations` records each applied SQL filename and SHA-256 checksum. Restarting API/worker/controller processes validates existing versions and does not repeat DDL or lock the current run row during initialization. Editing an applied SQL file fails startup; add a new numbered migration instead.

Pending migrations acquire an exclusive database advisory schema gate before touching business tables. Runtime transactions acquire the shared gate before row locks, so DDL waits for active work to commit and new work waits for DDL to finish. This avoids table-lock upgrade deadlocks when worker replicas restart alongside controllers.

For the first upgrade from older bootstrap images that predate this gate, quiesce application API/worker/controller/projection processes before migration, preserving database and broker volumes. The versioned migration protocol is then used for subsequent restarts. A run already marked stalled retains its diagnostic history and requires an operator-confirmed standalone reset or owner-coordinated federation recovery; startup does not silently clear failure state.

Application startup probes use the RabbitMQ AMQP TCP listener and PostgreSQL TCP readiness. An Erlang VM ping alone can succeed while RabbitMQ's application/listener is stopped; it is not the startup dependency condition. The broker has a bounded startup grace period to avoid declaring normal initialization unhealthy. CI failure diagnostics print container health histories and resource usage without dumping environment credentials. See [RabbitMQ readiness guidance](https://www.rabbitmq.com/docs/monitoring#health-checks-as-readiness-probes).

## Migration and local resource limits

Before switching a live application, quiesce old API writers, workers and its
controller. Back up and retain the database, broker volumes, run/epoch values
and credentials. Numbered migrations001–003 remain byte-identical; each new
backend checks their SHA-256 history and applies only its own additive adapter
metadata migrations. Never run old and new controllers concurrently. A connected
native session cannot be reconstructed from SQL; coordinate federation shutdown
and a new epoch with its owner, retaining prior data/journal for diagnosis.

Shipping explicitly uses locked php-amqplib3.7.5 with sockets, persistent mandatory
publication, publisher confirms, manual ACK after commit and bounded retry/DLQ
handling. It does not use Laravel’s wall-clock schedulers/queue delay as simulation
time. All business frameworks use persisted due jobs and grants, not private
worker timers. Laravel’s website session key is independently configured and
retained; startup never silently regenerates deployment secrets.

Local verification reserves20GiB and runs one Docker workload at a time through
`scripts/docker_guard.py`. It stops the workload when that reserve is breached.
Build images sequentially, bound/reclaim unused build caches between stacks, and
stop only the disposable test projects when finished. Keep application data
volumes; avoid blanket container/system/volume pruning. No service tests run on
the base host. Docker restart may change container IPs; reload frontend proxies
after dependencies recover and check application identity from inside each
website container, as a process-level liveness check alone can hit a stale peer IP.
