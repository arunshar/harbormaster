# Harbormaster Makefile
# All Terraform targets operate on the base environment.
# Hard cost cap for the whole platform is $75/month, enforced by the FinOps
# module's budget action (IAM deny policy on the platform role). A $30 soft
# budget sends SNS alerts at $5 / $15 / $25 actual and $30 forecast.

TF_DIR := infra/terraform/envs/base
COST_CAP := 75

.PHONY: help fmt init validate plan apply destroy cost \
        serve-install serve-lint serve-test serve-run serve-fixture serve-docker flink-package e2e

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

serve-lint:           ## ruff lint serving + streaming + cdc + tests
	$(PY) -m ruff check serving streaming cdc tests

serve-test:           ## run the unit + golden test suite
	$(PY) -m pytest -q

serve-fixture:        ## regenerate the recorded AIS replay fixture + expectations + sha
	PYTHONPATH=streaming $(PY) -m replay.generate

serve-run:            ## run the scoring API locally on :8000
	PYTHONPATH=serving $(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000

serve-docker:         ## build the serving container image (build context = repo root)
	docker build -f serving/Dockerfile -t harbormaster-serving:dev .

flink-package:        ## package the PyFlink feature job for Managed Flink -> dist/flink-app.zip
	rm -rf dist/flink-app && mkdir -p dist/flink-app/flink dist/flink-app/features
	cp streaming/flink/*.py streaming/flink/requirements.txt dist/flink-app/flink/
	cp streaming/features/*.py dist/flink-app/features/
	cd dist/flink-app && zip -qr ../flink-app.zip flink features
	@echo "packaged dist/flink-app.zip -> upload to the models bucket, set flink_code_s3_key on"

e2e:                  ## Phase 1 e2e acceptance against a live demo apply (needs HM_E2E=1 + SERVING_URL)
	HM_E2E=1 $(PY) -m pytest tests/e2e/test_phase1.py -v
