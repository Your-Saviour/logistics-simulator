# Shipping V1 design (SIMU-5)

Status: proposed for user approval. Source: https://ctfittwo.atlassian.net/browse/SIMU-5.
Baseline: `8012858`. Branch: `feat/simu-5-shipping-v1` in its own managed worktree.

## Intent and constraints

An employee can create customer orders, resolve shortages, receive the complete
order, pack it, request dispatch and follow confirmed delivery. Shipping runs
independently with its Laravel API, Blade/Livewire website, PHP workers and
controller, PostgreSQL and RabbitMQ. The private Python adapter owns native HELICS
only. Twin and the other departments are optional.

Preserve the existing authentication, atomic command audits, publisher confirms,
manual ACK after commit, bounded retries, simulation-time grants, outstanding-work
barriers, inbox deduplication and run/epoch fencing. Preserve sample HTTP contracts
and applied migration checksums. Add numbered shipping migrations. Never infer
delivery from an ETA. Never replace a configured HELICS owner with synthetic data
after a dependency failure.

SIMU-3 and SIMU-4 are under active development in separate worktrees. This branch
owns shipping changes and additive shipping contract/acceptance files. It must not
edit those agents' worktrees or depend on their uncommitted implementation.

## Approach

Recommended: extend the existing durable PHP ledger and job pipeline with focused
shipping domain classes. Commands, outcomes, provider facts and boundary outputs
commit under the existing run lock. This retains the foundation's recovery rules.

A separate shipping scheduler would duplicate clock/barrier/recovery ownership.
A synchronous CRUD implementation would bypass granted-time eligibility and
durable work. Neither meets the accepted architecture. No new runtime or queue
integration is needed. This recommendation has not yet been approved by the user.

## Proposed domain behavior

The following are implementation proposals where the epic leaves detail open.

An order has an immutable customer reference, destination, correlation UUID and
one or more distinct SKU lines with whole quantities. Validate codes using the
storage catalog convention; quantities are 1..10000 per line. Duplicate SKUs,
unknown fields and empty orders reject. One order creates one correlated shipment;
V1 does not split fulfilment, backorder individual lines or dispatch partial orders.

Each line tracks requested, reserved and physically received quantity, plus the
peer reservation/transfer references. Order readiness requires the exact complete
set of goods. Reservation facts alone never authorize packing. Repeated or
conflicting receipt facts cannot overreceive or receive a different SKU/order.
Shortage is visible and emits a correlated production requirement. Production
completion only authorizes another stock request; it is not physical receipt.
Reserve every line before authorizing any pick. Request fulfilment authorizes
automatic picking/transfer after complete reservation; it does not require a
second employee action. Persist that authorization and expose its progress so
the cancellation window is explicit. A shortage on one line cannot start
irreversible work on another line.

Employee actions are create, request fulfilment, pack, dispatch and cancel.
The order's derived states describe awaiting stock, shortage, awaiting receipt,
ready to pack, packed, awaiting carrier, in transit, delivered and cancelled.
Shipment state and provider acknowledgement are stored separately where needed.
Packing rejects until all lines have arrived. Dispatch rejects until packed.
A dispatch request is not departure; only the carrier's matching acceptance or
departure outcome moves the shipment in transit. Only the configured carrier or
destination's correlated successful arrival/delivery fact can mark it delivered.
Wrong references, failed outcomes and elapsed ETA cannot do so.

Cancellation is permitted before stock picking/physical handoff begins. It records
a durable cancellation intent and releases acquired reservations with stable
compensation identities. Cancellation completes after required releases are
confirmed. Late successful reservations are released, never silently forgotten.
Pending production demand is cancelled where the provider permits it; irreversible
production is retained as an explicitly visible outstanding consequence. Once a
peer confirms picking or transfer, or local goods have been received/packed,
cancellation rejects. Unknown peer progress must settle before cancellation can
claim completion. Returns and post-dispatch cancellation are outside V1.

## Transactions, commands and reads

Add shipping-owned order, line, shipment, command/outcome, provider-intent and
history tables through migration 005 or the next unused number at implementation.
Rows are run scoped. Foreign keys and checks enforce positive whole quantities,
unique line SKUs and one shipment per order. Use the current-run lock before
domain writes, command execution, reset and grant preparation.

Proposed API: `GET /api/shipping`, `GET /api/shipping/orders/{id}` and
`POST /api/shipping/commands`. Writes require an Idempotency-Key and explicit
`run_id`, `epoch`, `due_at` and `action`, following storage's asynchronous command
convention. HTTP acceptance returns a persisted command; the read model reports
pending/completed/rejected outcomes. Exact replay returns the same command;
changed bodies conflict. Check replay before rejecting a now-held/terminal run.
Expected business rejection records an outcome and settles the barrier without
partial effects. Infrastructure failure retains the existing retries/dead letter
behavior. Worker redelivery cannot duplicate reservations, goods or dispatch.

Employee and scoped service identities may read and submit authorized domain
commands. Operators alone control runs and read security audits. Operational
record history is visible to employees independently of the security audit.
Every successful mutation atomically persists its domain history and command audit.
Old epoch commands and browser submissions cannot mutate a new run.

## Providers and HELICS

