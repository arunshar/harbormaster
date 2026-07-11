"""Unit tests for phase5_helpers.py plus the live structural assertions for
the gate 5.0 scaffold (toggle + validation + armed teardown guard), the
test_phase4_helpers / test_kms_helpers convention: each helper is exercised
against synthetic HCL both ways, then pinned against the real tree."""

from __future__ import annotations

from e2e.phase5_helpers import (
    EKS_CLUSTER_MODULE_PATH,
    EKS_NODE_GROUP_MODULE_PATH,
    ENV_MAIN_TF_PATH,
    ENV_VARIABLES_TF_PATH,
    GUARD_MODULE_PATH,
    enable_phase5_references,
    enable_phase5_requires_enable_phase1,
    guard_is_armed_by_default,
    guard_window_default_hours,
    helm_data_sources_gated_on_keda_flag,
    keda_release_is_gated_on_install_keda,
    module_is_gated_on_enable_phase5,
    node_group_scaling_config,
    variable_default,
)


# --------------------------------------------------------------------------- #
# module_is_gated_on_enable_phase5
# --------------------------------------------------------------------------- #
def test_gated_true_on_a_real_matching_module_block():
    text = """
    module "eks_teardown_guard" {
      count  = var.enable_phase5 ? 1 : 0
      source = "../../modules/eks_teardown_guard"
    }
    """
    assert module_is_gated_on_enable_phase5(text, "eks_teardown_guard") is True


def test_gated_false_when_module_absent():
    assert module_is_gated_on_enable_phase5('module "other" { count = 1 }', "eks_cluster") is False


def test_gated_false_when_gated_on_a_different_variable():
    text = """
    module "eks_teardown_guard" {
      count = var.enable_phase4 ? 1 : 0
    }
    """
    assert module_is_gated_on_enable_phase5(text, "eks_teardown_guard") is False


def test_gated_false_when_hardcoded_on():
    text = 'module "eks_teardown_guard" { count = 1 }'
    assert module_is_gated_on_enable_phase5(text, "eks_teardown_guard") is False


def test_gated_not_fooled_by_a_comment_mention():
    text = """
    # module "eks_teardown_guard" is gated on var.enable_phase5 ? 1 : 0 in prose
    module "eks_teardown_guard" {
      count = 1
    }
    """
    assert module_is_gated_on_enable_phase5(text, "eks_teardown_guard") is False


# --------------------------------------------------------------------------- #
# enable_phase5_requires_enable_phase1
# --------------------------------------------------------------------------- #
def test_validation_true_on_the_exact_convention_condition():
    text = """
    variable "enable_phase5" {
      type    = bool
      default = false
      validation {
        condition     = !var.enable_phase5 || var.enable_phase1
        error_message = "enable_phase5 requires enable_phase1 = true."
      }
    }
    """
    assert enable_phase5_requires_enable_phase1(text) is True


def test_validation_false_when_absent():
    text = 'variable "enable_phase5" { type = bool\n default = false }'
    assert enable_phase5_requires_enable_phase1(text) is False


def test_validation_false_when_tied_to_the_wrong_phase():
    text = """
    variable "enable_phase5" {
      validation {
        condition     = !var.enable_phase5 || var.enable_phase2
        error_message = "wrong prerequisite"
      }
    }
    """
    assert enable_phase5_requires_enable_phase1(text) is False


# --------------------------------------------------------------------------- #
# variable_default / guard posture helpers
# --------------------------------------------------------------------------- #
def test_variable_default_extracts_literal():
    text = 'variable "max_age_hours" {\n  type    = number\n  default = 4\n}'
    assert variable_default(text, "max_age_hours") == "4"


def test_variable_default_none_when_no_default():
    text = 'variable "sns_topic_arn" {\n  type = string\n}'
    assert variable_default(text, "sns_topic_arn") is None


def test_variable_default_none_when_variable_absent():
    assert variable_default("", "guard_dry_run") is None


def test_guard_armed_true_only_on_false_default():
    armed = 'variable "guard_dry_run" {\n  type    = bool\n  default = false\n}'
    disarmed = 'variable "guard_dry_run" {\n  type    = bool\n  default = true\n}'
    assert guard_is_armed_by_default(armed) is True
    assert guard_is_armed_by_default(disarmed) is False


# --------------------------------------------------------------------------- #
# The real tree: gate 5.0's scaffold properties, pinned
# --------------------------------------------------------------------------- #
def test_real_guard_module_is_gated_on_enable_phase5():
    text = ENV_MAIN_TF_PATH.read_text()
    assert module_is_gated_on_enable_phase5(text, "eks_teardown_guard") is True


def test_real_enable_phase5_requires_enable_phase1():
    assert enable_phase5_requires_enable_phase1(ENV_VARIABLES_TF_PATH.read_text()) is True


def test_real_enable_phase5_defaults_false():
    assert variable_default(ENV_VARIABLES_TF_PATH.read_text(), "enable_phase5") == "false"


def test_real_guard_is_armed_by_default_with_the_4_hour_window():
    guard_vars = (GUARD_MODULE_PATH / "variables.tf").read_text()
    assert guard_is_armed_by_default(guard_vars) is True
    assert guard_window_default_hours(guard_vars) == "4"


def test_real_every_phase5_count_reference_is_a_module_gate():
    # Every count that consults enable_phase5 belongs to a module call: the
    # zero-diff argument's structural half (nothing partially gated).
    text = ENV_MAIN_TF_PATH.read_text()
    gated = enable_phase5_references(text)
    assert "eks_teardown_guard" in gated


