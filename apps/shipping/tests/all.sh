#!/bin/sh
set -eu
php /app/tests/run.php
php /app/tests/security.php
php /app/tests/ledger.php
php /app/tests/adapter.php
php /app/tests/controller_outage.php
php /app/tests/feature.php
php /app/tests/web.php
php /app/tests/ui_scope.php
