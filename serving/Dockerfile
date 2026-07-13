# Harbormaster serving plane image. Build from the REPO ROOT (needs pyproject +
# the serving/streaming package dirs):
#   docker build -f serving/Dockerfile -t harbormaster-serving .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Deps + package. The serving runtime extra supplies the configured Postgres,
# DynamoDB, and Redis paths. The wheel carries cdc.schema because registry and
# HITL initialization use its DDL. Shapely wheels bundle GEOS.
COPY pyproject.toml README.md ./
COPY serving/app ./serving/app
COPY streaming/features ./streaming/features
COPY cdc ./cdc
RUN pip install --upgrade pip && pip install ".[serving-runtime]"

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
