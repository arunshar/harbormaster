# Phase 4 sketch: drift -> HITL -> RL flywheel (design notes, NOT an execution plan)

**This is a sketch, not `docs/phases/PHASE_4.md`.** It exists to lock the three design
decisions the master plan's Phase 4 section names but does not fully specify (the drift
taxonomy, the preference-triple schema, and the reward-hacking probe), so a later session
can go straight to authoring the real gate-by-gate `PHASE_4.md` (in the `PHASE_1.md`/
`PHASE_2.md`/`PHASE_3.md` style: numbered gates, unit/smoke/checksum per gate, a cost
envelope, war stories) without re-deriving these three pieces from scratch. Nothing here is
built; no branch, no code, no tests. When Phase 4 execution starts, this sketch's content
gets promoted into `PHASE_4.md` gates and the master plan updated in the same commit, per
the standing governance rule (any plan change updates the phase doc AND the master plan
before executing).

Master plan text this sketch expands (`~/.claude/plans/i-am-thinking-to-rustling-sifakis.md`,
Phase 4): "Drift triggers... classify input vs concept vs calibration drift. Concept/
high-epistemic-uncertainty traces (near-threshold AND high EDL variance) route to the
Postgres HITL queue -> operator verdicts -> `preference_builder` -> Pi-GRPO DPO/GRPO
fine-tune on MSI -> holdout gate -> canary... A reward-hacking probe runs before any RL
redeploy and blocks promotion if reward rose while hard-violation rate rose."

## 1. Drift taxonomy (decisions locked)

Three categories, each with a different detection mechanism and a different required
input, because they are answering three different questions.

- **Input drift** ("has the population of vessels/tracks changed?"). Reuse anchor:
  `~/code/mirror/serving/monitoring/drift.py`'s `check_input_drift` (per-feature PSI + a
  two-sample KS test, `DriftConfig`'s `psi_warn=0.1`/`psi_alert=0.25`/`ks_pvalue_alert=0.05`
  defaults). Needs no labels, runs continuously on live feature distributions vs a rolling
  reference window. This is the cheapest, most reliable signal and should be the first
  alarm tier.
- **Calibration drift** ("does the model's predicted uncertainty still match its real
  error?"). Reuse anchor: `mlops/holdout_gate.py:calibration_ratio` (already ported from the
  same MIRROR formula in Phase 3, `mean(err^2) / mean(variance)`, 1.0 = perfectly
  calibrated) - Phase 4 does not re-port this, it re-calls the Phase 3 function directly
  against a rolling window of HITL-labeled outcomes (the trickle of ground truth HITL
  verdicts provide). Locked: the SAME `[0.8, 1.2]` range from the Phase 3 holdout gate is
  the alert band here too, for one reason worth stating explicitly: a model whose
  serving-time calibration has drifted outside the same range its own promotion gate
  required is, by definition, no longer the model that gate approved.
- **Concept drift** ("has the true input-to-label relationship changed?"). The hard one:
  there is no ground-truth label stream in production anomaly detection, so this is
  detected only by proxy, never directly, and the sketch is explicit about that limit
  rather than overclaiming a direct concept-drift detector. Two proxies, cross-validated
  against each other before either is trusted alone:
  1. **Near-threshold + high epistemic uncertainty trace volume.** A trace where the fused
     anomaly score sits near `anomaly_hitl_threshold` (already the existing HITL routing
     threshold, `serving/app/config.py`) AND the Pi-DPM head's epistemic variance is high
     is exactly the "the model itself is unsure" signal (the master plan's "EDL variance"
     language: ESRI's original detector was an RNN + Evidential Deep Learning regressor,
     per `docs/HONESTY.md`/`reference_neurosymbolic_framing.md`'s framing, and Pi-DPM is
     its personal re-creation; an EDL-style output decomposes into aleatoric vs epistemic
     uncertainty, not just a point score). **Locked interface change for Phase 4:**
     `serving/app/pidpm_client.py`'s `PiDpmClient.score`/`ascore` currently returns a single
     `float | None` (gate 3.6); Phase 4 extends the SageMaker payload contract to
     `{"score": float, "epistemic_variance": float}` and the client to return both, a
     backward-compatible additive change (existing callers reading `["score"]` keep working).
  2. **HITL disagreement rate.** Once enough HITL verdicts accumulate, the rate at which
     operators override the model's implied verdict (a "correct" label on a trace the model
     scored as anomalous, or vice versa) is the actual, ground-truth-adjacent concept-drift
     signal; it just lags the population-level proxy above by however long it takes to
     accumulate enough verdicts.
  A rising rate on proxy 1 with a flat disagreement rate on proxy 2 is "the model is seeing
  more ambiguous cases, but is still right about them" (not concept drift, more traffic
  through the HITL queue is fine); a rising rate on proxy 2 is concept drift regardless of
  proxy 1, and is the one that should actually trigger retraining.

