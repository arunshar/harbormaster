# Databricks Production Arc to Harbormaster: a study-to-build map

> **What this is.** This maps the managed-Databricks production patterns I studied
> (in the six Databricks Academy courses and the five local scripts in this repo) to the
> AWS-native components I am building in **Harbormaster**, my personal maritime
> anomaly-detection platform. Harbormaster does **not** run on Databricks. This is a
> learning-to-building bridge, not a claim of Databricks production experience.

## The two arcs in one line each

- **Databricks production arc** (this repo): train + register -> build agent -> RAG ->
  evaluate -> serve -> monitor, all on the managed Databricks platform (MLflow registry,
  Unity Catalog, Model Serving, Lakehouse Monitoring).
- **Harbormaster** (AWS-native, hybrid train-on-MSI / serve-on-AWS, $75/mo cap): six
  phases, 0 FinOps guardrails, 1 production vertical slice, 2 CDC, 3 lake + promotion,
  4 drift -> HITL -> RL flywheel, 5 multi-tenant + FDE.

The point of the map: every managed button in Databricks corresponds to something I build
by hand on AWS. Knowing both lets me say "I evaluated the managed pattern and chose the
self-hosted equivalent because X," which is the senior signal.

## Phase mapping (the spine)

| Databricks course (local script) | Core concept | Harbormaster phase | AWS-native equivalent |
|---|---|---|---|
| ML at Scale (01) | distributed training + batch inference (`spark_udf`, pandas UDFs, HPO) | **Phase 3** (EMR PySpark backfill of MarineCadastre to Iceberg; MSI H100 training; point-in-time feature export) | EMR transient Spark (auto-terminate) + MSI Slurm/Apptainer for GPU; `spark_udf` batch becomes Flink async-IO / EMR batch |
| Advanced ML Operations | CI/CD, IaC (DABs), Workflows, champion/challenger A/B, Lakehouse Monitoring | **Phase 0** (Terraform IaC + FinOps) + **Phase 3** (promotion gate: shadow then canary, auto-rollback) | Terraform + Helm + GitHub Actions + GHCR + Argo CD; champion/challenger becomes SageMaker Model Registry promotion + shadow/canary on error budgets |
| Single-Agent Apps (02) | build + trace + register an agent (UC functions as tools, models-from-code) | **Phase 1** (the ECS Fargate GeoTrace front door orchestrates deterministic kernels; a HeuristicPlanner replaces the LLM planner) | deterministic agents (STAGD/TGARD/S-KBM) in geotrace-agent; tracing becomes OTel/X-Ray; models-from-code + register becomes W&B + SageMaker Registry |
| Retrieval Agents / RAG (03) | parse/chunk -> embed -> Vector Search -> retrieval tool -> grounded answer | **Corridor/Route-Graph stage** (domain retrieval: corridor graph nodes/edges) + **Phase 5** Bedrock explanation (retrieval over deterministic reasons) | corridor graph (RDP + HDBSCAN + NOAA ENC) as the structured knowledge base; Bedrock + optional vector store over reason templates. The loosest mapping: this is geospatial retrieval, not text RAG |
| Agent Evaluation (04) | judges (built-in/guideline/custom/trace-based), offline/online, human feedback / review app | **Phase 3** (MIRROR A/B/C/D holdout gate: AUC, CRPS, calibration ratio in [0.8, 1.2]) + **Phase 4** (reward-hacking probe = custom/trace judge; Streamlit HITL = review app; verdicts become preference triples) | MIRROR holdout eval (offline gate); reward-hacking probe (judges the process); Streamlit HITL = human feedback; statistical judges, deliberately not LLM-as-judge for the score |
| GenAI Deployment & Monitoring (05) | Model Serving, inference tables, provisioned throughput, Lakehouse Monitoring, drift | **Phase 1** (ECS serving + `cost_tracker` + Grafana SLOs + Iceberg event landing = the inference table) + **Phase 3** (SageMaker async MME = provisioned-throughput analog) + **Phase 4** (drift) + **Phase 5** (KEDA scale-to-zero, multi-tenant) | ECS Fargate / SageMaker async MME; inference table becomes Firehose -> S3/Iceberg + `cost_tracker`; Lakehouse Monitoring becomes SageMaker Model Monitor + Evidently + custom PSI/KS/calibration |

