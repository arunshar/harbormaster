# envs/base/variables.tf
#
# Root-level variables for the Harbormaster "base" environment. Values come from
# terraform.tfvars (copy terraform.tfvars.example). Nothing here contains a real
# account id or secret.

variable "project" {
  description = "Project name, propagated to every module and the common tags."
  type        = string
  default     = "harbormaster"
}

variable "environment" {
  description = "Deployment environment for this root. Fixed to base here."
  type        = string
  default     = "base"

  validation {
    condition     = contains(["base", "demo"], var.environment)
    error_message = "environment must be one of: base, demo."
  }
}

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Email subscribed to budget and anomaly alerts. AWS sends a one-time confirmation link."
  type        = string
}

variable "platform_role_name" {
  description = <<-EOT
    Name of the IAM role the $75 hard-budget action attaches the deny policy to
    on breach. Must be an existing role used by your platform/CI to create
    spend-incurring resources. Phase 0 does not create this role for you; pass
    the name of a role you control.
  EOT
  type        = string
}

variable "enable_nat" {
  description = "Create the single NAT gateway in the network module. Default false to avoid the hourly charge."
  type        = bool
  default     = false
}

variable "enable_nightly_teardown" {
  description = "Create the EventBridge schedule that runs the teardown Lambda nightly."
  type        = bool
  default     = true
}

variable "teardown_dry_run" {
  description = "When true, the teardown Lambda only logs what it would tear down. Keep true until you trust it."
  type        = bool
  default     = true
}

variable "cost_anomaly_monitor_arn" {
  description = <<-EOT
    Reuse an existing Cost Explorer SERVICE anomaly monitor instead of creating one.
    AWS allows only one dimensional SERVICE monitor per account and auto-creates a
    "Default-Services-Monitor", so set this to that monitor's ARN on such accounts.
    Empty creates our own monitor.
  EOT
  type        = string
  default     = ""
}

variable "enable_phase1" {
  description = <<-EOT
    Gate for the Phase 1 streaming + serving pipeline (kinesis, firehose, rds,
    and the compute plane). Default false keeps a base apply Phase-0-only and
    cheap. Set true for a demo apply, then back to false (or destroy) to stop
    the billable compute.
  EOT
  type        = bool
  default     = false
}

variable "enable_phase2" {
  description = <<-EOT
    Gate for the Phase 2 CDC showcase plane (MSK Serverless, Debezium on
    Fargate, the CDC consumer, Redis on Fargate, slot-lag monitoring, and the
    RDS logical-replication parameter group). Default false keeps a base apply
    Phase-0-only. The AWS showcase also requires enable_phase1 = true (RDS,
    ECS cluster, serving); the local kind/Strimzi plane needs neither. Set true
    for a demo window, then back to false: MSK Serverless left running is the
    single biggest budget threat in the platform (~$18/day).
  EOT
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_phase2 || var.enable_phase1
    error_message = "enable_phase2 requires enable_phase1 = true (RDS, the ECS cluster, and the Cloud Map namespace are Phase 1 resources)."
  }
}

variable "enable_phase3" {
  description = <<-EOT
    Gate for the Phase 3 lake + promotion plane (transient EMR backfill, the
    Feast offline store export, the MSI->S3 checkpoint manifest path, and the
    SageMaker async Pi-DPM endpoint + promotion pipeline). Default false keeps
    a base apply Phase-0-only. Requires enable_phase1 = true (the SageMaker
    endpoint sits in the Phase 1 VPC; the lake export reuses the Phase 0 lake
    bucket and Glue catalog). Does NOT require enable_phase2 (CDC is
    orthogonal to training/promotion). Set true for a demo window, then back
    to false: an EMR job left running and a SageMaker endpoint left above its
    zero-minimum auto-scaling capacity are this phase's budget threats.
  EOT
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_phase3 || var.enable_phase1
    error_message = "enable_phase3 requires enable_phase1 = true (the VPC, lake bucket, and Glue catalog it depends on are Phase 0/1 resources)."
  }
}

variable "enable_phase4" {
  description = <<-EOT
    Gate for the Phase 4 drift-watch plane (modules/drift_watch: an
    EventBridge schedule -> Lambda running mlops/drift.py's input-drift check
    against two lake-bucket parquet snapshots -> the existing Phase 0 finops
    SNS topic). Default false; no resources exist behind this toggle yet
    (added at gate 4.6). Depends only on Phase 0 (the lake bucket and SNS
    topic), not Phase 1/3, since the module reads S3 snapshots rather than
    calling any Phase 1/3 service directly. Not applied during the 24-hour
    completion sprint (2026-07-04): authored, `terraform validate`- and
    plan-checksum-verified only, per docs/phases/PHASE_4.md gate 4.6.
  EOT
  type        = bool
  default     = false
}

variable "pidpm_image" {
  description = <<-EOT
    ECR image URI wrapping the frozen PiDpmScorer contract (built from
    mlops/pidpm_container/Dockerfile and pushed at demo time). Empty skips
    the SageMaker model/endpoint, the flink_code_s3_key pattern, so an apply
    before the image push and the checkpoint export creates no
    half-configured endpoint.
  EOT
  type        = string
  default     = ""
}

variable "pidpm_model_data_url" {
  description = <<-EOT
    S3 URI to the exported Pi-DPM checkpoint artifact (from
    mlops/manifest.py's one-way export). Empty skips the SageMaker
    model/endpoint, same reasoning as pidpm_image.
  EOT
  type        = string
  default     = ""
}

variable "cdc_connect_image" {
  description = <<-EOT
    ECR image URI for Debezium Connect (built from cdc/connect/Dockerfile and
    pushed at demo time). Empty skips the connect service, the Phase 1
    flink_code_s3_key pattern, so an apply before the image push creates no
    crash-looping service.
  EOT
  type        = string
  default     = ""
}

variable "cdc_consumer_image" {
  description = <<-EOT
    ECR image URI for the CDC consumer (built from cdc/consumer/Dockerfile and
    pushed at demo time). Empty skips the consumer service.
  EOT
  type        = string
  default     = ""
}

variable "flink_code_s3_key" {
  description = <<-EOT
    S3 key (in the lake bucket) of the packaged Flink job zip (make
    flink-package, uploaded to s3://<lake_bucket>/flink/flink-app.zip at
    demo time). Empty skips creating the Managed Flink application (gate
    1.5's modules/kda_flink gates create_app on this being non-empty), so a
    Phase 1 apply before the artifact is uploaded creates no
    half-configured Flink app. Despite three comments elsewhere in this
    repo referring to "the flink_code_s3_key pattern" as an existing
    env-level toggle (mirroring pidpm_image/cdc_connect_image), this
    variable and its wiring into module.kda_flink never actually existed
    until the first live Phase 1 W1 sprint-window run found the gap.
  EOT
  type        = string
  default     = ""
}
