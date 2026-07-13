# deploy/k8s/serving (Phase 5, gate 5.2)

The EKS serving front door: the SAME container image as the ECS Fargate
service (`serving/Dockerfile`, unmodified) as a `Deployment` + fixed
`NodePort` Service, scaled by a KEDA `ScaledObject` with
`minReplicaCount: 0`, the pod scale-to-zero floor a bare HPA cannot express.
Terraform owns the internal NLB, its instance target group, and the API
Gateway listener wiring in `modules/eks_frontdoor`.

Layout:

- `base/` is complete on its own: namespace, deployment, service, and the
  ScaledObject with the Kinesis lag trigger (an `aws-cloudwatch` trigger on
  `GetRecords.IteratorAgeMilliseconds` for the Phase 1 `ais-raw` stream; see
  the trigger-choice note in `base/scaledobject-kinesis.yaml` for why the
  `aws-kinesis-stream` scaler, which scales on shard count and can never
  reach zero, is not used).
- `with-cdc/` overlays the Phase 2 Kafka trigger (CDC consumer-group lag,
  group `hm-cdc-consumer`) as a JSON6902 patch appending to the SAME
  ScaledObject, because KEDA rejects a second ScaledObject on one
  scaleTargetRef. Apply it only when `enable_phase2` infrastructure exists,
  after substituting the real MSK bootstrap endpoint for
  `PLACEHOLDER_MSK_BOOTSTRAP:9098`.
- `golden/` holds the committed `kubectl kustomize` outputs of both
  variants, the gate 5.2 checksum; `tests/e2e/test_phase5_k8s_manifests.py`
  rebuilds and compares semantically when a kustomize binary is available
  and always validates the structure with a pure YAML parse.

Build:

    kubectl kustomize deploy/k8s/serving/base
    kubectl kustomize deploy/k8s/serving/with-cdc

The tracked Deployment contains a non-runnable `.invalid` zero-digest
sentinel. Render a live manifest only from an immutable ECR digest (no
account id or mutable tag is committed):

    make phase5-render-serving \
      IMAGE=<acct>.dkr.ecr.us-east-1.amazonaws.com/harbormaster-base-serving@sha256:<digest> \
      OUTPUT=/tmp/w4-serving.yaml

Rollback path: the ECS Fargate service is NOT deleted by this gate. The API
Gateway proxy route retargets via envs/base's `serving_target` variable
(`ecs` by default, `eks` only during W4). The EKS integration URI comes
directly from `module.eks_frontdoor[0].listener_arn`; operators never paste
or discover it out of band. Flipping the target back to `ecs` is the
rollback, with the Fargate service still running behind it.

Dry-run verification without AWS (the gate 5.2 smoke): create a kind
cluster, install the KEDA CRDs only (no operator, no images, no cloud), and
apply both variants; the ScaledObject is schema-validated server-side and
sits inert without the operator:

    kind create cluster --name hm-phase5-dryrun
    kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.20.0/keda-2.20.0-crds.yaml
    kubectl apply -k deploy/k8s/serving/base
    kubectl -n hm-serving get scaledobject serving-scaler -o yaml
    kind delete cluster --name hm-phase5-dryrun
