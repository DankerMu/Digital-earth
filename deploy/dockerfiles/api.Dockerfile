# Stage 1: Build
FROM python:3.11-slim AS builder
WORKDIR /repo

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY packages/config/pyproject.toml packages/config/README.md ./packages/config/
COPY packages/config/src ./packages/config/src
COPY packages/shared/src ./packages/shared/src

COPY apps/api/pyproject.toml ./apps/api/
WORKDIR /repo/apps/api
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-root --no-interaction

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY apps/api/src ./src
COPY packages/config/src ./packages/config/src
COPY packages/shared/src ./packages/shared/src
COPY packages/shared/config ./packages/shared/config
COPY config ./config

ENV DIGITAL_EARTH_CONFIG_DIR=/app/config
ENV PYTHONPATH=/app/src:/app/packages/config/src:/app/packages/shared/src

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
