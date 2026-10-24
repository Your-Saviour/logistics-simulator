# Shipping V1 (SIMU-5)

Shipping owns its Laravel API, Blade/Livewire employee website, PHP worker and
controller, PostgreSQL and RabbitMQ. Standalone operation needs no other
simulator. Native HELICS belongs to the private adapter, never PHP.

## Employee workflow

Sign in at `/` with a configured employee identity. Enter a customer reference,
destination and distinct SKU lines with whole quantities 1..10000. Request
fulfilment to reserve the complete order. Shortage produces a visible production
request; production confirmation retries reservation. Packing becomes available
only after every line is physically received. Pack and dispatch from their queues.
One order has one shipment with a carrier intent for each SKU line. The shipment
progresses through carrier confirmation and becomes delivered only when every
line has its matching destination confirmation. Elapsed ETA alone cannot mark
delivery.

Search by customer, order ID, destination or SKU. The order link opens quantities,
shipment confirmation and chronological record history. The command outcomes table
reports asynchronous acceptance, completion and business rejection. Employee
identities cannot control runs or read security audits. Browser actions derive a
stable operation identity from a locked nonce and the normalized form. The owned
PostgreSQL `shipping_prepared_commands` table retains the exact prepared body,
including due time and key. Replaying the original Livewire snapshot after a lost
response uses that prepared submission even when the run watermarks have advanced.

Cancellation is available before irreversible picking/physical handoff; its intent
persists independently of the displayed order status while pending facts and
reservation releases settle. Failed compensation blocks cancellation and never
resumes picking. Returns and cancellation after handoff are outside V1.

## HTTP commands

Use Basic authentication for APIs; browser sessions use CSRF-protected sign-in and
Livewire updates. `status:read` permits `GET /api/shipping` and
`GET /api/shipping/orders/{id}`. `jobs:write` permits
`POST /api/shipping/commands` with an `Idempotency-Key` header.

Read the current `run.id`, `run.epoch`, `run.granted` and `run.requested` from
`GET /api/status`. Submit a due time beyond the greater watermark by at least
`HANDOFF_QUANTUM`, allowing for network time and standalone speed. Example body:

```json
{
  "run_id": "20000000-0000-4000-8000-000000000001",
  "epoch": "30000000-0000-4000-8000-000000000001",
  "due_at": 25,
  "action": "create",
  "customer": "ORDER-1042",
  "destination": "CUSTOMER-A",
  "lines": [{"sku": "PRODUCT", "quantity": 4}, {"sku": "COMPONENT", "quantity": 3}]
}
```

`fulfil`, `pack`, `dispatch` and `cancel` use `reference: <order UUID>` instead of
customer/destination/lines. The create command ID becomes the order ID. Response
acceptance is durable, with `outcome: pending|completed|rejected` in the shipping
snapshot. Retry an uncertain submission with the exact same key and body. A changed
body conflicts. Invalid or old run/epoch submissions cannot mutate a new run.

## Persistent installation

Create `.superpowers/` if needed, copy `shipping.env.example` to
`.superpowers/shipping.env` (ignored by Git), and restrict it to mode 600.
Generate independent random operator, employee, database and broker secrets. Set
`SHIPPING_APP_KEY` to `base64:` plus 32 cryptographically random bytes encoded in
base64. Keep the key stable across API restarts so existing sessions remain valid.
Do not use example placeholders in a deployment.

From the repository root, run service work through the Docker guard:

```sh
python3 scripts/docker_guard.py --wait --label shipping-build -- docker compose --env-file .superpowers/shipping.env -f apps/shipping/compose.v1.yaml --profile local build shipping-api
python3 scripts/docker_guard.py --wait --label shipping-start -- docker compose --env-file .superpowers/shipping.env -f apps/shipping/compose.v1.yaml --profile local up -d --wait
```

The default website binding is `127.0.0.1:8085`. Place an authenticated HTTPS
reverse proxy in front for remote access. The API and website share port 8000
inside the API container. Owned database, broker and sessions use persistent
project-scoped volumes. All three PHP roles perform locked migrations at startup.
Readiness is `GET /api/health/ready`, authenticated using deployment credentials;
worker/controller heartbeats participate in readiness.

