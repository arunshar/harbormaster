# modules/ecs_serving/main.tf
#
# The deterministic AIS scorer as a Fargate service, reachable via Cloud Map
# private DNS (in-VPC callers like Flink) and, through the apigw module, an API
# Gateway HTTP API. No standing ALB. Scales 1->3 on CPU. An ECR repo holds the
# image built from serving/Dockerfile (pushed at deploy time). Task role reads
# the Feast DynamoDB table, the lake bucket, and the RDS master secret.

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

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnet_ids" {
  description = "Public subnets for the Fargate service (egress via IGW, no NAT)."
  type        = list(string)
}

variable "cluster_arn" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "feast_table_name" {
  type = string
}

variable "lake_bucket_arn" {
  type = string
}

variable "rds_secret_arn" {
  type    = string
  default = ""
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "max_count" {
  type    = number
  default = 3
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
  service     = "serving"
  tags        = merge(var.tags, { Module = "ecs_serving" })
}

# ---- Image registry -------------------------------------------------------

resource "aws_ecr_repository" "serving" {
  name                 = "${local.name_prefix}-serving"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-serving" })
}

# ---- Logs -----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "serving" {
  name              = "/harbormaster/${var.environment}/serving"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# ---- Cloud Map service discovery -----------------------------------------

resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = "${local.name_prefix}.local"
  description = "Harbormaster internal service discovery"
  vpc         = var.vpc_id
  tags        = local.tags
}

resource "aws_service_discovery_service" "serving" {
  name = local.service

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id

    dns_records {
      type = "A"
      ttl  = 10
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = local.tags
}

# ---- Security group -------------------------------------------------------

resource "aws_security_group" "serving" {
  name        = "${local.name_prefix}-serving-sg"
  description = "Serving container port from in-VPC callers (Flink, API Gateway VPC link)"
  vpc_id      = var.vpc_id

  ingress {
    description = "scorer port from in-VPC"
    from_port   = var.container_port
    to_port     = var.container_port
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-serving-sg" })
}

# ---- IAM: execution role (pull image, write logs) -------------------------

data "aws_iam_policy_document" "task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name_prefix}-serving-exec"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ---- IAM: task role (app permissions) -------------------------------------

resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-serving-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid    = "FeastRead"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
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

  dynamic "statement" {
    for_each = var.rds_secret_arn == "" ? [] : [var.rds_secret_arn]
    content {
      sid       = "RdsSecretRead"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.name_prefix}-serving-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# ---- Task definition ------------------------------------------------------

resource "aws_ecs_task_definition" "serving" {
  family                   = "${local.name_prefix}-serving"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = local.service
      image     = "${aws_ecr_repository.serving.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "FEAST_ONLINE_TABLE", value = var.feast_table_name },
        { name = "DB_SECRET_ARN", value = var.rds_secret_arn },
        { name = "PORT", value = tostring(var.container_port) },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.serving.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = local.service
        }
      }
    }
  ])

  tags = local.tags
}

# ---- Service --------------------------------------------------------------

resource "aws_ecs_service" "serving" {
  name            = "${local.name_prefix}-serving"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.serving.arn
  desired_count   = var.desired_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  network_configuration {
    # Public subnets + public IP so tasks reach ECR / Kinesis / Secrets / Logs
    # over the IGW with no NAT (~$32/mo) or interface endpoints. The SG allows
    # inbound only from the VPC CIDR, so the public IP is egress-only in practice.
    subnets          = var.public_subnet_ids
    security_groups  = [aws_security_group.serving.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.serving.arn
  }

  # Ignore desired_count drift so autoscaling owns it after the first apply.
  lifecycle {
    ignore_changes = [desired_count]
  }

  tags = local.tags
}

# ---- Autoscaling 1 -> max on CPU -----------------------------------------

resource "aws_appautoscaling_target" "serving" {
  max_capacity       = var.max_count
  min_capacity       = var.desired_count
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.serving.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${local.name_prefix}-serving-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.serving.resource_id
  scalable_dimension = aws_appautoscaling_target.serving.scalable_dimension
  service_namespace  = aws_appautoscaling_target.serving.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 50
    scale_in_cooldown  = 120
    scale_out_cooldown = 30
  }
}

# ---- Outputs --------------------------------------------------------------

output "ecr_repository_url" {
  value = aws_ecr_repository.serving.repository_url
}

output "service_name" {
  value = aws_ecs_service.serving.name
}

output "security_group_id" {
  value = aws_security_group.serving.id
}

output "cloudmap_service_arn" {
  value = aws_service_discovery_service.serving.arn
}

output "cloudmap_dns_name" {
  description = "In-VPC DNS for the scorer (e.g. serving.harbormaster-base.local)."
  value       = "${local.service}.${aws_service_discovery_private_dns_namespace.this.name}"
}

output "cloudmap_namespace_id" {
  description = "The private DNS namespace id (Phase 2 registers redis into it)."
  value       = aws_service_discovery_private_dns_namespace.this.id
}
