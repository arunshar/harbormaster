"""Streamlit HITL reviewer console (Phase 1.6, gate G6).

Run:  SERVING_URL=<serving-api> streamlit run serving/frontend/console.py

Reads the pending review queue (GET /v1/hitl/pending), shows it as a table plus a
best-effort map (points come from any reason evidence carrying lat/lon), and lets a
reviewer label {correct, incorrect, ambiguous} via POST /v1/feedback. Verified by
the gate-1.6 deploy smoke; the pure helpers in hitl_client are unit-tested here.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from frontend.hitl_client import (
    LABELS,
    HitlApi,
    feedback_payload,
    format_row,
    positions_from_rows,
)

st.set_page_config(page_title="Harbormaster HITL", layout="wide")
api = HitlApi(os.environ.get("SERVING_URL", "http://localhost:8000"))

st.title("Harbormaster - human-in-the-loop review")
reviewer = st.sidebar.text_input("Reviewer", value=os.environ.get("USER", "reviewer"))

try:
    rows = api.pending()
except Exception as exc:
    st.error(f"could not reach the serving API: {exc}")
    st.stop()

st.caption(f"{len(rows)} events awaiting review")
if not rows:
    st.success("Queue is empty.")
    st.stop()

points = positions_from_rows(rows)
if points:
    st.map(pd.DataFrame(points))

st.dataframe([format_row(r) for r in rows], use_container_width=True)

st.subheader("Label an event")
trace = st.selectbox("trace_id", [r.get("trace_id") for r in rows])
label = st.radio("verdict", LABELS, horizontal=True)
notes = st.text_input("notes (optional)")
if st.button("Submit verdict"):
    try:
        resp = api.feedback(feedback_payload(trace, label, reviewer, notes or None))
        st.success(f"recorded; {resp.get('queue_position', '?')} still pending")
    except Exception as exc:
        st.error(f"feedback failed: {exc}")
