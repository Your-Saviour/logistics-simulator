# Open-source reuse assessment

Research date: 24 October 2026. Method: primary project documentation, repositories, manifests, and selected source files. No candidate was installed or executed; a documented feature is not a verified working deployment.

## Recommendation

Retain the selected RabbitMQ/PostgreSQL architecture with department APIs, background worker pools, employee applications, and a separate digital-twin projection. Subsequent requirements strengthen the need for independent runtime boundaries: five separate websites, four independently usable business simulators, and HELICS support. No inspected project supplies that complete combination as a ready deployment. Open Factory Twin is the strongest domain-specific candidate for a bounded reuse spike. SimPy is a small simulation-engine candidate if a library is useful; it must not become an in-memory replacement for durable distributed business state.

The employee-frontend requirement also makes real ERP systems relevant. Odoo Community could provide authentic manufacturing and inventory workflows, but adopting it as the centre changes the approved direction from independent departmental services to a modular ERP. Treat that as an alternative requiring an explicit decision, not an invisible implementation shortcut. ERPNext similarly changes the proposed stack and database choice.

## Screenshot candidates

| Project | Verified purpose / software licence | Fit and possible reuse |
| --- | --- | --- |
| [Open Factory Twin / OFacT](https://github.com/OpenFactoryTwin/ofact) | Python production/logistics digital-twin framework; Apache-2.0 software, separately licensed non-code material | Closest domain match: resources, processes, orders, material flows, simulation, agent control, analytics. Investigate selected model/simulation components; not a complete distributed SMB application. |
| [LOTUSim](https://github.com/naval-group/LOTUSim) | ROS 2/Gazebo maritime multi-domain physics; EPL-2.0 | Optional maritime vehicle simulation if that becomes a requirement. Does not supply warehouse/order/employee workflows. A shipping company application does not inherently require ship physics. |
| [OTForge](https://github.com/iburres/otforge) | Electron/Docker ICS training platform; application MIT, bundled tools separately licensed | Relevant reference for industrial protocol/device containers and cyber-range scenarios. Not an autonomous business ERP or fulfilment model. |
| [HENDRICS](https://github.com/CEA-Leti/HENDRICS) | GPLv3 ICS testbed using STM32 hardware and containerized SCADA/monitoring services | Useful hardware-in-the-loop industrial exercise; poor foundation for the requested software-only business workflow. |
| “frostICS” | Exact project identity unverified; likely [frostyICS](https://github.com/austrisu/frostyICS), MIT | Likely match uses Siemens PLC/SCADA configurations. Its warehouse functions concern lighting/alarms rather than stock reservations, picking, or delivery. Do not equate the names without the original link. |
| [tpt-shipyard](https://github.com/tpt-solutions/tpt-shipyard) | Rust construction/shipyard engine; current source declares MIT OR Apache-2.0 | Narrow donor for construction scheduling, staging, and material planning; not a company application suite. Logistics is simplified and several companion integrations are explicitly stand-ins. |

## Open Factory Twin: shortlist for a spike

The [repository](https://github.com/OpenFactoryTwin/ofact) includes state models, simulation, agent-control and analytics code, and a [bicycle-factory simulation entry point](https://github.com/OpenFactoryTwin/ofact/blob/main/projects/tutorial/04_simulation/2_bicycle_factory_simulation.py). The [introductory documentation](https://openfactorytwin.github.io/ofact/) describes an earlier, narrower state-model release, so it understates current available source. Conversely, broad descriptions of the ecosystem should not be read as proof that all components are publicly deployable together.

Integration gaps:

- Its [Compose example](https://github.com/OpenFactoryTwin/ofact/blob/main/docs/dev/docker/docker-compose.yml) uses Openfire/XMPP and refers to a Dashboard-UI build directory absent from the inspected public tree. It does not provide the requested RabbitMQ/PostgreSQL departmental deployment.
- A [MongoDB adapter](https://github.com/OpenFactoryTwin/ofact/blob/main/ofact/twin/repository_services/db/mongodb.py) and SPADE/XMPP agent assumptions differ from the proposed persistence and queue boundaries.
- [Analytics/API code](https://github.com/OpenFactoryTwin/ofact/blob/main/ofact/planning_services/scenario_analytics/interface/controller.py) exists, but that does not establish four finished employee applications.
- [Working-demonstrator](https://github.com/OpenFactoryTwin/ofact/issues/6), [frontend](https://github.com/OpenFactoryTwin/ofact/issues/14), and [agent-control](https://github.com/OpenFactoryTwin/ofact/issues/13) issues document remaining integration work. A release page and recent repository activity establish maintenance evidence, not production readiness.

Proposed bounded execution spike, requiring separate authorization before installing/running a new stack: pin a revision, execute the smallest bicycle example, build a minimal production model, serialize its outcomes, and identify whether a worker can use a domain component without importing its entire agent/persistence stack. Compare that effort against implementing a small bill-of-materials/capacity model directly. A positive spike must preserve departmental database ownership, durable jobs, common simulation time, and RabbitMQ events.

## Other simulation engines

| Candidate | Available capabilities / licence | Fit |
| --- | --- | --- |
| [SimPy](https://simpy.readthedocs.io/en/stable/) | Python discrete-event processes, finite resources, manual stepping, fast or wall-clock execution; MIT | Small, focused library option for scenario/production modelling. No employee UI, persistence, broker or distributed clock supplied. |
| [salabim](https://github.com/salabim/salabim) | Python queues/resources/stores, simulation statistics, 2D/3D animation; MIT declared in [metadata](https://github.com/salabim/salabim/blob/master/pyproject.toml) | Useful if its native animation fits an experiment. Still requires custom web applications and distributed integration. |
| [JaamSim](https://github.com/jaamsim/jaamsim) | Java discrete-event simulation, visual model editor, interactive 3D; Apache-2.0 engine | Strong desktop modelling option; less natural for the selected distributed web application. Bundled example libraries may have separate licences. |

Important engineering distinction: SimPy and similar engines advance an in-process event queue. RabbitMQ distributes asynchronous work; it does not coordinate a discrete-event simulation clock. A common durable clock and due-job protocol still need to be designed and tested. Do not independently accelerate four engines and assume causal ordering or exactly-once inventory effects.

## Employee application alternatives

**[Odoo Community](https://github.com/odoo/odoo):** web-based business application suite, LGPLv3 core, with [manufacturing](https://github.com/odoo/odoo/blob/19.0/addons/mrp/__manifest__.py) and [stock](https://github.com/odoo/odoo/blob/19.0/addons/stock/__manifest__.py) modules in the public Community source. Official [Docker packaging](https://github.com/odoo/docker) uses PostgreSQL connections in its [entrypoint](https://github.com/odoo/docker/blob/master/19.0/entrypoint.sh). This could save substantial employee-workflow UI work. However, departmental modules normally operate within the same application/database boundary; independently scaled web processes are not independent manufacturing/storage/shipping services. Autonomous activity, fleet/delivery modelling, RabbitMQ adapters, a simulation clock and the combined twin remain custom work. Verify each required screen against Community source rather than assuming commercial product pages describe free features.

**[ERPNext](https://github.com/frappe/erpnext):** GPLv3 ERP with manufacturing, distribution and stock workflows. The official [Frappe Docker setup](https://github.com/frappe/frappe_docker/blob/main/docs/01-getting-started/04-single-compose-setup.md) separates frontend, backend, websocket, queues, scheduler, MariaDB and Redis. That is relevant infrastructure separation. But official [Helm documentation](https://github.com/frappe/helm/blob/main/erpnext/README.md) states ERPNext requires MariaDB; PostgreSQL support for the underlying Frappe framework does not establish ERPNext support. It also uses Redis-backed queues, not the selected RabbitMQ design. Consider only if changing these choices is acceptable.

## Narrow uses of the remaining screenshot projects

- LOTUSim has separate [React UI](https://github.com/naval-group/LOTUSim-UI-frontend) and [Express backend](https://github.com/naval-group/LOTUSim-UI-backend). Vessel position streaming is useful as a reference; not evidence of order/inventory integration. Instance-management endpoints include stubs, so multi-instance orchestration should be checked in source before relying on it.
- OTForge's [orchestrator package](https://github.com/iburres/otforge/blob/main/packages/orchestrator/package.json) uses a different application/persistence stack. Isolated protocol endpoints are a plausible future optional CyberLab module; importing a second range orchestrator is unlikely to simplify CyberLab.
- HENDRICS [server services](https://github.com/CEA-Leti/HENDRICS/blob/main/servers/README.md) include MQTT, Node-RED, InfluxDB, Grafana and FUXA. These are HMIs/ICS services, not interchangeable with employee warehouse and dispatch software.
- tpt-shipyard's [Dockerfile](https://github.com/tpt-solutions/tpt-shipyard/blob/master/Dockerfile) packages a CLI. Its [logistics implementation](https://github.com/tpt-solutions/tpt-shipyard/blob/master/crates/planning/tpt-yard-logistics/src/lib.rs) covers planning/arrival/staging calculations, not an API-backed warehouse execution service. Its WASM/Three.js demo is not proof of a complete persistent multi-user employee frontend.

## Decision to carry into design

Recommended: four autonomous simulator stacks and a fifth twin website, with selective reuse subject to a bounded OFacT spike; SimPy remains optional rather than a mandatory dependency. RabbitMQ handles internal background jobs; HELICS handles cross-simulator business exchange and time coordination. Prefer the simplest durable scheduling model that meets the lifecycle and granted-time requirements. Keep OT/maritime/shipyard physics out of the first release unless a concrete exercise needs them.

Alternative: centre the company on Odoo Community if authentic ERP workflows are more important than the four independent service/database boundaries. This is a meaningful change and should be chosen explicitly before an implementation plan.

These are fit assessments inferred from inspected code and documentation. Runtime reliability, resource consumption, multi-machine deployment, full feature completeness, and exact integration effort remain untested.

## HELICS: required co-simulation integration

[HELICS](https://github.com/GMLC-TDC/HELICS) is a co-simulation framework rather than a factory simulator. Its core is BSD-3-Clause. The official [Python bindings](https://python.helics.org/) expose combination federates, typed value publications/subscriptions, message endpoints and synchronous/asynchronous time requests.

For this project's now-required independent simulators, use one HELICS combination federate per active business simulator. Each owns its own API/worker/database state and must complete current-time local work before requesting the next grant. Incoming exchanges can produce earlier grants than requested. RabbitMQ queue emptiness cannot replace a durable completion ledger. See official [timing semantics](https://docs.helics.org/en/main/user-guide/fundamental_topics/timing_configuration.html) and [interface semantics](https://docs.helics.org/en/latest/user-guide/fundamental_topics/federates.html).

Standalone mode uses seeded synthetic providers at the same business boundaries and a local clock. Federated mode replaces each selected provider with a HELICS peer; startup validates exactly one provider per boundary. Do not duplicate business delivery through both HELICS and cross-department RabbitMQ exchanges. A HELICS adapter does not supply domain workflows, employee frontends, persistence or fault recovery automatically.

The twin can consume read-only departmental API/projection feeds. An optional receive-only HELICS observer must not control business state or hold back federation time. Observers do not automatically receive historical message replay; late joining depends on dynamic federation configuration. See [dynamic federation and observer documentation](https://docs.helics.org/en/latest/user-guide/advanced_topics/dynamic_federations.html). Prefer source snapshots plus durable event cursors for the twin.

For multi-host Docker, explicitly configure routable broker/core addresses and ports; official [networking guidance](https://docs.helics.org/en/main/user-guide/advanced_topics/networking.html) recommends tcp_ss for complex networks. Federation time is monotonic, so resetting a live participant is not a local rewind: coordinate a new run/epoch. Local pause and global federation pause are different operations. The surrounding simulator series' precise HELICS contracts remain unknown and must be supplied or mapped before claiming interoperability with those actual systems.
