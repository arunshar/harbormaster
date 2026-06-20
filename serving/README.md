# serving

Model serving and the inference front door for Harbormaster.

**Lands in:** Phase 2 (Serving).

**Will contain:** the GeoTrace front-door service (request handling, feature lookup from the online store, inline execution of the lightweight spatial detectors STAGD / TGARD / S-KBM) and the integration with the SageMaker asynchronous multi-model endpoint that serves the heavy Pi-DPM diffusion model. Models are trained on MSI and promoted into this plane across the model-promotion boundary; there is no GPU on AWS. An optional Bedrock layer generates natural-language explanations of already-detected anomalies (explanation only, never the detection decision). War stories P4 (async endpoint dropping bursts) and P5 (online store throttling on cold reads) anticipate the failure modes this code handles.

Empty for now. Phase 0 provisions only foundations and FinOps guardrails.
