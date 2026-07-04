# Harbormaster Makefile
# All Terraform targets operate on the base environment.
# Hard cost cap for the whole platform is $75/month, enforced by the FinOps
# module's budget action (IAM deny policy on the platform role). A $30 soft
# budget sends SNS alerts at $5 / $15 / $25 actual and $30 forecast.

TF_DIR := infra/terraform/envs/base
COST_CAP := 75

.PHONY: help fmt init validate plan apply destroy cost \
        serve-install serve-lint serve-test serve-run serve-fixture serve-docker flink-jar flink-package e2e \
        cdc-up cdc-down cdc-smoke cdc-consumer cdc-lambda-package cdc-e2e \
        lake-quality-smoke lake-backfill-smoke lake-training-export-smoke \
        drill-l1-training-serving-skew drill-l2-canary-rollback lake-e2e \
        pidpm-demo-checkpoint lake-package lake-package-venv drift-smoke \
        drift-lambda-package drill-l3-drift-classification drill-l4-reward-hacking phase4-e2e

help:
	@echo "Harbormaster Phase 0 targets (operate on $(TF_DIR)):"
	@echo "  make fmt       - terraform fmt (recursive)"
	@echo "  make init      - terraform init (local backend; run once before plan/apply)"
	@echo "  make validate  - terraform validate (isolated; no creds or backend needed)"
	@echo "  make plan      - terraform init + terraform plan"
	@echo "  make apply     - terraform apply (prints a confirmation prompt first)"
	@echo "  make destroy   - terraform destroy (prints a confirmation prompt first)"
	@echo "  make cost      - print the hard cost cap reminder"
	@echo ""
	@$(MAKE) --no-print-directory cost

cost:
	@echo "==> Harbormaster hard cost cap: \$$$(COST_CAP)/month."
	@echo "    Hard cap: aws_budgets_budget_action attaches an IAM deny policy to the platform role on breach."
	@echo "    Soft budget: \$$30/month, SNS alerts at \$$5 / \$$15 / \$$25 actual and \$$30 forecast."

fmt:
	terraform -chdir=$(TF_DIR) fmt -recursive

init:
	terraform -chdir=$(TF_DIR) init -input=false

# validate runs in an isolated data dir (TF_DATA_DIR) so it never leaves the real
# .terraform without a backend, which would otherwise break a later plan/apply.
validate:
	TF_DATA_DIR=.terraform.validate terraform -chdir=$(TF_DIR) init -backend=false -input=false
	TF_DATA_DIR=.terraform.validate terraform -chdir=$(TF_DIR) validate

plan: init
	@$(MAKE) --no-print-directory cost
	terraform -chdir=$(TF_DIR) plan

apply: init
	@$(MAKE) --no-print-directory cost
	@echo ""
	@echo "WARNING: 'make apply' will create real AWS resources and may incur cost."
	@echo "The \$$$(COST_CAP)/month hard cap is enforced by the FinOps module, but apply against"
	@echo "your own account only after reviewing 'make plan'."
	@printf "Type 'yes' to continue: " && read confirm && [ "$$confirm" = "yes" ] || (echo "Aborted." && exit 1)
	terraform -chdir=$(TF_DIR) apply

destroy:
	@echo "WARNING: 'make destroy' will delete the Harbormaster base environment resources."
	@printf "Type 'yes' to continue: " && read confirm && [ "$$confirm" = "yes" ] || (echo "Aborted." && exit 1)
	terraform -chdir=$(TF_DIR) destroy

# ---- Serving plane (Phase 1 vertical slice; no AWS, no cost) ----
# Local Python toolchain for the deterministic AIS scorer in serving/ + streaming/.
VENV := .venv
PY := $(VENV)/bin/python

serve-install:        ## create .venv and install the serving package + dev deps
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

serve-lint:           ## ruff lint serving + streaming + cdc + lake + tests
	$(PY) -m ruff check serving streaming cdc lake tests

serve-test:           ## run the unit + golden test suite
	$(PY) -m pytest -q

serve-fixture:        ## regenerate the recorded AIS replay fixture + expectations + sha
	PYTHONPATH=streaming $(PY) -m replay.generate

