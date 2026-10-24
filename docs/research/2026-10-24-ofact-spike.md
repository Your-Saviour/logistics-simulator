# Bounded Open Factory Twin assessment for SIMU-1

Decision: reject OFacT as the bootstrap runtime and do not copy/import its model code in this release. Reconsider isolated domain algorithms only when a concrete later application requirement justifies an adapter.

Examined upstream revision `45d044da62e7e3f993845c41b37471ea16bb2771` from [OpenFactoryTwin/ofact](https://github.com/OpenFactoryTwin/ofact/tree/45d044da62e7e3f993845c41b37471ea16bb2771). The evaluation inspected packaging, model imports, agent requirements, persistence and Docker composition, then executed the upstream sales-generation tutorial inside a Python 3.12 container with networking disabled and limits of 1 GiB memory / 2 CPUs. No XMPP/MongoDB services were installed.

Evidence from that revision:

- [Packaging](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/pyproject.toml) uses dynamic dependencies and lists Python 3.12; its project script is `ofact.cli:cli`.
- [Requirements](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/requirements.txt) include scientific/notebook libraries and SPADE/XMPP components. They are additional runtime dependencies rather than the selected PostgreSQL/RabbitMQ/HELICS scaffolding.
- [Docker example](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/docs/dev/docker/docker-compose.yml) starts an Openfire XMPP server and dashboard with a local Windows volume path. It is not a deployment for five independent applications with department-owned PostgreSQL databases.
- [Persistence](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/ofact/twin/repository_services/persistence.py) references MongoDB, while [StateModel](https://github.com/OpenFactoryTwin/ofact/blob/45d044da62e7e3f993845c41b37471ea16bb2771/ofact/twin/state_model/model.py) imports a broad connected graph of entities, processes, sales and time classes plus dill/numpy. Wrapping that graph would still require the transaction, ownership, clock-grant and run-fencing contracts implemented here.

Inference: adopting the platform would introduce another messaging/persistence model while leaving the ticket's reliability contracts unimplemented. Even model-only reuse would require mapping OFacT object identity and state mutations to each independently owned database and authoritative granted-time transition boundary. There is no sample business algorithm in this bootstrap that benefits enough to justify that work.

Upstream code and non-code licenses are recorded separately in its `LICENSE` and `LICENSE_non_code`; any later selective reuse must preserve applicable notices. No upstream code or assets are included here.


## Executed example

Run `python3 scripts/ofact_spike.py` to fetch the pinned revision, build the separate evaluation image and execute the unmodified code cells from `projects/tutorial/01_modelling/9_sales_generation.ipynb`. The runner uses the tutorial working directory because upstream project-path discovery depends on the current directory. The initial root-directory run correctly exposed a missing workbook path; changing the working directory required no upstream source patch.

Result on 2026-10-24: **20 orders, 8 customers, 2.016 seconds** for import/deserialization/generation in the local isolated ARM64 container. This is a bounded successful example run, not a performance benchmark or proof of the XMPP factory simulation. The example also serialized its model inside the disposable container. Upstream logged an optional missing-pyarrow message; generation completed successfully.

Evaluation-only dependencies: numpy 2.1.1, pandas 2.2.3, dill 0.4.0, scipy 1.15.2, openpyxl 3.1.5 and cerberus 1.3.7. They are not application dependencies. `tools/ofact/run_example.py` executes the source notebook and checks the resulting order/customer counts; source remains pinned and no upstream code/assets are copied into the application repository.

The successful import/generation shows OFacT offers richer product/customer/order objects. It does not remove the need for independently owned PostgreSQL state, transactional commands/audits/outboxes, grant-gated jobs, role-scoped APIs or five independent websites. The custom bootstrap remains smaller and directly enforces those contracts. The reject-for-bootstrap decision therefore stands; reused components: none.
