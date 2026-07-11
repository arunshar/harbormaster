# modules/sagemaker_pidpm
#
# The Pi-DPM async Multi-Model Endpoint (Phase 3, gate 3.6). One model
# (single-region: Harbormaster's entire footprint is us-east-1, so the
# master plan's "per-region checkpoints" language simplifies here to one
# region, honestly noted rather than built as unused multi-region scaffolding)
# behind a single named ProductionVariant ("champion"), fronted by an async
# inference EndpointConfig so the container is invoked via S3, not a
# synchronous HTTP call. Scale-to-zero is the AWS-documented two-part
# pattern for SageMaker async endpoints (target tracking alone cannot detect
# a 0->1 transition, since there is no running instance to measure a
# per-instance metric from):
#   (1) a target-tracking policy on ApproximateBacklogSizePerInstance
#       handles scale-out beyond 1 and, because min_capacity=0 is set on the
#       scalable target, scale-in all the way back to zero;
#   (2) a step-scaling policy + a CloudWatch alarm on HasBacklogWithoutCapacity
#       handles the 0->1 transition an idle endpoint cannot detect on its own.
# Whole-module gate at the envs/base call site (image AND model-artifact
# vars both non-empty), matching the ecs_connect/ecs_cdc_consumer
# image-gated convention: an apply before the container is built and the
# checkpoint is exported creates no half-configured endpoint.

variable "project" {
  type    = string
  default = "harbormaster"
}

variable "environment" {
  type = string
}

# Unused inside this module today (the provider region comes from the root),
# but envs/base passes aws_region to every regional module, so the input stays
# for interface uniformity rather than breaking the caller.
# tflint-ignore: terraform_unused_declarations
variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "container_image" {
  description = "ECR image URI wrapping the frozen PiDpmScorer.log_prob contract (mlops/pidpm_container/Dockerfile)."
  type        = string
}

variable "model_data_url" {
  description = "S3 URI to the exported checkpoint artifact (from mlops/manifest.py's one-way export)."
  type        = string
}

variable "candidate_model_data_url" {
  description = <<-EOT
    S3 URI to a challenger checkpoint artifact for the weighted-canary
    "candidate" variant (gate 3.7). Empty (the default) keeps the endpoint
    single-variant and the plan a ZERO diff; non-empty adds a second
    SageMaker model plus a second production variant planted at weight 0.0.
    Same exported-artifact provenance as model_data_url (mlops/manifest.py).
  EOT
  type        = string
  default     = ""
}

variable "models_bucket_arn" {
  type = string
}

variable "instance_type" {
  description = "GPU instance for the Pi-DPM head (the platform's one deliberate non-CPU-serving component; ECS stays CPU throughout)."
  type        = string
  default     = "ml.g4dn.xlarge"
}

variable "max_concurrent_invocations_per_instance" {
  type    = number
  default = 4
}

