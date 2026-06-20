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
