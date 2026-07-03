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

# -----------------------------------------------------------------------------
# Phase 1 (gate 1.3): streaming + serving pipeline. Every module is gated behind
# enable_phase1 (default false) so a base apply stays Phase-0-only and cheap.
# Flip enable_phase1 = true for a demo apply, then set it back to false (or
# destroy the Phase 1 resources) to stop the billable compute. Data plane in
# this batch: kinesis, firehose, rds. Compute plane (ecs_*, kda_flink, apigw)
# follows in the next batch.
# -----------------------------------------------------------------------------

module "kinesis" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/kinesis"

  project     = var.project
  environment = var.environment
  tags        = local.common_tags
}

module "firehose" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/firehose"

  project     = var.project
  environment = var.environment

  kinesis_stream_arn = module.kinesis[0].stream_arn
  lake_bucket_arn    = "arn:aws:s3:::${module.state_stores.lake_bucket_name}"

  tags = local.common_tags
}

module "rds" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/rds"

  project     = var.project
  environment = var.environment

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  # The VPC is 10.0.0.0/16 (network module default); allow in-VPC Postgres.
  allowed_ingress_cidrs = ["10.0.0.0/16"]

  # Phase 2: logical decoding for Debezium (parameter group + reboot at the
  # demo apply). Inert (no parameter group at all) while enable_phase2 = false.
  logical_replication = var.enable_phase2

  tags = local.common_tags
}

module "ecs_cluster" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/ecs_cluster"

  project     = var.project
  environment = var.environment
  tags        = local.common_tags
}

module "ecs_serving" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/ecs_serving"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids

  cluster_arn  = module.ecs_cluster[0].cluster_arn
  cluster_name = module.ecs_cluster[0].cluster_name

  feast_table_name = module.state_stores.feast_online_table_name
  lake_bucket_arn  = "arn:aws:s3:::${module.state_stores.lake_bucket_name}"
  rds_secret_arn   = module.rds[0].master_user_secret_arn

  tags = local.common_tags
}

module "apigw" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/apigw"

  project     = var.project
  environment = var.environment

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  cloudmap_service_arn = module.ecs_serving[0].cloudmap_service_arn

  tags = local.common_tags
}

module "ecs_ingestor" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/ecs_ingestor"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id             = module.network.vpc_id
  kinesis_stream_arn = module.kinesis[0].stream_arn
  lake_bucket_arn    = "arn:aws:s3:::${module.state_stores.lake_bucket_name}"

  tags = local.common_tags
}

module "kda_flink" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/kda_flink"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  kinesis_stream_arn = module.kinesis[0].stream_arn
  feast_table_name   = module.state_stores.feast_online_table_name
  lake_bucket_arn    = "arn:aws:s3:::${module.state_stores.lake_bucket_name}"

  # flink_code_s3_key stays empty until gate 1.5 uploads the job artifact, so the
  # Flink application (and its KPU cost) is not created by a 1.3 demo apply.

  tags = local.common_tags
}

module "observability" {
  count  = var.enable_phase1 ? 1 : 0
  source = "../../modules/observability"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  api_id              = module.apigw[0].api_id
  cluster_name        = module.ecs_cluster[0].cluster_name
  service_name        = module.ecs_serving[0].service_name
  kinesis_stream_name = module.kinesis[0].stream_name
  sns_topic_arn       = module.finops.sns_topic_arn

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Phase 2 (gate 2.7): the CDC showcase plane. Everything below is gated behind
# enable_phase2 (default false; also requires enable_phase1 for RDS, the ECS
# cluster, and the Cloud Map namespace). MSK Serverless is ~$18/day while up:
# demo windows only, then flip enable_phase2 back to false. The image-consuming
# services (connect, consumer) are additionally gated on their image vars so a
# plan/apply before the ECR pushes creates no crash-looping services (the
# flink_code_s3_key pattern from Phase 1).
# -----------------------------------------------------------------------------

module "msk" {
  count  = var.enable_phase2 ? 1 : 0
  source = "../../modules/msk_serverless"

  project     = var.project
  environment = var.environment

  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids

  tags = local.common_tags
}

module "redis_fargate" {
  count  = var.enable_phase2 ? 1 : 0
  source = "../../modules/redis_fargate"

  project     = var.project
  environment = var.environment

  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids

  cluster_arn           = module.ecs_cluster[0].cluster_arn
  cloudmap_namespace_id = module.ecs_serving[0].cloudmap_namespace_id

  tags = local.common_tags
}

module "ecs_connect" {
  count  = var.enable_phase2 && var.cdc_connect_image != "" ? 1 : 0
  source = "../../modules/ecs_connect"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  cluster_arn       = module.ecs_cluster[0].cluster_arn

  image = var.cdc_connect_image

  msk_cluster_arn        = module.msk[0].cluster_arn
  msk_topic_wildcard_arn = module.msk[0].topic_wildcard_arn
  msk_group_wildcard_arn = module.msk[0].group_wildcard_arn
  msk_bootstrap          = module.msk[0].bootstrap_brokers_sasl_iam

  rds_endpoint   = module.rds[0].db_endpoint
  rds_secret_arn = module.rds[0].master_user_secret_arn

  tags = local.common_tags
}

module "ecs_cdc_consumer" {
  count  = var.enable_phase2 && var.cdc_consumer_image != "" ? 1 : 0
  source = "../../modules/ecs_cdc_consumer"

  project     = var.project
  environment = var.environment
  aws_region  = var.aws_region

  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  cluster_arn       = module.ecs_cluster[0].cluster_arn

  image = var.cdc_consumer_image

  msk_cluster_arn        = module.msk[0].cluster_arn
  msk_topic_wildcard_arn = module.msk[0].topic_wildcard_arn
  msk_group_wildcard_arn = module.msk[0].group_wildcard_arn
  msk_bootstrap          = module.msk[0].bootstrap_brokers_sasl_iam

  feast_table_name = module.state_stores.feast_online_table_name
  lake_bucket_arn  = "arn:aws:s3:::${module.state_stores.lake_bucket_name}"
  redis_url        = "redis://${module.redis_fargate[0].redis_dns}:6379/0"

  tags = local.common_tags
}

module "cdc_monitoring" {
  count  = var.enable_phase2 ? 1 : 0
  source = "../../modules/cdc_monitoring"

  project     = var.project
  environment = var.environment

  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  rds_endpoint   = module.rds[0].db_endpoint
  rds_secret_arn = module.rds[0].master_user_secret_arn

  sns_topic_arn = module.finops.sns_topic_arn

  # Built by `make cdc-lambda-package` (handler + shared monitor + pg8000).
  lambda_source_dir = "${path.module}/../../../lambda/cdc_slot_lag/build"

  tags = local.common_tags
}
