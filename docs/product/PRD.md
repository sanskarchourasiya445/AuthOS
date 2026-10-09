# AuthOS — Product Requirements Document (PRD)

**Version:** 1.0 (Hackathon MVP)
**Status:** Draft for build
**Team:** 2 people + AI coding tools
**Related docs:** [`../../PLAN.md`](../../PLAN.md), [`../ai/agents.md`](../ai/agents.md), [`../architecture/system-architecture.md`](../architecture/system-architecture.md), [`../domain/domain-and-data.md`](../domain/domain-and-data.md), [`../decisions/decisions-and-risks.md`](../decisions/decisions-and-risks.md), [`../design/ux-design.md`](../design/ux-design.md)

---

## 1. Summary

AuthOS is an evidence-grounded **prior-authorization preparation system**. It turns payer policy requirements and patient records into a verified, auditable review packet. It prepares evidence; it never makes the medical or insurance decision.

**One-line pitch:** AuthOS is an evidence linter for prior authorization: each proposed claim must trace to chart evidence or be rejected, flagged, or routed for human review. A deterministic verifier is the core product capability; retrieval is supporting machinery.

---

## 2. Problem

Prior-authorization staff manually connect payer policies, clinical notes, treatment history, imaging, dates, and durations. A key operational risk is discovering documentation gaps only after a submission is prepared or sent. AuthOS targets provider-side pre-submission gap detection. It uses retrieval to help answer:

> Which policy criteria apply, what evidence supports each one, is that evidence sufficient, and can every claim be traced to its source?

Current pain points:

- Policies and charts use different vocabulary ("conservative treatment" vs. "PT, rehab sessions, NSAIDs").
- Evidence for one criterion is scattered across multiple documents.
- Duration and date claims are easy to get wrong.
- Gaps are discovered late, after submission or denial.
- Generic LLM tools can fabricate evidence with no audit trail.

---

## 3. Goals and Non-Goals

### 3.1 Goals

| ID | Goal |
|---|---|
| G1 | Extract structured criteria from a payer policy |
| G2 | Find per-criterion evidence in a patient chart using hybrid retrieval |
| G3 | Detect insufficient evidence and recover through bounded query rewriting |
| G4 | Verify every claim deterministically (source, patient, quote, dates, duration) |
| G5 | Classify each criterion as `MET`, `MISSING`, `AMBIGUOUS`, or `CONTRADICTED` |
| G6 | Escalate gaps to a human and require human approval before finalizing |
| G7 | Produce a cited, auditable review packet using verified evidence only |
| G8 | Report measured retrieval and evidence-quality metrics on a synthetic gold set |

### 3.2 Non-Goals

AuthOS does **not**: diagnose patients, recommend treatment, determine medical necessity, predict approval probability, make insurance decisions, submit claims, or fabricate missing evidence.

Out of scope for the MVP: real EHR integration, real payer APIs, real patient data, voice, Kubernetes, Redis, microservices, Graph RAG, HyDE, Self-RAG, notifications, production auth.

---

## 4. Users and Use Cases

### 4.1 Personas

| Persona | Description | Needs |
|---|---|---|
| **PA Specialist** (primary) | Prepares prior-auth submissions | Speed, traceable evidence, early gap detection |
| **Clinical/Documentation Reviewer** | Reviews the packet on the provider side before submission | Traceable evidence, clear gaps, ability to correct or reject unsupported claims |
| **Hackathon Judge** (audience, not a product user) | Evaluates the demonstration | Clear scenario, transparent limitations, reproducible tests |

### 4.2 Key User Stories

| ID | Story | Priority |
|---|---|---|
| U1 | As a specialist, I select a patient and requested service so the right policy is applied | P0 |
| U2 | I see the extracted policy criteria so I know what must be proven | P0 |
| U3 | I see per-criterion evidence with source, quote, and date so I can trust it | P0 |
| U4 | I see when a search failed and was retried so I can understand the system's reasoning | P0 |
| U5 | I see clearly which criteria are missing or ambiguous so I can act | P0 |
| U6 | I can add information or accept a gap for flagged criteria | P0 |
| U7 | I approve, edit, or reject the packet before finalization | P0 |
| U8 | I receive a final packet where every claim is cited | P0 |
| U9 | I can see measured quality metrics for the retrieval configurations | P1 |
| U10 | I see live execution status while the workflow runs | P1 |

---

## 5. Functional Requirements

### 5.1 Case and Policy Handling

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | The system shall list demo cases (patient + requested service) | P0 |
| FR-2 | The system shall select the applicable policy for the requested service | P0 |
| FR-3 | The system shall extract criteria, exceptions, and definitions as structured JSON validated against a schema | P0 |
| FR-4 | The system shall follow policy cross-references (depth ≤ 2) | P1 |

### 5.2 Evidence Retrieval

