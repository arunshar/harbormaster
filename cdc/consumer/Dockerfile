# Harbormaster CDC consumer image. Build from the REPO ROOT:
#   docker build -f cdc/consumer/Dockerfile -t harbormaster-cdc-consumer .
# Config is env-driven (HM_KAFKA_BOOTSTRAP, HM_ONLINE_TABLE, ...); see
# cdc/consumer/service.py ConsumerConfig.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv
WORKDIR /srv

# librdkafka ships inside the confluent-kafka wheel; no apt packages needed.
RUN pip install --upgrade pip && pip install \
    "confluent-kafka>=2.3" "boto3>=1.34" "redis>=5" \
    "pyiceberg[sql-sqlite]>=0.7" "pyarrow>=15" \
    "aws-msk-iam-sasl-signer-python>=1.0" \
    "structlog>=24.1" "prometheus-client>=0.20"

COPY cdc ./cdc

CMD ["python", "-m", "cdc.consumer.service"]
