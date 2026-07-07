# Harbormaster serving plane image. Build from the REPO ROOT (needs pyproject +
# the serving/streaming package dirs):
#   docker build -f serving/Dockerfile -t harbormaster-serving .
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Deps + package. pyproject maps serving/app -> app, streaming/features -> features,
# and ships app/artifacts/corridors.json inside the wheel. shapely wheels bundle GEOS.
COPY pyproject.toml README.md ./
COPY serving/app ./serving/app
COPY streaming/features ./streaming/features
RUN pip install --upgrade pip && pip install .

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD curl -fsS http://localhost:8000/healthz || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
