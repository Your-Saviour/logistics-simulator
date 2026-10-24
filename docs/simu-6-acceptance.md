# SIMU-6 Digital Twin acceptance

## Reproducible local checks

Run from the repository root. Builds and service checks run only in Docker,
serialized by `scripts/docker_guard.py` with the default 20 GiB disk reserve.

```sh
make stack-unit APP=twin
make twin-deployment-check
make stack-check APP=all
make mixed-check
```

`twin-deployment-check` allocates a unique disposable Compose project without
host ports or references to existing volumes. It builds the production Flask
and Nginx/React images. PostgreSQL and RabbitMQ are independent services; the
API and projection consumer are separately supervised containers. Cleanup
removes only this project's disposable containers and anonymous data volumes.
`STACK_REUSE_IMAGES=1` skips builds and requires the acceptance image tags to
already contain the changes under test.

The deployment check uses two explicitly labeled HTTP projection **fixtures**,
not native business applications. It checks:

- Startup with zero configured sources and one-source configuration.
- Two authenticated source snapshots and complete durable event history.
- Missing optional source health/readiness remains explicitly unknown.
- Source outage becoming stale while retaining its last snapshot and events.
- Source recovery, and two source commits while API, consumer and website stop.
- Consumer catch-up and a second API/consumer restart without duplicate events.
- Durable revision replay using `/api/twin/events?after=N`.
- Removing a source from configuration removes its visible current history.
- Production website root and Nginx API proxy, read-only defaults and no source
  credentials in returned snapshots.

Fixture progress while Twin stops demonstrates the absence of a dependency in
this isolated HTTP contract setup. Native business progress, correlated handoffs
and HELICS grant barriers require `mixed-check`; fixture checks do not prove
those behaviors. After the native employee browser flows, the verifier also
supports `--phase native` in the existing `twin-verify` container: it reads all
four real authenticated `/api/projection` endpoints and waits for Twin to retain
their current run/epoch, record identities, terminal committed record states
and complete captured immutable history. It requires a received warehouse transfer, completed production order
and received transport transfer; shipping is checked as observed data without
claiming an unexecuted fulfilment lifecycle. `--phase five-sites` checks five
unique HTML URLs and the remaining authenticated source/Twin APIs, with
`--skip-site NAME` for independently stopped websites. Shipping shares its
HTML/API process, so its explicit website outage excludes its source API too.
With all three Twin runtime services stopped, `--phase without-twin` requires
its API to be unreachable and verifies every real source remains running in the
same run/epoch while both granted and committed time advance within 20 seconds.
Restart Twin and rerun `--phase native` to verify recovery to those sources.
These phases consume the generated server-side environment; they do not print
credentials.

`stack-check APP=all` separately exercises five website URLs
and each application's dependency-only deployment. These commands are separate
pieces of evidence; none implies CyberLab or physical-host deployment.

## Evidence recorded for this change

On 25 October 2026 (Australia/Adelaide), the final
`make twin-deployment-check` production rebuild/rerun exited 0. It built the
backend and frontend, then passed `zero`, `subset`, `connected`, `stale`,
recovered `connected`, `advance`, `catchup`, `durable` and `reconfigured` phases.
All six fixture events survived consumer/API restart without duplication;
removing shipping left exactly three storage events. Missing optional source
health/readiness remained unknown. Production HTML and authenticated Nginx API
proxy checks passed throughout. Its isolated containers/network/data were
removed. Every guarded operation retained the default 20 GiB reserve.

The persistent [Compose entry point](../apps/twin/compose.yml) was separately
validated using unique project `simu-twin-persistent-smoke-1792851002-26795`,
`TWIN_PORT=0`, isolated test-only secrets/observer identity, zero sources, no
controls, and the just-built acceptance image overrides. All Docker commands
ran through `scripts/docker_guard.py --wait --label twin-persistent-smoke`.
The exact Compose operations were:

```sh
work() { python3 scripts/docker_guard.py --wait --label twin-persistent-smoke -- docker "$@"; }
compose() { work compose -p "$project" -f apps/twin/compose.yml "$@"; }
compose config --quiet
compose up -d --no-build
compose run --rm --no-deps -v "$PWD/scripts:/checks:ro" --entrypoint python api /checks/twin_acceptance.py --phase zero
compose ps --status running --services
compose down --volumes
```

This smoke exited 0: quiet configuration validation emitted no secrets; all five
roles (`api`, `broker`, `db`, `projection`, `web`) ran; zero-source API, healthy
projection heartbeat, database/broker readiness and production Nginx website/API
checks passed. Cleanup removed only that unique project's containers, network
and both named volumes. The default persistent `simu-twin-v1` project was never
started. This verifies packaging locally; it does not claim a hosted deployment
or persistence upgrade against an existing production volume.

## Final local verification and limits

Native unit suites passed: storage 179 checks; manufacturing 44 JVM tests and
four frontend tests/build; logistics Go vet and native tests; shipping PHP suite.
Twin passed 26 PostgreSQL/API/consumer tests. The earlier website passed 10
Playwright fixture checks and its production build.

`make stack-check APP=all` passed 19 browser checks, observation of all four real
sources, continued source time advancement with all Twin roles stopped, catch-up,
and five-site isolation. Its later recursive per-application startup stopped
with exit 75 at the disk reserve; the entire command did not finish successfully.

`STACK_REUSE_IMAGES=1 make mixed-check` passed the connected native federation
phase, including delayed/held grants, external power, correlated handoffs,
future-work barriers and Twin calendar/minimum-watermark checks. Later subset,
recovery and finalization phases did not run because guard lock contention
stopped the command with exit 75. The wrapper now waits for the guard lock;
that shell change was syntax checked, but the full command was not rerun.

The final facility replaces the SVG schematic with React Three Fiber/Three.js
and locally bundled CC0 Kenney GLB models. The guarded frontend command
(`--minimum-gib 18`, approved by the user for this update) passed two scene-state
tests, TypeScript checking and the production Vite build. The resulting assets
were copied to the running local preview at http://localhost:8086. A subsequent
browser check could not start: free space was 16.5 GiB, below the approved 18 GiB
reserve. Earlier browser screenshots cover the previous SVG scene, not this
final 3D scene. The final 3D browser appearance remains unverified.

Detailed local logs: `/tmp/simu6-review-*-green.log`,
`/tmp/simu6-twin-calendar-green.log`, `/tmp/simu6-stack-all.log`,
`/tmp/simu6-mixed-final.log`, `/tmp/twin-3d-build.log` and
`/tmp/twin-3d-visual.log`. These are local evidence, not hosted deployment checks.

## CyberLab deployment inputs and limits

The repository contains application images and module configuration inputs, not
an authorized CyberLab deployment entry point. No hosted cutover is performed by
these checks. Provision a separate Twin PostgreSQL database, RabbitMQ service,
API service (`ROLE=api`), consumer service (`ROLE=projection`) and web service
(`API_UPSTREAM=http://<twin-api>:8000`). Supply server-side source observer
identities with `status:read`, reachable HTTP projection URLs, optional public
website URLs and TLS/authentication at the deployment boundary. Set
`TWIN_SOURCES=[]` for a valid disconnected deployment. No native HELICS participant
or business controller depends on Twin availability. Preserve existing volume
identities and use numbered migrations during any operator-managed cutover.
