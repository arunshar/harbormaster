# envs/base/variables.tf
#
# Root-level variables for the Harbormaster "base" environment. Values come from
# terraform.tfvars (copy terraform.tfvars.example). Nothing here contains a real
# account id or secret.

variable "project" {
  description = "Project name, propagated to every module and the common tags."
  type        = string
  default     = "harbormaster"
}

variable "environment" {
  description = "Deployment environment for this root. Fixed to base here."
  type        = string
  default     = "base"

  validation {
    condition     = contains(["base", "demo"], var.environment)
    error_message = "environment must be one of: base, demo."
  }
}

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "alert_email" {
  description = "Email subscribed to budget and anomaly alerts. AWS sends a one-time confirmation link."
  type        = string
}

variable "platform_role_name" {
  description = <<-EOT
    Name of the IAM role the $75 hard-budget action attaches the deny policy to
    on breach. Must be an existing role used by your platform/CI to create
    spend-incurring resources. Phase 0 does not create this role for you; pass
    the name of a role you control.
  EOT
  type        = string
}

variable "enable_nat" {
  description = "Create the single NAT gateway in the network module. Default false to avoid the hourly charge."
  type        = bool
  default     = false
}

variable "enable_nightly_teardown" {
  description = "Create the EventBridge schedule that runs the teardown Lambda nightly."
  type        = bool
  default     = true
}

variable "teardown_dry_run" {
  description = "When true, the teardown Lambda only logs what it would tear down. Keep true until you trust it."
  type        = bool
  default     = true
}

variable "cost_anomaly_monitor_arn" {
  description = <<-EOT
    Reuse an existing Cost Explorer SERVICE anomaly monitor instead of creating one.
    AWS allows only one dimensional SERVICE monitor per account and auto-creates a
    "Default-Services-Monitor", so set this to that monitor's ARN on such accounts.
    Empty creates our own monitor.
  EOT
  type        = string
  default     = ""
}
