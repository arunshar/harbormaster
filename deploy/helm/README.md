# deploy/helm

Kubernetes deployment assets for Harbormaster's serving plane.

**Lands in:** Phase 2 (Serving).

**Will contain:** Helm charts for the EKS-hosted GeoTrace front door (the inline spatial detectors STAGD, TGARD, and S-KBM), plus the supporting Kubernetes manifests (service accounts with IRSA, horizontal pod autoscaling, ingress, and config for reaching the SageMaker async multi-model endpoint that serves Pi-DPM). Values files will be parameterized per environment (`base`, `demo`) and will follow the shared conventions: `project`, `environment`, `aws_region`, and the common tags.

Empty for now. Phase 0 provisions only foundations and FinOps guardrails; no compute clusters are created yet.
