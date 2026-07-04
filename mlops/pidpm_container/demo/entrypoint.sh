#!/bin/sh
# SageMaker invokes real-time containers as `docker run <image> serve` (its
# convention for distinguishing serving from training containers); with no
# ENTRYPOINT, that "serve" argument replaced this container's CMD entirely
# instead of being passed to it, so the container tried to execute a literal
# "serve" binary and failed with CannotStartContainerError (a real,
# first-live-run finding, W2 sprint window, 2026-07-04). This container only
# ever serves, so the entrypoint ignores whatever argument it's given
# ("serve", or nothing when run directly for local testing) and always
# launches gunicorn.
exec gunicorn --bind 0.0.0.0:8080 --workers 1 server:app
