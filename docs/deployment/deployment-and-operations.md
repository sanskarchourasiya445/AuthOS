# AuthOS — Deployment and Operations Plan

**Status:** Local-development plan for a synthetic-data MVP. No deployment has been performed or verified.

## MVP operating model

- Local development via Docker Compose for PostgreSQL; frontend and FastAPI may run locally or as Compose services, as chosen during setup.
- Use synthetic data only.
- No Kubernetes, microservices, Redis, external EHR or payer integrations in the MVP.
- LLM and embedding providers are external dependencies unless a local model is explicitly selected and tested.

## Configuration

Provide `.env.example` with documented placeholders for database URL, LLM provider/API key, model identifier, embedding provider/model, embedding dimension, retry cap and application environment. Never commit `.env` or real secrets. Validate required configuration at startup and fail with a clear safe error when missing.

## Startup and migration sequence

1. Install/pin dependencies.
2. Start PostgreSQL with pgvector enabled and health-checked.
3. Apply versioned schema migrations.
4. Load versioned synthetic policies and patient documents idempotently.
5. Build/rebuild embeddings and FTS indexes using the configured model/version.
6. Run unit, integration and synthetic evaluation tests.
7. Start API and frontend; verify health endpoint and core case workflow.

Exact commands and ports must be recorded after implementation is chosen and tested. Do not invent verified commands in advance.

## Observability

Record request/run ID, case/run IDs, workflow step, retrieval round, result status, validator flags, duration, model/provider version and safe error code. Do not log secrets or real clinical text. For each run, preserve enough metadata to reproduce evaluation configuration and explain why a criterion received its status.

## Failure handling

- Database unavailable: fail closed; do not create a packet from incomplete state.
- Model/embedding provider timeout: bounded retry with timeout, then mark the run failed and expose a safe retry path.
- Malformed LLM output: schema validation, one controlled retry where specified, then deterministic fallback or explicit failure; never silently trust malformed output.
- Verification failure: reject the candidate evidence/status and flag it for review.
- Retry budget exhausted: produce `MISSING` or `AMBIGUOUS` based on the verified evidence and escalate.

## Backup and recovery

For the synthetic demo, provide a reproducible seed/load command so the database can be rebuilt. Before a shared or persistent deployment, define backup schedule, encryption, restore testing, recovery-point/recovery-time objectives and deletion behavior. These values are currently TBD.

## Release checklist

- Tests pass in a clean environment.
- Migration and synthetic-data load are repeatable.
- Evaluation results are generated from the final code/configuration.
- No real patient data or secrets are present in repository/logs.
- Safety disclaimer and human finalization gate work.
- Demo fallback recording exists if required by the hackathon plan.
- Known limitations and unimplemented extensions are disclosed.
