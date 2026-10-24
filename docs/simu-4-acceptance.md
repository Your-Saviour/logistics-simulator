# SIMU-4 acceptance record

Implementation is isolated on `feat/simu-4-logistics-v1`, based on `8012858` in
`/Users/jaketownsend/.codex/worktrees/3551/logistics-simulator`.
The approved Go/Gin and Svelte design is recorded in
[the design](superpowers/specs/2026-10-24-simu-4-logistics-v1-design.md).
The [operator/deployment guide](logistics-v1.md) documents the final contracts.

| Ticket | Delivered behavior | Verification |
| --- | --- | --- |
| SIMU-27 | Configured routes/fleet, exclusive capacity and correlations | Real SQL contention, capacity and atomic audit regressions |
| SIMU-28 | Durable load/depart/arrive/unload, custody and epoch fencing | Complete employee lifecycle, early/duplicate arrival and grant-barrier tests |
| SIMU-29 | ETA separate from arrival, unloading and destination receipt | Lifecycle regression and native receiving peer |
| SIMU-30 | Independent employee fleet/route/transport queue and history | Production Svelte build and desktop/mobile Playwright flow |
| SIMU-31 | Explicit seeded providers and versioned HELICS handoffs | Deterministic providers, wire/schema tests and native storage/shipping reference peer |
| SIMU-32 | Recovery, multiple workers and external endpoint deployment | Production outage/restart checks and independently launched worker |

All service installation, builds, tests and browser runs execute inside Docker,
serialized by `scripts/docker_guard.py` with the default 20 GiB reserve. This
worktree shares the original checkout's guard lock through Git's common directory;
the `--wait` flag queues a workload without changing reserve or cleanup behavior. Existing data
volumes and applied SQL checksums are retained.

Initial tests were observed failing before implementation: missing transport
endpoint (404), absent client command method, missing adapter domain discriminator,
unsupported storage input, sample/transport idempotency collision (503), unrelated
receipt correlation, permanently rejected provider assignment, shared-endpoint
publication operation collision, and sample admission of internal transport keys.

## Final local results — 24 October 2026

| Check | Result |
| --- | --- |
| `make stack-unit APP=logistics` | PASS: Go vet and full suite, `ok simulator/logistics 7.887s` |
| Containerized `python scripts/check_contracts.py` and `pytest -q -p no:cacheprovider tests/adapter tests/test_storage_contracts.py` | PASS: schema/runtime parity and 25 tests in 0.98s |
| Production frontend Docker build | PASS: 3 client tests; zero Svelte errors/warnings; Vite production bundle |
| `make logistics-connected-check` | PASS: actual native storage/shipping handoffs, duplicate delivery and abrupt peer-loss custody/grant fencing |
| `make logistics-deployment-check` | PASS: fresh persistent packaging, zero backend restarts, independent worker using external SQL/broker URLs |
| Production HTTP and recovery phases | PASS: roles/audit/idempotency, terminal resets, real broker/database outage recovery and duplicate worker delivery |
| Transport acceptance phases | PASS: complete lifecycle, two worker replicas, in-transit worker stop/restart, retained unload/reservation across broker outage and separate receipt |
| Final containerized Playwright suite | PASS: 3/3 in 49.3s, including full employee lifecycle at desktop/mobile widths |

The production phases ran using:

```sh
COMPOSE_PROJECT_NAME=simu4-logistics-check BROWSER_CHECK_IMAGE=logistics-simulator:simu4-browser-check STACK_REUSE_IMAGES=1 make stack-check APP=logistics
```

All generic outage phases passed. That run exposed a test assertion incorrectly
requiring registered RabbitMQ consumers; Go workers intentionally use `basic.get`.
After correcting the assertion, the transport phases passed with
`STACK_STARTUP_ONLY=1` to skip repeating the unchanged generic outage checks.
The browser run then exposed a test locator mismatch for the Route combobox;
the corrected final browser suite was run against the same production images:

```sh
docker compose -p simu4-logistics-check -f deploy/generated/migration-logistics.json run --rm browser-check
```

Docker commands above were executed through the guard with `--wait`. Reused
images were built from this worktree in guarded Docker builds. The final browser
suite independently resets its run and executes the complete transport lifecycle.
A mobile regression was observed at 440px page width in a 390px viewport; the
verified CSS fix produces exactly 390px, with table scrolling inside the page.

Local logs are under `.superpowers/simu-4-*.log`. Rendered UI evidence is in
`.superpowers/sdd/simu-framework-migration/browser-artifacts/`, including
`logistics-v1-employee-desktop.png` and `logistics-v1-employee-mobile.png`.
The completed browser transfer contained 8 items, ETA/confirmed arrival 159s,
separate receipt 179s, and one custody movement for each transition.

A fresh read-only code review found three important issues. Stable operation and
event identities now include the complete HELICS output route; rejected provider
assignments receive a fresh durable attempt when capacity returns; both command
endpoints reserve internal transport keys. Each finding has a regression observed
failing before its fix and passing in the full Go suite. A failed-unload regression
also proves that custody and vehicle reservation remain unchanged.

Test projects now include a checkout-specific suffix, all worktrees share the Git
common-directory workload lock, and connected generation does not overwrite an
active standalone manifest. `BROWSER_CHECK_IMAGE` permits an isolated browser
checker image when multiple features are being verified on the same Docker host.
Migration 006 is additive; migrations 001–005 and existing volumes are preserved.

No hosted CI or physical CyberLab multi-host result is claimed. The native peer
implements the published Storage/Shipping boundary roles; it is not an acceptance
run against those departments' complete business applications. Separate-node
routing, TLS ingress and production cutover require deployment-owned configuration.
