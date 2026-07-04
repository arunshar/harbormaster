# Phase 3 AWS-showcase DEMO STAND-IN container. NOT Pi-DPM: see server.py's
# module docstring. Builds and runs today with no external dependencies
# (unlike ../Dockerfile, which needs pi-grpo's scorer code from a separate,
# un-vendored repo); this is what docs/runbooks/PHASE_3_AWS_SHOWCASE.md
# actually deploys to demonstrate the real SageMaker async endpoint
# infrastructure, scale-to-zero, and the promotion pipeline.

FROM python:3.11-slim

WORKDIR /opt/pidpm-demo

COPY server.py /opt/pidpm-demo/server.py

RUN pip install --no-cache-dir "flask>=3.0" "gunicorn>=22.0"

ENV MODEL_PATH=/opt/ml/model/checkpoint.json
EXPOSE 8080

# SageMaker's contract: /ping (health) and /invocations (score) on :8080.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "server:app"]
