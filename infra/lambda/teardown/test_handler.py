"""Dependency-light tests for the Harbormaster teardown Lambda.

These tests run WITHOUT AWS credentials and WITHOUT the real boto3 SDK calls by
monkeypatching boto3.client with a fake factory that returns canned responses.
They exercise the DRY_RUN path end to end and assert that:
  - no mutating API call is made while DRY_RUN is true,
  - only resources tagged Project=harbormaster are selected,
  - a partial failure in one service does not abort the whole run,
  - the handler returns a JSON-serializable result.

Run with either:
    python -m pytest infra/lambda/teardown/test_handler.py
    python infra/lambda/teardown/test_handler.py     (built-in runner fallback)

The built-in fallback at the bottom means the file passes even where pytest is
not installed.
"""

import importlib
import json
import os
import sys

# Ensure the handler module is importable when tests run from any cwd.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


# --------------------------------------------------------------------------- #
# Fake boto3 clients
# --------------------------------------------------------------------------- #
TAGGED = [{"Key": "Project", "Value": "harbormaster"}]
UNTAGGED = [{"Key": "Project", "Value": "something-else"}]


class _Recorder:
    """Records mutating calls so tests can assert they did NOT happen in
    DRY_RUN mode."""

    def __init__(self):
        self.calls = []

    def note(self, name, **kwargs):
        self.calls.append((name, kwargs))


class FakeFlinkClient:
    def __init__(self, recorder):
        self._rec = recorder

    def list_applications(self, **kwargs):
        return {
            "ApplicationSummaries": [
                {
                    "ApplicationName": "harbormaster-detector",
                    "ApplicationStatus": "RUNNING",
                    "ApplicationARN": "arn:aws:kinesisanalytics:::app/hb",
                },
                {
                    "ApplicationName": "other-app",
                    "ApplicationStatus": "RUNNING",
                    "ApplicationARN": "arn:aws:kinesisanalytics:::app/other",
                },
            ]
        }

    def list_tags_for_resource(self, ResourceARN):
        if ResourceARN.endswith("/hb"):
            return {"Tags": TAGGED}
        return {"Tags": UNTAGGED}

    def stop_application(self, **kwargs):
        self._rec.note("flink.stop_application", **kwargs)


class FakeEmrClient:
    def __init__(self, recorder):
        self._rec = recorder

    def list_clusters(self, **kwargs):
        return {
            "Clusters": [
                {"Id": "j-HB", "Name": "harbormaster-emr"},
                {"Id": "j-OTHER", "Name": "other-emr"},
            ]
        }

    def describe_cluster(self, ClusterId):
        if ClusterId == "j-HB":
            return {"Cluster": {"Tags": TAGGED}}
        return {"Cluster": {"Tags": UNTAGGED}}

    def terminate_job_flows(self, **kwargs):
        self._rec.note("emr.terminate_job_flows", **kwargs)


class FakeMskClient:
    def __init__(self, recorder):
        self._rec = recorder

    def list_clusters_v2(self, **kwargs):
        return {
            "ClusterInfoList": [
                {
                    "ClusterArn": "arn:aws:kafka:::cluster/hb",
                    "ClusterName": "harbormaster-msk",
                    "ClusterType": "SERVERLESS",
                    "Tags": {"Project": "harbormaster"},
                },
                {
                    "ClusterArn": "arn:aws:kafka:::cluster/other",
                    "ClusterName": "other-msk",
                    "ClusterType": "SERVERLESS",
                    "Tags": {"Project": "nope"},
                },
            ]
        }

    def delete_cluster(self, **kwargs):
        self._rec.note("msk.delete_cluster", **kwargs)


class _Paginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        for page in self._pages:
            yield page


class FakeAsgClient:
    def __init__(self, recorder):
        self._rec = recorder

    def get_paginator(self, name):
        return _Paginator(
            [
                {
                    "AutoScalingGroups": [
                        {
                            "AutoScalingGroupName": "harbormaster-asg",
                            "Tags": TAGGED,
                            "DesiredCapacity": 3,
                            "MinSize": 1,
                        },
                        {
                            "AutoScalingGroupName": "other-asg",
                            "Tags": UNTAGGED,
                            "DesiredCapacity": 5,
                            "MinSize": 2,
                        },
                    ]
                }
            ]
        )

    def update_auto_scaling_group(self, **kwargs):
        self._rec.note("asg.update_auto_scaling_group", **kwargs)


class FakeCeClient:
    def __init__(self, recorder):
        self._rec = recorder

    def get_cost_and_usage(self, **kwargs):
        return {
            "ResultsByTime": [
                {"Total": {"UnblendedCost": {"Amount": "12.34", "Unit": "USD"}}}
            ]
        }


class FakeSnsClient:
    def __init__(self, recorder):
        self._rec = recorder

    def publish(self, **kwargs):
        self._rec.note("sns.publish", **kwargs)


