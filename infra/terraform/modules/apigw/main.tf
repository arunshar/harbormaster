# modules/apigw/main.tf
#
# API Gateway HTTP API fronting the ecs_serving Fargate service via a VPC Link
# to its Cloud Map service. Scale-to-zero, ~$1 per million requests, no standing
# cost (chosen over an ALB to protect the $75 cap). External callers hit the
# invoke URL; in-VPC callers (Flink) can skip this and use the Cloud Map DNS.

variable "project" {
  type    = string
  default = "harbormaster"
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "cloudmap_service_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.tags, { Module = "apigw" })
}

# SG for the VPC link ENIs; egress-only (they originate connections to serving).
resource "aws_security_group" "vpc_link" {
  name        = "${local.name_prefix}-apigw-vpclink-sg"
  description = "API Gateway VPC link egress to the serving service"
  vpc_id      = var.vpc_id

  egress {
    description = "all outbound to in-VPC targets"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-apigw-vpclink-sg" })
}

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${local.name_prefix}-serving-vpclink"
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [aws_security_group.vpc_link.id]
  tags               = local.tags
}

resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name_prefix}-serving-api"
  protocol_type = "HTTP"
  tags          = local.tags
}

# Private integration to the Cloud Map service via the VPC link.
resource "aws_apigatewayv2_integration" "serving" {
  api_id             = aws_apigatewayv2_api.this.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = var.cloudmap_service_arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.this.id
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.serving.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  tags        = local.tags
}

output "api_endpoint" {
  description = "Invoke URL for the serving HTTP API (POST /v1/score-ais)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}
