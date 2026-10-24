FROM python:3.12-slim
WORKDIR /app
COPY apps/twin/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY src/simulator /app/src/simulator
COPY contracts/handling /app/contracts/handling
COPY migrations /app/migrations
COPY apps/twin/backend /app/twin
COPY apps/twin/tests /app/tests
COPY apps/twin/entrypoint.sh /app/entrypoint.sh
ENV PYTHONPATH=/app/src:/app
ENV SIMULATOR=twin
RUN useradd --uid 10001 --create-home twin && chmod +x /app/entrypoint.sh
USER twin
EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
