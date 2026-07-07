# versions.tf
#
# Provider pinning is mandatory for Harbormaster. War-story P8 (see
# PLATFORM_WAR_STORIES.md) is about provider drift forcing a destroy/replace
# cycle: an unpinned aws provider minor bump changed a default and Terraform
# planned a replacement of a stateful resource. We pin every provider here so a
# fresh `terraform init` on any machine resolves the same versions.
#
# This file declares the required Terraform CLI version and the providers used
# across the whole project (root and modules). Modules inherit these
# constraints through the configuration; they do not re-declare provider source
# or version (Terraform recommends a single required_providers block per
# configuration for the providers a module passes through).

terraform {
  required_version = ">= 1.9"

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
