# Antimeridian prism local regression, 2026-07-13

## Scope

This was a local-only reproduction and verification on macOS. No AWS command,
deployed service, or live behavior was exercised. The before probe used master
commit `39f3168028576f4c4b12169179089d3623a050c6` in a detached temporary
worktree. The after probe used branch `codex/prism-antimeridian` before commit.

Raw local outputs are retained outside the repository at
`/Users/arunsharma/code/harbormaster-antimeridian-artifacts`.

## Before reproduction

The detached worktree was created with:

```bash
git worktree add --detach /tmp/harbormaster-antimeridian-before \
  39f3168028576f4c4b12169179089d3623a050c6
```

The probe constructed two two-hour prisms at 20 m/s, projected their foci,
called `ellipse_polygon()`, and called the old gap distance helper. It ran with:

```bash
PYTHONPATH=/tmp/harbormaster-antimeridian-before/serving \
  /Users/arunsharma/code/harbormaster/.venv/bin/python - <<'PY'
import math
from datetime import UTC, datetime, timedelta
from app.agents.gap_detector import GapDetectorAgent
from app.components.space_time_prism import Prism
from app.models import Anchor, AnchorPair, SpeedBounds

now = datetime(2024, 6, 1, tzinfo=UTC)
for start, end in ((179.9, -179.9), (180.0, -180.0)):
    pair = AnchorPair(
        a=Anchor(lat=0.0, lon=start, t=now),
        b=Anchor(lat=0.0, lon=end, t=now + timedelta(hours=2)),
    )
    prism = Prism.compute(pair, SpeedBounds(v_max_mps=20.0))
    ax, ay = prism.proj.to_xy(pair.a.lat, pair.a.lon)
    bx, by = prism.proj.to_xy(pair.b.lat, pair.b.lon)
    geometry = prism.ellipse_polygon()
    print(start, end, prism.feasible, math.hypot(bx - ax, by - ay),
          geometry.geom_type, geometry.is_valid)

pair = AnchorPair(
    a=Anchor(lat=0.0, lon=179.9, t=now),
    b=Anchor(lat=0.0, lon=-179.9, t=now + timedelta(hours=2)),
)
print(GapDetectorAgent._euclidean_anchor(pair))
PY
```

Observed output:

```text
179.9 -> -179.9: feasible=False, projected_m=40007934.606712, type=Polygon, valid=False
180.0 -> -180.0: feasible=False, projected_m=40030173.592041, type=Polygon, valid=False
gap_distance_m=40007934.606712
```

The old implementation therefore took the long path around the planet and
emitted invalid seam-crossing polygons.

## After verification

The same focus and topology probe, plus noncanonical seams at longitudes 540
and -540 degrees, produced:

```text
179.9 -> -179.9: feasible=True, projected_m=22238.985329, type=MultiPolygon, valid=True, ccw=True
180.0 -> -180.0: feasible=True, projected_m=0.000000, type=MultiPolygon, valid=True, ccw=True
center=540: type=MultiPolygon, valid=True, ccw=True
center=-540: type=MultiPolygon, valid=True, ccw=True
```

The focused regression and coverage command was:

```bash
PYTHONPATH=serving:streaming:tests:. \
  /Users/arunsharma/code/harbormaster/.venv/bin/python -m pytest \
  serving/tests/test_space_time_prism.py \
  serving/tests/test_gap_detector_pidpm.py \
  serving/tests/test_rendezvous.py \
  serving/tests/test_orchestrator_pidpm_wiring.py \
  --cov=app.components.space_time_prism \
  --cov=app.agents.gap_detector \
  --cov-branch --cov-report=term-missing --cov-fail-under=90 -q
```

Result: 32 passed. The two changed modules reached 90.25% combined line and
branch coverage. The percentage includes the final polygonal-result filter,
whose extra GeometryCollection and non-area branches lowered the earlier
intermediate percentage while keeping the changed-module gate above 90%.

The CI-equivalent local gate was:

```bash
PY=/Users/arunsharma/code/harbormaster/.venv/bin/python
$PY -m ruff check serving streaming cdc lake mlops tests scripts infra/lambda
$PY -m ruff format --check serving streaming cdc lake mlops tests scripts infra/lambda
$PY -m bandit -q -c pyproject.toml -r serving streaming cdc lake mlops
PYTHONPATH=streaming $PY -c \
  "from replay.loader import verify_fixture; assert verify_fixture()"
$PY -m pytest -q --cov --cov-report=term-missing --cov-report=xml
```

Result: Ruff lint and format passed, Bandit found no issue, the fixture checksum
passed, and the full suite passed with 1,051 passed, 20 skipped, and 83.64%
total line and branch coverage. The local serving image built successfully;
runtime imports, `/healthz`, and a score request also passed.

## Boundaries

Ordinary geometry remains a Polygon. Geometry cut at an antimeridian seam is an
externally visible MultiPolygon with longitudes in `[-180, 180]` and RFC 7946
winding. Prism intersections retain only positive-area polygonal regions;
boundary-only Point or LineString contact returns an empty Polygon instead of
escaping the declared API type. This contract is pinned by a point-touch
regression, and the dynamic-merge regression executes a real two-ellipse union.
This change does not claim near-pole projection support; that remains a separate
hardening item.
