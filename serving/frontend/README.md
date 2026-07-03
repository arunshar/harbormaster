# serving/frontend - HITL reviewer console (Phase 1.6, gate G6)

A Streamlit console for the human-in-the-loop review queue. It reads pending
anomalous/ambiguous events from the serving API (`GET /v1/hitl/pending`), shows
them as a table plus a best-effort map (points come from any reason evidence that
carries `lat`/`lon`), and lets a reviewer submit a verdict
(`correct` / `incorrect` / `ambiguous`) via `POST /v1/feedback`. Those verdicts land
in the Postgres `hitl_queue` and seed the Phase 4 RL flywheel.

## Run

```bash
pip install -e ".[console]"
SERVING_URL=https://<api-gateway-invoke-url> streamlit run serving/frontend/console.py
# locally against a dev serving instance:
SERVING_URL=http://localhost:8000 streamlit run serving/frontend/console.py
```

## Layout

- `hitl_client.py` - the thin urllib API client (`HitlApi`) plus pure view helpers
  (`feedback_payload`, `format_row`, `reason_codes`, `positions_from_rows`) that are
  unit-tested in `tests/` with no server and no Streamlit.
- `console.py` - the Streamlit UI, kept thin over those helpers. Verified by the
  gate-1.6 deploy smoke (open the console, label the seeded anomaly, confirm the DB
  row updates); it is not imported by the test suite, so pytest needs no Streamlit.
