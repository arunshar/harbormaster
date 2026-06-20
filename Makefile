# Harbormaster Makefile
# All Terraform targets operate on the base environment.
# Hard cost cap for the whole platform is $75/month, enforced by the FinOps
# module's budget action (IAM deny policy on the platform role). A $30 soft
# budget sends SNS alerts at $5 / $15 / $25 actual and $30 forecast.

TF_DIR := infra/terraform/envs/base
COST_CAP := 75

.PHONY: help fmt validate plan apply destroy cost

help:
	@echo "Harbormaster Phase 0 targets (operate on $(TF_DIR)):"
	@echo "  make fmt       - terraform fmt (recursive)"
	@echo "  make validate  - terraform init -backend=false + terraform validate"
	@echo "  make plan      - terraform plan"
	@echo "  make apply     - terraform apply (prints a confirmation prompt first)"
	@echo "  make destroy   - terraform destroy (prints a confirmation prompt first)"
	@echo "  make cost      - print the hard cost cap reminder"
	@echo ""
	@$(MAKE) --no-print-directory cost

cost:
	@echo "==> Harbormaster hard cost cap: $$$(COST_CAP)/month."
	@echo "    Hard cap: aws_budgets_budget_action attaches an IAM deny policy to the platform role on breach."
	@echo "    Soft budget: \$$30/month, SNS alerts at \$$5 / \$$15 / \$$25 actual and \$$30 forecast."

fmt:
	terraform -chdir=$(TF_DIR) fmt -recursive

validate:
	terraform -chdir=$(TF_DIR) init -backend=false -input=false
	terraform -chdir=$(TF_DIR) validate

plan:
	@$(MAKE) --no-print-directory cost
	terraform -chdir=$(TF_DIR) plan

apply:
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