The default `AUTONOMOUS_SHIPPING=true` creates seeded provider customer orders and
operates those orders. Human-created orders require employee packing and dispatch.
Set it to `false` for employee-only order entry: synthetic goods/carrier still
answer fulfilment and dispatch requests. Legacy sample generation stays disabled
in this packaging. `SHIPPING_SCENARIO` sets seed, timezone, calendar and interval.
Defaults use Australia/Adelaide business hours.

## Role placement and CyberLab inputs

Use the same production image and independent role processes on the desired
hosts. Set `SHIPPING_DATABASE_URL` and `SHIPPING_AMQP_URL` to reachable private
addresses and omit `--profile local` to use external dependencies. Keep
`SHIPPING_DB_PASSWORD` and `SHIPPING_BROKER_PASSWORD` set for Compose interpolation;
these local-profile credentials are not used when explicit URLs are supplied.
Configure the API ingress, private dependency routing, environment secrets and
persistent storage in the target environment. Scale workers against the same
owned ledger/broker; retain one run controller. These are deployment inputs,
not a CyberLab module generator or a live cutover procedure.

Four explicit routing inputs are forwarded to every shipping role:

- `SHIPPING_STOCK_LOCATION` (default `FINISHED-A`) identifies the storage stock
  location used for reservations and picking.
- `SHIPPING_STOCK_DESTINATION` (default `DISPATCH`) is the storage transfer
  destination. Confirmed stock transfer must reach this configured dispatch
  location before shipping can treat the goods as received.
- `SHIPPING_PRODUCTION_LINE` (default `LINE-1`) identifies the manufacturing line;
  its peer configuration must support the requested product.
- `SHIPPING_CARRIER_ROUTE` (default `DISPATCH-CUSTOMER`) identifies the logistics
  route. That route must end at the order's destination, and a typed arrival fact
  must confirm the same destination. The route name alone cannot prove arrival.

Connected mode requires `CLOCK_MODE=helics`, explicit federation/run/epoch,
`BOUNDARY_PROVIDERS`, private adapter URL/token and authorized peer/output routes.
Goods may authorize separate storage and manufacturing routes; each owner may
confirm only its own fact types. A configured HELICS provider never falls back to
synthetic outcomes after failure. Shipping fixtures and standalone synthetic
acceptance do not establish interoperability with unmerged manufacturing/logistics
implementations. Reconcile their committed contracts before deployment together.

## Recovery and verification

Keep PostgreSQL and RabbitMQ volumes when restarting roles. Durable commands,
provider intents and stable event identities survive restarts; transient dependency
failure must retain pending work. Restore dependencies before restarting roles.
Run reset intentionally through operator controls; it changes the epoch and fences
old commands. Back up the database and broker with their established operational
procedures. Never edit applied migration SQL or attach disposable test volumes to
persistent installations.

Run the isolated production packaging acceptance:

```sh
sh scripts/check_shipping_deployment.sh
```

It uses project `simu5-shipping-v1`, production image
`logistics-simulator:simu5-shipping`, fresh random credentials and disposable
project volumes. It builds the current code, exercises authenticated multiline HTTP
fulfilment through shortage/replenishment/physical receipt and explicit carrier
delivery with matching confirmations for every carrier line, invalid transitions,
cancellation, exact replay/body conflict, pending
command recovery after a real worker stop/start, and a real employee browser
workflow with queue filtering, detail/history and mobile overflow assertions. A
second browser test replays the exact original signed Livewire request after its
command completes, proving response loss cannot create a second order.
Only its own project volumes are removed. Existing shipping deployments remain
separate. Desktop/mobile PNGs and retained failure traces are written under
`.superpowers/sdd/simu-5-shipping/deployment/`.

Also run `make stack-unit APP=shipping`, `make stack-check APP=shipping` and native
HELICS acceptance through the shared guard. Report local production-container,
peer-fixture/native and hosted evidence separately; no hosted result is implied by
these local commands.
