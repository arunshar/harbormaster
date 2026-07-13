"""Gate 5.2 structural validation of the EKS serving manifests.

Two layers, per the gate's degrade-honestly rule:
  1. ALWAYS: pure YAML parsing of the committed manifests, asserting the
     trigger configs, the minReplicaCount: 0 scale-to-zero floor, the image
     substitution point, and the KEDA-legal single-ScaledObject shape.
  2. WHEN a kustomize binary exists (kubectl's built-in is used; GitHub
     runners and this dev box both ship it): rebuild both variants and
     compare SEMANTICALLY against the committed golden outputs in
     deploy/k8s/serving/golden/ (parsed-document equality, not bytes, so a
     kustomize version's cosmetic reordering cannot false-alarm). Skipped
     with a visible reason where no binary exists.

The live kind-cluster dry-run (CRDs + server-side apply) is a demo-window /
authoring-session verification, executed and recorded in the gate 5.2
commit body, not repeated per test run.

Also pins the apigw retarget posture: the EKS integration is authored, the
route target defaults to the ECS path, and the ECS service resource still
exists (the documented rollback path).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SERVING_DIR = REPO_ROOT / "deploy" / "k8s" / "serving"
BASE_DIR = SERVING_DIR / "base"
WITH_CDC_DIR = SERVING_DIR / "with-cdc"
GOLDEN_DIR = SERVING_DIR / "golden"
APIGW_MODULE = REPO_ROOT / "infra" / "terraform" / "modules" / "apigw"
ENV_MAIN = REPO_ROOT / "infra" / "terraform" / "envs" / "base" / "main.tf"
EKS_FRONTDOOR = REPO_ROOT / "infra" / "terraform" / "modules" / "eks_frontdoor"
KDA_FLINK_MAIN = REPO_ROOT / "infra" / "terraform" / "modules" / "kda_flink" / "main.tf"
BOUNDARY = REPO_ROOT / "infra" / "aws" / "harbormaster-permissions-boundary.json"
ECS_SERVING_MAIN = REPO_ROOT / "infra" / "terraform" / "modules" / "ecs_serving" / "main.tf"
W4_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "WAVE4_LIVE_WINDOWS.md"
IMAGE_SENTINEL = "harbormaster.invalid/serving@sha256:" + "0" * 64


def _load_all(path: Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def _load_one(path: Path) -> dict:
    docs = _load_all(path)
    assert len(docs) == 1, f"{path} must hold exactly one document"
    return docs[0]


# --------------------------------------------------------------------------- #
# Deployment / Service
# --------------------------------------------------------------------------- #
def test_deployment_is_the_unmodified_serving_image_shape():
    doc = _load_one(BASE_DIR / "deployment.yaml")
    assert doc["kind"] == "Deployment"
    assert doc["metadata"]["namespace"] == "hm-serving"
    container = doc["spec"]["template"]["spec"]["containers"][0]
    # Non-runnable sentinel replaced only by the digest-validating W4 renderer.
    assert container["image"] == IMAGE_SENTINEL
    assert ":latest" not in container["image"]
    assert container["ports"][0]["containerPort"] == 8000
    assert container["readinessProbe"]["httpGet"]["path"] == "/healthz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    # KEDA owns replicas: the deployment must not pin its own count.
    assert "replicas" not in doc["spec"]


def test_service_fronts_port_8000():
    doc = _load_one(BASE_DIR / "service.yaml")
    assert doc["kind"] == "Service"
    assert doc["spec"]["type"] == "NodePort"
    port = doc["spec"]["ports"][0]
    assert port["port"] == 80
    assert port["targetPort"] == 8000
    assert port["nodePort"] == 30080
    assert doc["spec"]["selector"] == {"app": "serving"}


# --------------------------------------------------------------------------- #
# ScaledObject: the scale-to-zero floor and the Kinesis lag trigger
# --------------------------------------------------------------------------- #
def test_scaledobject_scale_to_zero_floor():
    doc = _load_one(BASE_DIR / "scaledobject-kinesis.yaml")
    assert doc["kind"] == "ScaledObject"
    assert doc["apiVersion"] == "keda.sh/v1alpha1"
    assert doc["spec"]["minReplicaCount"] == 0
    assert doc["spec"]["maxReplicaCount"] == 3
    assert doc["spec"]["scaleTargetRef"] == {"name": "serving"}


def test_kinesis_lag_trigger_is_the_iterator_age_metric():
    # Recorded deviation from the spec's wording: aws-cloudwatch on
    # GetRecords.IteratorAgeMilliseconds, because the built-in
    # aws-kinesis-stream scaler scales on shard count (never zero, not lag).
    doc = _load_one(BASE_DIR / "scaledobject-kinesis.yaml")
    triggers = doc["spec"]["triggers"]
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig["type"] == "aws-cloudwatch"
    md = trig["metadata"]
    assert md["namespace"] == "AWS/Kinesis"
    assert md["metricName"] == "GetRecords.IteratorAgeMilliseconds"
    assert md["dimensionName"] == "StreamName"
    # The Phase 1 stream name modules/kinesis builds.
    assert md["dimensionValue"] == "harbormaster-base-ais-raw"
    assert md["identityOwner"] == "operator"
    activation = int(md["activationTargetMetricValue"])
    target = int(md["targetMetricValue"])
    assert 0 < activation < target


def test_runbook_stabilizes_keda_after_flink_before_retargeting():
    runbook = W4_RUNBOOK.read_text()
    flink_running = runbook.index("FLINK_RUNNING_EPOCH=$(date +%s)")
    stabilization = runbook.index("KEDA_STABLE_SAMPLES=0")
    retarget = runbook.index("PLAN_LABEL=wave4-w4-retarget-eks")
    observer = runbook.index("scripts/observe_phase5_scale.py")
    assert flink_running < stabilization < retarget < observer
    assert 'test "$KEDA_STABLE_SAMPLES" -ge 2' in runbook


def test_runbook_proves_nightly_teardown_is_wet_before_eks_plan():
    runbook = W4_RUNBOOK.read_text()
    schedule = runbook.index("nightly-teardown-preflight.json")
    target_lookup = runbook.index(".Target.Arn | select(startswith($prefix))")
    preflight = runbook.index("nightly-teardown-lambda-preflight.json")
    guard_only_plan = runbook.index("PLAN_LABEL=wave4-w4-nightly-guard")
    wet_recheck = runbook.index("nightly-teardown-lambda-before-eks.json")
    eks_plan = runbook.index("PLAN_LABEL=wave4-w4-eks")
    assert schedule < target_lookup < preflight < guard_only_plan < wet_recheck < eks_plan
    assert "TEARDOWN_LAMBDA=harbormaster-base-nightly-teardown" not in runbook
    assert '--function-name "$TEARDOWN_LAMBDA_ARN"' in runbook
    assert runbook.count('.Environment.Variables.DRY_RUN == "false"') >= 3
    assert '(.address | startswith("module.finops."))' in runbook
    assert '((.actions | index("delete")) == null)' in runbook


def test_runbook_simulates_platform_boundary_intersection_before_assume_role():
    runbook = W4_RUNBOOK.read_text()
    simulator = runbook.index("simulate_platform bounded-role allowed")
    self_deny = runbook.index("simulate_platform self-mutation explicitDeny")
    boundary_deny = runbook.index("simulate_platform boundary-mutation explicitDeny")
    assume_role = runbook.index("PLATFORM_SESSION=$(aws sts assume-role")
    assert simulator < self_deny < boundary_deny < assume_role
    assert "aws iam simulate-principal-policy" in runbook


def test_runbook_restores_the_admin_identity_before_refreshing_an_expired_session():
    runbook = W4_RUNBOOK.read_text()
    admin_capture = runbook.index("ADMIN_CALLER_ARN=$(jq -r .Arn")
    assume_role = runbook.index("PLATFORM_SESSION=$(aws sts assume-role")
    unset_session = runbook.index("unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN")
    restored_caller = runbook.index('test "$RESTORED_CALLER_ARN" = "$ADMIN_CALLER_ARN"')

    assert admin_capture < assume_role < unset_session < restored_caller


def test_observer_timeout_covers_load_and_scaler_recovery_budget():
    runbook = W4_RUNBOOK.read_text()
    timeout_match = re.search(r"--timeout-seconds (\d+) &", runbook)
    duration_match = re.search(r"^DURATION_S=(\d+) \\$", runbook, re.MULTILINE)
    assert timeout_match is not None
    assert duration_match is not None

    scaled_object = _load_one(BASE_DIR / "scaledobject-kinesis.yaml")
    spec = scaled_object["spec"]
    metric_window = int(spec["triggers"][0]["metadata"]["metricCollectionTime"])
    required_budget = (
        int(duration_match.group(1))
        + metric_window
        + int(spec["cooldownPeriod"])
        + 2 * int(spec["pollingInterval"])
    )
    assert int(timeout_match.group(1)) >= required_budget


def test_kafka_trigger_patch_targets_the_same_scaledobject():
    # KEDA rejects two ScaledObjects on one scaleTargetRef, so the Phase 2
    # trigger is a JSON6902 append, not a second ScaledObject.
    patch_ops = yaml.safe_load((WITH_CDC_DIR / "scaledobject-kafka-trigger.yaml").read_text())
    assert len(patch_ops) == 1
    op = patch_ops[0]
    assert op["op"] == "add"
    assert op["path"] == "/spec/triggers/-"
    trig = op["value"]
    assert trig["type"] == "kafka"
    md = trig["metadata"]
    # The CDC consumer's real group.id (cdc/consumer/service.py).
    assert md["consumerGroup"] == "hm-cdc-consumer"
    assert md["lagThreshold"] == "100"
    assert md["sasl"] == "aws_msk_iam"
    assert md["tls"] == "enable"
    # The bootstrap endpoint is a placeholder until an enable_phase2 apply
    # exists to read it from; committing a live endpoint would be doc-drift.
    assert md["bootstrapServers"].startswith("PLACEHOLDER_MSK_BOOTSTRAP")

    kustomization = _load_one(WITH_CDC_DIR / "kustomization.yaml")
    target = kustomization["patches"][0]["target"]
    assert target["kind"] == "ScaledObject"
    assert target["name"] == "serving-scaler"


def test_base_kustomization_lists_all_manifests():
    doc = _load_one(BASE_DIR / "kustomization.yaml")
    assert doc["resources"] == [
        "namespace.yaml",
        "deployment.yaml",
        "service.yaml",
        "scaledobject-kinesis.yaml",
    ]
    assert "images" not in doc


# --------------------------------------------------------------------------- #
# Golden checksum: semantic compare of the kustomize build
# --------------------------------------------------------------------------- #
def _kustomize_build(path: Path) -> list[dict]:
    if shutil.which("kustomize"):
        cmd = ["kustomize", "build", str(path)]
    elif shutil.which("kubectl"):
        cmd = ["kubectl", "kustomize", str(path)]
    else:
        pytest.skip(
            "no kustomize/kubectl binary on this box: degrading honestly to the "
            "pure-YAML structural checks above (the golden semantic compare ran "
            "where the binary exists)"
        )
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(out.stdout) if doc]


def _index(docs: list[dict]) -> dict[tuple, dict]:
    return {
        (d["apiVersion"], d["kind"], d["metadata"].get("namespace"), d["metadata"]["name"]): d
        for d in docs
    }


@pytest.mark.parametrize("variant", ["base", "with-cdc"])
def test_kustomize_build_matches_committed_golden(variant):
    built = _index(_kustomize_build(SERVING_DIR / variant))
    golden = _index(_load_all(GOLDEN_DIR / f"{variant}.yaml"))
    assert built == golden, (
        f"kustomize build deploy/k8s/serving/{variant} drifted from "
        f"golden/{variant}.yaml; regenerate the golden ONLY after a reviewed change"
    )


def test_golden_with_cdc_has_both_triggers_and_zero_floor():
    # Pure re-parse of the committed golden, binary-free: the with-cdc build
    # must hold ONE ScaledObject carrying both triggers and the zero floor.
    docs = _load_all(GOLDEN_DIR / "with-cdc.yaml")
    scaled = [d for d in docs if d["kind"] == "ScaledObject"]
    assert len(scaled) == 1
    spec = scaled[0]["spec"]
    assert spec["minReplicaCount"] == 0
    assert [t["type"] for t in spec["triggers"]] == ["aws-cloudwatch", "kafka"]


# --------------------------------------------------------------------------- #
# apigw retarget: authored, defaulted to ECS, rollback intact
# --------------------------------------------------------------------------- #
def test_apigw_eks_integration_is_authored_but_gated():
    main = (APIGW_MODULE / "main.tf").read_text()
    assert 'resource "aws_apigatewayv2_integration" "serving_eks"' in main
    assert 'count = var.eks_integration_uri != "" ? 1 : 0' in main


def test_apigw_route_defaults_to_the_ecs_path():
    variables = (APIGW_MODULE / "variables.tf").read_text()
    main = (APIGW_MODULE / "main.tf").read_text()
    # Default target is ecs, and the route target is the conditional retarget
    # expression (whose default branch is the exact pre-Phase-5 value).
    assert 'default     = "ecs"' in variables
    assert 'var.serving_target == "eks"' in main
    assert "integrations/${aws_apigatewayv2_integration.serving.id}" in main


def test_ecs_serving_service_still_exists_as_the_rollback_path():
    # Gate 5.2's no-untested-cutover decision: the Fargate service resource
    # must survive this gate.
    assert 'resource "aws_ecs_service" "serving"' in ECS_SERVING_MAIN.read_text()


def test_root_wires_the_terraform_owned_nlb_listener_into_apigw():
    main = ENV_MAIN.read_text()
    assert 'module "eks_frontdoor"' in main
    assert 'source = "../../modules/eks_frontdoor"' in main
    assert "module.eks_frontdoor[0].listener_arn" in main
    assert "module.eks_frontdoor[0].security_group_id" in main
    assert "serving_target = var.serving_target" in main


def test_frontdoor_is_an_internal_nlb_attached_to_the_managed_node_group():
    main = (EKS_FRONTDOOR / "main.tf").read_text()
    assert 'resource "aws_lb" "serving"' in main
    assert 'load_balancer_type               = "network"' in main
    assert "internal                         = true" in main
    assert 'target_type          = "instance"' in main
    assert 'resource "aws_autoscaling_attachment" "serving"' in main
    assert "autoscaling_group_name = var.node_autoscaling_group_name" in main
    assert "port                 = var.node_port" in main
    assert "security_groups                  = [aws_security_group.nlb.id]" in main


def test_frontdoor_security_groups_prevent_vpc_nodeport_bypass():
    frontdoor = (EKS_FRONTDOOR / "main.tf").read_text()
    apigw = (APIGW_MODULE / "main.tf").read_text()
    assert 'resource "aws_security_group" "nlb"' in frontdoor
    assert "referenced_security_group_id = aws_security_group.nlb.id" in frontdoor
    assert "cidr_ipv4" not in frontdoor
    assert 'resource "aws_vpc_security_group_ingress_rule" "eks_nlb_from_vpc_link"' in apigw
    assert "referenced_security_group_id = aws_security_group.vpc_link.id" in apigw


def test_flink_role_and_boundary_allow_only_the_signed_api_invoke_path():
    flink = KDA_FLINK_MAIN.read_text()
    boundary = __import__("json").loads(BOUNDARY.read_text())
    assert 'sid       = "InvokeServingApi"' in flink
    assert 'actions   = ["execute-api:Invoke"]' in flink
    assert 'resources = ["${var.serving_api_execution_arn}/$default/POST/v1/score-ais"]' in flink
    ceiling = next(
        statement
        for statement in boundary["Statement"]
        if statement["Sid"] == "AllowHarbormasterServiceCeiling"
    )
    assert "execute-api:Invoke" in ceiling["Action"]
