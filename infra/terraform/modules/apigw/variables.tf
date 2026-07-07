# modules/apigw/variables.tf
#
# Inputs for the serving HTTP API and its hardening controls (throttling, access
# logging, authorization, WAF). Every hardening variable defaults to a safe,
# no-new-spend posture so envs/base validates unchanged and nothing costly is
# forced on at rest.

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

variable "cloudmap_service_arn" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

# --- Throttling (stage-level default route settings) -------------------------
# Non-zero defaults so the public endpoint is never unbounded. These bound
# requests per second and the burst bucket for the $default stage's default
# route. They do not add cost; they only cap throughput.

variable "throttling_rate_limit" {
  description = "Steady-state request rate cap (requests/second) for the default route."
  type        = number
  default     = 50
}

variable "throttling_burst_limit" {
  description = "Burst bucket size (requests) for the default route."
  type        = number
  default     = 100
}

# --- Access logging ----------------------------------------------------------
# A dedicated CloudWatch log group receives structured JSON access logs. A
# 14-day retention keeps storage cheap. This is a few cents of cost at low
# volume, so it is opt-out via a flag but defaults on for auditability.

variable "enable_access_logging" {
  description = "Emit structured JSON access logs to CloudWatch for the stage."
  type        = bool
  default     = true
}

variable "access_log_retention_days" {
  description = "CloudWatch log-group retention (days) for API access logs."
  type        = number
  default     = 14
}

# --- Authorization -----------------------------------------------------------
# authorization_mode picks the posture for the proxy route:
#   "AWS_IAM" (default) - SigV4 IAM authorization. Free for HTTP APIs; callers
#                         must sign requests with IAM credentials. Safe default:
#                         the route is not anonymously open.
#   "JWT"     - JWT authorizer (e.g. Cognito / any OIDC issuer). Requires
#               jwt_issuer and jwt_audience; also free (no Lambda invoke cost).
#   "NONE"    - explicitly anonymous. Author-only escape hatch; not recommended.
# Defaulting to AWS_IAM closes the "no authorizer" gap without new spend and
# without standing up an identity provider.

variable "authorization_mode" {
  description = "Route authorization posture: AWS_IAM, JWT, or NONE."
  type        = string
  default     = "AWS_IAM"

  validation {
    condition     = contains(["AWS_IAM", "JWT", "NONE"], var.authorization_mode)
    error_message = "authorization_mode must be one of: AWS_IAM, JWT, NONE."
  }
}

variable "jwt_issuer" {
  description = "OIDC issuer URL for the JWT authorizer (required when authorization_mode = JWT)."
  type        = string
  default     = ""
}

variable "jwt_audience" {
  description = "Allowed audiences (client IDs) for the JWT authorizer (required when authorization_mode = JWT)."
  type        = list(string)
  default     = []
}

# --- WAF ---------------------------------------------------------------------
# WAF has a standing per-web-ACL and per-rule cost, so it is authored but off by
# default. Flip enable_waf to true (and apply) to attach a managed-rule web ACL
# to the stage. Kept minimal: AWS common rule set plus a rate-based rule.

variable "enable_waf" {
  description = "Create and associate a WAFv2 web ACL with the stage (has cost; off by default)."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "5-minute request ceiling per source IP for the WAF rate-based rule."
  type        = number
  default     = 2000
}
