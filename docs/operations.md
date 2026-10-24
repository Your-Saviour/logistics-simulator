# Run control, failure and distributed operation

## Standalone

One controller holds the per-database PostgreSQL advisory lease. It advances granted time by the positive handoff quantum, paced at the selected speed, only after current-time jobs/output settle. The database records a time anchor; restart preserves the run and jobs and advances without skipping unsettled work. It does not attempt exact wall-time catch-up after a long outage. Workers fail closed after 15 seconds without controller heartbeat.

`hold` freezes local time and transitions. Pending commands remain durable. `resume` resets the wall anchor and proceeds. `reset` is a locked, confirmed operation creating a new run UUID and epoch UUID; previous runs are archived. Old queued IDs cannot affect the new run. Queries and independent projection reads remain usable during hold.

## Connected HELICS example

```sh
make configure
python3 scripts/federation_compose.py
docker compose -f deploy/generated/federation.json up -d --build --wait
```

Stop standalone/suite deployments first because the website ports are the same. The connected project uses its own volumes. Its identity is retained in `deploy/generated/federation.identity.json`; rerendering does not rewind a live run. The fifth website monitors APIs and is not a time-regulating federate. A separate `external-power` process supplies a typed 25 kW condition and deliberately delays time requests.

For a short self-cleaning test using four temporary application databases plus the external peer, run `make federation-test`. It proves a delayed grant leaves effects untouched, exchanges typed power and sample messages through the production adapter/outbox code, deduplicates input and disconnects cleanly.

Local hold is not federation-wide pause: it may hold peers at a causal boundary, but acknowledges no global pause. The bootstrap provides no federation-wide pause controller. An external federation owner must coordinate a barrier and collect participant acknowledgements; the twin has no global-control authority. Speed changes and live local reset are rejected in connected mode.

Requested, granted and committed times are distinct. An asynchronous pending request never authorizes future work. The durable job/boundary-output ledger, not RabbitMQ queue emptiness, determines when another request may be sent. Input is validated and persisted before the controller requests further time. Sample work at a grant is committed exactly once in its own database; HELICS is not a distributed database transaction.

Finalization stops new scheduling and requires current-time work to settle. A standalone finalized run can be reset. Connected finalization disconnects the participant and does not rewind its peers. For reset/recovery, the federation owner finalizes/aborts the old federation, allocates a new common run/epoch and launches participants with fresh run databases (archive previous databases first). The adapter deliberately refuses to restart into a live persisted HELICS run with granted/requested time; no checkpoint/rejoin protocol is claimed. Connected controllers are not auto-restarted by the sample Compose file.

## Failure behavior

- Database unavailable: transactions stop; no ACK or private-clock advancement. The broker redelivers after reconnect.
- RabbitMQ unavailable: jobs and outbox remain in PostgreSQL; the worker reconnects using wall-time delays. Current unfinished work prevents further grants.
- Worker processing error: retry durably after two wall seconds, at most three attempts. Terminal failure marks the job dead and run failed and dead-letters its delivery. Inspect the UI error and `sample.jobs.dead.v1`; standalone recovery uses confirmed reset after investigation.
- Malformed delivery: dead-letter immediately without crashing the worker. A duplicate/fenced delivery is acknowledged without another effect.
- Controller lease contention: the losing process cannot stall the owner. A reset between prepare and grant is fenced without failing the new standalone run.
- HELICS peer or initialization wait exceeding 60 wall seconds: mark stalled. No local time or synthetic fallback. `HELICS_TIMEOUT_SECONDS` is configurable.
- HELICS output publication has no shared transaction with PostgreSQL. A crash after send but before marking sent may replay; consumers deduplicate stable event IDs. Unrecoverable native state loss requires an agreed federation abort/new epoch, not a claim of distributed exactly-once transport.
- Twin source outage: retain its last snapshot and show disconnected/stale. Each source watermark is independent; no atomic federation snapshot is implied.

## Multiple hosts and credentials

Generated manifests use local Compose DNS. It resolves only inside that one Docker network. To move a worker to another host, explicitly supply `DATABASE_URL`, `AMQP_URL`, `SIMULATOR`, `APP_USERNAME`, `APP_PASSWORD`, mode/provider and federation configuration as appropriate. Run the same backend image with `python -m simulator.worker`; no API container or shared business server is required on that worker host. Deploy only the selected roles; local dependency containers are not required by the process.

For generated manifests, `<APP>_DATABASE_URL`, `<APP>_AMQP_URL`, `<APP>_APP_USERNAME`, `<APP>_APP_PASSWORD` and `<APP>_API_UPSTREAM` override addresses/identities (for example `STORAGE_DATABASE_URL`). Use a Compose override for role-specific environment, ports, volumes and `TWIN_SOURCES`. The latter is a JSON array of `{name,url,username,password}` for read-only source API polling; the server never returns those credentials to the browser. In a suite with overridden app credentials, update the twin's source credentials too.

Expose database/broker listener ports only on the intended lab interfaces and configure their service users/virtual hosts consistently with application URLs. Passwords in URLs must be percent-encoded; generated hex secrets require no escaping. Frontends proxy through their own configured API upstream, so source credentials are not embedded in JS bundles.

HELICS uses `tcp_ss`. Set the broker to a routable address and set core/local advertised interfaces and receive ports in `HELICS_CONFIG`/core-init. Ensure peer hosts can reach those ports; do not publish a container-only hostname as a cross-host advertised address. Logical endpoint names such as `storage/events` are not HTTP URLs or TCP ports. See [HELICS networking](https://docs.helics.org/en/main/user-guide/advanced_topics/networking.html).

Local Compose and source configuration are verified; separate physical hosts, TLS ingress, site firewall policy, production authentication and unknown external simulator contracts are not verified by this bootstrap. No cloud resources or adjacent repository changes are included.