def test_real_guard_lambda_source_is_the_finops_packaging_convention():
    text = ENV_MAIN_TF_PATH.read_text()
    assert "${path.module}/../../../lambda/eks_teardown" in text


# --------------------------------------------------------------------------- #
# Gate 5.1 helpers, both ways on synthetic HCL
# --------------------------------------------------------------------------- #
def test_scaling_config_extracts_the_scale_to_zero_shape():
    text = """
    resource "aws_eks_node_group" "this" {
      scaling_config {
        min_size     = var.min_size
        max_size     = var.max_size
        desired_size = var.desired_size
      }
    }
    """
    cfg = node_group_scaling_config(text)
    assert cfg == {
        "min_size": "var.min_size",
        "max_size": "var.max_size",
        "desired_size": "var.desired_size",
    }


def test_scaling_config_none_when_absent():
    assert node_group_scaling_config('resource "aws_eks_node_group" "this" {}') is None


def test_scaling_config_not_fooled_by_a_comment_mention():
    text = """
    # narrating scaling_config { min_size = 9, max_size = 9, desired_size = 9 }
    resource "aws_eks_node_group" "this" {
      scaling_config {
        min_size     = var.min_size
        max_size     = var.max_size
        desired_size = var.desired_size
      }
    }
    """
    assert node_group_scaling_config(text) == {
        "min_size": "var.min_size",
        "max_size": "var.max_size",
        "desired_size": "var.desired_size",
    }


def test_keda_gating_true_on_install_keda_count():
    text = """
    resource "helm_release" "keda" {
      count = var.install_keda ? 1 : 0
      name  = "keda"
    }
    """
    assert keda_release_is_gated_on_install_keda(text) is True


def test_keda_gating_false_when_unconditional():
    text = 'resource "helm_release" "keda" {\n  name = "keda"\n}'
    assert keda_release_is_gated_on_install_keda(text) is False


def test_helm_data_gating_needs_both_sources():
    only_one = """
    data "aws_eks_cluster" "phase5" {
      count = var.enable_phase5_keda ? 1 : 0
    }
    data "aws_eks_cluster_auth" "phase5" {
      name = "x"
    }
    """
    assert helm_data_sources_gated_on_keda_flag(only_one) is False


def test_helm_data_gating_true_when_both_gated():
    both = """
    data "aws_eks_cluster" "phase5" {
      count = var.enable_phase5_keda ? 1 : 0
      name  = "x"
    }
    data "aws_eks_cluster_auth" "phase5" {
      count = var.enable_phase5_keda ? 1 : 0
      name  = "x"
    }
    """
    assert helm_data_sources_gated_on_keda_flag(both) is True


# --------------------------------------------------------------------------- #
# The real tree: gate 5.1's properties, pinned
# --------------------------------------------------------------------------- #
def test_real_eks_cluster_and_node_group_are_gated_on_enable_phase5():
    text = ENV_MAIN_TF_PATH.read_text()
    assert module_is_gated_on_enable_phase5(text, "eks_cluster") is True
    assert module_is_gated_on_enable_phase5(text, "eks_node_group") is True
    gated = enable_phase5_references(text)
    assert {"eks_teardown_guard", "eks_cluster", "eks_node_group"} <= gated


def test_real_node_group_defaults_are_the_scale_to_zero_shape():
    # The spec pins scaling_config { min_size = 0, max_size = 3,
    # desired_size = 0 }; the literals live in the variables' defaults.
    node_vars = (EKS_NODE_GROUP_MODULE_PATH / "variables.tf").read_text()
    assert variable_default(node_vars, "min_size") == "0"
    assert variable_default(node_vars, "max_size") == "3"
    assert variable_default(node_vars, "desired_size") == "0"
    cfg = node_group_scaling_config((EKS_NODE_GROUP_MODULE_PATH / "main.tf").read_text())
    assert cfg == {
        "min_size": "var.min_size",
        "max_size": "var.max_size",
        "desired_size": "var.desired_size",
    }


def test_real_node_group_is_spot():
    text = (EKS_NODE_GROUP_MODULE_PATH / "main.tf").read_text()
    assert 'capacity_type  = "SPOT"' in text


def test_real_keda_release_is_gated_and_pinned():
    main = (EKS_CLUSTER_MODULE_PATH / "main.tf").read_text()
    cluster_vars = (EKS_CLUSTER_MODULE_PATH / "variables.tf").read_text()
    assert keda_release_is_gated_on_install_keda(main) is True
    assert variable_default(cluster_vars, "install_keda") == "false"
    # The chart version is pinned (war-story P8), not floating.
    assert variable_default(cluster_vars, "keda_chart_version") is not None


def test_real_helm_provider_is_count_safe():
    text = ENV_MAIN_TF_PATH.read_text()
    assert helm_data_sources_gated_on_keda_flag(text) is True


def test_real_enable_phase5_keda_requires_enable_phase5():
    text = ENV_VARIABLES_TF_PATH.read_text()
    assert variable_default(text, "enable_phase5_keda") == "false"
    assert "!var.enable_phase5_keda || var.enable_phase5" in text


def test_real_cluster_endpoint_is_private_by_default():
    main = (EKS_CLUSTER_MODULE_PATH / "main.tf").read_text()
    cluster_vars = (EKS_CLUSTER_MODULE_PATH / "variables.tf").read_text()
    assert "endpoint_private_access = true" in main
    assert variable_default(cluster_vars, "endpoint_public_access") == "false"
