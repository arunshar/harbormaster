# W4 Recovery4 Terraform state comparison, 2026-08-05

## Outcome

Recovery4 stopped on a local false-positive state comparison, not on a changed Terraform resource, output, serial, lineage, or check result. The single-use package remains failed and consumed because it stopped before its later state-object, inventory, and readiness gates.

No TOTP, Terraform plan, Terraform mutation, or AWS mutation occurred. The failure artifact records `line=761`, `status=1`, `totp_requested=false`, `terraform_plan_run=false`, `terraform_mutation_run=false`, and `aws_mutation_run=false`.

## Root cause

The helper serialized the pinned S3 state object and `terraform state pull` result with `jq -S -c`, then used `cmp`. The `-S` option sorts JSON object keys but preserves array order. Terraform emitted the same 34 `check_results` records in a different outer-array order, so the exact byte comparison failed before the helper reached its later deterministic state fingerprint.

This behavior was already documented in `docs/drills/W4_STAGE1_PARTIAL_APPLY_2026-08-04.md`. Earlier recovery code sorted `check_results` by `config_addr` and nested `objects` by `object_addr`, but Recovery4's earlier exact comparison omitted that normalization.

## Local forensic evidence

The captured states both reported state format 4, Terraform 1.15.6, serial 69, lineage `419a8985-87a0-4470-0b20-25f2ef23f7d4`, 28 outputs, 157 resources, and 34 check-result groups. All 34 groups occupied different array indexes, but their address-keyed content was identical.

The tracked comparator was executed locally against the exact ignored Recovery4 state files. It wrote the mode-600 hash-only report at:

```text
artifacts/w4/20260805T080819Z-state-comparator-final3/comparison.json
```

The report contains no Terraform state values:

| Field | Pinned S3 object | `terraform state pull` |
|---|---|---|
| Raw SHA-256 | `3457cbcfeddfcddb4d4574ff55e794d25d53e0733ae73c78b24a5e3686f4e3b9` | `3dc373edbd280e5b98d1f1281ba62327c82426bbf24d1891d51282c72fa0a445` |
| Check-result groups | 34 | 34 |
| Nested check objects | 33 | 33 |
| Normalized SHA-256 | `8a4223242bffeabccea39b73a87ba88b911397cdcb3217a9cb3884e073ba1262` | `8a4223242bffeabccea39b73a87ba88b911397cdcb3217a9cb3884e073ba1262` |

The normalized states are equivalent. Deliberate local changes to serial, lineage, resources, outputs, check status, object status, membership, addresses, `null` versus `[]`, and unrelated array order all remain mismatches.

## Fix

`scripts/compare_terraform_state.py` implements a strict Terraform-state-v4 comparison:

1. Parse decimal numbers losslessly and reject duplicate JSON keys, non-finite numbers, non-object roots, incomplete or mistyped Terraform-v4 top-level state, malformed check collections, missing addresses or statuses, and duplicate addresses.
2. Sort only the known order-insensitive `check_results` and nested `objects` collections by their unique addresses.
3. Preserve `objects: null` versus `objects: []` and every other state value, type, field, and array order.
4. Compare the full normalized documents in memory.
5. Write only raw hashes, normalized hashes, counts, an algorithm identifier, and a reason code to a mode-600 report.
6. Return 0 for equivalent states, 1 for valid but different states, and 2 for malformed input or an unsafe invocation.

The committed sanitized witness compactly records the exact two `check_results`
address orders, their shared address-to-object/status records, and provenance
hashes. Its local-only provenance test reconstructs both projections and requires
exact equality with the ignored captures. The fixture excludes state resources,
outputs, attributes, and values.

## Regression evidence

All evidence below is stored under the mode-700 directory
`artifacts/w4/20260805T080819Z-state-comparator-final3`. Each file is mode 600,
and `evidence-files.sha256` binds the complete set. The comparator source SHA-256
is `6481fb8a7a7e4a0eec9f92f3873b478c50d6cb57f0342b7f6833ac71b8d3df07`;
the test source SHA-256 is
`32bed8c37000a10570d5b85d0ec3fb51460f5330a0c8faea9765e2dddf6c8f86`.

The focused local run with the exact ignored Recovery4 pair supplied passed
(`focused-exact-capture.log`):

```text
87 passed in 0.14s
```

The fresh-checkout form, which exercises the sanitized witness but not ignored
state files, passed (`focused-fresh.log`):

```text
86 passed, 1 skipped in 0.11s
```

The one skip is the explicit local-only full-state capture check. All committed
comparator regression cases and the sanitized 34-record Recovery4 permutation
run in the fresh-checkout path used by CI.

The changed comparator module reached 98.50% combined line and branch coverage
in that fresh-checkout run (`coverage.log`).

The full local gates also passed:

```text
make serve-lint: ruff check passed; 226 files already formatted
make serve-test: 1200 passed, 28 skipped, 21 warnings in 6.33s
```

The corresponding logs are `serve-lint.log` and `serve-test.log`. Empty
`bandit.log` and `py-compile.log` files record successful no-output runs.

## Remaining boundary

Recovery4 did not produce `state-object-after-head.json`, `state-summary.json`, `recovery4-readonly-verdict.json`, `recovery4-readonly-checkpoint.json`, or `evidence-files.sha256`. It is not a successful checkpoint and must not be edited, retried, or reinterpreted.

After this fix is merged with green CI, prepare a fresh checksum-bound Recovery5 package. Copy the tracked comparator into that package, include it in the input manifest, keep every Version ID, ETag, serial, lineage, backend-lock, before/after/final metadata, inventory, budget, and nightly-sweep gate, and independently review the package before any live read-only run. Any later Terraform or AWS mutation remains human-run.
