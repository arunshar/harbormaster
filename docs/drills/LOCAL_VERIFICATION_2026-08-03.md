# Local verification, 2026-08-03

## Scope

This record supports the documentation-only honesty and status refresh based on
commit `7c37e56f1c2dad9462148c922405a567a5b4fbf4`. No live AWS command was run for
this verification, and no cloud behavior is inferred from these local results.

## Test and coverage result

Command, matching the coverage invocation in `.github/workflows/serving-ci.yml`:

```bash
.venv/bin/python -m pytest -q --cov --cov-report=term-missing --cov-report=xml
```

Observed result:

```text
1110 passed, 20 skipped, 21 warnings
Line coverage: 85.23%
Branch coverage: 77.46%
Combined coverage: 83.86%
Required coverage: 80.0%
```

The percentages come from the generated local `coverage.xml`. That XML is
intentionally ignored; this tracked record preserves the measured summary and
the exact command without treating a generated artifact as durable evidence.

## Additional local checks

```text
make serve-test: passed, 1110 passed and 20 skipped
make serve-lint: passed
make validate: passed
make flink-package: passed after Docker Desktop was started
Flink package required-member check: all five members present
git diff --check: passed
```

The Flink package check verifies only local build completeness. W4 must create a
fresh package and checksum in its own timestamped evidence directory before any
live AWS step.
