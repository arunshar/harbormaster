# modules/eks_node_group/variables.tf

variable "project" {
  description = "Project name, used in tags and resource names."
  type        = string
  default     = "harbormaster"
}

variable "environment" {
  description = "Deployment environment: base or demo."
  type        = string

  validation {
    condition     = contains(["base", "demo"], var.environment)
    error_message = "environment must be one of: base, demo."
  }
}

variable "cluster_name" {
  description = "Name of the EKS cluster this node group joins (module.eks_cluster[0].cluster_name, which also orders creation after the control plane)."
  type        = string
}

variable "node_role_arn" {
  description = "Worker-node IAM role ARN (module.eks_cluster[0].node_role_arn; the role lives with the rest of the EKS IAM surface)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Phase 1 VPC private subnets the nodes launch into."
  type        = list(string)
}

variable "instance_types" {
  description = "Spot instance-type candidates. Two families so a single spot pool interruption cannot starve the group."
  type        = list(string)
  default     = ["t3.medium", "t3a.medium"]
}

variable "disk_size" {
  description = "Node root volume size in GiB."
  type        = number
  default     = 20
}

variable "min_size" {
  description = "Scale-to-zero floor. 0 is the point of the phase (the GKE min_node_count=0 pattern); raise only for a demo that cannot tolerate cold node starts."
  type        = number
  default     = 0

  validation {
    condition     = var.min_size >= 0
    error_message = "min_size must be >= 0."
  }
}

variable "max_size" {
  description = "Node ceiling, bounding the worst-case spot spend of a runaway scale-out."
  type        = number
  default     = 3
}

variable "desired_size" {
  description = "Initial desired capacity. 0 so an apply creates no instance; the demo runbook (or an autoscaler) bumps it, and lifecycle ignores the drift thereafter."
  type        = number
  default     = 0
}

variable "tags" {
  description = "Common tags applied to every resource."
  type        = map(string)
  default     = {}
}
