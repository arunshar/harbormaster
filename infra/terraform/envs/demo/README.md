# envs/demo

The `demo` environment is the short-lived, stand-up-then-tear-down variant of
Harbormaster used to show the platform live (for example during an interview or
a walkthrough) without leaving anything running afterward. Phase 0 does not ship
a full `demo` root yet; this directory documents the intended shape so the
naming and conventions stay consistent with `envs/base`.

## How `demo` differs from `base`

Same three modules (`network`, `state_stores`, `finops`), wired the same way,
with these differences:

- `environment = "demo"`. Every resource name and the common `Environment` tag
  carry `demo`, so `base` and `demo` resources never collide and cost can be
  filtered per environment.
- The FinOps guardrails apply unchanged: the $30 soft budget, the $75 hard cap
  with the IAM deny action, the Cost Explorer anomaly monitor, and the nightly
  teardown Lambda. A demo is exactly when an idle, forgotten streaming job is
  most likely, so the teardown sweep matters more here, not less.
- `teardown_dry_run = false` is the expected setting once trusted, so the
  nightly sweep actually stops lingering workloads.
- `enable_nat` stays `false`. A demo has no reason to pay for NAT.
- State stays in the LOCAL backend. A demo is ephemeral; there is no reason to
  migrate its state to S3.

## Shared conventions (identical to `base`)

- Variables: `project` (default `harbormaster`), `environment` (`demo` here),
  `aws_region` (default `us-east-1`), `platform_role_name`, `alert_email`.
- Common tags on every resource:
  `{ Project = var.project, Environment = var.environment, ManagedBy = "terraform" }`.
- Provider pins come from `infra/terraform/versions.tf`: `aws ~> 5.0`,
  `archive ~> 2.0`, `random ~> 3.0`, Terraform `>= 1.6`.

## When you build it out

Create `main.tf`, `variables.tf`, `outputs.tf`, `backend.tf`, and a
`terraform.tfvars.example` mirroring `envs/base`, changing only the `environment`
default to `demo` and the defaults noted above. The module `source` paths are the
same `../../modules/<name>` relative references.

## Stand up and tear down

```bash
# from infra/terraform/envs/demo, once main.tf exists
terraform init
terraform apply        # stand up the demo
# ... show the platform ...
terraform destroy      # tear everything down; leaves no spend behind
```

The nightly teardown Lambda is the safety net if you forget to run
`terraform destroy`: it stops the expensive streaming and batch workloads even
though it does not delete the cheap foundation (VPC, empty buckets, idle
on-demand tables), which cost effectively nothing at rest.
