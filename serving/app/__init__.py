"""Harbormaster serving plane.

The deterministic AIS anomaly-scoring front door. The geometric kernel and the
deterministic agents are vendored from the GeoTrace-Agent reuse anchors named in
docs/phases/PHASE_1.md; the LLM planner and summarizer are replaced by a
deterministic HeuristicPlanner and a fixed scoring fusion so the live path costs
zero tokens. Heavy models (Pi-DPM) are trained on MSI and promoted in later;
here the gap scorer uses the numpy surrogate.
"""

__version__ = "0.1.0"
