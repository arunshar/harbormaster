# Runbook: Wave 5 signed serving load and soak

Status: tool authored and tested locally. No live load or soak has been run from
this implementation. Every result field remains evidence from the specific run
that produced its artifact directory. A local test result is not AWS behavior.

This runbook is for a future Arun-run AWS window after W4 returns to a known safe
resting state. The load command sends signed POST requests to the live scoring
route, can incur AWS cost, and may enqueue one or more HITL rows before an
unsafe response can be observed. The maximum is bounded by the in-flight cap.
Codex prepares and reviews the command, but Arun pastes and runs it in the
authenticated terminal.

## 1. What the tool measures

`scripts/loadtest_signed_serving.py` sends one frozen, kinematically boring AIS
request through the exact regional API Gateway `/v1/score-ais` route.

It records three distinct latency surfaces:

- Scheduled-to-completion latency: time from the intended open-loop arrival to
  the validated response. This is the goodput latency surface and includes
  scheduler lag.

- Client latency: elapsed wall time around the signed HTTP request. This includes
  signing, network, API Gateway, integration, and serving time after the worker
  starts.
- Server latency: the service's validated `latency_ms` response field. This is
  the scoring path's server-reported latency.

The tool does not call either surface a measured cost. Cost per valid inference
requires a separate billing artifact for the same time window and a later
reconciliation step.

The workload is one fixed request, identified as `w5-boring-fixed-v1` and copied
into every artifact directory. It is suitable for stable capacity comparisons.
It is not a representative AIS distribution or a model-quality benchmark.

## 2. Measurement contract

- Arrival model: open loop with absolute monotonic deadlines.
- Retry policy: none. One scheduled request causes at most one HTTP attempt.
- Rate bound: at most 50 requests per second, matching the committed API Gateway
  steady-state throttle.
- In-flight bound: at most 100 client requests.
- Process bound: the supported live CLI always creates a parent supervisor and
  passes the child a one-use inherited pipe grant. A forged ambient environment
  variable is not sufficient. The parent sends SIGTERM at the monotonic
  graceful deadline and SIGKILL at the hard deadline if needed. Parent loss is
  also observed through pipe EOF by the child.
- Configured-time bound: one shared equation covers a 60-second source and
  read-only ownership reserve, the signed preflight timeout, all phases,
  per-request-phase drain detection, a 30-second normal sealing reserve, and
  the termination grace. It must fit within four hours and before the cutoff.
- Request bound: at most 100,000 client requests including the signed preflight,
  with a lower explicit cap required on every command.
- URL bound: exact regional HTTPS execute-api host and exact
  `/v1/score-ais` path. Userinfo, ports, query strings, fragments, wrong regions,
  alternate hosts, and redirects are rejected.
- Identity: only `us-east-1` is accepted. Account `645322802947`, an assumed
  `harbormaster-platform` role, the Terraform-owned
  `harbormaster-base-serving-api` name and tags, and exactly one
  `POST /v1/score-ais` route protected by `AWS_IAM` are checked read-only before
  any scoring POST. The control-plane checks use explicit official STS and API
  Gateway endpoints.
- Source: clean worktree, reviewed Git HEAD, and exact SHA256 values for the
  harness, shared response validator, and serving request model.
- Credentials: fresh SigV4 credentials and timestamp for every attempt. Frozen
  credentials are never cached by the harness. Proxy, CA, and AWS endpoint
  override variables are rejected. Configured endpoint URLs are ignored, and
  the scoring request uses an opener with proxies disabled.
- Response contract: HTTP 200, matching MMSI, valid score and confidence,
  valid reasons, a 32-character lowercase hexadecimal trace ID, and bounded
  server latency.
- Non-stateful envelope: `hitl_required=false` and an empty reason-code list.
  The preflight must satisfy it. Any measured response outside it stops further
  scheduling and invalidates the run.
- Response size: at most 64 KiB. The event ledger is capped at 128 MiB.
- Warmup: retained in raw evidence and excluded from trial summaries according
  to scheduled phase, regardless of completion time.
- Cold starts: unsupported by this profile. The signed safety preflight occurs
  first, so every reported trial is explicitly prewarmed.
- Percentiles: R-7 linear interpolation at `q*(n-1)`, the same arithmetic used
  by the existing local score benchmark.
