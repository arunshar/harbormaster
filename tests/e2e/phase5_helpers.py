"""Pure helpers for the Phase 5 scaffold acceptance (gates 5.0+).

Phase 5's infrastructure is authored-not-applied, so what a test CAN honestly
pin down is structural, mirroring gate 4.7's phase4_helpers.py and the CMK
pass's kms_helpers.py: the Phase 5 modules are whole-module count-gated on
enable_phase5, enable_phase5 carries the enable_phase1 cross-validation (the
enable_phase2/3 convention), and the gate 5.0 teardown guard is armed by
default (guard_dry_run defaults false) with the 4-hour window the spec names.
Unit-tested unguarded in test_phase5_helpers.py.
"""

from __future__ import annotations

import re
from pathlib import Path

INFRA_TERRAFORM_PATH = Path(__file__).parent.parent.parent / "infra" / "terraform"
ENV_MAIN_TF_PATH = INFRA_TERRAFORM_PATH / "envs" / "base" / "main.tf"
ENV_VARIABLES_TF_PATH = INFRA_TERRAFORM_PATH / "envs" / "base" / "variables.tf"
GUARD_MODULE_PATH = INFRA_TERRAFORM_PATH / "modules" / "eks_teardown_guard"

# Matches a `module "<name>" { count = var.enable_phase5 ? 1 : 0 ... }` block
# specifically, scoped to content between its own braces (gate 3.9's lesson:
# an unscoped substring match can be fooled by a mention in a comment).
_PHASE5_GATED_MODULE_RE_TEMPLATE = (
    r'module\s+"{name}"\s*\{{[^{{}}]*count\s*=\s*var\.enable_phase5\s*\?\s*1\s*:\s*0\b'
)

# The enable_phase5 -> enable_phase1 cross-variable validation, inside the
# enable_phase5 variable block's validation stanza.
_PHASE5_REQUIRES_PHASE1_RE = re.compile(
    r'variable\s+"enable_phase5"\s*\{.*?'
    r"condition\s*=\s*!var\.enable_phase5\s*\|\|\s*var\.enable_phase1",
    re.DOTALL,
)

_VARIABLE_BLOCK_RE_TEMPLATE = r'variable\s+"{name}"\s*\{{(.*?)\n\}}'
_DEFAULT_RE = re.compile(r"default\s*=\s*(\S+)")


def module_is_gated_on_enable_phase5(env_main_tf_text: str, module_name: str) -> bool:
    """True if the named module call's whole-module count is structurally tied
    to enable_phase5 (not hardcoded, not gated on a different var)."""
    pattern = re.compile(_PHASE5_GATED_MODULE_RE_TEMPLATE.format(name=re.escape(module_name)))
    return pattern.search(env_main_tf_text) is not None


def enable_phase5_requires_enable_phase1(env_variables_tf_text: str) -> bool:
    """True if enable_phase5 carries the exact cross-variable validation the
    enable_phase2/enable_phase3 convention prescribes."""
    return _PHASE5_REQUIRES_PHASE1_RE.search(env_variables_tf_text) is not None


def variable_default(tf_text: str, variable_name: str) -> str | None:
    """The literal default expression of a variable block, or None when the
    variable is absent or declares no default. Matches the block lazily up to
    the first newline-anchored closing brace, so nested validation blocks
    inside the variable stay in scope."""
    pattern = re.compile(
        _VARIABLE_BLOCK_RE_TEMPLATE.format(name=re.escape(variable_name)), re.DOTALL
    )
    block = pattern.search(tf_text)
    if not block:
        return None
    default = _DEFAULT_RE.search(block.group(1))
    return default.group(1) if default else None


def guard_is_armed_by_default(guard_variables_tf_text: str) -> bool:
    """True if the teardown guard's dry-run default is false (armed): the
    structural-not-procedural property gate 5.0 exists to provide."""
    return variable_default(guard_variables_tf_text, "guard_dry_run") == "false"


def guard_window_default_hours(guard_variables_tf_text: str) -> str | None:
    """The guard's default force-destroy window (the spec pins 4)."""
    return variable_default(guard_variables_tf_text, "max_age_hours")


def enable_phase5_references(env_main_tf_text: str) -> set[str]:
    """Names of the module calls in envs/base/main.tf whose count references
    enable_phase5. Supports the zero-diff argument: every Phase 5 surface must
    sit behind the toggle, so the false plan collapses them all."""
    module_headers = [
        (m.start(), m.group(1)) for m in re.finditer(r'module\s+"([^"]+)"\s*\{', env_main_tf_text)
    ]
    gated: set[str] = set()
    for ref in re.finditer(r"count\s*=\s*var\.enable_phase5\s*\?\s*1\s*:\s*0", env_main_tf_text):
        preceding = [name for start, name in module_headers if start < ref.start()]
        if preceding:
            gated.add(preceding[-1])
    return gated
