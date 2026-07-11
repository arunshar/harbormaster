"""The customer-managed permissions boundary must not silently disable the
teardown safety-net (Wave 3 pressure-test finding; war story P38).

The boundary is a ceiling: a role's effective permissions are its inline policy
INTERSECT this boundary. If a service the teardown Lambdas call is missing from
the Allow ceiling, every such call is AccessDenied at runtime, the Lambda
catches it and reports "nothing to tear down," and the resource bills
indefinitely past the $75 cap. That is exactly the procedural-failure mode the
structural teardown guard (gate 5.0) and the nightly finops sweeper were built
to prevent, so the boundary must cover every service they delete.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOUNDARY = REPO / "infra" / "aws" / "harbormaster-permissions-boundary.json"

# Services the teardown paths invoke, each with a delete/scale-to-zero call that
# fails closed (leaving cost running) if the boundary omits it:
#   eks         - the EKS teardown guard force-destroys the control plane + node groups
#   kafka       - the finops nightly sweep deletes MSK Serverless (~$18/day, the biggest threat)
#   autoscaling - the finops sweep drains EC2 Auto Scaling groups to zero
#   sagemaker / elasticmapreduce / kinesisanalytics - Phase 3/1 compute the sweep also stops
#   sns / cloudwatch / logs - how the guard reports and observes
_TEARDOWN_CRITICAL = {
    "eks",
    "kafka",
    "autoscaling",
    "sagemaker",
    "elasticmapreduce",
    "kinesisanalytics",
    "sns",
    "cloudwatch",
    "logs",
    "ec2",
}


def _ceiling_services() -> set[str]:
    doc = json.loads(BOUNDARY.read_text())
    ceiling = next(s for s in doc["Statement"] if s["Sid"] == "AllowHarbormasterServiceCeiling")
    actions = ceiling["Action"]
    assert ceiling["Effect"] == "Allow"
    return {a.split(":", 1)[0] for a in actions}


def test_boundary_ceiling_covers_every_teardown_critical_service():
    services = _ceiling_services()
    missing = sorted(_TEARDOWN_CRITICAL - services)
    assert not missing, (
        f"the permissions boundary omits {missing}; the teardown Lambdas' delete/scale "
        "calls for those services would be AccessDenied and the cost would bill indefinitely"
    )


def test_boundary_still_denies_iam_and_boundary_escalation():
    # the ceiling widening must not have weakened the escalation guards
    doc = json.loads(BOUNDARY.read_text())
    deny_sids = {s["Sid"] for s in doc["Statement"] if s["Effect"] == "Deny"}
    assert "DenyAllIamWriteEscalation" in deny_sids
    assert "DenyBoundaryAlterationAndOrgEscape" in deny_sids
