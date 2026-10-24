Tests were authored before their production behavior. Observed red failures:
valid job rejected by initial Rules scaffold; operator scope missing; durable
migration/adapter session not implemented; status route returned404; sign-in form
missing; unscoped Livewire status accepted. Domain, security, ledger/AMQP, adapter
journal, Laravel route and Blade/scope suites then passed inside guarded Docker.

`all.sh` runs each PHP harness in a separate process to avoid helper/app singleton
cross-contamination. Stop the disposable worker/controller first. `http.php` and
`web_http.php` instead target the actual production server and need all roles up.
`finalize.php` requires API up with worker/controller stopped. See ../README.md for
commands, environment, test-only state mutations and honest integration limits.