Keep the existing `orders`, `goods` and `carrier` provider settings. The goods
provider owns the stock/production interaction, with explicit routed outputs to
storage requests and manufacturing demand. Standalone providers use deterministic
scenario-seeded customer demand, stock availability/shortages, replenishment,
physical receipt and carrier outcomes. They use the same validated domain command
and fact handlers as connected peers. A scheduled synthetic carrier outcome is
an explicit provider confirmation with provenance, not an ETA state transition.

Autonomous employee actions operate only on provider-created orders. Human-created
orders remain available for employee packing/dispatch. Standalone fulfilment and
carrier providers still respond to employee requests when automatic customer order
generation is disabled. Expose seed, provider ownership and outstanding intents.

Define additive, versioned shipping envelope schemas/fixtures. Retain the existing
envelope identity, correlation, source/destination, effective_time and quantity
unit fields. Use the published storage request and fact shapes where applicable.
Persist destination-specific full envelopes before publication rather than
broadcasting sample quantities to every output. Match receipt/dispatch outcomes to
the exact pending intent and expected owner; enforce peer routing, payload shape,
aggregate references, event identity, effective time and run/epoch before mutation.

The baseline storage protocol cannot yet perform the entire connected lifecycle:
it accepts reservation requests but lacks peer release/pick/transfer commands and
explicit shortage outcomes. This is an implementation dependency, not permission
to infer success. Add the minimum backward-compatible storage boundary operations
and rejection facts required for the shipping lifecycle, with storage regressions
and a separate focused commit. Retain its HTTP/domain rules and existing schemas;
reuse warehouse command execution rather than duplicate its business logic. Include
a connected shipping/storage lifecycle test. This is a proposed scope extension
within SIMU-5's required stock integration; it is called out for user review.

Extend shipping peer configuration to authorize a list of explicit source/endpoint
routes on goods while accepting the existing single-route shape for compatibility.
Storage alone owns reservations, picks, releases and stock handoff. Manufacturing
alone owns production outcomes. Validate event type against that route's ownership;
an authorized manufacturing route must never assert a stock receipt. Do not use
storage as a hidden relay or relax source authentication for either peer.

Durably ingest valid future facts, execute only at granted time and acknowledge
adapter receives after durable commit. All current-time domain jobs and unsent
outputs participate in the existing time barrier. Retry publication with the same
event/request identity. Native ambiguity retains coordinated epoch recovery.

The current baseline publishes storage requests and facts but does not yet have
completed manufacturing/logistics domain contracts. Before integration, inspect
the committed SIMU-3/SIMU-4 contracts and reconcile mappings explicitly. Do not
claim connected interoperability based solely on sample events or a local mock.
If those branches are unavailable, shipping peer fixtures prove the documented
shipping contract and acceptance must clearly report the remaining integration.

## Website and deployment

Extend the existing independent Blade/Livewire site in its established industrial
style. Provide order entry, searchable orders, packing and dispatch queues, order
and shipment detail, command outcomes and chronological record history. Display
persisted quantities, provider provenance and failure reasons. Derive available
actions from durable state; enforce the same rules again server side. Keep uncertain
command identity/body for retry. Preserve authenticated sessions, CSRF and server
authorization on every Livewire update.

Retain the department image and api/worker/controller roles, owned PostgreSQL and
internal RabbitMQ. Add shipping V1 scenario/provider configuration to standalone
Docker packaging. Follow the storage V1 precedent for documented CyberLab inputs:
configurable role placement, reachable dependency addresses, independent secrets,
persisted state and readiness. The baseline has no CyberLab generator; adjacent
CyberLab module/provisioning work belongs to SIMU-13. Do not modify a neighboring
CyberLab checkout or perform live cutover. Document installation, identities,
providers, recovery and examples.

## Verification and resource safety

Build and test services only in Docker through `scripts/docker_guard.py`, keeping
the 20 GiB reserve. Share the guard's lock with concurrent worktrees; use unique
shipping test project/image identities so another agent's containers are untouched.
Keep generated credentials/manifests untracked and retain existing volumes.

Run the existing shipping native suite as baseline, then add regressions for full
multiline lifecycle, complete fulfilment, shortages, invalid/duplicate receipts,
premature packing/dispatch, explicit delivery, cancellation races/compensation,
idempotent replay/body conflict, concurrent workers, reset fencing, held/earlier
grants, output barriers, restart and broker/database failures. Verify real HTTP
and session authorization, forged Livewire actions, employee workflow, searching,
detail/history and UI screenshots in disposable deployments. Add standalone
production-container acceptance and connected domain fixtures; exercise native
HELICS routing with the new envelope types. Run `make stack-unit APP=shipping`
and `make stack-check APP=shipping` with isolated test configuration. Record exact
commands/results and distinguish local fixture, native peer and hosted evidence.

## Builder discretion and completion

The implementer may choose focused class boundaries, indexes, pagination,
deterministic scenario values and visual layout within the established style.
No dependency upgrade is planned. Any material peer-contract incompatibility must
be resolved and documented rather than guessed into a claim of completion.

Completion requires working employee and autonomous lifecycles, shipping-specific
recovery tests, independent deployment, verified website and documented connected
contracts. A design or implementation plan alone does not complete SIMU-5.
