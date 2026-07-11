"""Unit tests for phase5_helpers.py plus the live structural assertions for
the gate 5.0 scaffold (toggle + validation + armed teardown guard), the
test_phase4_helpers / test_kms_helpers convention: each helper is exercised
against synthetic HCL both ways, then pinned against the real tree."""

from __future__ import annotations

from e2e.phase5_helpers import (
    ENV_MAIN_TF_PATH,
    ENV_VARIABLES_TF_PATH,
    GUARD_MODULE_PATH,
    enable_phase5_references,
    enable_phase5_requires_enable_phase1,
    guard_is_armed_by_default,
    guard_window_default_hours,
    module_is_gated_on_enable_phase5,
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