| ID | Requirement | Priority |
|---|---|---|
| FR-5 | Retrieval shall be restricted to the case patient's documents | P0 |
| FR-6 | Retrieval shall combine dense and full-text search using Reciprocal Rank Fusion | P0 |
| FR-7 | Each criterion shall be decomposed into required facts (e.g., treatment type, start date, end date) | P0 |
| FR-8 | The system shall judge whether retrieved evidence covers all required facts | P0 |
| FR-9 | If insufficient, the system shall rewrite the query to target missing facts and retry, with a **maximum of 2 retries** | P0 |
| FR-10 | Every retrieval round (query, found facts, missing facts, sufficiency) shall be logged | P0 |
| FR-11 | The system shall support optional reranking and parent-document expansion | P1 |

### 5.3 Verification

| ID | Requirement | Priority |
|---|---|---|
| FR-12 | The system shall verify that each cited source document exists | P0 |
| FR-13 | The system shall verify that each quote appears verbatim in its source | P0 |
| FR-14 | The system shall verify that evidence belongs to the case patient | P0 |
| FR-15 | The system shall compute durations from dates and reject conflicting LLM claims | P0 |
| FR-16 | Deterministic validator failures shall override LLM-proposed statuses | P0 |
| FR-17 | The system shall assign `MET`, `MISSING`, `AMBIGUOUS`, or `CONTRADICTED` per criterion | P0 |

### 5.4 Human Review and Packet

| ID | Requirement | Priority |
|---|---|---|
| FR-18 | Non-`MET` criteria shall be routed to human review | P0 |
| FR-19 | Reviewers can add information (re-verified by validators) or accept a gap | P0 |
| FR-20 | Final packet generation shall require explicit human approval | P0 |
| FR-21 | The packet shall use only verified structured evidence and include citations | P0 |
| FR-22 | Packet text shall be scanned for claims not supported by evidence | P0 |
| FR-23 | Every step shall be written to an audit log | P0 |

### 5.5 Evaluation

| ID | Requirement | Priority |
|---|---|---|
| FR-24 | A synthetic gold dataset shall define expected chunks, evidence, and status per criterion | P0 (mini) |
| FR-25 | The system shall compute context recall, context precision, MRR, citation correctness, status accuracy, and false-`MET` rate | P0 (mini) |
| FR-26 | The system shall compare retrieval configurations (ablation) and report real measured numbers | P0 (mini) |

---

## 6. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Safety | Persistent disclaimer: administrative preparation, not a medical or insurance decision |
| NFR-2 | Data | Synthetic data only; no real PHI anywhere |
| NFR-3 | Reliability | Agent loops bounded; malformed LLM output retried once, then falls back |
| NFR-4 | Auditability | Every status traces to a quote, source, and retrieval log |
| NFR-5 | Determinism | Checks that code can do (dates, IDs, quote match) are never delegated to the LLM |
| NFR-6 | Performance | Demo case run completes in under ~60 seconds; demo cases may be cached |
| NFR-7 | Reproducibility | `docker-compose up` plus one seed command recreates the demo |
| NFR-8 | Least privilege | Retrieval tools read-only; report tool write-only |

---

## 7. Demo Scenarios (Acceptance Basis)

| Case | Scenario | Expected outcome |
|---|---|---|
| **A** | Happy path | First retrieval sufficient; most criteria `MET`; packet generated |
| **B** | Vocabulary mismatch | Round 1 insufficient (duration missing); rewrite; round 2 finds PT dates; verified 7 weeks; `MET`. A planted "about 8 weeks" claim is rejected by the validator |
| **C** | Missing evidence | Initial retrieval plus up to two corrective retries fail; `MISSING`; human review; no fabricated evidence |

---

## 8. Success Metrics

**Product (demo)**

- All three cases run end to end in the UI.
- Case B visibly shows a failed retrieval, a rewrite, and a successful retrieval.
- At least one validator rejection is shown live.

**Technical (measured, never invented)**

| Metric | Target |
|---|---|
| False-`MET` rate | Lowest of all configurations; ideally 0 on the gold set |
| Citation correctness | 100% (validators guarantee existence and verbatim match) |
| Status accuracy | Reported per configuration |
| Hybrid + loop vs. dense-only | Improvement reported honestly, even if small |

---

## 9. Scope and Priorities

**P0 (must ship):** synthetic data, Postgres, criteria extraction, hybrid retrieval, metadata filtering, query decomposition, rewriting, sufficiency check, verification, LangGraph workflow, human review, packet, minimal UI, mini eval.

**P1 (if time):** reranker, parent expansion, MCP, cross-references, interrupt/resume, streaming status, eval dashboard.

**Cut line:** see `PLAN.md` section 15.

---

## 10. Assumptions and Dependencies

- LLM API access and an embedding model are available throughout the hackathon.
- Synthetic data is hand-verified for dates and durations.
- A single policy (lumbar MRI) is sufficient to demonstrate the architecture.
- Judges value demonstrable control loops over breadth of features.

---

## 11. Open Questions

| # | Question | Default if unresolved |
|---|---|---|
| 1 | Which embedding model and dimension? | Pick in Phase 0 and pin in config |
| 2 | Cache LLM results for demo cases? | Yes, with a flag to run live |
| 3 | Is MCP worth including in the 24-hour window? | Only after Phase 6 |
| 4 | Should `CONTRADICTED` appear in the demo? | Include if time allows; otherwise in the eval set |
