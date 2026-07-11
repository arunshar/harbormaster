# modules/eks_node_group
#
# Phase 5 gate 5.1: the scale-to-zero worker capacity behind the EKS front
# door. This is the AWS-provider equivalent of the pattern pcrf-monorepo
# actually ships on GKE (google_container_node_pool.gpu with
# min_node_count = 0, "scales to zero when idle"), mirrored as a PATTERN,
# not a resource port, per the PHASE_5.md anchor fact-check:
# aws_eks_node_group with scaling_config { min_size = 0, max_size = 3,
# desired_size = 0 }. Spot capacity, matching the platform's standing
# "spot everywhere non-critical" FinOps principle (the ECS serving service
# already runs FARGATE_SPOT).
#
# desired_size is the demo-window knob: it starts at 0 so an apply creates
# NO EC2 instance and no compute cost, the runbook bumps it (or a cluster
# autoscaler does) when KEDA needs somewhere to schedule, and lifecycle
# ignores its drift so the next plan never fights the scaler, the exact
# convention modules/ecs_serving established for its autoscaled
# desired_count. The IAM node role lives in modules/eks_cluster (one module
# owns every EKS-trust IAM surface); this module is pure capacity.
#
# Whole-module gate at the envs/base call site (count = var.enable_phase5 ?
# 1 : 0), so the default plan stays a zero diff by construction.

locals {
  name_prefix = "${var.project}-${var.environment}"

  tags = merge(var.tags, {
    Module = "eks_node_group"
  })
}

resource "aws_eks_node_group" "this" {
  cluster_name    = var.cluster_name
  node_group_name = "${local.name_prefix}-serving-spot"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.private_subnet_ids

  capacity_type  = "SPOT"
  instance_types = var.instance_types
  disk_size      = var.disk_size

  scaling_config {
    min_size     = var.min_size
    max_size     = var.max_size
    desired_size = var.desired_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    "harbormaster.io/pool" = "serving"
  }

  tags = merge(local.tags, {
    Name = "${local.name_prefix}-serving-spot"
  })

  # The scaler (or the demo runbook) owns desired_size after creation; a
  # plan must never scale a live demo back down mid-window (or up mid-idle).
  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}
