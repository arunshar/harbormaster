# modules/eks_cluster/outputs.tf

output "cluster_name" {
  description = "Name of the EKS cluster (deterministic; matches the teardown guard's watched name)."
  value       = aws_eks_cluster.this.name
}

output "cluster_arn" {
  description = "ARN of the EKS cluster."
  value       = aws_eks_cluster.this.arn
}

output "cluster_endpoint" {
  description = "API server endpoint (private unless endpoint_public_access was flipped for a demo window)."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded cluster CA bundle."
  value       = aws_eks_cluster.this.certificate_authority[0].data
}

output "cluster_security_group_id" {
  description = "The EKS-managed cluster security group id."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "node_role_arn" {
  description = "IAM role ARN for worker nodes, consumed by modules/eks_node_group."
  value       = aws_iam_role.node.arn
}

output "kms_key_arn" {
  description = "Module-local CMK encrypting EKS secrets and the control-plane log group."
  value       = aws_kms_key.eks.arn
}
