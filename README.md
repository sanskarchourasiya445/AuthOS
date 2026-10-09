# AuthOS

**Evidence-grounded prior-authorization preparation system.** AuthOS is designed to turn a synthetic patient chart, a requested service, and a payer policy into a criterion-level, source-traceable review packet. It prepares evidence; it does not make medical or insurance decisions.

> **Project status:** early prototype scaffold. A deterministic evidence-provenance verifier, three synthetic chart fixtures, a synthetic demo policy, a template packet renderer, and five unit tests are present. No LLM/RAG/API/UI workflow has been verified end to end; do not claim model accuracy or real-world effectiveness.

## MVP boundary

- Synthetic patients and synthetic policy documents only.
- One narrow demo service/policy: lumbar MRI (`POL-LMRI-001`).
- Criterion statuses: `MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`.
- Hybrid retrieval (PostgreSQL full-text search + pgvector dense search + Reciprocal Rank Fusion) remains planned and should be compared with a whole-chart-in-context baseline.
- A bounded corrective retrieval loop with at most two retries after the initial search.
- Deterministic verification for source existence, exact quote, patient identity, dates/durations where applicable, and criterion/evidence mapping.
- Human review is required before a packet is finalized.

## Non-goals

No diagnosis, treatment recommendation, medical-necessity decision, approval prediction, insurer decision, claim submission, real EHR/payer integration, or real patient data in the MVP. MCP is an extension after the core workflow works. A2A is not an MVP dependency.

## Start here

1. Read [`PLAN.md`](PLAN.md) for the staged hackathon implementation plan.
2. Read [`docs/README.md`](docs/README.md) for the documentation index and status.
3. Follow [`docs/pre-development-readiness.md`](docs/pre-development-readiness.md) for the lightweight hackathon build checks.
4. Keep evaluation results honest: report only numbers produced by a reproducible run.

## Proposed stack (not yet verified as implemented)

React + TypeScript + Vite + Tailwind; FastAPI + Python 3.11 + Pydantic; LangGraph; PostgreSQL + pgvector + built-in full-text search; a model provider behind a configuration boundary; pytest; Docker Compose for local development.

## Safety statement

AuthOS prepares administrative evidence for human review. A `MET` result means that the defined criterion has supporting evidence that passed the specified checks; it is not a coverage determination or approval prediction. `MISSING` means supporting evidence was not found in the supplied synthetic records after the defined search process, not that the underlying event never occurred.

## Current prototype files

- `backend/authos_core/verifier.py` — deterministic source, exact-quote, and patient-match checks; exact quote validation is not semantic proof.
- `data/synthetic/patients.json` — three synthetic patient scenarios.
- `data/synthetic/policy.json` — illustrative synthetic policy, not a real payer policy.
- `tests/test_verifier.py` — unit tests for verifier and template packet rendering.

Run tests from the repository root: `python -m unittest discover -s tests -v`.
