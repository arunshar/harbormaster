"""Async-IO SageMaker client for the Pi-DPM async Multi-Model Endpoint
(Phase 3, gate 3.6).

Mirrors `watchlist.py`'s WatchlistLookup conventions exactly: injected
clients (either may be None -> disabled), an `enabled` property, a
`from_settings` classmethod that builds real boto3 clients with tight
timeouts and degrades to disabled on construction failure, and an
async/sync split (`ascore`/`score`) where the blocking boto3/S3-polling work
runs off the event loop via `asyncio.to_thread`.

The one real behavioral difference from the watchlist lookup: "fail open"
here means "return None so the caller falls back to the existing analytic
`_pi_dpm_score` in gap_detector.py", not "return an empty/zero score" - the
analytic estimator is a real, reasonable estimate on its own (it is exactly
what Phase 1/2 already ship), so a SageMaker outage degrades quality, it
never stops scoring.

SageMaker async inference contract: the caller uploads the input payload to
S3, calls `invoke_endpoint_async` (returns an OutputLocation immediately,
the container scores in the background), then polls OutputLocation for the
result. The container itself, wrapping the frozen `PiDpmScorer.log_prob`
contract, is out of scope for this client (see mlops/pidpm_container/).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import structlog

from app.config import Settings
from app.metrics import PIDPM_LOOKUP_ERRORS

log = structlog.get_logger(__name__)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"not an s3 uri: {uri}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


class PiDpmClient:
    """Injected clients (either may be None -> disabled). `score`/`ascore`
    return None on any failure, timeout, or when disabled: the caller must
    treat None as "fall back to the existing estimate", never as a score of
    zero."""

    def __init__(
        self,
        *,
        sagemaker_client: Any | None,
        s3_client: Any | None,
        endpoint_name: str,
        input_bucket: str,
        input_prefix: str = "pidpm/async-input",
        poll_interval_s: float = 0.1,
        timeout_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sagemaker = sagemaker_client
        self._s3 = s3_client
        self._endpoint_name = endpoint_name
        self._input_bucket = input_bucket
        self._input_prefix = input_prefix
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._monotonic = monotonic

    @property
    def enabled(self) -> bool:
        return (
            self._sagemaker is not None
            and self._s3 is not None
            and bool(self._endpoint_name)
            and bool(self._input_bucket)
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> PiDpmClient:
        """Build real clients from config; degrade to disabled when unset or
        on construction failure. Same tight-timeout shape as
        WatchlistLookup.from_settings: this runs on the scoring path."""
        sagemaker_client = None
        s3_client = None
        if settings.pidpm_endpoint:
            try:
                import boto3
                from botocore.config import Config as BotoConfig

                region = os.environ.get(
                    "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
                )
                boto_config = BotoConfig(
                    connect_timeout=1,
                    read_timeout=1,
                    retries={"max_attempts": 2, "mode": "standard"},
                )
                sagemaker_client = boto3.client(
                    "sagemaker-runtime", region_name=region, config=boto_config
                )
                s3_client = boto3.client("s3", region_name=region, config=boto_config)
            except Exception as exc:
                log.warning("pidpm_client_unavailable_disabled", err=str(exc))
        return cls(
            sagemaker_client=sagemaker_client,
            s3_client=s3_client,
            endpoint_name=settings.pidpm_endpoint,
            input_bucket=settings.pidpm_input_bucket,
        )

    async def ascore(self, trajectory: list[list[float]]) -> float | None:
        """Event-loop-safe: the blocking upload/invoke/poll sequence runs in
        a worker thread so a slow or stalled endpoint cannot stall every
        request on the loop. Zero-cost when disabled."""
        if not self.enabled:
            return None
        import asyncio

        return await asyncio.to_thread(self.score, trajectory)

    def score(self, trajectory: list[list[float]]) -> float | None:
        if not self.enabled:
            return None

        try:
            input_key = f"{self._input_prefix}/{uuid.uuid4()}.json"
            self._s3.put_object(
                Bucket=self._input_bucket,
                Key=input_key,
                Body=json.dumps({"trajectory": trajectory}).encode(),
            )
            resp = self._sagemaker.invoke_endpoint_async(
                EndpointName=self._endpoint_name,
                InputLocation=f"s3://{self._input_bucket}/{input_key}",
                ContentType="application/json",
            )
            output_bucket, output_key = _parse_s3_uri(resp["OutputLocation"])
        except Exception as exc:  # fail open: caller falls back to the analytic estimate
            PIDPM_LOOKUP_ERRORS.inc()
            log.warning("pidpm_invoke_failed_fallback_to_analytic", err=str(exc))
            return None

        deadline = self._monotonic() + self._timeout_s
        while self._monotonic() < deadline:
            try:
                obj = self._s3.get_object(Bucket=output_bucket, Key=output_key)
                payload = json.loads(obj["Body"].read())
                return float(payload["score"])
            except self._not_found_error():
                self._sleep(self._poll_interval_s)
            except Exception as exc:
                PIDPM_LOOKUP_ERRORS.inc()
                log.warning("pidpm_output_read_failed_fallback_to_analytic", err=str(exc))
                return None

        PIDPM_LOOKUP_ERRORS.inc()
        log.warning("pidpm_score_timeout_fallback_to_analytic", timeout_s=self._timeout_s)
        return None

    def _not_found_error(self) -> type[Exception]:
        """The S3 client's own NoSuchKey exception type (only resolvable
        once a real boto3 client exists; a plain KeyError-shaped fake in
        tests can raise this same attribute path)."""
        return self._s3.exceptions.NoSuchKey
