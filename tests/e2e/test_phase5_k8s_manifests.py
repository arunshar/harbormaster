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

import os
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
W4_OPERATOR_PLAN = REPO_ROOT / "docs" / "runbooks" / "W4_OPERATOR_PLAN_2026-07-14.md"
PHASE5_PLAN = REPO_ROOT / "docs" / "phases" / "PHASE_5.md"
CANONICAL_HANDOFF = REPO_ROOT / "sessions" / "CODEX_HANDOFF_2026-07-12.md"
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


def test_runbook_guards_the_expected_missing_elb_service_linked_role():
    runbook = W4_RUNBOOK.read_text()
    probe = runbook.index('ELB_ROLE_BEFORE="$ARTIFACT_DIR/')
    no_such_entity = runbook.index("\\(NoSuchEntity\\)", probe)
    create = runbook.index("aws iam create-service-linked-role", no_such_entity)
    verify = runbook.index(
        "aws iam get-role --role-name AWSServiceRoleForElasticLoadBalancing",
        create,
    )

    assert probe < no_such_entity < create < verify
    assert '2> "$ELB_ROLE_BEFORE_STDERR"' in runbook
    assert 'exit "$ELB_ROLE_LOOKUP_STATUS"' in runbook
    assert 'if test "$ELB_SERVICE_LINKED_ROLE_PRESENT" = false; then' in runbook
    assert "already exists|has been taken" in runbook
    assert '"$ARTIFACT_DIR/elb-service-linked-role.json"' in runbook[verify:]


def test_runbook_has_an_executable_verified_iam_reconciliation_rollback():
    runbook = W4_RUNBOOK.read_text()
    prior_boundary = runbook.index("PRIOR_BOUNDARY_VERSION=$(jq -er")
    prior_policy = runbook.index("platform-policy-before-document.json")
    prior_duration = runbook.index("PRIOR_PLATFORM_MAX_SESSION_DURATION=$(jq -er")
    rollback_start = runbook.index("rollback_iam_reconciliation()")
    mutation = runbook.index("NEW_BOUNDARY_VERSION=$(aws iam create-policy-version")
    rollback_end = runbook.index("rollback_incomplete_iam_reconciliation()")
    rollback = runbook[rollback_start:rollback_end]

    assert prior_boundary < prior_policy < prior_duration < rollback_start < mutation
    restore_boundary = rollback.index("aws iam set-default-policy-version")
    restore_policy = rollback.index("aws iam put-role-policy")
    restore_duration = rollback.index("aws iam update-role")
    assert restore_boundary < restore_policy < restore_duration
    assert '"file://$ARTIFACT_DIR/platform-policy-before-document.json"' in rollback
    assert "boundary-rollback-verification.json" in rollback
    assert "platform-policy-rollback-verification.json" in rollback
    assert "platform-role-rollback-verification.json" in rollback
    assert ".[0].PolicyDocument == .[1].PolicyDocument" in rollback
    assert "IAM_RECONCILIATION_ROLLBACK_STARTED=false" in runbook
    assert 'test "$IAM_RECONCILIATION_ROLLBACK_STARTED" = true' in runbook
    assert "INT) original_status=130" in runbook
    assert "TERM) original_status=143" in runbook
    for trigger in ("EXIT", "INT", "TERM", "ERR"):
        assert f'rollback_incomplete_iam_reconciliation {trigger} "$iam_trap_status"' in runbook
    assert runbook.index("IAM_RECONCILIATION_COMPLETE=true") < runbook.index(
        "PLATFORM_SESSION=$(aws sts assume-role"
    )


