FROM serversideup/php:8.4-frankenphp@sha256:c44f4a10b8bd83238b6e71eb5d223c6a08745ef643c6b7aff899e66672e5d20f AS toolchain
USER root
RUN install-php-extensions sockets
WORKDIR /app
USER www-data
FROM toolchain AS dependencies
COPY --chown=www-data:www-data apps/shipping/composer.json apps/shipping/composer.lock ./
RUN composer install --no-dev --no-interaction --prefer-dist --no-scripts --no-progress --optimize-autoloader && composer clear-cache
FROM dependencies AS runtime
COPY --chown=www-data:www-data apps/shipping/ /app/
RUN mkdir -p storage/framework/cache storage/framework/sessions storage/framework/views storage/logs bootstrap/cache
ENV GOMAXPROCS=2 GOMEMLIMIT=128MiB FRANKENPHP_CONFIG="num_threads 2"
ENV ROLE=api SIMULATOR=shipping APP_ENV=production APP_DEBUG=false CADDY_SERVER_ROOT=/app/public CADDY_HTTP_PORT=8000 SSL_MODE=off PHP_MEMORY_LIMIT=256M PHP_OPCACHE_ENABLE=1 AUTORUN_ENABLED=false
EXPOSE 8000
# The base probe assumes every process serves Caddy. Worker/controller roles
# report through SQL heartbeats and /api/health/ready, like the other stacks.
HEALTHCHECK NONE
CMD ["sh", "/app/entrypoint.sh"]
