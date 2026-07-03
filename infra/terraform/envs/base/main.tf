# envs/base/main.tf
#
# Root configuration for the Harbormaster "base" environment. Wires the three
# Phase 0 modules together: network, state_stores, finops. This root is the only
# place a provider is configured; provider version constraints live in the
# shared ../../versions.tf (symlinked/loaded here via the terraform block below).
#
# Apply order note: build guardrails first. terraform apply creates the FinOps
# budgets and the teardown Lambda alongside the network and stores, so the $75
# cap and nightly sweep exist before any heavier Phase 1 compute is added.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  # Common tags applied to every resource across every module, per the shared
  # conventions. default_tags above also stamps these provider-wide; passing
  # them into modules keeps the tags explicit on resources that need name-scoping.
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Network
# -----------------------------------------------------------------------------

module "network" {
  source = "../../modules/network"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region
  enable_nat  = var.enable_nat

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# State stores (lake + models buckets, Feast online + TF lock tables)
# -----------------------------------------------------------------------------

module "state_stores" {
  source = "../../modules/state_stores"

  project     = var.project
  environment = var.environment

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# FinOps guardrails (budgets, anomaly detection, teardown Lambda)
# -----------------------------------------------------------------------------

module "finops" {
  source = "../../modules/finops"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  alert_email        = var.alert_email
  platform_role_name = var.platform_role_name

  enable_nightly_teardown = var.enable_nightly_teardown
  teardown_dry_run        = var.teardown_dry_run

  existing_cost_anomaly_monitor_arn = var.cost_anomaly_monitor_arn

  # Lambda source lives at infra/lambda/teardown relative to this root:
  # envs/base -> ../../.. = infra, then lambda/teardown.
  lambda_source_dir = "${path.module}/../../../lambda/teardown"

  tags = local.common_tags
}
