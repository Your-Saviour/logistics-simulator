# Shipping V1 Implementation Plan

> Execute inline using superpowers:executing-plans. The user approved the design on 24 October 2026.

**Goal:** Deliver independent shipping order entry through confirmed delivery.
**Architecture:** Extend the current PHP durable ledger; route domain jobs through its existing RabbitMQ workers and clock barriers. Keep provider intents and complete boundary envelopes durable.
**Tech Stack:** Laravel, Blade/Livewire, PostgreSQL, RabbitMQ, private HELICS adapter.
**Spec:** `docs/superpowers/specs/2026-10-24-simu-5-shipping-design.md`.

## Global Constraints

- Work only in the SIMU-5 worktree; preserve other agents' branches.
- Docker-only service builds/tests; use the original checkout's Docker guard to share its lock across worktrees; retain 20 GiB reserve.
- Preserve migration checksums, sample APIs, role scopes, granted-time barriers, stable retries and run/epoch fencing.
- Physical receipts authorize packing; confirmed transport outcomes authorize delivery.

## Review Focus

- Multiline shortages must not allow partial picking.
- Cancellation racing with a reservation or pick must retain compensation or reject safely.
- Replayed provider facts must not duplicate physical goods or dispatch.
- Reset/held runs and early grants must not execute stale or future work.
- Connected routes must reject facts from the wrong owner and preserve complete correlated outputs.

### Task 1: Durable shipping commands and providers

**Files:** `apps/shipping/src/ShippingRules.php`, `Fulfilment.php`, `Providers.php`, `Ledger.php`, `Settings.php`, `Controller.php`, migration 005, `tests/shipping.php`.
**Interfaces:** `Fulfilment::submit(string $key,array $body,?array $audit):array`, `snapshot():array`, `execute(Unit $u,array $run,array $job):void`; domain jobs retain existing scheduler fields.

- [ ] Add real SQL lifecycle tests; run inside the isolated shipping test project and observe missing implementation failure.
- [ ] Add additive tables, validation, idempotent scheduled commands, atomic transitions/history and durable provider intents.
- [ ] Implement seeded standalone customer, goods/production and carrier replies through the same fact handlers; retain operator controls and sample API.
- [ ] Cover shortages, exact receipts, full reservation before pick, safe cancellation/compensation, delivery provenance, replay/conflict, grant barriers and reset fencing.
- [ ] Run native suite; commit `feat: implement durable shipping lifecycle (SIMU-5)`.

### Task 2: HTTP and employee website

**Files:** shipping routes, service provider, Livewire component/views/style, shipping HTTP/session/browser checks.
**Interfaces:** `GET /api/shipping`, `GET /api/shipping/orders/{id}`, `POST /api/shipping/commands`; use Task 1 service.

- [ ] Add failing authenticated HTTP and Livewire tests for order creation, employee operations, detail/history and forged commands.
- [ ] Implement routes and independent order desk, search, queues and record detail in the existing style.
- [ ] Preserve exact command body/key after uncertain outcomes; enforce scopes server side on every update.
- [ ] Run HTTP/session checks and verify real browser screenshots; commit `feat: add shipping employee order desk (SIMU-5)`.

### Task 3: Connected boundaries, deployment and acceptance

**Files:** shipping adapter/rules/settings; additive contract schemas/fixtures; minimum storage boundary extensions/tests; shipping deployment/check scripts and docs.
**Interfaces:** durable full envelopes carry event/correlation/aggregate identity; explicit per-owner routes accept legacy single-route configuration.

- [ ] Add failing routing/duplicate/malformed/late/old-epoch tests and storage peer operation/shortage tests.
- [ ] Route targeted durable outputs and typed incoming facts through HELICS adapter; extend minimum storage peer operations using its existing domain engine.
- [ ] Inspect committed SIMU-3/4 contracts and align connected mappings without modifying their worktrees.
- [ ] Add standalone deployment and connected real/native peer lifecycle acceptance; document configuration and limitations with exact evidence.
- [ ] Run shipping unit/production acceptance and relevant storage regressions in Docker with isolated project/image identities.
- [ ] Obtain whole-branch review, fix important findings with regressions and commit final verification record.
