# modules/state_stores/variables.tf

variable "project" {
  description = "Project name, used in tags and bucket/table names."
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

variable "lake_noncurrent_expiration_days" {
  description = "Days after which noncurrent (versioned) lake object versions expire."
  type        = number
  default     = 30
}

variable "raw_transition_ia_days" {
  description = "Days after which raw/ objects transition to S3 Standard-IA to cut storage cost."
  type        = number
  default     = 30
}

variable "abort_multipart_days" {
  description = "Days after which incomplete multipart uploads are aborted (avoids paying for orphaned parts)."
  type        = number
  default     = 7
}

variable "feast_online_table_ttl_enabled" {
  description = "Whether to enable a TTL attribute on the Feast online DynamoDB table."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags applied to every resource."
  type        = map(string)
  default     = {}
}
