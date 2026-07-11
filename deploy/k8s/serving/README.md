# deploy/k8s/serving (Phase 5, gate 5.2)

The EKS serving front door: the SAME container image as the ECS Fargate
service (`serving/Dockerfile`, unmodified) as a `Deployment` + ClusterIP
`Service`, scaled by a KEDA `ScaledObject` with `minReplicaCount: 0`, the
scale-to-zero floor a bare HPA cannot express.

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

Image substitution happens ONLY via the base kustomization's `images:`
transform (no account id is committed):

    cd deploy/k8s/serving/base
    kustomize edit set image harbormaster-serving=<acct>.dkr.ecr.us-east-1.amazonaws.com/harbormaster-base-serving:latest

Rollback path: the ECS Fargate service is NOT deleted by this gate. The API
Gateway proxy route retargets via `modules/apigw`'s `serving_target`
variable ("ecs" by default, "eks" plus `eks_integration_uri` for the new
path); flipping it back to "ecs" is the rollback, with the Fargate service
still running behind it. An HTTP API VPC Link can only target an ELB
listener or Cloud Map service ARN, so `eks_integration_uri` takes the ARN of
whichever of those fronts the `serving` Service at demo time.

Dry-run verification without AWS (the gate 5.2 smoke): create a kind
cluster, install the KEDA CRDs only (no operator, no images, no cloud), and
apply both variants; the ScaledObject is schema-validated server-side and
sits inert without the operator:

    kind create cluster --name hm-phase5-dryrun
    kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.15.1/keda-2.15.1-crds.yaml
    kubectl apply -k deploy/k8s/serving/base
    kubectl -n hm-serving get scaledobject serving-scaler -o yaml
    kind delete cluster --name hm-phase5-dryrun