**Decision table (defensibility rule, verbatim from the master plan, made concrete):**

| Drift category | Detection | Response |
|---|---|---|
| Input drift only | PSI/KS alert, calibration + disagreement flat | Log + dashboard; no action (population shift the model already generalizes over) |
| Calibration drift | `calibration_ratio` outside `[0.8, 1.2]` | Plain supervised retraining on the accumulated HITL-labeled trickle (the ~90% case: you have labels, so DPO/GRPO is not needed) |
| Concept drift (HITL disagreement rising) | Proxy 2 above a locked threshold (to be set empirically at Phase 4 gate-authoring time from a real disagreement-rate baseline, not guessed here) | Route the disagreeing traces into the preference-triple pipeline (below); DPO/GRPO is reserved for exactly this regime: two plausible explanations, no ground-truth label (e.g., ambiguous rendezvous), which is what a HITL disagreement without a hard label actually is |

## 2. Preference-triple schema (decisions locked)

Ports (does not cross-repo-import) pi-grpo's real `app/components/preference_builder.py`
(`from_hitl_jsonl`, `synthesize_from_reward`) and `app/components/physics_reward.py`'s real
`RewardBreakdown` fields, matching this repo's established external-reuse pattern (vendor
the shape, do not import the module).

**Locked schema** (one JSON object per preference triple, written by a new
`mlops/preference_builder.py` this sketch does not implement):

```json
{
  "trace_id": "the harbormaster trace_id from AisScoreOut, the join key back to the scored event",
  "mmsi": 367000001,
  "context": {
    "anchors": "the anchor/trajectory window the orchestrator scored, same shape run_plan already builds",
    "reasons": "the ScoreReason list the orchestrator produced (so the trainer sees what the model claimed, not just its final score)"
  },
  "chosen": {
    "source": "hitl_operator_label | reward_synthesized",
    "verdict_or_trajectory": "whatever the HITL console captured (correct/incorrect/ambiguous, extended in Phase 4 with a corrected-trajectory field if the operator can supply one) or the higher-reward candidate for a synthesized pair",
    "reward": {"total": 0.0, "hard": 0.0, "soft": 0.0, "data": 0.0, "pref": 0.0}
  },
  "rejected": {
    "source": "hitl_operator_label | reward_synthesized",
    "verdict_or_trajectory": "the disagreeing/lower-reward alternative",
    "reward": {"total": 0.0, "hard": 0.0, "soft": 0.0, "data": 0.0, "pref": 0.0}
  },
  "preference_source": "hitl_verdict | reward_synthesized",
  "hitl_operator": "operator id, null when reward_synthesized",
  "hard_violation_in_either_arm": false,
  "created_at": "iso8601"
}
```

Two construction paths, both already named in the master plan and both real pi-grpo entry
points to port, not invent:
- **`from_hitl_jsonl`-shaped path:** a HITL disagreement (Postgres `hitl` table, per
  `serving/app/hitl.py`'s existing schema, extended with the operator's chosen/rejected
  framing) exports to this schema directly; `preference_source = "hitl_verdict"`.
- **`synthesize_from_reward`-shaped path:** for the ~10% RL-eligible regime where two
  candidate explanations exist but no operator has weighed in yet (or to densify a sparse
  HITL signal), synthesize a pair directly from `PhysicsReward.score()`'s own output:
  whichever of two candidate trajectories/verdicts the reward function already prefers
  becomes `chosen`. **Locked invariant (carried over from pi-grpo's own reward design, not
  new to Phase 4):** the reward's `hard` term is unbounded and weighted `5.0` against
  `soft`/`data`/`pref` at `1.0` each (`RewardWeights`, pi-grpo `app/components/
  physics_reward.py`), so a synthesized pair can never let a kinematically impossible
  trajectory win; `hard_violation_in_either_arm` is computed and stored on every triple
  specifically so the reward-hacking probe (below) can audit this claim rather than assume it.

