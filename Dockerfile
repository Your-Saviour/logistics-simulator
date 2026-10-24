FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY migrations ./migrations
COPY contracts ./contracts
COPY tests ./tests
COPY examples ./examples
COPY scripts ./scripts
RUN useradd --uid 10001 --create-home simulator
USER simulator
CMD ["uvicorn", "simulator.api:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
