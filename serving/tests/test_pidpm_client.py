"""PiDpmClient tests (Phase 3, gate 3.6): disabled-by-default, the async
SageMaker invoke + S3-poll sequence, and fail-open behavior. No AWS: both
the sagemaker-runtime and S3 clients are injected fakes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.metrics import PIDPM_LOOKUP_ERRORS
from app.pidpm_client import PiDpmClient


class NoSuchKey(Exception):
    pass


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[dict[str, Any]] = []

        class _Exceptions:
            NoSuchKey = NoSuchKey

        self.exceptions = _Exceptions()

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    def seed_output(self, bucket: str, key: str, payload: dict) -> None:
        self.objects[(bucket, key)] = json.dumps(payload).encode()


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeSageMaker:
    def __init__(self, *, output_location: str, err: Exception | None = None) -> None:
        self.output_location = output_location
        self.err = err
        self.calls: list[dict[str, Any]] = []

    def invoke_endpoint_async(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.err:
            raise self.err
        return {"OutputLocation": self.output_location}


def _client(sagemaker=None, s3=None, **overrides) -> PiDpmClient:
    return PiDpmClient(
        sagemaker_client=sagemaker,
        s3_client=s3,
        endpoint_name=overrides.pop("endpoint_name", "hm-pidpm"),
        input_bucket=overrides.pop("input_bucket", "hm-models-bucket"),
        sleep=lambda _s: None,  # never actually sleep in tests
        **overrides,
    )


def test_disabled_when_no_clients_injected():
    client = PiDpmClient(sagemaker_client=None, s3_client=None, endpoint_name="", input_bucket="")
    assert client.enabled is False


def test_ascore_returns_none_when_disabled():
    client = PiDpmClient(sagemaker_client=None, s3_client=None, endpoint_name="", input_bucket="")
    assert asyncio.run(client.ascore([[1.0, 2.0]])) is None


def test_score_happy_path_uploads_input_and_returns_the_polled_score():
    s3 = FakeS3()
    s3.seed_output("hm-models-bucket", "pidpm/async-output/result.json", {"score": 0.73})
    sagemaker = FakeSageMaker(
        output_location="s3://hm-models-bucket/pidpm/async-output/result.json"
    )
    client = _client(sagemaker=sagemaker, s3=s3)

    result = client.score([[40.0, -74.0], [40.1, -74.1]])

    assert result == 0.73
    assert len(s3.puts) == 1
    body = json.loads(s3.puts[0]["Body"])
    assert body["trajectory"] == [[40.0, -74.0], [40.1, -74.1]]
    assert sagemaker.calls[0]["EndpointName"] == "hm-pidpm"


def test_ascore_runs_off_the_event_loop_and_returns_the_same_result():
    s3 = FakeS3()
    s3.seed_output("hm-models-bucket", "out/result.json", {"score": 0.42})
    sagemaker = FakeSageMaker(output_location="s3://hm-models-bucket/out/result.json")
    client = _client(sagemaker=sagemaker, s3=s3)

    result = asyncio.run(client.ascore([[1.0, 2.0]]))
    assert result == 0.42


def test_score_polls_until_the_output_appears():
    s3 = FakeS3()
    sagemaker = FakeSageMaker(output_location="s3://hm-models-bucket/out/result.json")
    client = _client(sagemaker=sagemaker, s3=s3, poll_interval_s=0.0, timeout_s=1.0)

    # seed the output only after the first poll attempt would have missed it
    calls = {"n": 0}
    real_get = s3.get_object

    def flaky_get(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise s3.exceptions.NoSuchKey()
        s3.seed_output("hm-models-bucket", "out/result.json", {"score": 0.9})
        return real_get(**kwargs)

    s3.get_object = flaky_get
    assert client.score([[1.0, 2.0]]) == 0.9
    assert calls["n"] >= 3


def test_score_times_out_and_fails_open():
    s3 = FakeS3()  # never seeded: every get_object raises NoSuchKey forever
    sagemaker = FakeSageMaker(output_location="s3://hm-models-bucket/out/result.json")
    client = _client(sagemaker=sagemaker, s3=s3, timeout_s=0.0, poll_interval_s=0.0)

    before = PIDPM_LOOKUP_ERRORS._value.get()
    assert client.score([[1.0, 2.0]]) is None
    assert PIDPM_LOOKUP_ERRORS._value.get() == before + 1


def test_score_fails_open_when_invoke_raises():
    s3 = FakeS3()
    sagemaker = FakeSageMaker(output_location="unused", err=RuntimeError("endpoint not found"))
    client = _client(sagemaker=sagemaker, s3=s3)

    before = PIDPM_LOOKUP_ERRORS._value.get()
    assert client.score([[1.0, 2.0]]) is None
    assert PIDPM_LOOKUP_ERRORS._value.get() == before + 1


def test_score_fails_open_on_a_non_notfound_read_error():
    s3 = FakeS3()
    sagemaker = FakeSageMaker(output_location="s3://hm-models-bucket/out/result.json")
    client = _client(sagemaker=sagemaker, s3=s3)

    def boom(**kwargs):
        raise RuntimeError("access denied")

    s3.get_object = boom
    before = PIDPM_LOOKUP_ERRORS._value.get()
    assert client.score([[1.0, 2.0]]) is None
    assert PIDPM_LOOKUP_ERRORS._value.get() == before + 1