serve-run:            ## run the scoring API locally on :8000
	PYTHONPATH=serving $(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

serve-run-cdc:        ## run the scoring API wired to the local CDC stack (Phase 2 env)
	HM_PG_DSN=postgresql://hm_admin:hm_local_pw@127.0.0.1:30432/harbormaster \
	HM_ONLINE_TABLE=hm-local-feast-online HM_DDB_ENDPOINT_URL=http://127.0.0.1:30800 \
	HM_REDIS_URL=redis://127.0.0.1:30379/0 \
	PYTHONPATH=serving $(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

serve-docker:         ## build the serving container image (build context = repo root)
	docker build -f serving/Dockerfile -t harbormaster-serving:dev .

flink-jar:            ## build the Kinesis-connector fat-jar via Maven in Docker -> streaming/flink/target/pyflink-dependencies.jar
	docker run --rm -v "$$(pwd)/streaming/flink":/build -w /build maven:3-eclipse-temurin-11 mvn -q -B package

flink-package: flink-jar  ## package the PyFlink feature job for Managed Flink -> dist/flink-app.zip
	rm -rf dist/flink-app dist/flink-app.zip && mkdir -p dist/flink-app/lib
	cp streaming/flink/job.py dist/flink-app/main.py
	cp streaming/flink/requirements.txt dist/flink-app/requirements.txt
	cp streaming/flink/target/pyflink-dependencies.jar dist/flink-app/lib/
	cd dist/flink-app && zip -qr ../flink-app.zip main.py requirements.txt lib
	@echo "packaged dist/flink-app.zip (main.py at root + lib/pyflink-dependencies.jar) -> upload to the lake bucket, set flink_code_s3_key on"

e2e:                  ## Phase 1 e2e acceptance against a live demo apply (needs HM_E2E=1 + SERVING_URL)
	HM_E2E=1 $(PY) -m pytest tests/e2e/test_phase1.py -v

# ---- CDC plane (Phase 2; local kind/Strimzi stack, $0) ----
KIND_CLUSTER := hm-cdc
# 1.1.0: 0.45.x's bundled fabric8 client cannot parse the /version response of
# current Kubernetes (unknown field emulationMajor on kind v0.32 / k8s 1.36)
# and crash-loops; 1.x also moves the CRs to kafka.strimzi.io/v1 (20-kafka.yaml).
STRIMZI_VERSION := 1.1.0
STRIMZI_URL := https://github.com/strimzi/strimzi-kafka-operator/releases/download/$(STRIMZI_VERSION)/strimzi-cluster-operator-$(STRIMZI_VERSION).yaml

cdc-up:               ## create the local CDC stack (kind + Strimzi Kafka + Debezium + pg + redis + ddb-local)
	kind create cluster --config deploy/k8s/cdc/kind-config.yaml || true
	kubectl apply -f deploy/k8s/cdc/00-namespace.yaml
	curl -sL $(STRIMZI_URL) | sed 's/namespace: myproject/namespace: hm-cdc/' | kubectl apply -n hm-cdc -f -
	kubectl apply -f deploy/k8s/cdc/10-postgres.yaml -f deploy/k8s/cdc/11-redis.yaml -f deploy/k8s/cdc/12-dynamodb-local.yaml
	kubectl wait -n hm-cdc --for=condition=Available deploy/strimzi-cluster-operator --timeout=300s
	kubectl apply -f deploy/k8s/cdc/20-kafka.yaml
	kubectl wait -n hm-cdc --for=condition=Ready kafka/hm --timeout=600s
	kubectl apply -f deploy/k8s/cdc/30-connect.yaml
	kubectl wait -n hm-cdc --for=condition=Available deploy/debezium-connect --timeout=300s
	@echo "local CDC stack is up (kafka :30092, connect :30083, pg :30432, redis :30379, ddb :30800)"

cdc-down:             ## delete the local CDC stack
	kind delete cluster --name $(KIND_CLUSTER)

cdc-smoke:            ## insert-to-online latency smoke against the local stack (needs cdc-up)
	$(PY) scripts/cdc_smoke.py

cdc-consumer:         ## run the CDC consumer against the local stack
	HM_KAFKA_BOOTSTRAP=127.0.0.1:30092 HM_ONLINE_TABLE=hm-local-feast-online \
	HM_DDB_ENDPOINT_URL=http://127.0.0.1:30800 HM_REDIS_URL=redis://127.0.0.1:30379/0 \
	$(PY) -m cdc.consumer.service

LAMBDA_BUILD := infra/lambda/cdc_slot_lag/build

cdc-e2e:              ## Phase 2 e2e acceptance against a running CDC stack (local defaults)
	HM_CDC_E2E=1 \
	SERVING_URL=$${SERVING_URL:-http://localhost:8000} \
	HM_ONLINE_TABLE=$${HM_ONLINE_TABLE:-hm-local-feast-online} \
	HM_DDB_ENDPOINT_URL=$${HM_DDB_ENDPOINT_URL:-http://127.0.0.1:30800} \
	HM_KAFKA_BOOTSTRAP=$${HM_KAFKA_BOOTSTRAP:-127.0.0.1:30092} \
	HM_REDIS_URL=$${HM_REDIS_URL:-redis://127.0.0.1:30379/0} \
	HM_CDC_PG_DSN=$${HM_CDC_PG_DSN:-postgresql://hm_admin:hm_local_pw@127.0.0.1:30432/harbormaster} \
	HM_CDC_RESTART_CMD=$${HM_CDC_RESTART_CMD:-kubectl -n hm-cdc rollout restart deploy/debezium-connect && kubectl -n hm-cdc rollout status deploy/debezium-connect --timeout=240s} \
	$(PY) -m pytest tests/e2e/test_phase2.py -v

cdc-lambda-package:   ## vendor pg8000 + the shared monitor into the slot-lag Lambda build dir
	rm -rf $(LAMBDA_BUILD) && mkdir -p $(LAMBDA_BUILD)
	cp infra/lambda/cdc_slot_lag/handler.py cdc/monitor/slot_lag.py $(LAMBDA_BUILD)/
	$(PY) -m pip install --quiet --target $(LAMBDA_BUILD) "pg8000>=1.31"
	@echo "packaged $(LAMBDA_BUILD); terraform archives it via modules/cdc_monitoring"

# ---- Lake + promotion plane (Phase 3; pure Python locally, no JVM, $0) ----
# Real Spark/EMR requires a JVM this dev machine does not have (see the
# no-local-JVM finding in docs/phases/PHASE_3.md); every gate here runs the
# same transform functions lake/backfill/job.py calls on EMR, in plain Python.

lake-quality-smoke:   ## run the MarineCadastre GE suite against the committed fixture
	$(PY) scripts/lake_quality_smoke.py

lake-backfill-smoke:  ## GE gate -> transforms -> real Iceberg write, end to end, no Spark
	$(PY) scripts/lake_backfill_smoke.py

lake-training-export-smoke: ## point-in-time training-set export against the committed fixture
	$(PY) scripts/lake_training_export_smoke.py

drill-l1-training-serving-skew: ## drill: holdout passes a skew, shadow catches it (docs/drills/L1)
	$(PY) scripts/drill_l1_training_serving_skew.py

drill-l2-canary-rollback:       ## drill: clean gate+shadow, canary catches a regression + reverts (docs/drills/L2)
	$(PY) scripts/drill_l2_canary_rollback.py

lake-e2e:             ## Phase 3 e2e acceptance: all 5 criteria, pure functions + fakes, no live stack
	$(PY) -m pytest tests/e2e/test_phase3.py tests/e2e/test_lake_helpers.py -v

pidpm-demo-checkpoint: ## build the DEMO STAND-IN Pi-DPM checkpoint tar.gz (not real Pi-DPM)
	$(PY) scripts/build_demo_pidpm_checkpoint.py

lake-package:         ## package the EMR backfill entrypoint + --py-files zip -> dist/lake-emr/
	bash scripts/package_lake_for_emr.sh

lake-package-venv:    ## lake-package + linux/amd64 venv archive via Docker (pulls the EMR image, slow)
	bash scripts/package_lake_for_emr.sh --with-venv

# ---- Phase 4: drift -> HITL -> RL flywheel (pure Python locally, no AWS, $0) ----

drift-smoke:          ## gate 4.1: check_input_drift against the committed fixture pair
	$(PY) scripts/drift_smoke.py

DRIFT_LAMBDA_BUILD := infra/lambda/drift_watch/build

drift-lambda-package: ## gate 4.6: vendor mlops/drift.py + pandas/pyarrow into the drift-watch Lambda build dir
	rm -rf $(DRIFT_LAMBDA_BUILD) && mkdir -p $(DRIFT_LAMBDA_BUILD)/mlops
	cp infra/lambda/drift_watch/handler.py $(DRIFT_LAMBDA_BUILD)/
	cp mlops/__init__.py mlops/drift.py $(DRIFT_LAMBDA_BUILD)/mlops/
	$(PY) -m pip install --quiet --target $(DRIFT_LAMBDA_BUILD) -r infra/lambda/drift_watch/requirements.txt
	@echo "packaged $(DRIFT_LAMBDA_BUILD); terraform archives it via modules/drift_watch (not applied this sprint)"

drill-l3-drift-classification: ## drill: all 4 decision-table rows classify correctly, incl. the false-alarm row (docs/drills/L3)
	$(PY) scripts/drill_l3_drift_classification.py

drill-l4-reward-hacking:       ## drill: a gamed candidate is blocked before shadow, an honest one promotes (docs/drills/L4)
	$(PY) scripts/drill_l4_reward_hacking.py

phase4-e2e:           ## Phase 4 e2e acceptance: all 5 criteria, pure functions + fakes, no live stack
	$(PY) -m pytest tests/e2e/test_phase4.py -v
