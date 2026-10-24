# SIMU-1 verification record

Local verification on 2026-10-24, Linux ARM64 containers on Docker Desktop. Scope is application bootstrap; CyberLab integration is excluded.

| Check | Evidence |
| --- | --- |
| PostgreSQL/API tests | `make test`: 28 passed. Includes concurrent duplicates, worker restart, run/epoch fencing, held/future work, controller lease contention, reset races, idempotency replay and unavailable-power deferral. |
| Native HELICS | `make federation-test`: four application processes and external power peer passed delayed-grant, typed 25 kW, message, input deduplication and production outbox checks. |
| Connected deployment | Full Docker federation started healthy; each application completed a HELICS peer sample with independent persisted effects. |
| Independent deployments | Each of manufacturing, storage, logistics, shipping and twin started alone and passed HTTP checks. Independent twin reported zero sources. |
| Browser | Five Playwright checks passed login, live state, controls, sign-out and mobile width. Desktop/mobile screenshots inspected. |
| Recovery | Actual RabbitMQ redelivery with two worker replicas, worker restart, broker outage, malformed-message and three-attempt terminal-failure DLQ, and old-epoch fencing passed. |
| Frontend | TypeScript and Vite production build passed; npm audit reported zero vulnerabilities. |
| Configuration | All five standalone manifests and suite parsed with Compose; each standalone dependency graph references only its own services. |
| Review | Independent review identified controller/reset, retry/DLQ, malformed input and power deferral bugs. Regression tests cover the fixes. Additional native deployment checks caught publication during pending grants; the controller now settles outputs only outside pending requests. |

The backend test run emits one upstream Starlette TestClient deprecation warning for its httpx compatibility path. This does not fail the tests. The test client can migrate to httpx2 separately.

Hosted GitHub Actions has been configured but has not run from a push in this session. Linux AMD64, separate physical hosts, production ingress/identity, unknown external simulator interfaces and coordinated federation-wide pause/checkpoint recovery have not been validated. The connected adapter intentionally requires a new owner-coordinated epoch after native state loss; it does not silently fall back to synthetic inputs or independently rewind a live federation.
