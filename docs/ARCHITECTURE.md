# Architecture

Harbormaster is a hybrid system: a training plane on MSI (off-cloud, GPU-bearing) and a serving plane on AWS (managed, no GPU). The two planes meet at a model-promotion boundary: artifacts trained on MSI are exported and loaded by the AWS serving stack. This document covers the full topology and the opinionated tradeoffs behind it.

## Hybrid topology

```
                          TRAINING PLANE  (MSI, off-cloud, GPU)
  +-----------------------------------------------------------------------+
  |  Historical AIS (~600 GB)  -->  Slurm jobs (PyTorch, PhysicsNeMo)       |
  |  Trains: Pi-DPM diffusion, STAGD / TGARD / S-KBM spatial detectors      |
  |  Output: versioned model artifacts (weights + metadata)                |
  +-----------------------------------------------------------------------+
                                   |
                                   |  model promotion (export -> S3 model bucket -> registry)
                                   v
  =======================================================================
                          SERVING PLANE  (AWS, no GPU)
  =======================================================================

   AISStream (live AIS, ~150K ships)
        |
        v
   Fargate ingestor  (parse, normalize, dedupe)
        |
        v
   Kinesis Data Streams  (durable ordered transport)
        |
        +-----------------------------+
        v                             v
   Flink (KDA)                   Firehose
   streaming features            |
        |                        v
        v                   S3 + Iceberg  (lakehouse, partitioned, time-travel)
   Feast / DynamoDB
   (online feature store)
        |
        v
   ECS Fargate: GeoTrace front door
   (STAGD / TGARD / S-KBM detectors)
        |
        |  async, heavy model
        v
   SageMaker async inference (MME)  -->  Pi-DPM
        |
        v
   anomaly events + explanations

   RDS (Postgres)  --Debezium CDC-->  Kinesis  (change stream into the lakehouse)

   Observability:  metrics / traces / logs  -->  dashboards + alerting  (both planes)
   FinOps:         AWS Budgets  -->  $30 soft (SNS alerts) | $75 hard (deny policy on platform role)
```

## Plane responsibilities

**Training plane (MSI).** All GPU work. Heavy training on historical AIS produces the diffusion model (Pi-DPM) and the spatial detectors. MSI runs Slurm; jobs are submitted off-cloud. Nothing in the training plane runs on AWS, which is what keeps the AWS bill inside the $75 hard cap.

**Serving plane (AWS).** Everything live and low-latency. Live AIS comes in through AISStream, is normalized by a Fargate ingestor, and is put on Kinesis as the durable transport backbone. From Kinesis the data fans out two ways: into Flink for streaming feature computation (landing in Feast/DynamoDB as the online store), and into Firehose for batch landing into the S3/Iceberg lakehouse. The ECS Fargate-hosted GeoTrace front door serves the lightweight spatial detectors (STAGD, TGARD, S-KBM) inline and delegates the heavy Pi-DPM diffusion model to a SageMaker asynchronous multi-model endpoint. (EKS is a Phase 5 plan, not the current build; see `docs/phases/PHASE_1.md` and `docs/phases/PHASE_5.md`.) RDS plus Debezium provides CDC of operational state into the same lakehouse.

## Key tradeoffs (opinionated)

**Kinesis over MSK.** Kinesis Data Streams is the transport backbone, not self-managed Kafka (MSK). Rationale: at this scale (~150K ships, continental-scale, not petabyte) a fully managed, pay-per-shard stream removes broker operations entirely and fits the cost cap. MSK would mean paying for always-on brokers and managing them; that cost and operational load is not justified here. The tradeoff is less ecosystem flexibility and a 24h-to-365d retention ceiling, which is acceptable because the lakehouse is the system of record.

**Flink over Spark Structured Streaming.** Streaming feature computation uses Flink (via Kinesis Data Analytics), not Spark. Rationale: true event-at-a-time processing with real watermarks and event-time windows fits AIS, where out-of-order and late position reports are normal. Flink's keyed state and timers map cleanly onto per-vessel feature state. Spark's micro-batch model adds latency and makes per-vessel event-time logic harder. The tradeoff is a steeper operational learning curve, accepted deliberately because event-time correctness is a core requirement.

**Iceberg for the lakehouse.** S3 plus Apache Iceberg, not raw Parquet directories or Hive-style tables. Rationale: Iceberg gives schema evolution, hidden partitioning, snapshot isolation, and time-travel, which matter for a CDC sink and for reproducible training pulls back to MSI. The tradeoff is added catalog and maintenance machinery (snapshot expiry, compaction), accepted because correctness and reproducibility outweigh it.

**No GPU on AWS.** All GPU-bound training stays on MSI. Rationale: GPU instances are the single largest way to blow a $75 cap, and MSI provides the GPU capacity for free to the project. AWS serves; MSI trains. SageMaker async inference runs Pi-DPM on CPU-class or small managed compute, sized to stay within budget, and the async queue absorbs bursts so we never over-provision. The tradeoff is a model-promotion boundary to manage and higher inference latency for the heavy model, which the async (not real-time) endpoint design accommodates.

**Bedrock for explanation only (PLANNED, Phase 5, not yet deployed).** The natural-language explanation layer is a Phase 5 design item (see `PLATFORM_BOOK.md` section 10, gate 5.6); it is not built and not deployed today. As planned, where natural-language explanation of an anomaly is useful, it would be generated by Amazon Bedrock as an explanation layer over already-detected events. Rationale: the detection decision stays with the deterministic spatial models and Pi-DPM, which are auditable and physics-aware; Bedrock would never make the anomaly call, it would only narrate one. The tradeoff is that explanations are advisory text, not part of the detection contract, which is exactly the intent.

## Cost and provider posture

- The FinOps module is provisioned first and gates everything else: $30 soft budget with SNS alerts at $5/$15/$25 actual and $30 forecast, and a $75 hard cap whose budget action attaches an IAM deny policy to the platform role.
- Providers are pinned in `infra/terraform/versions.tf` (aws ~> 5.x, archive, random). This is a hard rule: war story P8 records provider drift forcing resource replacement, so the pin protects against silent breaking upgrades.
