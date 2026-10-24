# Logistics simulator

SIMU-1 application bootstrap: four independent business simulator skeletons and a fifth digital-twin website. Python APIs/workers/controllers, React/TypeScript frontends, PostgreSQL, RabbitMQ and HELICS. Department-specific V1 workflows are separate work.

```sh
make up APP=storage
make credentials APP=storage
# Open http://127.0.0.1:8182
```

Use `make suite` for all five, or select `manufacturing`, `storage`, `logistics`, `shipping` or `twin` independently. `make check` runs the backend, native federation, frontend and configuration checks.

- [Start and verify the applications](docs/bootstrap.md)
- [Verification record and limits](docs/verification.md)
- [API and boundary contracts](docs/contracts.md)
- [Clock control, recovery and multi-host configuration](docs/operations.md)
- [OFacT reuse decision](docs/research/2026-10-24-ofact-spike.md)
- [Original system design](docs/superpowers/specs/2026-10-24-logistics-simulator-design.md)
- [Static design previews](docs/previews/README.md)

This implementation is application development only. It does not include CyberLab integration or cloud deployment.