@pytest.mark.parametrize("shell", ["bash", "zsh"])
@pytest.mark.parametrize(
    ("trigger", "expected_status"),
    [("ERR", 1), ("EXIT", 1), ("INT", 130), ("TERM", 143)],
)
def test_iam_rollback_handler_runs_once_in_bash_and_zsh(shell, trigger, expected_status, tmp_path):
    binary = shutil.which(shell)
    if binary is None:
        pytest.skip(f"{shell} is not installed")

    runbook = W4_RUNBOOK.read_text()
    handler_start = runbook.index("rollback_incomplete_iam_reconciliation()")
    handler_end = runbook.index("\n```\n\n`ARUN RUNS`", handler_start)
    handler = runbook[handler_start:handler_end]
    probe = f"""
set -euo pipefail
IAM_RECONCILIATION_COMPLETE=false
IAM_RECONCILIATION_ROLLBACK_STARTED=false
rollback_iam_reconciliation() {{
  printf 'rollback\\n' >> "$ROLLBACK_LOG"
}}
{handler}
case "$TRIGGER" in
  ERR) false ;;
  EXIT) exit 0 ;;
  INT) kill -INT "$$" ;;
  TERM) kill -TERM "$$" ;;
esac
exit 99
"""
    rollback_log = tmp_path / "rollback.log"
    env = {**os.environ, "ROLLBACK_LOG": str(rollback_log), "TRIGGER": trigger}
    result = subprocess.run(
        [binary, "-s"],
        input=probe,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == expected_status, result.stderr
    assert rollback_log.read_text().splitlines() == ["rollback"]


def test_runbook_captures_exact_keda_operator_diagnostics():
    runbook = W4_RUNBOOK.read_text()
    stage_2 = runbook.index("## 5. Stage 2")
    describe = runbook.index("kubectl describe deployment -n keda keda-operator", stage_2)
    logs = runbook.index("kubectl logs -n keda deployment/keda-operator", describe)
    scan = runbook.index("NoCredentialProviders", logs)
    stage_3 = runbook.index("## 6. Build, push", scan)

    assert stage_2 < describe < logs < scan < stage_3
    assert '"$ARTIFACT_DIR/keda-operator-describe.txt"' in runbook[describe:logs]
    assert "--all-containers=true --tail=500" in runbook[logs:scan]
    assert '"$ARTIFACT_DIR/keda-operator.log"' in runbook[logs:stage_3]


def test_runbook_requires_all_measurement_processes_to_succeed():
    runbook = W4_RUNBOOK.read_text()
    status = runbook.index("measurement-command-status.json")
    all_zero = runbook.index(
        ".load_exit == 0 and .observer_exit == 0 and .flink_capture_exit == 0",
        status,
    )
    verdict = runbook.index("measurement-evidence-verdict.json", all_zero)
    verdict_block = runbook[all_zero:verdict]

    assert "MEASUREMENT_PROCESSES_SUCCEEDED=true" in verdict_block
    assert '--argjson processes_succeeded "$MEASUREMENT_PROCESSES_SUCCEEDED"' in verdict_block
    assert "processes_succeeded: $processes_succeeded" in verdict_block
    assert '--argjson criterion_a "$MEASUREMENT_CRITERION_A_PASSED"' in verdict_block
    assert '--argjson criterion_b "$MEASUREMENT_CRITERION_B_PASSED"' in verdict_block
    assert "kinesis_metric_captured: $kinesis_metric_captured" in verdict_block
    assert "flink_lag_captured: $flink_lag_captured" in verdict_block
    assert "criteria: {a: $criterion_a, b: $criterion_b}" in verdict_block


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


def test_guard_proof_failure_uses_reviewed_terraform_cleanup_without_state_rm():
    runbook = W4_RUNBOOK.read_text()
    poll = runbook.index("DELETION_CONFIRMED=false")
    verdict = runbook.index("guard-criterion-verdict.json", poll)
    section_11 = runbook.index("## 11. Reconcile state", verdict)
    cleanup = runbook.index("wave4-w4-guard-fallback-cleanup", section_11)
    final_assertion = runbook.index('test "$MEASUREMENT_CRITERION_A_PASSED" != true', cleanup)
    polling = runbook[poll:section_11]
    reconciliation = runbook[section_11:cleanup]

    assert not re.search(r'^test "\$DELETION_CONFIRMED" = true$', runbook, re.MULTILINE)
    assert poll < verdict < section_11 < cleanup < final_assertion
    assert 'exit "$LIST_STATUS"' not in polling
    assert 'exit "$DESCRIBE_STATUS"' not in polling
    assert 'GUARD_POLL_FAILURE_REASON="list-nodegroups failed' in polling
    assert 'GUARD_POLL_FAILURE_REASON="describe-cluster failed' in polling
    assert 'if aws logs tail "/aws/lambda/$GUARD" --since 60m' in polling
    assert 'test -s "$ARTIFACT_DIR/guard-live-fire.log"' in polling
    assert "final_log_captured: $final_log_captured" in polling
    assert 'if test "$GUARD_PROOF_SUCCEEDED" = true; then' in reconciliation
    assert "terraform -chdir=infra/terraform/envs/base state rm" in reconciliation
    assert "guard-fallback-state-preserved.txt" in reconciliation
    assert "preserving EKS cluster and node-group state" in reconciliation
    assert ".add == 0" in runbook[cleanup:]
    assert '((.actions | index("create")) == null)' in runbook[cleanup:]
    assert '.actions == ["delete"]' in runbook[cleanup:]
    assert "module.eks_cluster[0].aws_eks_cluster.this" in runbook[cleanup:]
    assert "module.eks_node_group[0].aws_eks_node_group.this" in runbook[cleanup:]
    assert 'test "$MEASUREMENT_CRITERION_B_PASSED" != true' in runbook
    assert 'test "$GUARD_PROOF_SUCCEEDED" != true' in runbook
    assert "W4 incomplete after safe resting cleanup" in runbook


def test_final_verification_rechecks_identity_budget_action_and_boundary():
    runbook = W4_RUNBOOK.read_text()
    final = runbook[runbook.index("## 12. Final verification") :]

    assert "final-platform-caller-identity.json" in final
    assert "assumed-role/harbormaster-platform/" in final
    assert "hard-budget-final.json" in final
    assert "hard-budget-actions-final.json" in final
    assert "boundary-final.json" in final
    assert "(.Budget.BudgetLimit.Amount | tonumber) == 75" in final
    assert '.Status == "STANDBY"' in final
    assert '.ApprovalModel == "AUTOMATIC"' in final
    assert '--arg version "$NEW_BOUNDARY_VERSION"' in final


def test_sanitized_handoff_excludes_plans_and_rejects_aws_credentials():
    runbook = W4_RUNBOOK.read_text()
    sanitizer = runbook[runbook.index('HANDOFF_DIR="$ARTIFACT_DIR-sanitized"') :]

    assert "! -name '*.plan.txt' ! -name '*.tfplan'" in sanitizer
    assert "-type f -name '*.tfplan'" in sanitizer
    assert "-type f -name '*.plan.txt'" in sanitizer
    assert "AKIA[0-9A-Z]{16}" in sanitizer
    assert "ASIA[0-9A-Z]{16}" in sanitizer
    assert '"(AccessKeyId|SecretAccessKey|SessionToken)"' in sanitizer


def test_w4_docs_assign_the_phase_gate_and_cold_start_claim_correctly():
    operator = W4_OPERATOR_PLAN.read_text()
    handoff = CANONICAL_HANDOFF.read_text()
    phase5 = PHASE5_PLAN.read_text()

    assert "operator Steps 4 through 15" in operator
    assert "Guard assertion; Stage 0 only if dry" in operator
    assert "On guard failure, both addresses remain" in operator
    assert "canonical Sections 1-12" in handoff
    assert '"Window W4"' not in handoff
    assert "Optional same-window" not in handoff
    assert "A successful W4 already closes the Phase 5 gate" in handoff
    assert "Wave 5 does not reopen" in handoff
    assert "a successful W4 closes the Phase 5 gate" in phase5
    assert "Wave 5 is a separate" in phase5
    assert re.search(r"grounds the observed\s+cold-start behavior", handoff)
    assert re.search(r"only if the\s+measured value", handoff)


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