variable "backlog_target_value" {
  description = "Target-tracking setpoint for ApproximateBacklogSizePerInstance."
  type        = number
  default     = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "permissions_boundary_arn" {
  description = "ARN of the IAM permissions boundary to attach to roles this module creates. Empty attaches no boundary. The harbormaster-platform deploy policy requires the harbormaster-permissions-boundary on every managed role (see war story P32, the two-sided contract), so envs/base sets this at apply time."
  type        = string
  default     = ""
}

locals {
  name_prefix   = "${var.project}-${var.environment}"
  tags          = merge(var.tags, { Module = "sagemaker_pidpm" })
  variant_name  = "champion"
  models_bucket = replace(var.models_bucket_arn, "arn:aws:s3:::", "")

  # Weighted-canary challenger (gate 3.7). Variant names match the defaults
  # baked into mlops/canary_actuator.py's factories; change both together.
  candidate_variant_name = "candidate"
  candidate_enabled      = var.candidate_model_data_url != ""
}

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name                 = "${local.name_prefix}-pidpm-endpoint"
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null
  assume_role_policy   = data.aws_iam_policy_document.sagemaker_assume.json
  tags                 = local.tags
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid    = "ReadModelArtifactAndWriteAsyncIO"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [
      var.models_bucket_arn,
      "${var.models_bucket_arn}/*",
    ]
  }

  statement {
    sid    = "PullContainerImage"
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PublishAsyncInferenceMetricsAndLogs"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "${local.name_prefix}-pidpm-endpoint"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

resource "aws_sagemaker_model" "pidpm" {
  name               = "${local.name_prefix}-pidpm"
  execution_role_arn = aws_iam_role.execution.arn

  primary_container {
    image          = var.container_image
    model_data_url = var.model_data_url
  }

  tags = local.tags
}

# The weighted-canary challenger model (gate 3.7). Count-gated on the
# candidate artifact being supplied at all: with candidate_model_data_url
# empty (the default) this model and the second variant below are absent and
# the plan is a ZERO diff. Same container image as the champion, a promotion
# swaps the checkpoint, never the frozen PiDpmScorer scoring contract.
resource "aws_sagemaker_model" "candidate" {
  count              = local.candidate_enabled ? 1 : 0
  name               = "${local.name_prefix}-pidpm-candidate"
  execution_role_arn = aws_iam_role.execution.arn

  # CKV_AWS_370: on for the candidate (the scorer makes no outbound calls;
  # SageMaker still handles the S3 model download and async output upload at
  # the platform layer). The champion above predates this and its finding is
  # an accepted baseline entry; flipping the champion is a live-window
  # decision, not a silent config change to a live-verified resource.
  enable_network_isolation = true

  primary_container {
    image          = var.container_image
    model_data_url = var.candidate_model_data_url
  }

  tags = local.tags
}

# The promotion registry (mlops/registry.py's register_candidate) calls
# create_model_package with a ModelPackageGroupName, which creates a
# VERSIONED model package; SageMaker requires that named group to already
# exist (create_model_package does not create it). Provisioning it here,
# not via a manual runbook CLI step, so it tears down with the rest of the
# module on enable_phase3=false, matching this repo's "guardrails/resources
# as code, not a checklist" convention (HM3-AUDIT-02, ~/code/sagemaker-
# deepdive/audit/HANDOFF_PHASE3_AUDIT_2026-07-04.md, option (b)).
resource "aws_sagemaker_model_package_group" "pidpm" {
  model_package_group_name        = "${local.name_prefix}-pidpm"
  model_package_group_description = "Pi-DPM promotion approval group (Phase 3)"
  tags                            = local.tags
}

resource "aws_sagemaker_endpoint_configuration" "pidpm" {
  name = "${local.name_prefix}-pidpm"

  production_variants {
    variant_name           = local.variant_name
    model_name             = aws_sagemaker_model.pidpm.name
    instance_type          = var.instance_type
    initial_instance_count = 1
    initial_variant_weight = 1.0
  }

  # The candidate rides the same endpoint as a second variant, planted at
  # weight 0.0 (the champion above keeps 1.0). Terraform only ever plants it
  # there: the 5/25/50/100 canary ramp and the full-weight rollback shift
  # runtime weights via the UpdateEndpointWeightsAndCapacities API on the
  # ENDPOINT (mlops/canary_actuator.py), which never touches this endpoint
  # configuration, so a post-ramp plan stays clean. A dynamic block rather
  # than a second static one so the champion block above stays byte-equivalent
  # and the no-candidate plan a ZERO diff. NOTE: endpoint configs are
  # immutable, so flipping the candidate on REPLACES this config; do it on a
  # fresh Phase 3 window, not against a live endpoint (the enable_cmk RDS
  # replacement precedent in envs/base).
  dynamic "production_variants" {
    for_each = local.candidate_enabled ? [1] : []
    content {
      variant_name           = local.candidate_variant_name
      model_name             = aws_sagemaker_model.candidate[0].name
      instance_type          = var.instance_type
      initial_instance_count = 1
      initial_variant_weight = 0.0
    }
  }

  async_inference_config {
    output_config {
      s3_output_path = "s3://${local.models_bucket}/pidpm/async-output"
    }
    client_config {
      max_concurrent_invocations_per_instance = var.max_concurrent_invocations_per_instance
    }
  }

  tags = local.tags
}

resource "aws_sagemaker_endpoint" "pidpm" {
  name                 = "${local.name_prefix}-pidpm"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.pidpm.name
  tags                 = local.tags
}

# ---- Scale-to-zero: target tracking (1 <-> 0, and above 1) ----
#
# CHAMPION VARIANT ONLY, deliberately. The candidate variant is excluded from
# autoscaling and holds its fixed initial_instance_count of 1 for the length
# of a canary ramp (demo-scoped: a ramp lasts minutes and the endpoint is
# torn down with enable_phase3 after the window, so a second scalable target
# plus its HasBacklogWithoutCapacity alarm pair for a variant planted at
# weight 0.0 is standing complexity with nothing to scale).

resource "aws_appautoscaling_target" "pidpm" {
  service_namespace  = "sagemaker"
  resource_id        = "endpoint/${aws_sagemaker_endpoint.pidpm.name}/variant/${local.variant_name}"
  scalable_dimension = "sagemaker:variant:DesiredInstanceCount"
  min_capacity       = 0
  max_capacity       = 1
}

resource "aws_appautoscaling_policy" "backlog_target_tracking" {
  name               = "${local.name_prefix}-pidpm-backlog-tracking"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.pidpm.service_namespace
  resource_id        = aws_appautoscaling_target.pidpm.resource_id
  scalable_dimension = aws_appautoscaling_target.pidpm.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = var.backlog_target_value

    # ApproximateBacklogSizePerInstance is published per-endpoint under the
    # EndpointName dimension. Application Auto Scaling's own rule: if a
    # metric is published with dimensions, the policy must specify the same
    # ones, or it queries a metric series that doesn't exist. Without this,
    # the target-tracking alarms sit in INSUFFICIENT_DATA forever and
    # scale-in to zero never fires -- with initial_instance_count = 1 on
    # ml.g4dn.xlarge (~$0.74/hr, ~$530/mo), that's a standing GPU cost that
    # breaches the $75/mo cap. Caught by an external audit before this was
    # ever applied against real AWS; verified fixed in the live W2 window,
    # 2026-07-04.
    customized_metric_specification {
      metric_name = "ApproximateBacklogSizePerInstance"
      namespace   = "AWS/SageMaker"
      statistic   = "Average"

      dimensions {
        name  = "EndpointName"
        value = aws_sagemaker_endpoint.pidpm.name
      }
    }
  }
}

