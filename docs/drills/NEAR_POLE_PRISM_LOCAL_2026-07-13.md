# Near-pole prism local regression, 2026-07-13

## Scope

This was a local-only geometry reproduction and verification on macOS with
Python 3.12.11. No AWS command, deployed serving process, or live traffic was
used. The before probe ran at master commit
`f3478020bee116add9f6a60172ff7d45b5cef488` in detached worktree
`/tmp/harbormaster-polar-before`. The after probe ran on branch
`codex/prism-near-pole` before commit.

Raw console artifacts are retained outside the repository:

- `/Users/arunsharma/code/harbormaster-polar-artifacts/before_probe.txt`
- `/Users/arunsharma/code/harbormaster-polar-artifacts/after_probe.txt`
- `/Users/arunsharma/code/harbormaster-polar-artifacts/focused_coverage.txt`
- `/Users/arunsharma/code/harbormaster-polar-artifacts/full_gate.txt`
- `/Users/arunsharma/code/harbormaster-polar-artifacts/docker_smoke.txt`

## Domain contract

The kernel uses a small spherical azimuthal-equidistant projection centered on
the spherical midpoint of the active foci. Near-pole ellipse and MOBR requests
are supported only when the requested footprint does not contain or touch
either geographic pole. A containing or touching footprint raises exactly:

```text
prism footprint contains or touches a geographic pole
```

Antipodal focus pairs and pairs whose unit-vector sum is too small for a stable
spherical midpoint raise exactly:

```text
active foci are antipodal or numerically singular
```

The midpoint cutoff is `1e-6` on the focus unit-vector sum norm. Near an
antipode this norm is approximately the angular distance from exact antipodal
separation. The cutoff rejects pairs within about 6.37 m of that singularity
and limits midpoint roundoff amplification to approximately the millimeter
scale. This is a numerical-domain guard, not a claim that giant continental or
global ellipses are a good use of this local planar geometry.

## Before reproduction

The detached worktree was created with:

```bash
git worktree add --detach /tmp/harbormaster-polar-before \
  f3478020bee116add9f6a60172ff7d45b5cef488
```

The probe constructed thin, east-west 10 m by 0.1 m ellipses in both
hemispheres. The minor axis stayed away from the pole, so these were
non-containing footprints. It also inverse-projected a 10 m radial offset and
measured the result with the kernel's haversine function.

At latitude 89.9999 in both hemispheres, geometry remained finite, but the 10 m
radial offset measured only 9.666399144490 m. At latitude 89.99999, both
`ellipse_polygon()` and `mobr()` failed:

```text
ValueError: polygon spans 360 degrees or more
```

At that same latitude, the equirectangular inverse returned longitude
515.273324189 degrees for the 10 m offset, and the resulting point measured
only 2.172325174972 m from the center. The error was therefore in the local
projection, not in antimeridian normalization or pole containment.

The midlatitude control at a one-degree center produced these bounds before
the change:

```text
(1.986508121033, 0.995503391970, 2.013491878967, 1.004496608030)
```

## Implementation

The replacement projection uses these spherical operations:

1. Convert both foci to unit vectors and normalize their sum to obtain the
   spherical midpoint. Lift its longitude to the foci's continuous wrapped
   midpoint instead of forcing it into one canonical turn.
2. Forward-project with the azimuthal-equidistant central angle computed from
   a clamped haversine half-chord and a wrapped longitude delta.
3. Inverse-project with the spherical exponential map in a center/east/north
   basis. `atan2(z, hypot(x, y))` retains small pole clearances that an
   `asin(z)` inverse loses to rounding.
4. Preserve output longitude around the local reference, then lift sequential
   ring coordinates onto one continuous branch before antimeridian cutting.
5. Use wrapped haversine focus distance for feasibility and ellipse axes.
6. Express each geographic pole analytically in projected coordinates as
   `(0, R * (pole_latitude - center_latitude))`, rotate it into the ellipse's
   local axes, and test ellipse or MOBR containment inclusively before polygon
   sampling. The check therefore catches pole contact even between sample
   angles.
7. Resample a nondegenerate inverse-projected ellipse up to 4,096 points when a
   coarse ring is invalid. Densify each projected MOBR edge, then take its
   polygonal union with the sampled ellipse in continuous longitude space.
   The union conservatively repairs chord under-bounding while retaining the
   local metric rectangle. A 124-candidate rotation sweep produced 116 valid
   supported cases, eight expected pole-domain rejections, and no unexpected
   errors, invalid geometry, or bounds failures. Its largest numerical overlay
   sliver was `1.566772838107898e-09` of ellipse area, below the pinned `1e-8`
   tolerance.
