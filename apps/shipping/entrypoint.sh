#!/bin/sh
set -eu
umask 077
php artisan simulator:migrate
case "${ROLE:-api}" in
 api) exec frankenphp run --config /etc/frankenphp/Caddyfile --adapter caddyfile ;;
 worker) exec php artisan simulator:worker ;;
 controller) exec php artisan simulator:controller ;;
 *) echo 'ROLE must be api, worker or controller' >&2; exit 1 ;;
esac
