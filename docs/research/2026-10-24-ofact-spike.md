# Bounded Open Factory Twin assessment for SIMU-1

Decision: reject OFacT as the bootstrap runtime and do not copy/import its model code in this release. Reconsider isolated domain algorithms only when a concrete later application requirement justifies an adapter.

Examined upstream revision `45d044da62e7e3f993845c41b37471ea16bb2771` from [OpenFactoryTwin/ofact](https://github.com/OpenFactoryTwin/ofact/tree/45d044da62e7e3f993845c41b37471ea16bb2771). This was a bounded source-compatibility spike: shallow checkout outside the project, inspection of packaging, model imports, agent requirements, persistence and Docker composition. No XMPP/MongoDB services were installed and no OFacT runtime/performance claim is made.

Evidence from that revision:

- [Packaging](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/pyproject.toml) uses dynamic dependencies and lists Python 3.12; its project script is `ofact.cli:cli`.
- [Requirements](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/requirements.txt) include scientific/notebook libraries and SPADE/XMPP components. They are additional runtime dependencies rather than the selected PostgreSQL/RabbitMQ/HELICS scaffolding.
- [Docker example](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/docs/dev/docker/docker-compose.yml) starts an Openfire XMPP server and dashboard with a local Windows volume path. It is not a deployment for five independent applications with department-owned PostgreSQL databases.
- [Persistence](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/ofact/twin/repository_services/persistence.py) references MongoDB, while [StateModel](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/ofact/twin/state_model/model.py) imports a broad connected graph of entities, processes, sales and time classes plus dill/numpy. Wrapping that graph would still require the transaction, ownership, clock-grant and run-fencing contracts implemented here.

Inference: adopting the platform would introduce another messaging/persistence model while leaving the ticket's reliability contracts unimplemented. Even model-only reuse would require mapping OFacT object identity and state mutations to each independently owned database and authoritative granted-time transition boundary. There is no sample business algorithm in this bootstrap that benefits enough to justify that work.

Upstream code and non-code licenses are recorded separately in its `LICENSE` and `LICENSE_non_code`; any later selective reuse must preserve applicable notices. No upstream code or assets are included here.
