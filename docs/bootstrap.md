# SIMU-1 application bootstrap

Scope: application development only. CyberLab integration, cloud provisioning and departmental V1 workflows are excluded. The static previews remain in `docs/previews`; the running applications are React websites backed by Python services.

## Start an application

Requires Docker Engine with Compose v2 and Python 3.12+ for generation scripts. Node 22 is needed only to run frontend checks outside Docker.

```sh
make up APP=storage
make credentials APP=storage
make smoke APP=storage
```

Use `manufacturing`, `storage`, `logistics`, `shipping` or `twin`. Each starts only its own containers. The application username is `<application>-operator`; the generated password is displayed by the explicit credentials command. Credentials are unique per application and retained in git-ignored, mode-0600 files under `deploy/generated`. Do not regenerate/delete secrets against existing data volumes: PostgreSQL/RabbitMQ credentials are initialized only when their volumes are first created.

| Application | Local website |
| --- | --- |
| Manufacturing | http://127.0.0.1:8181 |
| Storage | http://127.0.0.1:8182 |
| Logistics | http://127.0.0.1:8183 |
| Shipping | http://127.0.0.1:8184 |
| Digital twin | http://127.0.0.1:8185 |

```sh
make suite                  # all five independent stacks, twin observes four APIs
make down APP=suite         # stop suite, retaining volumes and secrets
make up APP=twin            # starts independently with no configured sources
```

Standalone and suite projects have separate database/broker volumes. Stop one deployment before starting another that uses the same website ports. The suite shares build artifacts and one local Docker network, but each application owns separate API, database, broker, credentials and worker/controller processes. No central business-state runtime or login service is required. Twin owns a separate projection process and database; it does not own a business clock.

## What is implemented

Each business application exposes authenticated run state, sample jobs, an employee command form, run hold/resume, standalone speeds 1/5/20/60, confirmed reset and finalization. Autonomous sample commands arrive every 30 simulation seconds through the same validation as employee commands. Sample effects are persisted item counts, not completed warehouse, production, fleet or order workflows. The work ledger displays up to 100 recent jobs; it is a bootstrap view rather than a complete audit UI.

PostgreSQL owns runs, epochs, durable due jobs, inbox, effects and internal/boundary outboxes. A run row lock serializes transition boundaries across worker replicas. RabbitMQ delivers persistent job identifiers with publisher confirmations, mandatory routing and manual acknowledgements. A consumer acknowledges only after committing a result or retaining retry work durably. Three processing failures mark a job dead and its run failed; the terminal delivery goes to `sample.jobs.dead.v1`. Dependency outages do not spend the processing retry budget.

Workers verify grant eligibility, run/epoch and a recent controller heartbeat before executing. The controller holds a PostgreSQL advisory lease and cannot request another grant while current-time work or boundary outputs remain outstanding. Local time advances in positive quanta, preserving requested/granted/committed distinctions. A held run still serves queries and retains pending commands. PostgreSQL and broker endpoints are configurable for remote workers; no worker uses a private business clock.

## Verification

```sh
make check                   # PostgreSQL tests, native HELICS smoke, TS/build/audit, Compose validation
make suite
make smoke APP=suite
make recovery                # actual queue redelivery, two worker replicas, broker outage and epoch fencing
cd apps/web
npx playwright install chromium
npx playwright test           # login, controls, live state, desktop/mobile and sign-out across all five
cd ../..
python3 scripts/standalone_check.py
python3 scripts/connected_check.py   # disposable full-stack HELICS test
make suite                          # restore the local review deployment
```

`make recovery` intentionally restarts only simulator worker/broker containers and resets the storage sample run. `standalone_check.py` stops the simulator suite, starts each application alone and tears it down; `--restore-suite` restores the suite at the end. No other project is stopped. Tests use a separate `simu-tests` Compose project; `make clean-tests` removes its containers while retaining application deployments.

GitHub Actions runs these checks; a local successful run does not establish that a hosted Actions run has occurred. Native HELICS was verified in Linux ARM64 Docker. Linux AMD64 is covered by the configured Actions job when it runs; multiple physical hosts have not been exercised.

See [contracts](contracts.md), [operations](operations.md) and the [OFacT assessment](research/2026-10-24-ofact-spike.md).
