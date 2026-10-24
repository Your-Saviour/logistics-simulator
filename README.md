# Independent business simulators

Four business simulator foundations and an optional digital twin. Each business
application owns its API, workers, durable scheduler, PostgreSQL state, RabbitMQ
internal jobs and independent identities. HELICS coordinates connected business
time through one private adapter per department. The twin only observes sources.

| Application | Backend | Website | Source and commands |
| --- | --- | --- | --- |
| Storage | C# / ASP.NET Core | Vue / TypeScript | [Storage](apps/storage/README.md) · [SIMU-48](https://ctfittwo.atlassian.net/browse/SIMU-48) |
| Manufacturing | Java / Spring Boot | Angular / TypeScript | [Manufacturing](apps/manufacturing/README.md) · [SIMU-49](https://ctfittwo.atlassian.net/browse/SIMU-49) |
| Logistics | Go / Gin | Svelte / TypeScript | [Logistics](apps/logistics/README.md) · [SIMU-50](https://ctfittwo.atlassian.net/browse/SIMU-50) |
| Shipping | PHP / Laravel | Blade / Livewire | [Shipping](apps/shipping/README.md) · [SIMU-51](https://ctfittwo.atlassian.net/browse/SIMU-51) |
| Digital twin | Python / Flask | React / TypeScript | [Twin](apps/twin/README.md) · [SIMU-52](https://ctfittwo.atlassian.net/browse/SIMU-52) |

Storage implements the [SIMU-2 warehouse lifecycle](docs/storage-v1.md). The other
departments remain bootstrap sample workflows pending SIMU-3–6. Framework migration verification is tracked in [verification](docs/verification.md).
CyberLab integration and distributed packaging (SIMU-13) remain excluded.
Adapter, verification and documentation follow-up are tracked in
[SIMU-45](https://ctfittwo.atlassian.net/browse/SIMU-45),
[SIMU-46](https://ctfittwo.atlassian.net/browse/SIMU-46) and
[SIMU-47](https://ctfittwo.atlassian.net/browse/SIMU-47).

## Build and verify in Docker

The host only edits files and orchestrates Docker. No service toolchain or test
server needs to run on the host. Guarded workloads run sequentially and reserve
20 GiB of free disk space; do not launch competing builds in other terminals.

```sh
make stack-unit APP=storage     # native backend checks with isolated dependencies
make stack-check APP=storage    # independent production images, HTTP/recovery/browser checks
make mixed-check               # C#/Java/Go/PHP HELICS federation and optional Flask twin
```

Select `manufacturing`, `logistics`, `shipping` or `twin` independently. The test
projects publish no host ports and never attach existing deployment volumes.
Their websites have distinct service-DNS origins inside the test network.
Application READMEs describe configuration, process entry points, dependency
locks and preserved-state cutover. The shared [bootstrap guide](docs/bootstrap.md)
explains the verification flow and test cleanup.

- [Boundary, HTTP and seeded-input contracts](docs/contracts.md)
- [Private HELICS adapter protocol and recovery](docs/adapter-protocol.md)
- [Clock control and operational limits](docs/operations.md)
- [Acceptance scope, excluding SIMU-13](docs/simu-1-acceptance.md)
- [OFacT reuse decision](docs/research/2026-10-24-ofact-spike.md)
- [Approved framework migration design](docs/superpowers/specs/2026-10-24-simu-1-framework-migration-design.md)
- [Historical design and static previews](docs/previews/README.md)

## Historical bootstrap

The original uniform Python/FastAPI and React implementation remains in
`src/simulator/api.py`, `worker.py`, `controller.py` and `apps/web` as a compatibility
reference. Its `make up`, `make suite`, `make smoke`, `make recovery` and `make check`
commands belong to that historical implementation. They do not establish migrated
framework acceptance. `make` alone retains its historical configuration-generation
behavior. Existing deployments are not automatically switched or reset by this
source migration; follow the documented quiesce/backup/cutover procedure.
