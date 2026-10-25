# Manufacturing OT v1

This private HTTP protocol connects the Java controller to the equipment journal;
it is not a HELICS publication or a second business API. Bearer authentication
and a private Docker network are required. POST `/v1/commands` accepts
`command.schema.json`; successful replies are `{version, command_id, result}`,
where result is the durable physical snapshot. GET `/v1/status` observes the
same snapshot and current connection/recovery state.

A command UUID is immutable within its run/epoch/controller session. An exact
replay returns its original receipt; changed content conflicts. Stale scopes
are rejected before cached receipts. Steps are consecutive integer seconds,
never wall-clock elapsed time. Completion facts follow `completed.schema.json`;
Java additionally validates expected order, scope, quantities, correlation and
a deterministic event UUID before committing business output. Scrap must not
exceed total quantity; good plus scrap must equal the dispatch quantity.

422 rejects an invalid command; 409 fences a conflicting identity/scope or
requires controlled recovery; 503 retains an uncertain intent for exact retry.
A process restart with an existing journal requires a new epoch. A cached
receipt alone does not authorise further physical progress after restart.
See [operation and register map](../../../docs/manufacturing-ot.md).
