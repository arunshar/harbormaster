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

locals {
  name_prefix  = "${var.project}-${var.environment}"
  tags         = merge(var.tags, { Module = "sagemaker_pidpm" })
  variant_name = "champion"
  models_bucket = replace(var.models_bucket_arn, "arn:aws:s3:::", "")
}

data "aws_caller_identity" "current" {}

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
  name               = "${local.name_prefix}-pidpm-endpoint"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
  tags               = local.tags
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

resource "aws_sagemaker_endpoint_configuration" "pidpm" {
  name = "${local.name_prefix}-pidpm"

  production_variants {
    variant_name           = local.variant_name
    model_name             = aws_sagemaker_model.pidpm.name
    instance_type          = var.instance_type
    initial_instance_count = 1
    initial_variant_weight = 1.0
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

    customized_metric_specification {
      metric_name = "ApproximateBacklogSizePerInstance"
      namespace   = "AWS/SageMaker"
      statistic   = "Average"
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
  alarm_name          = "${local.name_prefix}-pidpm-has-backlog-without-capacity"
  namespace           = "AWS/SageMaker"
  metric_name         = "HasBacklogWithoutCapacity"
  dimensions = {
    EndpointName = aws_sagemaker_endpoint.pidpm.name
    VariantName  = local.variant_name
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