The tightest fit: **local script 05 (serve + sqlite inference table + monitoring
dashboard) maps almost one-to-one onto Harbormaster Phase 1's serving + observability**,
and script 05's tool-miss quality signal maps to an off-corridor / deterministic-reason
miss signal.

## Managed to self-hosted (the Rosetta table)

| Databricks (managed) | Harbormaster (self-hosted AWS) |
|---|---|
| MLflow Registry + `@champion` alias | W&B (lineage) + SageMaker Model Registry (promotion). Harbormaster cut MLflow on purpose |
| Unity Catalog (governance) | IAM + Glue Catalog + Iceberg + `tenant_id` row-level isolation |
| Delta tables | S3 + Apache Iceberg |
| Model Serving endpoint | ECS Fargate front door + SageMaker async MME (GPU head only) |
| Inference tables | Firehose -> S3/Iceberg payload landing + `cost_tracker` |
| Lakehouse Monitoring | SageMaker Model Monitor + Evidently + custom PSI/KS + signature calibration-drift |
| `mlflow.genai` judges + review app | MIRROR holdout gate + reward-hacking probe + Streamlit HITL |
| Vector Search + managed embeddings | corridor graph (+ Bedrock explanation with optional vector store) |
| `spark_udf` batch | Flink async-IO / EMR batch |
| DABs + Workflows | Terraform + Helm + GitHub Actions + Argo CD |
| `ai_query` / Foundation Model APIs | Bedrock (explanation layer only, never the score) |
| Provisioned throughput | SageMaker async MME, scale-to-zero, per-region |

## Deliberate divergences (the interview-grade stories)

Each of these is a place where I know the managed Databricks pattern and chose a different
AWS-native path for a reason worth defending:

1. **Cut MLflow** (Databricks' core) for W&B + SageMaker Registry. Avoids three-registry
   sprawl; uses AWS-native promotion gates. The cut is documented, not accidental.
2. **Strip the LLM from the scoring path** (deterministic kernels + a HeuristicPlanner).
   Databricks' agent courses are LLM-centric; Harbormaster's "agent" is deterministic for
   cost and defensibility. The LLM (Bedrock) only explains, it never computes a score.
3. **Kinesis + Managed Flink**, not Spark Structured Streaming or Delta Live Tables.
   Right tool per job for high-volume, keyed AIS telemetry with true event-time state.
4. **ECS Fargate**, not a managed Model Serving endpoint. The EKS control plane alone is
   roughly $73/mo and would consume the entire $75 cap; Fargate scales to zero cheaply.
5. **Statistical judges** (AUC / CRPS / calibration ratio, plus the unbounded hard-physics
   invariant), not LLM-as-judge for the score. Defensible, no hallucinated verdicts.

## What to actually port (concrete build actions)

- Reuse the **script 05 pattern** (log to an inference table, compute quality metrics,
  render a dashboard, plus the tool-miss = not-found-sentinel quality signal) to reinforce
  Harbormaster Phase 1's `cost_tracker` + Grafana board, and add an "off-corridor /
  reason-miss" quality metric alongside drift.
- New idea the Eval course suggests for **Phase 5**: self-evaluate the Bedrock explanation
  layer with a guardrail LLM-judge for *faithfulness* (does the explanation use only the
  deterministic reasons), mirroring script 04's guideline judge.
- The **champion/challenger + shadow/canary** discipline from Advanced ML Operations is
  exactly Phase 3's promotion gate; use the Deployment & Monitoring and ML Operations deep
  dives as the conceptual reference while wiring the SageMaker Registry promotion.

## How to use this map

When building each Harbormaster phase, open the corresponding deep-dive guide in the arc
repo for the managed reference implementation, then translate via the Rosetta table to the
AWS-native component. The divergences are talking points for interviews; the port list is
the actual to-do.
