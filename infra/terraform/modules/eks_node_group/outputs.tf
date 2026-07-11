# modules/eks_node_group/outputs.tf

output "node_group_name" {
  description = "Name of the spot node group."
  value       = aws_eks_node_group.this.node_group_name
}

output "node_group_arn" {
  description = "ARN of the spot node group."
  value       = aws_eks_node_group.this.arn
}

output "node_group_status" {
  description = "Lifecycle status of the node group."
  value       = aws_eks_node_group.this.status
}
