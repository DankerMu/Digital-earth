FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libeccodes-dev \
    libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/data-pipeline/pyproject.toml services/data-pipeline/poetry.lock* ./
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction

COPY services/data-pipeline/src ./src
COPY services/data-pipeline/config ./config
COPY config ./config
COPY packages/config/src ./packages/config/src

ENV DIGITAL_EARTH_CONFIG_DIR=/app/config
ENV PYTHONPATH=/app/src:/app/packages/config/src

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "main"]