- Good request: started, HTTP 200, full response contract passed, matching MMSI,
  safe non-HITL envelope, and scheduled-to-completion latency at or below the
  explicitly recorded threshold.
- Goodput denominator: every scheduled measured request, including a request the
  client could not start because of schedule lag or the in-flight cap.
- Evidence validity and performance outcome are separate. A fully captured SLO
  breach is valid evidence with `targets_met=false`.

The client does not send a tenant header. Tenant selection is deployment-level
in the current service. The artifact proves local request IDs, echoed MMSI, and
uniqueness across every observed contract-valid service trace ID from preflight,
warmup, and measured trials. It does not prove request-scoped tenant identity.

The transport-injection seam used by offline regression tests is not a live
invocation path and does not support a live-behavior claim. The production
signed transport itself requires the active inherited supervisor grant, so a
wrapper around that function cannot turn the offline seam into a scoring call.

## 3. Artifact contract

The `--artifact-dir` path must not exist. The tool creates it with mode `0700`
and refuses to overwrite it. Its files use mode `0600`:

- `run-spec.json`: normalized controls, verified target ownership, reviewed
  source hashes, supervisor claim binding, workload hash, Python and platform
  data, and the no-live-claim contract.
- `workload.json`: exact canonical request bytes used for signing.
- `events.jsonl`: append-only, one canonical JSON event per line, with strictly
  increasing event sequence numbers.
- `summary.json`: terminal status, validity, gates, accounting, client and server
  distributions, trial variation, and explicit uncollected billing fields.
- `evidence-files.sha256`: checksum manifest over the four evidence files.
- `failure.json`: present only when terminal ledger persistence fails. It marks
  the run invalid and is included in the checksum manifest.

Before the child starts, the supervisor exclusively creates immutable sibling
files named `<artifact-dir>.supervisor-claim.json` and
`<artifact-dir>.supervisor-claim.sha256`. The claim binds the run UUID, absolute
artifact path, cutoff, target API, reviewed commit, and reviewed source hashes.
The run specification carries the claim ID and digest.

If the process supervisor intervenes or completed evidence does not match that
claim, it writes sibling files named
`<artifact-dir>.supervisor-stop.json` and
`<artifact-dir>.supervisor-stop.sha256`. A supervisor stop always means
`valid_for_measurement=false`. The stop verdict binds the same claim and
absolute artifact path. It never manufactures a successful summary.

After the child exits and the parent validates the claim, run specification,
summary, and internal checksum manifest, the parent exclusively writes
`<artifact-dir>.supervisor-complete.json` and
`<artifact-dir>.supervisor-complete.sha256`. This is the only positive terminal
supervisor verdict. A summary and claim without a checksum-valid complete
verdict are not acceptable measurement evidence. Complete and stop verdicts
are mutually exclusive.

No request headers, credentials, environment variables, raw exception strings,
or response bodies are written to these files.

## 4. Preconditions for any live run

Do not run this tool during Recovery4, during W4 creation or cleanup, while a
Terraform writer is active, near the nightly teardown sweep, or from an expired
session.

The future operator window must establish all of these first:

1. W4 is at its documented safe resting state.
2. The `$75/month` budget and automatic freeze action are active.
3. The wet nightly teardown guard is configuration-matched.
4. The serving route is intentionally pinned to the target under test.
5. No Terraform writer or state lock is active.
6. The authenticated caller and session expiry are recorded.
7. The complete load, observation, rollback, and cleanup window fits before the
   nightly sweep.
8. `master` is clean and the harness commit is the reviewed commit. Copy the
   reviewed Git and source SHA256 values from the independently reviewed plan
   package. Do not calculate replacement expected values during the live window.
9. A one-request signed preflight is acceptable. The tool performs it before
   scheduling load and stops if it fails or requests HITL.
10. An absolute UTC cutoff satisfies the recorded shared equation for read-only
    guards, preflight, phases, drains, normal sealing, and termination grace.

Any failure above is a STOP. Do not weaken a guard, extend a cutoff in place, or
reuse an artifact directory.

## 5. Proposed bounded load command

These parameters define a proposed first production load run. They are not a
record of an executed run:

- Warmup: 60 seconds at 20 requests per second.
- Three measured trials: 300 seconds each at 20 requests per second.
- Cooldown: 60 seconds between trials.
- Client in-flight cap: 20.
- Per-request timeout: 5 seconds.
- Drain detection threshold: 10 seconds. It invalidates measurement and stops
  new scheduling. The outer process supervisor is the hard deadline.
- Maximum scheduled-to-completion latency for goodput: 1,000 ms. This is an
  explicit run-level end-to-end threshold, not the server kernel's separate
  300 ms p95 target.
- Minimum valid success ratio: 99.9%.
- Minimum goodput ratio: 99.0%.
- Planned client requests: 19,201 including preflight, below the explicit 20,000
  cap.

Arun runs this only in the approved future window:

```bash
cd /Users/arunsharma/code/harbormaster

W5_RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
W5_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
W5_ARTIFACT_DIR="artifacts/w5/${W5_STAMP}-signed-load"
W5_SCORE_URL="${SERVING_API_URL%/}/v1/score-ais"
: "${W5_API_ID:?copy from the reviewed Wave 5 plan package}"
: "${W5_REVIEWED_GIT_HEAD:?copy from the reviewed Wave 5 plan package}"
: "${W5_HARNESS_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_WINDOW_LOGIC_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_MODELS_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_OPERATOR_CUTOFF_UTC:?set the reviewed absolute UTC cutoff}"

.venv/bin/python scripts/loadtest_signed_serving.py \
  --kind load \
  --api-url "$W5_SCORE_URL" \
  --region us-east-1 \
  --expected-api-id "$W5_API_ID" \
  --expected-git-head "$W5_REVIEWED_GIT_HEAD" \
  --expected-harness-sha256 "$W5_HARNESS_SHA256" \
  --expected-window-logic-sha256 "$W5_WINDOW_LOGIC_SHA256" \
  --expected-models-sha256 "$W5_MODELS_SHA256" \
  --operator-cutoff-utc "$W5_OPERATOR_CUTOFF_UTC" \
  --run-id "$W5_RUN_ID" \
  --artifact-dir "$W5_ARTIFACT_DIR" \
  --workload bench/fixtures/wave5_score_request.json \
  --target-rps 20 \
  --max-in-flight 20 \
  --warmup-seconds 60 \
  --trial-seconds 300 \
  --trials 3 \
  --cooldown-seconds 60 \
  --request-timeout-seconds 5 \
  --drain-timeout-seconds 10 \
  --goodput-max-scheduled-response-ms 1000 \
  --max-schedule-lag-ms 100 \
  --max-total-requests 20000 \
  --minimum-success-ratio 0.999 \
  --minimum-goodput-ratio 0.99 \
  --confirm-live 'RUN SIGNED SERVING LOAD'
```

The script exits:

- `0`: terminal evidence is valid and all configured targets passed.
- `1`: a run failed, evidence is invalid, or configured targets were not met.
- `2`: operator configuration error, including artifact collision.
- `124`: the process supervisor intervened at the reviewed cutoff. The sibling
  supervisor-stop artifact is the controlling invalid verdict.
- `130`: interrupted run. Partial evidence is sealed when local storage permits.

The event ledger persists `preflight_attempt_started` before dispatch. If the
client is interrupted before the response outcome is known, the summary records
`attempted=true`, `client_outcome_known=false`, and `outcome=unknown`. Attempted
means client dispatch began; it does not prove the service processed the call.

An exit code of `1` with `valid_for_measurement=true` can be a truthful measured
target breach. Do not rerun simply to obtain a green result. Preserve and review
the first valid canonical run.

## 6. Proposed bounded soak command

Run the soak only in a separately reviewed window with at least one hour plus
preflight, warmup, evidence review, rollback, and cleanup margin. The proposed
profile is 10 requests per second for one hour after a 60-second warmup. It
schedules 36,601 client requests including preflight under a 40,000 cap.