def make_fake_boto3_client(recorder, failing_service=None):
    """Return a function that mimics boto3.client(service_name) and dispatches
    to the right fake. If failing_service is set, that service raises to test
    the defensive per-service error handling."""

    def _factory(service_name, **kwargs):
        if service_name == failing_service:
            raise RuntimeError("simulated {} outage".format(service_name))
        if service_name == "kinesisanalyticsv2":
            return FakeFlinkClient(recorder)
        if service_name == "emr":
            return FakeEmrClient(recorder)
        if service_name == "kafka":
            return FakeMskClient(recorder)
        if service_name == "autoscaling":
            return FakeAsgClient(recorder)
        if service_name == "ce":
            return FakeCeClient(recorder)
        if service_name == "sns":
            return FakeSnsClient(recorder)
        raise AssertionError("unexpected service: {}".format(service_name))

    return _factory


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class _Boto3Stub:
    """Stand-in for the boto3 module so tests run even where boto3 is not
    installed. Tests overwrite .client with a fake factory."""

    client = None


def _load_handler(monkeyenv):
    """Import (or reimport) the handler module with the given environment so the
    module-level PROJECT_TAG_VALUE picks up overrides. If real boto3 is absent
    (handler.boto3 is None), substitute a stub object whose .client the test
    then replaces."""
    for k, v in monkeyenv.items():
        os.environ[k] = v
    if "handler" in sys.modules:
        handler = importlib.reload(sys.modules["handler"])
    else:
        handler = importlib.import_module("handler")
    if handler.boto3 is None:
        handler.boto3 = _Boto3Stub()
    return handler


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_dry_run_makes_no_mutating_calls():
    os.environ["DRY_RUN"] = "true"
    os.environ.pop("ALERT_TOPIC_ARN", None)
    handler = _load_handler({"PROJECT_TAG": "harbormaster"})
    recorder = _Recorder()
    handler.boto3.client = make_fake_boto3_client(recorder)

    result = handler.lambda_handler({"source": "test"}, None)

    # DRY_RUN must not perform any mutation or publish.
    assert recorder.calls == [], recorder.calls
    assert result["dry_run"] is True
    # The result must be JSON-serializable.
    json.dumps(result, default=str)


def test_only_tagged_resources_are_selected():
    os.environ["DRY_RUN"] = "true"
    handler = _load_handler({"PROJECT_TAG": "harbormaster"})
    recorder = _Recorder()
    handler.boto3.client = make_fake_boto3_client(recorder)

    result = handler.lambda_handler({}, None)
    res = result["results"]

    assert res["managed_flink"]["stopped"] == ["harbormaster-detector"]
    assert res["emr"]["terminated"] == ["j-HB"]
    assert res["msk_serverless"]["deleted"] == ["harbormaster-msk"]
    assert res["auto_scaling"]["zeroed"] == ["harbormaster-asg"]
    assert res["cost_explorer"]["summary"]["amount"] == 12.34


def test_per_service_failure_does_not_abort_run():
    os.environ["DRY_RUN"] = "true"
    handler = _load_handler({"PROJECT_TAG": "harbormaster"})
    recorder = _Recorder()
    # EMR blows up; everything else must still complete.
    handler.boto3.client = make_fake_boto3_client(recorder, failing_service="emr")

    result = handler.lambda_handler({}, None)
    res = result["results"]

    assert res["emr"]["error"] is not None
    assert "simulated emr outage" in res["emr"]["error"]
    # Other services unaffected.
    assert res["managed_flink"]["stopped"] == ["harbormaster-detector"]
    assert res["auto_scaling"]["zeroed"] == ["harbormaster-asg"]
    assert res["cost_explorer"]["summary"]["amount"] == 12.34


def test_wet_run_performs_actions_and_publishes():
    os.environ["DRY_RUN"] = "false"
    os.environ["ALERT_TOPIC_ARN"] = "arn:aws:sns:us-east-1:000000000000:hb-alerts"
    handler = _load_handler({"PROJECT_TAG": "harbormaster"})
    recorder = _Recorder()
    handler.boto3.client = make_fake_boto3_client(recorder)

    result = handler.lambda_handler({}, None)

    names = [c[0] for c in recorder.calls]
    assert "flink.stop_application" in names
    assert "emr.terminate_job_flows" in names
    assert "msk.delete_cluster" in names
    assert "asg.update_auto_scaling_group" in names
    assert "sns.publish" in names
    assert result["dry_run"] is False
    # Reset for any subsequent runners.
    os.environ["DRY_RUN"] = "true"
    os.environ.pop("ALERT_TOPIC_ARN", None)


# --------------------------------------------------------------------------- #
# Built-in runner fallback (works without pytest installed).
# --------------------------------------------------------------------------- #
def _run_all():
    tests = [
        test_dry_run_makes_no_mutating_calls,
        test_only_tagged_resources_are_selected,
        test_per_service_failure_does_not_abort_run,
        test_wet_run_performs_actions_and_publishes,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print("PASS {}".format(t.__name__))
        except AssertionError as e:
            failures += 1
            print("FAIL {}: {}".format(t.__name__, e))
        except Exception as e:  # noqa: BLE001
            failures += 1
            print("ERROR {}: {}".format(t.__name__, e))
    if failures:
        print("{} test(s) failed".format(failures))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(_run_all())
