# envs/base/outputs.tf
#
# Surface the values Phase 1 components (streaming, CDC, serving) will need to
# reference, plus the FinOps control-plane identifiers.

# ---- Network ----------------------------------------------------------------

output "vpc_id" {
  description = "ID of the Harbormaster VPC."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs, one per AZ."
  value       = module.network.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Private subnet IDs, one per AZ."
  value       = module.network.private_subnet_ids
}

output "s3_vpc_endpoint_id" {
  description = "S3 gateway VPC endpoint ID."
  value       = module.network.s3_vpc_endpoint_id
}

output "dynamodb_vpc_endpoint_id" {
  description = "DynamoDB gateway VPC endpoint ID."
  value       = module.network.dynamodb_vpc_endpoint_id
}

# ---- State stores -----------------------------------------------------------

output "lake_bucket_name" {
  description = "Data-lake S3 bucket name (holds raw/, iceberg/, features/)."
  value       = module.state_stores.lake_bucket_name
}

output "models_bucket_name" {
  description = "Model-artifacts S3 bucket name."
  value       = module.state_stores.models_bucket_name
}

output "feast_online_table_name" {
  description = "Feast online-store DynamoDB table name."
  value       = module.state_stores.feast_online_table_name
}

output "tf_state_lock_table_name" {
  description = "Terraform state-lock DynamoDB table name (for the optional S3 backend)."
  value       = module.state_stores.tf_state_lock_table_name
}

# ---- FinOps -----------------------------------------------------------------

output "budget_alerts_sns_topic_arn" {
  description = "SNS topic ARN that receives budget and cost-anomaly alerts."
  value       = module.finops.sns_topic_arn
}

output "spend_freeze_policy_arn" {
  description = "ARN of the deny policy attached to the platform role on $75 breach."
  value       = module.finops.spend_freeze_policy_arn
}

output "teardown_lambda_name" {
  description = "Name of the nightly teardown Lambda."
  value       = module.finops.teardown_lambda_name
}

# ---- Phase 1 (null when enable_phase1 = false) ------------------------------

output "kinesis_stream_name" {
  description = "Name of the ais-raw Kinesis stream (Phase 1)."
  value       = one(module.kinesis[*].stream_name)
}

output "firehose_delivery_stream_name" {
  description = "Name of the ais-raw -> S3 Firehose delivery stream (Phase 1)."
  value       = one(module.firehose[*].delivery_stream_name)
}

output "rds_endpoint" {
  description = "Postgres endpoint address (Phase 1)."
  value       = one(module.rds[*].db_endpoint)
}

output "rds_master_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credentials (Phase 1)."
  value       = one(module.rds[*].master_user_secret_arn)
}

output "serving_api_endpoint" {
  description = "API Gateway HTTP API invoke URL for the scorer (Phase 1)."
  value       = one(module.apigw[*].api_endpoint)
}

output "serving_ecr_repository_url" {
  description = "ECR repo URL for the serving image (Phase 1)."
  value       = one(module.ecs_serving[*].ecr_repository_url)
}

output "serving_cloudmap_dns" {
  description = "In-VPC DNS name for the scorer (Phase 1)."
  value       = one(module.ecs_serving[*].cloudmap_dns_name)
}

output "ingestor_task_definition_arn" {
  description = "Replay ingestor Fargate task definition ARN (Phase 1)."
  value       = one(module.ecs_ingestor[*].task_definition_arn)
}

output "flink_role_arn" {
  description = "Managed Flink service execution role ARN (Phase 1)."
  value       = one(module.kda_flink[*].role_arn)
}

output "phase1_dashboard_name" {
  description = "CloudWatch dashboard for the Phase 1 slice (Phase 1)."
  value       = one(module.observability[*].dashboard_name)
}