```bash
cd /Users/arunsharma/code/harbormaster

W5_RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
W5_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
W5_ARTIFACT_DIR="artifacts/w5/${W5_STAMP}-signed-soak"
W5_SCORE_URL="${SERVING_API_URL%/}/v1/score-ais"
: "${W5_API_ID:?copy from the reviewed Wave 5 plan package}"
: "${W5_REVIEWED_GIT_HEAD:?copy from the reviewed Wave 5 plan package}"
: "${W5_HARNESS_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_WINDOW_LOGIC_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_MODELS_SHA256:?copy from the reviewed Wave 5 plan package}"
: "${W5_OPERATOR_CUTOFF_UTC:?set the reviewed absolute UTC cutoff}"

.venv/bin/python scripts/loadtest_signed_serving.py \
  --kind soak \
  --api-url "$W5_SCORE_URL" \
  --region us-east-1 \
  --expected-api-id "$W5_API_ID" \
  --expected-git-head "$W5_REVIEWED_GIT_HEAD" \
  --expected-harness-sha256 "$W5_HARNESS_SHA256" \
  --expected-window-logic-sha256 "$W5_WINDOW_LOGIC_SHA256" \
  --expected-models-sha256 "$W5_MODELS_SHA256" \
  --operator-cutoff-utc "$W5_OPERATOR_CUTOFF_UTC" \
  --run-id "$W5_RUN_ID" \
  --artifact-dir "$W5_ARTIFACT_DIR" \
  --workload bench/fixtures/wave5_score_request.json \
  --target-rps 10 \
  --max-in-flight 10 \
  --warmup-seconds 60 \
  --trial-seconds 3600 \
  --trials 1 \
  --cooldown-seconds 0 \
  --request-timeout-seconds 5 \
  --drain-timeout-seconds 10 \
  --goodput-max-scheduled-response-ms 1000 \
  --max-schedule-lag-ms 100 \
  --max-total-requests 40000 \
  --minimum-success-ratio 0.999 \
  --minimum-goodput-ratio 0.99 \
  --confirm-live 'RUN SIGNED SERVING LOAD'
```

The soak summary adds 60-second buckets. Use them to identify time-dependent
latency, success, or client-capacity drift. Do not reduce the full raw event
ledger to one pooled percentile during review.

## 7. Immediate post-run verification

Do not start another trial until the first artifact is independently reviewed.

```bash
cd /Users/arunsharma/code/harbormaster

(cd "$W5_ARTIFACT_DIR" && shasum -a 256 -c evidence-files.sha256)
(cd "$(dirname "$W5_ARTIFACT_DIR")" && \
  shasum -a 256 -c "$(basename "$W5_ARTIFACT_DIR").supervisor-claim.sha256")
(cd "$(dirname "$W5_ARTIFACT_DIR")" && \
  shasum -a 256 -c "$(basename "$W5_ARTIFACT_DIR").supervisor-complete.sha256")

jq '{
  status,
  stop_reason,
  valid_for_measurement,
  targets_met,
  verdict,
  accounting,
  client_request_identity,
  trace_identity,
  performance_gates,
  pooled_measured_trials,
  trial_variation,
  billing
}' "$W5_ARTIFACT_DIR/summary.json"
```

Required integrity conditions:

1. Every checksum reports `OK`.
2. Exactly one terminal supervisor verdict exists. A candidate measurement
   requires the checksum-valid complete verdict and no stop verdict.
3. Event sequence numbers are contiguous from 1.
4. Planned and observed request accounting match.
5. Request IDs are unique. Every observed service trace ID across preflight,
   warmup, and measured trials is unique.
6. Each measured trial is fully accounted.
7. `billing.status` remains `not_collected` until a separate billing artifact is
   captured and reconciled.
8. No claim is copied into `docs/HONESTY.md` or the audit document before the
   artifact, target state, and time window are independently reviewed.

## 8. Stop conditions

Stop the live window and preserve evidence on any of these:

- Identity, budget, teardown, route, or cutoff mismatch.
- Hidden credential prompt or expired credentials.
- Unexpected target URL or redirect.
- Failed or non-boring signed preflight, including any HITL request or reason.
- Artifact collision, write failure, checksum failure, or noncontiguous events.
- Response-contract failure or duplicate trace ID.
- Schedule-lag or client-overload drops.
- Drain timeout, supervisor intervention, signal, or internal failure.
- Any AWS, Terraform, Kubernetes, or Flink action outside the separately reviewed
  operator sequence.

Target failure is not permission to raise rate, duration, concurrency, or cost.
Review the evidence, restore the documented serving state, complete cleanup, and
schedule any follow-up as a new bounded run with a new UUID and artifact path.
