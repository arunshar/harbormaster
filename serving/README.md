# serving

Model serving and the inference front door for Harbormaster.

**Phase 1 vertical slice (local, no AWS, zero token cost): shipped.** The GeoTrace
front-door is adapted into a deterministic AIS anomaly scorer. The heavy Pi-DPM
diffusion model (trained on MSI) and the SageMaker async endpoint, the Bedrock
explanation layer, and the AWS wiring land in later phases; this slice is the
serving logic and its tests, runnable offline.

## What runs here

`POST /v1/score-ais` scores one AIS fix against a vessel's recent history with a
deterministic plan (no LLM):

- **HeuristicPlanner** routes by history length (0 / 1 / 3+), replacing the LLM planner.
- Vendored GeoTrace deterministic agents do the work: the Hagerstrand **space-time
  prism** kernel, **GapDetector** (STAGD + AGM, numpy Pi-DPM surrogate),
  **Validator** (S-KBM kinematic gate), and **RendezvousFinder** (TGARD, kept for
  the multi-vessel path).
- **CorridorDeviationDetector** (the corridor add-on) runs the GTRA perpendicular
  association against the static sea-lane graph in `app/artifacts/corridors.json`.
- A fixed fusion turns agent signals into an anomaly `score`, a verdict
  `confidence`, and the HITL decision; anomalous/ambiguous events enqueue to the
  **Postgres HITL queue** (in-memory fallback when no DSN is set).

Reasons emitted: `implausible_speed`, `abnormal_gap`, `off_corridor`,
`unexpected_node`. Corrupt-grade teleports (beyond the corrupt-data bound) are
rejected with HTTP 422 rather than scored.

Routes: `GET /healthz`, `GET /metrics` (Prometheus), `POST /v1/score-ais`,
`POST /v1/feedback`, `GET /v1/hitl/pending`.

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app and routes |
| `app/orchestrator.py` | deterministic `run_plan` + scoring fusion + HITL routing |
| `app/agents/` | heuristic_planner + vendored agents + corridor_detector |
| `app/components/` | space_time_prism kernel + corridor graph geometry |
| `app/artifacts/corridors.json` | frozen GTRA-style sea-lane graph (demo) |
| `app/hitl.py` | Postgres + in-memory HITL backends |
| `app/cost.py`, `app/metrics.py` | per-inference cost ledger + Prometheus metrics |
| `tests/` | unit + golden tests (golden cases from the recorded fixture) |
| `Dockerfile` | serving image (build from repo root) |

## Run it

```bash
make serve-install      # venv + deps
make serve-test         # unit + golden tests
make serve-lint         # ruff
make serve-run          # API on :8000
make serve-docker       # build the container image
```

Settings use the `HM_` env prefix; see `env.example`. Honesty framing for the
corridor work (ESRI vs personal): `../docs/corridor-detector.md` and
`../docs/HONESTY.md`.
