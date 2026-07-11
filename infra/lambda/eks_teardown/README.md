# EKS teardown guard Lambda (Phase 5, gate 5.0)

Source for the Lambda deployed by `infra/terraform/modules/eks_teardown_guard`,
packaged exactly like `infra/lambda/teardown` (the Phase 0 nightly teardown):
`data "archive_file"` zips this directory as-is, boto3 comes from the Lambda
runtime, nothing is bundled.

Why it exists: the EKS control plane is the only Phase 1-5 compute surface
whose idle cost cannot be scaled to zero (a flat ~$73/mo per-cluster charge
that bills whether or not any node or pod runs). Every other phase's cost
discipline is "flip the toggle back after the demo", which is procedural and
has already failed once this project (Phase 2's MSK Serverless risk). This
guard is structural: a recurring EventBridge Scheduler schedule re-evaluates
the cluster's age every run and force-destroys the node groups, then the
cluster, once `MAX_AGE_HOURS` (default 4) has elapsed, unless the cluster's
`KeepAliveUntil` tag holds a future ISO 8601 timestamp.

Decision function (pure, boundary-tested in `test_handler.py`):

    should_teardown(created_at, keep_alive_until, now, max_age_hours)

Failure posture: an absent, empty, or unparseable `KeepAliveUntil` grants no
extension; an unparseable `MAX_AGE_HOURS` falls back to the 4-hour default.
The guard always fails toward teardown, never toward an immortal control
plane. EKS refuses `DeleteCluster` while node groups exist, so a run deletes
node groups first and the recurring schedule converges the cluster delete on
a later run; no waiter is held inside one invocation.

Test locally (no AWS, no credentials):

    python -m pytest infra/lambda/eks_teardown/test_handler.py -q
