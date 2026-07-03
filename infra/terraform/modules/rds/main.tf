# modules/rds/main.tf
#
# Postgres 16 for the HITL queue and operational state, on a db.t4g.micro
# (free-tier eligible). Private subnets only, not publicly accessible, and the
# master password is managed by RDS in Secrets Manager (never in Terraform
# state). PostGIS is enabled by the app via CREATE EXTENSION at first connect.

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

variable "allowed_ingress_cidrs" {
  description = "CIDRs allowed to reach Postgres on 5432 (e.g. the VPC CIDR for in-VPC serving/ingestor/Flink)."
  type        = list(string)
  default     = []
}

variable "instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "harbormaster"
}

variable "master_username" {
  type    = string
  default = "hm_admin"
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.tags, { Module = "rds" })
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-pg"
  subnet_ids = var.private_subnet_ids

  tags = merge(local.tags, { Name = "${local.name_prefix}-pg-subnets" })
}

resource "aws_security_group" "this" {
  name        = "${local.name_prefix}-pg-sg"
  description = "Postgres 5432 from in-VPC Harbormaster services"
  vpc_id      = var.vpc_id

  ingress {
    description = "Postgres from allowed CIDRs"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_ingress_cidrs
  }

  egress {
    description = "all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-pg-sg" })
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name_prefix}-pg"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.master_username
  # RDS manages the master password in Secrets Manager; nothing lands in state.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  multi_az               = false

  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true

  tags = merge(local.tags, { Name = "${local.name_prefix}-pg" })
}

output "db_endpoint" {
  value = aws_db_instance.this.address
}

output "db_port" {
  value = aws_db_instance.this.port
}

output "db_name" {
  value = aws_db_instance.this.db_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  value = aws_security_group.this.id
}
