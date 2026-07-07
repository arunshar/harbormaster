# Phase 3 AWS-showcase DEMO STAND-IN container. NOT Pi-DPM: see server.py's
# module docstring. Builds and runs today with no external dependencies
# (unlike ../Dockerfile, which needs pi-grpo's scorer code from a separate,
# un-vendored repo); this is what docs/runbooks/PHASE_3_AWS_SHOWCASE.md
# actually deploys to demonstrate the real SageMaker async endpoint
# infrastructure, scale-to-zero, and the promotion pipeline.

FROM python:3.11-slim

WORKDIR /opt/pidpm-demo

COPY server.py entrypoint.sh /opt/pidpm-demo/

RUN pip install --no-cache-dir "flask>=3.0" "gunicorn>=22.0" \
    && chmod +x /opt/pidpm-demo/entrypoint.sh

ENV MODEL_PATH=/opt/ml/model/checkpoint.json
EXPOSE 8080

# SageMaker's contract: /ping (health) and /invocations (score) on :8080.
# SageMaker invokes real-time containers as `docker run <image> serve`; with
# no ENTRYPOINT that argument replaced CMD entirely instead of being passed
# to it (CannotStartContainerError, a real first-live-run finding, W2 sprint
# window, 2026-07-04). entrypoint.sh ignores whatever argument it's given.
ENTRYPOINT ["/opt/pidpm-demo/entrypoint.sh"]
