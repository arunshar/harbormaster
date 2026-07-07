# CorridorDeviationDetector: design and grounding

The third deterministic agent in the Phase 1 scoring path. This doc is the tracked,
IP-safe design reference; any raw internship analysis stays local-only under
`docs/internship/` per `.gitignore`, and `docs/HONESTY.md` carries the framing.

## Honesty framing (read first)

Per `docs/HONESTY.md`: the original maritime corridor / sea-lane deviation work,
including the production waypoint and route artifacts, belongs to ESRI and is not
reproduced, copied, or claimed here. Harbormaster's corridor graph is a **clean,
personal reimplementation** built from public references (NOAA ENC charts and a
one-time MarineCadastre extract) for demonstration. The committed
`serving/app/artifacts/corridors.json` is a small, synthetic demo graph for the
New York / New Jersey approaches, not an ESRI deliverable. No ESRI code, data, or
infrastructure is used or merged.

## What the agent does

A vessel can be physically plausible (passes the speed and gap checks) yet still
behave anomalously by leaving the established sea-lane or turning sharply where no
turn is expected. The CorridorDeviationDetector runs the GTRA association test
against the static corridor graph and emits two reasons into the same fusion +
HITL path as the gap and speed signals:

- `off_corridor`: the current fix's perpendicular distance to the nearest sea-lane
  edge exceeds `off_corridor_threshold_m` (2 km). Severity scales linearly to 1.0
  at `corridor_saturation_m` (6 km).
- `unexpected_node`: a course change larger than `unexpected_node_heading_deg`
  (45 deg) occurs farther than `waypoint_radius_m` (5 km) from any expected
  waypoint node (course changes near a waypoint are normal routing).

Both are inline CPU over a read-only artifact loaded once at startup, so there is
no new always-on cost.

## The artifact

`serving/app/artifacts/corridors.json` is a frozen GTRA-style graph:
- `lanes`: sea-lane polylines (lon, lat node lists). The demo has one NE approach lane.
- `waypoints`: the expected course-change nodes (the lane nodes double as waypoints).

The production artifact is built offline from NOAA ENC charts plus a one-time
MarineCadastre extract and loaded read-only from the S3 model bucket; the demo
artifact is checked in so the slice runs offline. The recorded fixture's
off-corridor vessel (MMSI 367000003) runs ~10 km off this lane and is the
documented `off_corridor` golden case in `streaming/fixtures/expectations.json`.

## Geometry

Distances use a local equirectangular projection centered on the lane centroid
(Euclidean to first order over the demo region). The off-corridor test is the
point-to-segment perpendicular distance to the nearest lane edge; the
unexpected-node test compares the course-over-ground of the last two segments.
For continental-scale corridors, switch to a UTM zone (pyproj), mirroring the
note in `space_time_prism.py`.

## Status of the PHASE_1.md precondition (c)

Precondition (c) ("the internship-contents reveal is folded in or explicitly
deferred") is satisfied: the corridor add-on is the folded-in contribution,
reimplemented cleanly and honestly per the framing above. Preconditions (a)
Ray/rate submission and (b) the AWS account setup (gate G0) remain owner tasks,
unchanged by this slice, which is entirely local and incurs no AWS cost.
