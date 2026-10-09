# AuthOS — Test Strategy

**Status:** Required before implementation; tests are planned, not yet executed.

## Test layers

### 1. Unit tests

- Pydantic schema validation and enum/state transitions.
- Exact quote/source-span verification.
- Patient identity and source ownership validation.
- Date parsing and duration calculation, including inclusive/exclusive boundary cases.
- Criterion required-fact sufficiency logic.
- `MET` rejection when evidence or mandatory validators fail.
- Packet rendering from verified data only.

### 2. Integration tests

- Fresh PostgreSQL setup and migrations.
- Document/policy ingestion to chunks, FTS and vector fields.
- Dense, keyword and hybrid retrieval with metadata filters.
- Run persistence and retrieval logs.
- FastAPI endpoints against a test database.
- Human review, edit/re-run and finalization audit events.

### 3. AI/RAG tests

Use `docs/ai/evaluation-plan.md` and the gold dataset. Test happy path, corrective retrieval, missing evidence, contradictory evidence, wrong-patient trap, exact-quote mismatch, outdated policy, prompt injection, malformed structured output, retries exhausted and provider failure. Assert evidence provenance and status, not just generated prose.

### 4. End-to-end tests

- Select a synthetic case and run the workflow.
- Inspect criteria, sources and retry timeline.
- Confirm failed validation is visible and invalid evidence is not used.
- Review gaps and record a human action.
- Confirm packet cannot be finalized without explicit approval.
- Confirm final packet includes citations, gaps, reviewer decisions and disclaimer.

### 5. Security and resilience tests

- Invalid IDs/payloads and illegal state transitions.
- Cross-patient access attempts.
- Prompt injection in a synthetic source document.
- Missing/invalid environment configuration.
- Database/model-provider timeout and malformed output.
- Duplicate run/finalize requests and audit behavior.

## MVP exit criteria

- All critical deterministic validator tests pass.
- The three baseline scenarios produce the expected status and workflow behavior.
- No test case with unsupported, wrong-patient, or quote-mismatched evidence yields `MET`.
- Retry count never exceeds the documented cap.
- No packet is finalized without a recorded human approval action.
- A fresh environment can initialize the database and run tests from documented instructions.
- Evaluation output reports denominators, configuration and known limitations.

Numeric quality thresholds remain TBD until the baseline dataset is reviewed. A passing test suite does not establish clinical effectiveness or production readiness.
