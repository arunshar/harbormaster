# ADR 0003: Single-region, single-AZ RDS is a deliberate cost posture under a $75/month cap

**Status:** Accepted

**Date:** 2026-07-06

## Context

The platform runs under a $75/month hard cap (plus a $30 soft budget), enforced before anything else was built (ARCHITECTURE.md, FinOps module). The RDS module (`infra/terraform/modules/rds/main.tf`) reflects that posture in its real values: `instance_class = db.t4g.micro` (free-tier), single region, `multi_az = false`, `backup_retention_period = 1` (one day of automated backups), `skip_final_snapshot = true`, and `deletion_protection = false`. These are cost choices, not a disaster-recovery design. This ADR states the recovery posture they imply so no one reads more durability into the stack than exists.

## Decision

Accept single-region, single-AZ RDS with one-day backups as the deliberate cost posture, and do not claim any disaster-recovery capability beyond what these settings provide.

Recovery posture implied by the real settings:

- **RPO:** with `multi_az = false` there is no synchronous standby, so an instance or AZ loss falls back to backups. Point-in-time recovery is bounded by `backup_retention_period = 1`, giving at most a one-day recovery window; worst-case loss is whatever committed after the last recoverable point. `skip_final_snapshot = true` means a `terraform destroy` takes no final snapshot, so a destroy is an unrecoverable loss.
- **RTO:** single-AZ has no automatic standby promotion; recovery is a manual restore-from-backup into a new instance, on the order of tens of minutes to hours, and unbounded if the backup or region is gone. `deletion_protection = false` removes the guardrail against accidental deletion.

## Consequences

Positive: the database stays free-tier and inside the cap; the posture is explicit and auditable. Negative and accepted: no AZ-failure survivability, a one-day recovery ceiling, no cross-region protection, and a destroy-loses-data footgun.

## Alternatives considered

**Multi-AZ.** Buys a synchronous standby with automatic failover (RTO in low minutes, near-zero RPO on AZ loss). Rejected: roughly doubles the instance cost, which the $75 cap does not allow for a personal demo.

**Cross-region automated backups / a read replica in a second region.** Buys survival of a full region outage. Rejected: adds cross-region storage and transfer cost plus a standing replica, again outside the cap. What Multi-AZ and cross-region backup would cost is real money the project deliberately does not spend, and what they would buy (AZ and region survivability) is capability this stack honestly does not have.
