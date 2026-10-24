# Independent website design previews

These are five self-contained HTML previews with illustrative local state. They are not implemented services or connected simulators. Each document opens independently without a build or dependencies:

- [Digital twin](twin.html): dark facility schematic, sample business lifecycle, order progress, event feed.
- [Manufacturing](manufacturing.html): production work order ready for release.
- [Storage](storage.html): stock and a pick list ready for confirmation.
- [Logistics](logistics.html): a sample delivery ready for arrival confirmation.
- [Shipping](shipping.html): a sample shipment ready to dispatch.

The different starting states allow each employee website to demonstrate its own task without running the other four. Each document's sample state stays in its own page; links open other previews in separate tabs. Shared design styling does not imply a shared application runtime. No RabbitMQ, PostgreSQL, real authentication, HELICS, external simulators or production backend are connected.

The full system design requires five separately deployed websites, four autonomous business simulator stacks, and optional connected operation through HELICS. This preview has not yet implemented that infrastructure. The local brainstorming server serves the same documents for review; it is a preview convenience, not the proposed deployment topology.
