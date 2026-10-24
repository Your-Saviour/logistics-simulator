# Storage verification

Run these commands from the repository root, one workload at a time:

```sh
sh scripts/check_stack_unit.sh storage
sh scripts/check_stacks.sh storage
```

These are host orchestration entry points. Service builds, dependency installs
and tests run inside Docker through `scripts/docker_guard.py`. The guard serializes
work and enforces the default 20 GiB free-space reserve. Neither command requires
host .NET, Node or npm execution. `SIMULATOR_MINIMUM_FREE_GIB` may raise the reserve.

## Latest backend evidence

The backend review run recorded **44 total checks passed (PostgreSQL and
RabbitMQ)** in the local artifact:

```text
.superpowers/sdd/simu-framework-migration/storage-dispose-lease-green.log
```

That total includes 13 pure validation/calendar/input checks. It covers strict
quantities and finite times, PostgreSQL URL options, timezone/DST calculations,
seed compatibility, earlier grants, completion barriers, concurrent exactly-once
sample effects, hold/reset and epoch fencing, bounded domain retries, migration
checksum refusal, confirmed mandatory publication and manual dead lettering.

The review regressions also verify:

- Connected finalize records `finalizing` until native acknowledgement; a native
  finalization failure can still mark the run `stalled`.
- JSON null is manually dead-lettered, and the consumer continues with the next
  valid job. Poison bodies cannot indefinitely requeue ahead of valid work.
- Standalone controller SQL lease loss retains the active run and epoch, then
  reacquires its lease after the disconnect instead of forcing a reset.

`check_stack_unit.sh storage` creates a uniquely named disposable test project,
starts PostgreSQL/RabbitMQ and runs `tests/Storage.Tests.csproj`. Its cleanup
removes only that project's containers and test volume. The harness intentionally
resets its own test run and temporarily tampers/restores an applied checksum;
never point it at production state. No application API/controller/worker services
should share that test database while the harness is running.

## Production and integration checks

`check_stacks.sh storage` generates the isolated standalone manifest, builds the
production API and Vue/nginx images sequentially, and runs the shared HTTP
acceptance, standalone dependency/recovery and browser checks. The frontend build
runs its component tests and TypeScript/production build. The generated stack has
independent test identities/data and no published host ports; cleanup stops only
that generated stack.

Production-image common HTTP, standalone terminal reset, broker/database outage,
duplicate delivery and browser checks passed. The final dedicated-lease rerun is
`storage-lease-production-green.log` in the same evidence directory. The Vue build
passed its two component tests and production compilation.

Mixed-language native handoffs, all four native-ACK finalizations and actual
adapter loss/restart fencing passed in `mixed-stacks-green.log`. This includes
visible SQL `stalled` after owner loss, committed effects retained, and no future
work or synthetic fallback. The controller's dedicated non-pooled lease also
passes a fresh physical-session ownership-release regression.

See [shared verification](../../docs/verification.md) for the commands/platform and
CI limitations. Hosted CI and physical multi-host behavior are not claimed.

Connected execution remains owner-coordinated: native session loss or ambiguous
finalization requires a new federation epoch. Standalone SQL connection/timeout
recovery preserves the current run and retries lease acquisition; workers retain
unacknowledged durable deliveries without consuming domain retry attempts.
