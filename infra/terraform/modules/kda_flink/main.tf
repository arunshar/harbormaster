# modules/kda_flink/main.tf
#
# Amazon Managed Service for Apache Flink (KDA v2): computes AIS features and
# calls the scorer. The IAM role and log group are always created (free). The
# Flink application itself is gated behind flink_code_s3_key: it is created only
# once the 1.5 build uploads the job artifact to S3, so a 1.3 demo apply stands
# up the plumbing without incurring KPU cost. Flink calls the public API Gateway
# endpoint, so it needs no VPC configuration.

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

variable "kinesis_stream_arn" {
  type = string
}

variable "feast_table_name" {
  type = string
}

variable "lake_bucket_arn" {
  type = string
}

variable "code_bucket_arn" {
  type    = string
  default = ""
}

variable "flink_code_s3_key" {
  type    = string
  default = ""
}

variable "runtime_environment" {
  type    = string
  default = "FLINK-1_20"
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.tags, { Module = "kda_flink" })
  create_app  = var.flink_code_s3_key != ""
}

data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["kinesisanalytics.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flink" {
  name               = "${local.name_prefix}-flink"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "flink" {
  statement {
    sid    = "ReadStream"
    effect = "Allow"
    actions = [
      "kinesis:DescribeStream",
      "kinesis:DescribeStreamSummary",
      "kinesis:GetShardIterator",
      "kinesis:GetRecords",
      "kinesis:ListShards",
    ]
    resources = [var.kinesis_stream_arn]
  }

  statement {
    sid    = "WriteFeatures"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:UpdateItem",
    ]
    resources = ["arn:aws:dynamodb:${var.aws_region}:*:table/${var.feast_table_name}"]
  }

  statement {
    sid    = "LakeReadWrite"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObject",
    ]
    resources = [
      var.lake_bucket_arn,
      "${var.lake_bucket_arn}/*",
    ]
  }

  statement {
    sid       = "Logs"
    effect    = "Allow"
    actions   = ["logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.aws_region}:*:*"]
  }
}

resource "aws_iam_role_policy" "flink" {
  name   = "${local.name_prefix}-flink"
  role   = aws_iam_role.flink.id
  policy = data.aws_iam_policy_document.flink.json
}

resource "aws_cloudwatch_log_group" "flink" {
  name              = "/harbormaster/${var.environment}/flink"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_stream" "flink" {
  name           = "flink-app"
  log_group_name = aws_cloudwatch_log_group.flink.name
}

# Flink application: created only once the 1.5 artifact exists (flink_code_s3_key).
resource "aws_kinesisanalyticsv2_application" "flink" {
  count = local.create_app ? 1 : 0

  name                   = "${local.name_prefix}-flink"
  runtime_environment    = var.runtime_environment
  service_execution_role = aws_iam_role.flink.arn

  application_configuration {
    application_code_configuration {
      code_content {
        s3_content_location {
          bucket_arn = var.code_bucket_arn
          file_key   = var.flink_code_s3_key
        }
      }
      code_content_type = "ZIPFILE"
    }

    flink_application_configuration {
      parallelism_configuration {
        configuration_type = "DEFAULT"
      }
    }
  }

  cloudwatch_logging_options {
    log_stream_arn = aws_cloudwatch_log_stream.flink.arn
  }

  tags = local.tags
}

output "role_arn" {
  value = aws_iam_role.flink.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.flink.name
}

output "application_name" {
  value = one(aws_kinesisanalyticsv2_application.flink[*].name)
}
