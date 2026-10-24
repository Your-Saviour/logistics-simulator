# Shipping V1 acceptance (SIMU-5)

The feature is implemented on `feat/simu-5-shipping-v1`, isolated from the main
checkout and the concurrently developed SIMU-3/SIMU-4 worktrees. Shipping owns its
Laravel/Blade/Livewire site, PHP API/worker/controller, PostgreSQL and internal
RabbitMQ. Its private adapter owns native HELICS only.

## Delivered behavior

Employees create distinct SKU lines, request complete-order fulfilment, follow
shortages and production requirements, receive physical goods, pack and dispatch,
and follow correlated delivery confirmations. No pick is requested until every
line is reserved. Packing requires every physical receipt. One shipment has
per-line carrier intents and completes only after every destination confirmation;
ETA alone never completes it. Search, queues, record detail and chronological
history use persisted state. Operator controls/security audits remain role scoped.

Cancellation persists independently of status. Late reservations are released;
failed compensation cannot restart picking. Provider facts bind to exact remote
reservations, physical transfers/destinations and departure journeys. Future facts
are durably stored before interpretation at granted time. Exact replay, epoch
fencing, outstanding-work barriers and commit-before-ACK behavior are retained.
Prepared browser operations persist exact identity/body/due time in PostgreSQL,
so replay of the original signed Livewire snapshot after a lost response cannot
create another order.

## Local verification

All service builds/tests ran in Docker through the common Git-worktree guard,
retaining the default 20 GiB reserve. Disposable projects use their own databases,
secrets, broker state and journals. Existing deployment volumes were not used.

| Check | Result |
| --- | --- |
| `make stack-unit APP=shipping` | Passed; 507 printed framework/domain checks, including all four review regressions. |
| Additional guarded `php /app/tests/shipping_autonomous.php` | Passed seeded autonomous delivery, repeat-seed deduplication and service restart observation. The unified suite now includes this test. |
| Guarded `python scripts/check_contracts.py --write` and `pytest -q -p no:cacheprovider tests/adapter` | Published/runtime schemas match; 24 adapter tests passed. |
| Storage C# assertion harness against real PostgreSQL/RabbitMQ | 160 checks passed, including explicit peer operations, rejection/causation and automation ownership. |
| `sh scripts/check_shipping_deployment.sh` | Fresh production build, independent startup, HTTP multiline lifecycle, per-line confirmations, worker stop/queue/restart, zero process restarts, and two browser tests passed. |
| `sh scripts/check_shipping_connected.sh` | Fresh production/native builds; future grant eligibility, duplicate input, typed multiline fulfilment/delivery, ETA/partial-confirmation barriers, unauthorized native endpoint rejection and same-journal restart fencing passed. |
| `COMPOSE_PROJECT_NAME=simu5-storage-regression make storage-connected-check` | Explicit storage peer operations and the existing real two-federate C# warehouse lifecycle passed; isolated teardown succeeded. |
| `STACK_REUSE_IMAGES=1 COMPOSE_PROJECT_NAME=simu5-shipping-stack make stack-check APP=shipping` | Passed common fixtures/roles/audits, terminal/failed/stalled resets, broker/database outage recovery, duplicate delivery, worker recovery and two standard browser checks. |

The standard stack check reused the feature's validated production build and
already-built bootstrap/browser images. A final fresh production build then
passed the targeted Laravel HTTP/PostgreSQL regression that prevents the legacy
sample API from occupying internal `shipping:` job keys (RED before the fix,
GREEN in the final image). These checks do not claim hosted CI execution. Shipping-specific production/native checks are wired
into the shipping CI matrix job.

Browser acceptance covers desktop/mobile employee operation and exact replay of
an original signed Livewire request after its first command has completed. Both
browser cases passed. The final screenshots were visually inspected, including
the restored matching order row after search debounce:

- `.superpowers/sdd/simu-5-shipping/deployment/shipping-v1-employee-desktop.png`
- `.superpowers/sdd/simu-5-shipping/deployment/shipping-v1-employee-mobile.png`

The native run recorded 14 completed provider intents and 32 history entries.
See [native evidence](simu-5-connected-evidence.md), [operations](shipping-v1.md)
and [wire contracts](contracts.md). Raw transcripts/screenshots remain untracked.

## Migration and integration effects

Shipping migrations 005–008 add owned order state, command/provider/history
ledgers, exact incoming event bodies, customer aggregate identity, cancellation
intent and prepared browser operations. Previously applied SQL/checksums are
unchanged. Storage gains additive peer commands and correlated rejection facts;
HELICS customer reservations now require explicit pick/transfer authorization.
Standalone storage automation and production issue remain intact. No live
cutover, credential replacement, volume pruning or automatic native rejoin occurs.

Shipping's native peer is controlled test code. It validates real HELICS/PHP
integration, and the separate warehouse check validates real C#/native behavior;
neither proves the combined C#/Java/Go/PHP business chain. SIMU-3/SIMU-4 contract
shapes were inspected, but merging their independently developed branches and
running that combined integration remains separate. Shared adapter/schema/CI
files require normal merge reconciliation. Adjacent CyberLab module/provisioning
work remains SIMU-13; department role/configuration inputs are documented here.

## Implementation choices and review

- The guard uses the common Git directory and optional waiting so worktrees share
  one resource lock. The cost is queued builds while another workload owns it.
- Independent storage and packaging/acceptance tasks used separate file ownership
  and were integrated through the full PHP, browser and native checks. This needs
  integration verification rather than relying only on individual task results.
- Per-line carrier legs preserve the published single-SKU transport contract.
  Supporting a single richer shipment manifest later needs a peer contract change.

A fresh whole-branch review identified four Important issues. Each was reproduced
with a failing regression, fixed, then covered by the green suite: durable
cancellation after compensation failure, exact physical peer continuity, per-owner
failure/all-leg completion, and browser response-loss replay. No review findings
were deferred.
