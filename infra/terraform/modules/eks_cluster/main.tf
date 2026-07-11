# modules/eks_cluster
#
# Phase 5 gate 5.1: the EKS control plane that replaces ECS Fargate as the
# serving front door (locked decision in docs/phases/PHASE_5.md: same
# serving/Dockerfile image, same API-Gateway-over-VPC-Link shape, only the
# orchestration substrate changes). Control plane only; the worker capacity
# lives in modules/eks_node_group (scale-to-zero spot, the GKE
# min_node_count=0 pattern's AWS equivalent). Whole-module gate at the
# envs/base call site (count = var.enable_phase5 ? 1 : 0), so the default
# plan is a zero diff by construction.
#
# COST WATCH: this is the one Phase 1-5 resource whose idle cost cannot be
# scaled to zero (~$73/mo flat, ~$0.10/hour, billed with zero nodes and zero
# pods; docs/phases/PHASE_1.md:41 is why EKS waited until Phase 5). The
# structural mitigation is modules/eks_teardown_guard (gate 5.0), which
# force-destroys this cluster after its max_age_hours window unless the
# keep_alive_until tag stamped below holds a future timestamp. The cluster
# name is the same deterministic "<project>-<environment>-eks" string the
# guard computes, shared via envs/base's phase5_cluster_name local, so the
# two can never disagree and the guard needs no dependency on this module.
#
# API endpoint posture: PRIVATE by default (endpoint_private_access = true,
# endpoint_public_access = false), in the Phase 1 VPC's private subnets per
# the gate spec. KNOWN LIMITATION, stated honestly: with a private-only
# endpoint, kubectl/helm (including the keda helm_release below) can only
# reach the API from inside the VPC. A demo window driven from the laptop
# either runs through an in-VPC hop or temporarily sets
# endpoint_public_access = true with a tight public_access_cidrs allowlist
# in tfvars; both defaults keep the authored posture private and checkov
# clean.
#
# KEDA install: a helm_release, count-gated behind var.install_keda (default
# false), SEPARATE from the module being instantiated. This is deliberate,
# not decorative. A Terraform provider block cannot be count-gated, and the
# helm provider needs live cluster credentials at PLAN time; configuring it
# from this module's outputs in the same apply that creates the cluster is
# the classic flaky chicken-and-egg. The clean story envs/base implements:
# the helm provider is configured from aws_eks_cluster/aws_eks_cluster_auth
# DATA sources that only exist while enable_phase5_keda = true, so a
# disabled-phase5 (or disabled-keda) plan never needs cluster credentials,
# and flipping enable_phase5_keda on is a documented SECOND apply after the
# cluster exists. Two-step, honest, and validate-safe at every toggle state.

locals {
  name_prefix = "${var.project}-${var.environment}"

  tags = merge(var.tags, {
    Module = "eks_cluster"
  })

  cluster_name   = var.cluster_name != "" ? var.cluster_name : "${local.name_prefix}-eks"
  log_group_name = "/aws/eks/${var.cluster_name != "" ? var.cluster_name : "${local.name_prefix}-eks"}/cluster"

  # The teardown guard's keep-alive contract (gate 5.0): a future ISO 8601
  # timestamp in this tag extends the demo window; empty stamps nothing.
  keep_alive_tags = var.keep_alive_until != "" ? { (var.keep_alive_tag_key) = var.keep_alive_until } : {}
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# -----------------------------------------------------------------------------
# Module-local CMK: EKS secrets-envelope encryption + the control-plane log
# group. Inline jsonencode per the modules/kms precedent (a key policy's
# Resource must be "*", and checkov flags wildcard-resource policy DOCUMENTS).
# -----------------------------------------------------------------------------

resource "aws_kms_key" "eks" {
  description             = "${local.name_prefix} CMK for EKS secrets encryption and control-plane logs"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AccountRootFullAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogsUse"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = [
              "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:${local.log_group_name}",
            ]
          }
        }
      },
    ]
  })

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-eks-cmk"
  })
}

resource "aws_kms_alias" "eks" {
  name          = "alias/${local.name_prefix}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

# -----------------------------------------------------------------------------
# IAM: cluster role + node role. The node role lives here (not in
# modules/eks_node_group) per the gate spec, so one module owns every
# EKS-trust IAM surface and the node-group module stays pure capacity.
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "cluster_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name                 = "${local.name_prefix}-eks-cluster"
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null
  assume_role_policy   = data.aws_iam_policy_document.cluster_assume.json

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "node_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name                 = "${local.name_prefix}-eks-node"
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null
  assume_role_policy   = data.aws_iam_policy_document.node_assume.json

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_read" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# -----------------------------------------------------------------------------
# Control-plane log group, pre-created so retention and encryption are
# Terraform-owned (EKS would otherwise create it unmanaged, retain-forever).
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "cluster" {
  name              = local.log_group_name
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.eks.arn
  tags              = local.tags
}

# -----------------------------------------------------------------------------
# The control plane.
# -----------------------------------------------------------------------------

resource "aws_eks_cluster" "this" {
  name     = local.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.eks_version

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_public_access
    public_access_cidrs     = var.endpoint_public_access ? var.public_access_cidrs : null
  }

  encryption_config {
    resources = ["secrets"]

    provider {
      key_arn = aws_kms_key.eks.arn
    }
  }

  # All five control-plane log types: the M3 backpressure drill (gate 5.3)
  # reads authenticator/api latencies, and audit is table stakes for the
  # multi-tenant posture this phase exists to demonstrate.
  enabled_cluster_log_types = [
    "api",
    "audit",
    "authenticator",
    "controllerManager",
    "scheduler",
  ]

  tags = merge(local.tags, local.keep_alive_tags, {
    Name = local.cluster_name
  })

  depends_on = [
    aws_iam_role_policy_attachment.cluster_policy,
    aws_cloudwatch_log_group.cluster,
  ]
}

# -----------------------------------------------------------------------------
# KEDA, via the official Helm chart. Count-gated on install_keda (default
# false): the two-step provider story documented in the module header. wait
# is off because the node group starts at desired_size = 0 (scale-to-zero
# floor); with no schedulable node yet, a waiting helm_release would block
# the apply on pods that cannot start. The demo runbook bumps the node group
# to 1 and verifies the KEDA rollout before applying ScaledObjects.
# -----------------------------------------------------------------------------

resource "helm_release" "keda" {
  count = var.install_keda ? 1 : 0

  name             = "keda"
  repository       = "https://kedacore.github.io/charts"
  chart            = "keda"
  version          = var.keda_chart_version
  namespace        = var.keda_namespace
  create_namespace = true

  wait    = false
  timeout = 600

  depends_on = [aws_eks_cluster.this]
}
