# Per-department HELICS adapter

The adapter owns native handles for exactly one business combination federate.
It has no business database access. Every business application deploys its own
instance; the twin never uses it. Protocol: `docs/adapter-protocol.md` and
`contracts/adapter/v1/command.schema.json`.

Run builds/tests inside containers, from the repository root:

```sh
docker build -t logistics-simulator:adapter -f apps/adapter/Dockerfile .
docker run --rm --entrypoint pytest logistics-simulator:adapter -q -p no:cacheprovider tests/adapter
docker run --rm --entrypoint python logistics-simulator:adapter examples/helics/adapter_smoke.py
```

The reference smoke opens only container-local HTTP listeners. It proves delayed
and earlier grants, typed external 25 kW input, replayed publication, receive
ACK barriers and a killed native owner's restart refusal. Native disconnect
warnings are expected during the deliberate kill test.

Runtime requires `SIMULATOR`, `FEDERATION_ID`, `FEDERATION_RUN_ID`,
`FEDERATION_EPOCH`, `HELICS_CONFIG`, `HELICS_OUTPUTS`, `HELICS_ADAPTER_TOKEN` and
`ADAPTER_JOURNAL`. The image listens on 8010. Give `/journal` a department-owned
persistent writable volume. Keep the interface private; do not expose the
adapter token to browsers. One Gunicorn worker and one thread serialize access
alongside an in-process lock and an exclusive journal owner lock. Never add
workers to scale a native federate.

SQLite is an operation intent/result journal and native-loss fence, not a
HELICS checkpoint. Same-process HTTP retries reuse request IDs and return the
original result. A restart after native initialization is stalled for the old
epoch. Coordinate a new federation epoch with its owner and archive the old
journal before launch. No live rejoin or silent synthetic fallback is claimed.

Supported runtime is Python 3.12 / HELICS 3.6.1, Flask 3.1.3 and Gunicorn 26.2.0;
resolved dependencies are locked in `requirements.lock`. Unit and native smoke
checks were exercised in Linux ARM64 Docker, not on the base host.
