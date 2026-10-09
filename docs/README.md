# AuthOS Documentation Index

**Status convention:** `Draft` means proposed and awaiting review; `Baseline` means the current working decision but still subject to validation; `Required before coding` marks a gate, not evidence that approval has occurred. The current project is at documentation/planning stage.

## Product and UX

- [Product requirements (PRD)](product/PRD.md) — problem, scope, users, requirements, scenarios, success measures and open questions. **Review before coding.**
- [UX design](design/ux-design.md) — screens, status language, interactions, accessibility and demo flow. **Review core flows before UI implementation.**
- [Market research and differentiation](product/market-research.md) — research questions, comparison framework and evidence gaps. **Research validation pending.**

## Domain, architecture and data

- [Domain and data](domain/domain-and-data.md) — glossary, status definitions, synthetic policy/patients and evaluation data.
- [System architecture](architecture/system-architecture.md) — components, workflow, RAG, API surface and deployment assumptions.
- [API contract](api/api-contract.md) — endpoint behavior, proposed Pydantic schemas, errors and human-review transitions.
- [Data model and schema decisions](database/data-model.md) — logical entities, constraints, indexes and migration approach.
- [Agents and workflow](ai/agents.md) — responsibilities, shared rules, tool permissions and bounded orchestration.

## AI quality and safety

- [AI/RAG evaluation plan](ai/evaluation-plan.md) — synthetic gold set, metrics, baselines, failure analysis and release gates.
- [Security and privacy](security/security-and-privacy.md) — threat boundaries, synthetic-only controls and future real-data gates.
- [Decisions and risks](decisions/decisions-and-risks.md) — current ADRs, risk register, assumptions and cut line.

## Delivery readiness

- [Pre-development readiness checklist](pre-development-readiness.md) — explicit go/no-go checklist and unresolved blockers.
- [Test strategy](testing/test-strategy.md) — unit, integration, retrieval, safety and end-to-end coverage.
- [Deployment and operations](deployment/deployment-and-operations.md) — local setup, configuration, migrations, observability, backup and release assumptions.
- [Implementation plan](../PLAN.md) — phases, ownership split, timebox and extension order.

## Documentation maintenance rules

1. The PRD owns product scope and non-goals.
2. `domain-and-data.md` owns domain terminology and criterion statuses.
3. `api-contract.md` owns API request/response behavior; `contracts/schemas.py` should become its executable implementation source when coding begins.
4. `system-architecture.md` and the ADRs own architectural decisions. Update an ADR when a decision changes; do not silently drift.
5. The evaluation plan owns metric definitions and thresholds. Results belong in versioned run output, not as unsubstantiated claims in prose.
6. Keep the source data synthetic. Any proposal to use real patient data reopens the security, privacy, legal, access-control, retention and deployment gates.