8. Remove only consecutive seam coordinates equal within `1e-12` degrees,
   with relative tolerance disabled. Distinct centimeter-scale coordinates
   remain unchanged while numerical seam duplicates cannot invalidate a split
   ring. Zero-axis MOBRs skip densification and union so infeasible prisms keep
   finite, zero-area bounds.

## After verification

The same 10 m by 0.1 m footprints returned valid finite Polygons in both
hemispheres at latitudes 89.9999 and 89.99999. The 10 m radial probes measured:

```text
latitude  89.9999:  9.999999999643 m
latitude -89.9999:  9.999999999643 m
latitude  89.99999: 9.999999999621 m
latitude -89.99999: 9.999999999621 m
```

Exact antipodal foci and the near-singular pair separated by 179.99999 degrees
both produced the documented focus-domain error. North and south ellipse and
MOBR pole-contact probes all produced the documented footprint-domain error.
A separate one-centimeter-clearance regression passes and confirms the inverse
does not round a supported boundary onto latitude 90 degrees.

The after midlatitude bounds were:

```text
MOBR:    (1.986508102523, 0.995503364293, 2.013491897477, 1.004496608030)
ellipse: (1.986508121033, 0.995503391970, 2.013491878967, 1.004496608030)
```

Every coordinate remains within `5e-8` degrees of the pre-fix bounds. The
existing antimeridian cases, including exact positive/negative 180-degree and
noncanonical 540-degree seams, stay in the focused consumer suite.

## Focused regression and coverage

The focused command was:

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

Result: 75 passed. `space_time_prism.py` reached 90% line and branch coverage,
`gap_detector.py` reached 92%, and the combined result was 90.85%.

## CI-equivalent local gate

The repository gate was:

```bash
PY=/Users/arunsharma/code/harbormaster/.venv/bin/python
$PY -m ruff check serving streaming cdc lake mlops tests scripts infra/lambda
$PY -m ruff format --check serving streaming cdc lake mlops tests scripts infra/lambda
$PY -m bandit -q -c pyproject.toml -r serving streaming cdc lake mlops
PYTHONPATH=streaming $PY -c \
  "from replay.loader import verify_fixture; assert verify_fixture()"
PYTHONPATH=serving:streaming:tests:. $PY -m pytest -q \
  --cov --cov-report=term-missing --cov-report=xml
```

Ruff lint passed, all 223 files were formatted, Bandit exited zero, and the
replay fixture verified. The full suite passed with 1,094 passed, 20 skipped,
21 warnings, and 83.86% total line and branch coverage.

The first full run exposed a compatibility regression outside the focused
test set: the route-optimizer reward was
`0.7902652130125583` instead of its exact pinned value
`0.7902652130125524`. Its corridor graph imports this module's haversine
function. Unconditional modulo wrapping had perturbed an already canonical
longitude delta by floating-point roundoff. The final wrapper preserves inputs
already in `[-pi, pi]` bit-for-bit and wraps only out-of-range deltas. Both
pinned reward tests then passed, and the full gate above was rerun from a fresh
process.

## Local serving Docker smoke

The local-only smoke was:

```bash
docker build -f serving/Dockerfile -t harbormaster-serving:polar .
docker run --rm -d --name hm-serving-polar \
  -p 18080:8000 harbormaster-serving:polar
curl --fail --silent --show-error http://127.0.0.1:18080/healthz
curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"mmsi":367999999,"fix":{"lat":89.9999,"lon":0.0,"t":"2026-07-13T12:00:00.100000Z"},"history":[{"lat":89.9999,"lon":0.0,"t":"2026-07-13T12:00:00Z"}],"domain":"vessel"}' \
  http://127.0.0.1:18080/v1/score-ais
docker stop hm-serving-polar
```

The image built successfully. Health returned
`{"status":"ok","version":"0.1.0"}`. The near-pole request exercised the
prism path at latitude 89.9999 and returned HTTP 200 with `n_history=1` and a
locally measured response field of `latency_ms=4.179415999999492`. The
container was stopped and removed; no matching container remains.

## Evidence boundary

This closes the local near-pole projection defect and pins the unsupported pole
and antipodal boundaries. It does not establish deployed latency, Managed
Flink behavior, AWS integration, or numerical suitability for a global-scale
footprint. Geometry that contains or touches a pole remains deliberately
unsupported and fails before GeoJSON construction.
