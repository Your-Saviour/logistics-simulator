FROM python:3.12-slim
WORKDIR /app
COPY apps/adapter/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock
COPY src/simulator /app/src/simulator
COPY tests/adapter /app/tests/adapter
COPY examples/helics /app/examples/helics
ENV PYTHONPATH=/app/src
RUN useradd --uid 10001 --create-home adapter && mkdir /journal && chown adapter /journal
USER adapter
ENV ADAPTER_JOURNAL=/journal/adapter.sqlite
EXPOSE 8010
CMD ["gunicorn", "--workers", "1", "--threads", "1", "--bind", "0.0.0.0:8010", "simulator.adapter:from_env()"]
