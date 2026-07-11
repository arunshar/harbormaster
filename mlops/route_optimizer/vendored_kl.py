"""VENDORED from pi-grpo, not imported (docs/phases/PHASE_5.md gate 5.7).

Provenance: pi-grpo local mirror at
``~/Desktop/msi-mirror/paper-work/pi-grpo``, commit ``6b54808``
(2026-07-10), file ``app/trainers/base.py``. Vendored 2026-07-11.

``AdaptiveKLController`` is copied with its update rule verbatim, byte for
byte in every arithmetic expression, so the cross-check test
(``mlops/tests/test_route_optimizer_kl.py``) can assert bit-for-bit equality
against the real source on a fixed input, the same spirit as Phase 3's
AUC/CRPS cross-checks against sklearn/scipy. ``cosine_lr`` is copied
verbatim as well (pure math). The ONLY departures from the source file:
``clip_grad_norm`` is not vendored (it wraps ``torch.nn.utils``; the numpy
retarget's global-norm clip lives in ``ppo.py``), and the ``import torch``
line goes with it. Do NOT "improve" this file; a change here breaks the
bit-for-bit provenance claim and must re-run the cross-check.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class AdaptiveKLController:
    """Heuristic KL controller from Stiennon et al. (2020), Ouyang et al. (2022).

    Doubles or halves `kl_coef` to keep KL near `target` over a horizon
    of `horizon` updates. Bounded so a runaway batch cannot push the
    coefficient to absurd values.
    """

    kl_coef: float = 0.2
    target: float = 6.0
    horizon: int = 10000
    clip_min: float = 1e-3
    clip_max: float = 100.0

    def update(self, current_kl: float, n_steps: int) -> None:
        if current_kl is None or math.isnan(current_kl):
            return
        proportional_error = (current_kl - self.target) / self.target
        proportional_error = float(max(min(proportional_error, 0.2), -0.2))
        mult = 1.0 + proportional_error * n_steps / self.horizon
        self.kl_coef = float(min(max(self.kl_coef * mult, self.clip_min), self.clip_max))


def cosine_lr(step: int, *, warmup: int, total: int, lr_max: float, lr_min: float) -> float:
    if step < warmup:
        return lr_max * step / max(1, warmup)
    progress = (step - warmup) / max(1, total - warmup)
    return lr_min + 0.5 * (lr_max - lr_min) * (1 + math.cos(math.pi * progress))