**Storage decision:** append-only JSONL under a new `mlops/preference_data/` (mirroring
`mlops/manifest.py`'s file-based, content-addressable-friendly convention), exported to S3
alongside the training-set export from gate 3.3, not a new database table; preference
triples are training data, not operational state, and should live where MSI training reads
from, not in Postgres.

## 3. Reward-hacking probe (decisions locked)

**Definition (the master plan's rule, made checkable):** a DPO/GRPO-fine-tuned candidate is
blocked from promotion if its mean total reward on a held-out set is HIGHER than the
baseline's AND its hard-violation rate is also HIGHER than the baseline's. Reward rising
while respecting physics more (or the same) is real improvement; reward rising while
violating physics more is the model exploiting the `soft`/`data`/`pref` terms at the hard
term's expense, which the unbounded `5.0`-weighted `hard` term is specifically supposed to
prevent, so a candidate that manages it anyway is gaming the reward, not improving.

**Locked function sketch** (to land as `mlops/reward_hacking_probe.py`, reusing the
`RewardBreakdown` shape ported into `mlops/preference_builder.py` above; not implemented in
this sketch):

```python
@dataclass(frozen=True)
class RewardHackingProbeResult:
    baseline_mean_reward: float
    candidate_mean_reward: float
    baseline_hard_violation_rate: float
    candidate_hard_violation_rate: float
    blocked: bool
    reason: str | None

def run_reward_hacking_probe(
    baseline_rewards: list[RewardBreakdown],
    candidate_rewards: list[RewardBreakdown],
    *,
    hard_violation_threshold: float = 0.0,  # a RewardBreakdown.hard below this counts as a violation
) -> RewardHackingProbeResult:
    ...
```

Blocking condition: `candidate_mean_reward > baseline_mean_reward AND
candidate_hard_violation_rate > baseline_hard_violation_rate`. Anything else (reward up
with violations flat or down; reward down regardless of violations) passes the probe,
though a reward decrease still has to clear the ordinary holdout gate (`mlops/
holdout_gate.py`, unchanged from Phase 3) to be promotable at all.

**Where it plugs in:** a new step inserted into `mlops/promote.py`'s state machine
(gate 3.7) between the holdout gate and shadow, specifically for DPO/GRPO-sourced
candidates (supervised-retrain candidates from the calibration-drift path skip it, since
there is no reward function in that path to game). This is an *addition* to the existing
state machine, not a redesign: `run_promotion`'s signature would gain an optional
`reward_hacking_result: RewardHackingProbeResult | None` argument, checked immediately
after the holdout gate exactly the way the holdout gate itself is checked before shadow.

**Accept criterion this satisfies (master plan, verbatim):** "the reward-hacking probe
blocks a deliberately gamed checkpoint." A future gate-authoring session should design a
drill for this the same way gates 3.8's L1/L2 drills were built: construct a synthetic
candidate whose `RewardBreakdown` stream deliberately has higher `total` and a higher
violation rate than a synthetic baseline, and assert the probe blocks it, then a second
synthetic candidate with higher `total` and a lower or equal violation rate, and assert the
probe passes it.

## Reuse anchors (do not rebuild)

`mlops/holdout_gate.py:calibration_ratio` (gate 3.7, reused directly for calibration-drift
detection, not re-ported). `~/code/mirror/serving/monitoring/drift.py` (`check_input_drift`,
`DriftConfig`) for input drift. `serving/app/hitl.py` (the existing HITL queue schema, to be
extended, not replaced, with chosen/rejected framing). `serving/app/pidpm_client.py` (gate
3.6, the client whose contract Phase 4 additively extends with `epistemic_variance`).
External, ported not imported: pi-grpo's `app/components/preference_builder.py`
(`from_hitl_jsonl`, `synthesize_from_reward`) and `app/components/physics_reward.py`
(`RewardWeights`, `RewardBreakdown`, `PhysicsReward.score`, `to_panel()`). `mlops/promote.py`
(gate 3.7, the state machine this phase adds one step to, not replaces).

## Open questions for the real `PHASE_4.md` (deliberately left open here)

- The concept-drift disagreement-rate alert threshold needs a real empirical baseline
  (from accumulated HITL verdicts) before it can be a locked number; this sketch names the
  mechanism, not the threshold.
- Whether `epistemic_variance` comes from a true EDL (Dirichlet/evidential) output head on
  the real trained Pi-DPM, or an ensemble-variance proxy, is an MSI-training-time decision
  outside this sketch's scope (Phase 4 execution's own gate, not sketched here).
- Corrected-trajectory capture in the HITL console (letting an operator supply a better
  trajectory, not just a label) is a serving/frontend UI change not scoped here; the schema
  above accommodates it (`verdict_or_trajectory`) but does not require it for the flywheel
  to function on labels alone.