# ---- Scale-out from absolute zero (target tracking cannot see this transition) ----

resource "aws_appautoscaling_policy" "scale_out_from_zero" {
  name               = "${local.name_prefix}-pidpm-scale-out-from-zero"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.pidpm.service_namespace
  resource_id        = aws_appautoscaling_target.pidpm.resource_id
  scalable_dimension = aws_appautoscaling_target.pidpm.scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type         = "ExactCapacity"
    cooldown                = 60
    metric_aggregation_type = "Maximum"

    step_adjustment {
      scaling_adjustment          = 1
      metric_interval_upper_bound = 0
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "has_backlog_without_capacity" {
  alarm_name  = "${local.name_prefix}-pidpm-has-backlog-without-capacity"
  namespace   = "AWS/SageMaker"
  metric_name = "HasBacklogWithoutCapacity"
  # EndpointName only, matching AWS's own canonical scale-from-zero example
  # (docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html)
  # exactly. An extra VariantName dimension here queries a metric series
  # AWS doesn't publish (unlike ApproximateBacklogSize, which SageMaker
  # does emit per-variant): the alarm sat with zero datapoints for 15+
  # minutes with real, persistent backlog the whole time, so the 0-to-1
  # scale-out from absolute zero would never have fired. A real, first-
  # live-run finding, W2 sprint window, 2026-07-04 -- caught live, not by
  # the prior audit (whose HM3-AUDIT-01 finding was the separate
  # target-tracking scale-IN policy's missing EndpointName dimension).
  dimensions = {
    EndpointName = aws_sagemaker_endpoint.pidpm.name
  }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.scale_out_from_zero.arn]
  tags                = local.tags
}

output "endpoint_name" {
  value = aws_sagemaker_endpoint.pidpm.name
}

output "model_name" {
  value = aws_sagemaker_model.pidpm.name
}

output "model_package_group_name" {
  value = aws_sagemaker_model_package_group.pidpm.model_package_group_name
}

# Empty when no candidate artifact is supplied, the kms_key_arn
# empty-string-collapse convention.
output "candidate_model_name" {
  value = local.candidate_enabled ? aws_sagemaker_model.candidate[0].name : ""
}
