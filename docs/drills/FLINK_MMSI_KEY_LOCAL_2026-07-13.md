# Flink malformed MMSI key hardening: local verification

Date: 2026-07-13 PDT

Scope: local source, packaging, and container checks only. No AWS command or
Managed Service for Apache Flink job was run.

## Defect and execution ordering

The production graph keyed each raw record with
`lambda raw: json.loads(raw)["mmsi"]`. Flink evaluates `key_by` before
`FeatureProcess.process_element`, so malformed JSON or an invalid MMSI could
raise before the process function reached `_quarantine`.

The graph now uses `mmsi_partition_key` with `Types.LONG()`. The selector and
the process function share a strict JSON-decoding, required-field-conversion,
and MMSI contract:

- accept an integer or ASCII digit string;
- require a value from 0 through 999,999,999;
- reject boolean or float MMSIs, signs, missing fields, out-of-range MMSIs, and
  invalid JSON;
- normalize decoder recursion failures from deeply nested JSON;
- normalize parser failures to `ValueError`;
- map invalid records to sentinel key `-1` so the process function can run.

`FeatureProcess` parses the record again. On failure it calls `_quarantine` and
returns before `_history.value()` or any state update. `_quarantine` always logs
the event and writes an envelope to S3 only when a quarantine bucket is
configured.

This change does not add full AIS semantic validation. A record with a valid
MMSI can still pass this parser with an out-of-range or non-finite coordinate,
negative SOG, or timezone-naive timestamp. That broader input-quality boundary
is outside finding 4 and remains a separate robustness concern.

## Focused source verification

```text
COVERAGE_FILE=/tmp/.coverage-flink-key .venv/bin/python -m pytest -q \
  streaming/flink/tests \
  --cov=flink.transforms --cov=flink.window_logic --cov-branch \
  --cov-fail-under=90 --cov-report=term-missing \
  --cov-report=xml:/tmp/harbormaster-flink-key-coverage.xml \
  --junitxml=/tmp/harbormaster-flink-key-focused-junit.xml
```

Result: 93 passed in 0.48 seconds. Combined line and branch coverage was
99.64%. The source transform copy had complete coverage; the packaged-runtime
copy reported 99% with one partial branch.

Artifacts:

- `/tmp/harbormaster-flink-key-focused-junit.xml`
- `/tmp/harbormaster-flink-key-coverage.xml`

The tests cover both parser copies, valid integer and string MMSIs, malformed
and out-of-range values, depth-10,000 nested JSON, selector source parity,
production graph wiring, and the return-before-state invariant.

## Deployable ZIP verification

`make flink-package` completed successfully. The resulting
`dist/flink-app.zip` contained exactly these members:

```text
main.py
requirements.txt
flink/__init__.py
flink/window_logic.py
lib/pyflink-dependencies.jar
```

The ZIP was then imported from `/tmp` with `python -S` and only the archive on
`PYTHONPATH`. The imported module path resolved inside the ZIP. A valid MMSI
returned `367000001`; malformed and depth-10,000 JSON each raised normalized
`ValueError` from `parse_ais_json` and returned sentinel `-1` from
`mmsi_partition_key`.

Artifacts:

- `/tmp/harbormaster-flink-key-package.log`
- `/tmp/harbormaster-flink-key-zip-members.log`
- `/tmp/harbormaster-flink-key-zip-import.log`

## Repository gates

The CI-equivalent source checks passed:

```text
ruff check: passed
ruff format --check: 222 files already formatted
Bandit: no issues identified
recorded replay fixture checksum: passed
pytest: 1002 passed, 20 skipped, 16 warnings in 11.87 seconds
repository line and branch coverage: 83.44%
```

Artifacts:

- `/tmp/harbormaster-flink-key-ruff.log`
- `/tmp/harbormaster-flink-key-format.log`
- `/tmp/harbormaster-flink-key-bandit.log`
- `/tmp/harbormaster-flink-key-fixture.log`
- `/tmp/harbormaster-flink-key-full-suite.log`
- `/tmp/harbormaster-flink-key-final-source-junit.xml`
- `/tmp/harbormaster-flink-key-final-source-coverage.xml`

The local serving production image also built and passed its CI runtime-import,
health, and scoring smoke checks. This standard repository gate does not
exercise the Flink artifact.

- `/tmp/harbormaster-flink-key-container-build.log`
- `/tmp/harbormaster-flink-key-container-smoke.log`

## Evidence boundary and residual risk

This run proves the local parser, selector, graph wiring, package contents, and
isolated packaged-runtime behavior. It does not prove live throughput,
backpressure recovery, task restart behavior, or S3 quarantine delivery.

All malformed records share sentinel key `-1`. They do not read or update keyed
state, but a sustained malformed-input burst can concentrate work in one key
group and create a hot partition. The W4 human-run window remains responsible
for live Flink backpressure evidence.
