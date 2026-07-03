# modules/observability/main.tf
#
# Phase 1 observability (gate G7): a CloudWatch dashboard over the AWS-native
# metrics of the slice (ECS serving, API Gateway, Kinesis) plus two SLO alarms
# (API Gateway 5xx and p95 latency) wired to the budget SNS topic. The app-level
# $/inference and anomalies/min ship via CloudWatch EMF from the serving task
# (metrics.py / cost.py) and are added to the dashboard once EMF is enabled.

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

variable "api_id" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "service_name" {
  type = string
}

variable "kinesis_stream_name" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.tags, { Module = "observability" })

  dashboard = {
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Serving CPU / running tasks"
          region = var.aws_region
          period = 60
          stat   = "Average"
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.service_name],
            ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", var.cluster_name, "ServiceName", var.service_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "API Gateway: requests + p95 latency"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiId", var.api_id, { stat = "Sum" }],
            ["AWS/ApiGateway", "Latency", "ApiId", var.api_id, { stat = "p95" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "API Gateway errors"
          region = var.aws_region
          period = 60
          stat   = "Sum"
          metrics = [
            ["AWS/ApiGateway", "5xx", "ApiId", var.api_id],
            ["AWS/ApiGateway", "4xx", "ApiId", var.api_id],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Kinesis ais-raw throughput"
          region = var.aws_region
          period = 60
          metrics = [
            ["AWS/Kinesis", "IncomingRecords", "StreamName", var.kinesis_stream_name, { stat = "Sum" }],
            ["AWS/Kinesis", "GetRecords.IteratorAgeMilliseconds", "StreamName", var.kinesis_stream_name, { stat = "Maximum" }],
          ]
        }
      },
    ]
  }
}

resource "aws_cloudwatch_dashboard" "phase1" {
  dashboard_name = "${local.name_prefix}-phase1"
  dashboard_body = jsonencode(local.dashboard)
}

# SLO alarm: score-success 99.9% -> proxy on API Gateway 5xx over the demo window.
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name_prefix}-api-5xx"
  alarm_description   = "API Gateway 5xx >= 1 (score-success SLO 99.9%)"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = var.api_id }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.sns_topic_arn]
  tags                = local.tags
}

# SLO alarm: kernel-path p95 < 300 ms -> API Gateway p95 latency.
resource "aws_cloudwatch_metric_alarm" "api_latency_p95" {
  alarm_name          = "${local.name_prefix}-api-latency-p95"
  alarm_description   = "API Gateway p95 latency > 300 ms (kernel-path SLO)"
  namespace           = "AWS/ApiGateway"
  metric_name         = "Latency"
  dimensions          = { ApiId = var.api_id }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  threshold           = 300
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.sns_topic_arn]
  tags                = local.tags
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.phase1.dashboard_name
}
