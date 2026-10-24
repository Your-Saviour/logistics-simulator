# SIMU-1 application acceptance, excluding SIMU-13

SIMU-13 and CyberLab/distributed packaging remain excluded. This delivery covers application foundations, not departmental V1 workflows under SIMU-2 through SIMU-6. The parent epic remains open while excluded work remains.

The selected runtimes are ASP.NET Core/Vue for Storage, Spring Boot/Angular for Manufacturing, Go/Gin/Svelte for Logistics, Laravel/Blade/Livewire for Shipping, and Flask/React for Twin. Business APIs, workers and controllers execute in their own backend language. Private Python adapters own native HELICS only. Existing Python application deployments remain a historical compatibility reference; cutover is explicit and preserves their databases.

| Included task | Implementation and verification entry point |
| --- | --- |
| SIMU-45: native adapter | Authenticated versioned commands, durable operation journal, receive acknowledgement, time barriers and native-owner loss fencing. `apps/adapter/Dockerfile`, `tests/adapter`, `examples/helics/adapter_smoke.py`. |
| SIMU-48: Storage | Application-owned C# ledger, workers, controller, adapter client and Vue UI. `sh scripts/check_stack_unit.sh storage`; `sh scripts/check_stacks.sh storage`. |
| SIMU-49: Manufacturing | Application-owned Java ledger, workers, controller, adapter client and Angular UI. Same commands with `manufacturing`. |
| SIMU-50: Logistics | Application-owned Go ledger, workers, controller, adapter client and Svelte UI. Same commands with `logistics`. |
| SIMU-51: Shipping | Application-owned PHP ledger, workers, controller and Laravel session/Livewire UI; direct confirmed RabbitMQ AMQP rather than Redis queues. Same commands with `shipping`. |
| SIMU-52: Twin | Flask read model and React UI, source projection and read-only identity enforcement. Same commands with `twin`. |
| SIMU-46: cross-language verification | Shared HTTP fixtures in `contracts/http/v1`, independent production-container checks, actual PostgreSQL/RabbitMQ outages, duplicate deliveries and browser checks. `sh scripts/check_stacks.sh all`; mixed native federation and optional Twin source checks: `sh scripts/check_mixed_stacks.sh`. CI: [stacks.yml](../.github/workflows/stacks.yml). |
| SIMU-47: documentation | Selected runtime/build matrix, adapter recovery, preserved-state cutover and verification evidence in [verification.md](verification.md), [operations.md](operations.md), [bootstrap.md](bootstrap.md) and each application's README. |

The earlier SIMU-7–12 foundations remain requirements: independent deployments/credentials; strict HTTP and boundary contracts; durable SQL inbox/outbox and confirmed RabbitMQ work; grant-gated local/native time; deterministic seeded calendar providers; scoped identities and atomic accepted/rejected audits. The new checks exercise these through each selected runtime. SIMU-14's [OFacT assessment](research/2026-10-24-ofact-spike.md) remains the reuse decision; no upstream application runtime was imported.

All service builds and tests run in Docker containers. Host scripts generate private disposable manifests and orchestrate Docker. Workloads run serially with a 20 GiB default free-space reserve. Test manifests expose no host ports and never reference live deployment volumes. See the verification record for actual results and limitations; a workflow definition is not evidence of a successful hosted run.

API authentication uses independent deployment secrets and HTTP Basic; Shipping's browser uses Laravel sessions and CSRF protection. Production ingress requires TLS. Native finalization waits for acknowledgement before persisting `finalized`. Native state loss requires a coordinated new epoch; local controllers do not silently substitute synthetic peers or rewind a live federation.
