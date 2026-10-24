# SIMU-5 controlled native HELICS acceptance

The shipping connected check runs the production Laravel API, RabbitMQ worker,
PHP controller and private HTTP HELICS adapter against PostgreSQL and a real
HELICS TCP broker. A second native federate supplies controlled storage,
manufacturing and carrier wire facts. Employee actions use the shipping HTTP API.
The verifier reads SQL for assertions and never writes business tables.

This is native transport and PHP business integration evidence. The peer fixture
does not execute the C# warehouse, Spring Boot manufacturing or Go logistics
applications, so this check does not establish cross-language departmental
interoperability or peer inventory/vehicle conservation.

## Reproduce

From the repository root:

```sh
sh scripts/check_shipping_connected.sh
```

All images, services and verification execute inside Docker through
`scripts/docker_guard.py --wait`, retaining its default 20 GiB free-space reserve.
The fixed isolated Compose project is `simu5-shipping-connected`; the native image
is `logistics-simulator:simu5-shipping-adapter`. The generator creates fresh run,
epoch, passwords and adapter credentials in an untracked mode-0600 manifest under
`deploy/generated/`. It exposes no host service ports. Exit cleanup removes only
this project's containers and disposable volumes, including its native journal.
No existing application volumes are used or pruned.

The command builds the production PHP, native adapter and repository bootstrap
verifier images sequentially. `SHIPPING_CONNECTED_REUSE_IMAGES=1` skips those builds
when the caller has already built the exact source being verified;
`SHIPPING_CONNECTED_IMAGE` can select that production PHP image. The bootstrap
verifier supplies Python HTTP/PostgreSQL client dependencies. Local diagnostic logs are retained at
`.superpowers/sdd/simu-5-shipping/connected-services.log`; generated configuration
and logs remain untracked.

## Assertions

- An external native customer order is accepted at grant 1 with effective time 20.
  No customer order exists before the grant reaches its due time. A duplicate is
  sent again after durable acceptance and creates one incoming record and command.
- A two-line order receives a typed stock shortage rejection, production demand,
  physically received replenishment, and complete reservations. Shipping emits no
  customer pick until every line is reserved.
- Typed pick, transfer and arrival facts retain remote reservation/transfer IDs
  and external customer correlation. Receipt confirms each entire line before
  employee packing and dispatch through HTTP.
- The peer supplies one typed carrier departure per line. The granted clock passes
  both planned ETAs while the shipment remains in transit. The first destination
  receipt leaves it in transit; the second confirms delivery.
- All three boundary providers remain HELICS, sample effects remain zero, and no
  business command is rejected during the legitimate lifecycle.
- A stale epoch command to the private adapter returns HTTP 409. A valid customer
  envelope sent through an unauthorized actual native source endpoint stalls the
  controller without creating another customer order.
- Restarting the adapter against the same journal leaves it stalled and rejects
  initialization. The existing run, epoch and delivered shipment remain intact;
  there is no automatic synthetic fallback or live epoch reconstruction.

## Local result

On 2026-10-24, `sh scripts/check_shipping_connected.sh` exited **0** locally on
Docker Desktop after rebuilding all three images from the final reviewed source.
All five printed acceptance groups passed. The delivered two-line order retained
**14 completed provider intents and 32 history entries**. The unauthorized-source
and restarted-adapter cases deliberately ended in a stalled native epoch.

The command removed every `simu5-shipping-connected` container, its network and
its three disposable volumes. Free space remained above the 20 GiB reserve
(32.4 GiB after cleanup). Nonsecret metadata and peer traces were retained at
`.superpowers/sdd/simu-5-shipping/native-verification.json` and
`native-peer-state.json`; the full build/check transcript is `connected-run.log`
in the same directory. This is local evidence, not hosted deployment evidence.

The existing `scripts/storage_peer.py` fixture was also updated to request explicit
customer picking and transfer, matching the new storage ownership rule. A
subsequent isolated `COMPOSE_PROJECT_NAME=simu5-storage-regression make storage-connected-check`
passed the real C# warehouse/native peer lifecycle and clean teardown. That is
a storage regression result, not proof of the combined C#/PHP/Java/Go chain.
