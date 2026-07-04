#!/usr/bin/env bash
# W1 sprint window: push the serving + ingestor images to ECR, force a new
# ECS deployment, then package + upload the Flink job. Run from repo root:
#   bash scripts/w1_push_images.sh
set -euo pipefail

AWS_REGION=us-east-1
SERVING_REPO="645322802947.dkr.ecr.us-east-1.amazonaws.com/harbormaster-base-serving"
INGESTOR_REPO="645322802947.dkr.ecr.us-east-1.amazonaws.com/harbormaster-base-ingestor"
LAKE_BUCKET="harbormaster-base-lake-ce479d91"

echo "==> ECR login"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "${SERVING_REPO%%/*}"

echo "==> Tag + push serving"
docker tag harbormaster-serving:dev "${SERVING_REPO}:latest"
docker push "${SERVING_REPO}:latest"

echo "==> Tag + push ingestor"
docker tag harbormaster-ingestor:dev "${INGESTOR_REPO}:latest"
docker push "${INGESTOR_REPO}:latest"

echo "==> Force new ECS deployment (picks up the freshly pushed serving image)"
aws ecs update-service --region "$AWS_REGION" \
  --cluster harbormaster-base-cluster \
  --service harbormaster-base-serving --force-new-deployment >/dev/null
echo "    deployment triggered"

echo "==> Package + upload the Flink job"
make flink-package
aws s3 cp dist/flink-app.zip "s3://${LAKE_BUCKET}/flink/flink-app.zip" --region "$AWS_REGION"

echo "==> Done. Verify:"
echo "    aws ecr describe-images --region $AWS_REGION --repository-name harbormaster-base-serving --query 'imageDetails[].imageTags'"
echo "    aws ecr describe-images --region $AWS_REGION --repository-name harbormaster-base-ingestor --query 'imageDetails[].imageTags'"
