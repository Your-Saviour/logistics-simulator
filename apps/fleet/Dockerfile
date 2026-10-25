FROM python:3.12-slim
WORKDIR /app
COPY apps/twin/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY apps/fleet/backend /app/fleet
COPY apps/fleet/tests /app/tests
COPY contracts /app/contracts
COPY apps/fleet/migrations /app/migrations
COPY apps/fleet/entrypoint.sh /app/entrypoint.sh
ENV PYTHONPATH=/app
RUN useradd --uid 10002 --create-home fleet && chmod +x /app/entrypoint.sh
USER fleet
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "fleet.worker"]
