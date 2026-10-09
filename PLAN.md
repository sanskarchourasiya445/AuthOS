# AuthOS — Implementation Plan

> Evidence-grounded prior-authorization preparation system.
> Team: 2 people + AI coding tools (Antigravity / Claude Code / Cursor).
> Window: 24 hours. Code freeze at **hour 21**.
> Documentation status: planning baseline; implementation and evaluation results are not verified by this document package.

---

## 0. How to Use This Plan

- Phases 0–6 are the **hackathon core**. Do them in order.
- Phases 7–14 are **extensions**. Start one only when the previous phase runs end to end and the demo still works.
- Every phase has: owner, tasks, deliverable, and an **exit check**. Do not move on until the exit check passes.
- Every extension is **measured** in the ablation. If it does not help, report that honestly.

**Roles**

| Person | Focus | Owns |
|---|---|---|
| **A** | Backend and agents | Postgres, ingestion, retrieval, LangGraph, verifier, API |
| **B** | Data, validators, UI, demo | Synthetic data, validators, tests, React UI, eval, pitch |

---

## 1. Product Scope

**What it does:** Given a synthetic patient, a requested service (lumbar MRI) and a payer policy, AuthOS extracts policy criteria, searches the chart for evidence per criterion, retries when evidence is insufficient, verifies every claim, and produces a review packet after a human approves.

**What it never does:** diagnose, recommend treatment, decide medical necessity, predict approval, submit claims, or fabricate missing evidence.

**Statuses per criterion**

| Status | Meaning |
|---|---|
| `MET` | Verified evidence supports the criterion |
| `MISSING` | No supporting evidence was found in the supplied records after the defined bounded search |
| `AMBIGUOUS` | Partial, indirect, or conflicting evidence |
| `CONTRADICTED` | Chart evidence contradicts the criterion (e.g., "declined PT") |

---

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript + Vite + Tailwind |
| Backend | FastAPI + Python 3.11 + Pydantic |
| Orchestration | LangGraph |
| DB | PostgreSQL + pgvector + built-in FTS |
| LLM | Claude via API (structured outputs) |
| Embeddings | Any hosted or local embedding model; pin the dimension in config |
| Tests | pytest |
| Infra | docker-compose only |
| Tool protocol (extension) | MCP |

---

## 3. Repository Structure

```text
authos/
├── PLAN.md
├── README.md
├── docker-compose.yml
├── .env.example
│
├── contracts/
│   ├── schemas.py              # Pydantic models (single source of truth)
│   └── mock_response.json      # Mock API payload for the UI
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── db/
│   │   ├── schema.sql
│   │   └── session.py
│   ├── agents/
│   │   ├── policy_analyst.py
│   │   ├── evidence_agent.py
│   │   ├── verifier.py
│   │   └── packet_author.py
│   ├── graph/
│   │   ├── state.py
│   │   └── workflow.py
│   ├── rag/
│   │   ├── ingest.py
│   │   ├── hybrid_search.py
│   │   ├── query_rewrite.py
│   │   ├── sufficiency.py
│   │   ├── reranker.py          # extension
│   │   └── parent_expand.py     # extension
│   ├── validators/
│   │   ├── citations.py
│   │   ├── dates.py
│   │   └── evidence.py
│   ├── mcp/
│   │   └── server.py            # extension
│   ├── evaluation/
│   │   ├── dataset.json
│   │   ├── evaluate.py
│   │   └── ablation.py
│   ├── data/
│   │   ├── policies/
│   │   └── patients/
│   └── tests/
│
└── frontend/
    └── src/
        ├── api/
        ├── components/
        ├── pages/
        └── hooks/
```

---

## 4. Core Contracts (Write These in Phase 0)

### 4.1 Criterion

```json
{
  "id": "C2",
  "text": "Conservative treatment for at least 6 weeks",
  "evidence_type": "treatment_history",
  "min_duration_days": 42,
  "required_facts": ["treatment_type", "start_date", "end_date"],
  "exception_ids": ["E1"],
  "source_chunk": "POL-LMRI-001-S4"
}
```

### 4.2 Evidence item

```json
{
  "source_id": "PT_NOTE_004",
  "patient_id": "P-104",
  "quote": "Patient completed PT from March 4 through April 22.",
  "date": "2026-04-22",
  "retrieval_round": 2
}
```

### 4.3 Criterion result

```json
{
  "criterion_id": "C2",
  "status": "MET",
  "verified": true,
  "evidence": [],
  "missing_facts": [],
  "retry_log": [
    {
      "round": 1,
      "query": "conservative treatment 6 weeks",
      "found": ["treatment_type"],
      "missing": ["duration"],
      "sufficient": false
    },
    {
      "round": 2,
      "query": "physical therapy treatment start date end date duration persistent symptoms",
      "found": ["treatment_type", "start_date", "end_date"],
      "missing": [],
      "sufficient": true
    }
  ],
  "validator_flags": []
}
```

### 4.4 Workflow state (LangGraph)

```python
class AuthState(TypedDict):
    case_id: str
    patient_id: str
    service: str
    policy_id: str
    criteria: list[Criterion]
    current_index: int
    retrieval_round: int            # max 2 retries
    retrieved: list[EvidenceItem]
    sufficiency: SufficiencyResult | None
    results: dict[str, CriterionResult]
    human_decisions: dict[str, str]
    packet: ReviewPacket | None
```

### 4.5 API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/cases` | List demo cases |
| POST | `/api/v1/cases/{id}/run` | Run workflow |
| GET | `/api/v1/cases/{id}/results` | Criteria results with retry logs |
| POST | `/api/v1/cases/{id}/review` | Submit human decisions (add info, accept gap) |
| POST | `/api/v1/cases/{id}/approve` | Approve / edit / reject, then generate packet |
| GET | `/api/v1/cases/{id}/packet` | Final packet |
| GET | `/eval/ablation` | Ablation results (extension) |

---

## 5. Database Schema (Outline)

```sql
-- policies
policy_chunks(id, policy_id, section, text, embedding vector(N), tsv tsvector)

-- patient charts
documents(id, patient_id, doc_type, doc_date, title, full_text)
chart_chunks(id, document_id, patient_id, text, doc_date,
             embedding vector(N), tsv tsvector)

-- workflow
cases(id, patient_id, service, policy_id, status)
criterion_results(case_id, criterion_id, status, verified, payload jsonb)
audit_log(id, case_id, step, payload jsonb, created_at)
```

Indexes: `ivfflat` or `hnsw` on embeddings, `GIN` on `tsv`, btree on `patient_id`.

---

## 6. Synthetic Data Design

### 6.1 Policy: POL-LMRI-001 (Lumbar MRI)

| ID | Criterion |
|---|---|
| C1 | Low back pain documented for at least 6 weeks |
| C2 | Conservative treatment (PT, NSAIDs, or equivalent) for at least 6 weeks |
| C3 | Persistent symptoms despite treatment |
| C4 | Neurological deficit documented **or** radicular symptoms |
| C5 | No lumbar MRI in the prior 12 months |
| E1 | **Exception:** red-flag findings waive C1/C2 |

Add a definitions section ("conservative treatment means…") and one cross-reference ("see Section 4.2") to exercise policy parsing.

### 6.2 Patients (3 for core; grow later)

| Case | Patient | Purpose | Trap |
|---|---|---|---|
| **A** | P-101 | Happy path | None; most criteria clearly met |
| **B** | P-104 | Corrective retrieval | Vocabulary mismatch: policy says "conservative treatment"; chart says "PT", "rehab sessions", "NSAIDs"; duration lives in a different note than the treatment |
| **C** | P-107 | Missing evidence | Treatment mentioned, but no duration and no documentation of persistent symptoms |

Each patient: 5–10 documents (primary care note, specialist note, PT evaluation / follow-up / discharge, imaging report, medication history).

**Case B anchor facts:** PT start March 4, end April 22 → **49 days = 7 weeks**. Make sure one note loosely says "about 8 weeks" so the validator has something to reject.

> **Rule:** Verify every date and duration by hand. Do not trust AI-generated date math.

### 6.3 Later traps (Phase 13)

- Negation: "patient declined PT"
- Conflicting notes
- Relative dates: "6 weeks ago"
- Wrong-patient document planted in the corpus
- Abbreviation-heavy notes ("LBP", "NSAID trial")

---

## 7. Phased Build

### PHASE 0 — Setup and Contracts (h0–1) · A + B together

**Tasks**
- [ ] Init repo, branch strategy (A: `backend/`, B: `frontend/` + `data/` + `validators/`)
- [ ] docker-compose: Postgres + pgvector
- [ ] `.env.example` (API keys, DB URL, embedding dim)
- [ ] Write `contracts/schemas.py` from section 4
- [ ] Write `contracts/mock_response.json` for all three cases
- [ ] Mock FastAPI returning the mock payload

**Deliverable:** UI can be built against the mock API; backend knows its output shape.

**Exit check:** `GET /cases/{id}/results` returns valid mock JSON validated by Pydantic.

---

### PHASE 1 — Data and Foundations (h1–4) · parallel

**A: Ingestion and base search**
- [ ] `schema.sql` and DB session
- [ ] Chunking: policy by section; chart by paragraph (~200–400 tokens), keep `patient_id` and `doc_date` as metadata
- [ ] Embed and load policy and chart chunks; populate `tsv`
- [ ] Dense search function and FTS search function, both filtered by `patient_id`

**B: Synthetic data**
- [ ] Write POL-LMRI-001 (plain text with sections)
- [ ] Write P-101, P-104, P-107 documents
- [ ] Hand-check every date and duration
- [ ] Write gold labels draft: for each criterion and case, expected status and source IDs

**Deliverable:** Data loaded; both search types return results for a test query.

**Exit check:** Searching "physical therapy" for P-104 returns the PT notes; searching with another patient's ID returns none of them.

---

### PHASE 2 — Hybrid Retrieval, Criteria, Validators (h4–9) · parallel

**A: Retrieval and policy analysis**
- [ ] RRF fusion of dense + FTS (k=60)
- [ ] Metadata filtering (patient, policy, date range)
- [ ] Policy Analyst: retrieve policy sections, extract structured criteria as JSON (Pydantic-validated, retry once on malformed output)
- [ ] Hardcoded fallback criteria file in case extraction is flaky on demo day

**B: Deterministic validators (write tests first)**
- [ ] `citations.py`: source ID exists; quote appears verbatim in source document (normalize whitespace only)
- [ ] `evidence.py`: patient ID matches case patient; evidence maps to the criterion's required facts
- [ ] `dates.py`: parse dates; compute duration; compare to `min_duration_days`; reject unsupported claims (e.g., "8 weeks" vs. computed 7)
- [ ] pytest: pass cases, fail cases, wrong patient, fabricated quote, wrong duration

**Deliverable:** `hybrid_search(query, patient_id)` works; criteria extracted; validators pass tests.

**Exit check:** Validator rejects "8 weeks" for March 4 → April 22 and accepts "7 weeks".

---

### PHASE 3 — The Agent Loop (h9–14) · A leads, B builds UI

**A: LangGraph workflow**
- [ ] Nodes: `case_router` (deterministic), `policy_analyst`, `retrieve`, `sufficiency_check`, `rewrite_query`, `verify`, `assign_status`
- [ ] Query decomposition: criterion → required facts → search queries
- [ ] Vocabulary expansion: "conservative treatment" → PT, physiotherapy, rehab, NSAIDs, home exercise
- [ ] Sufficiency judge: given criterion + required facts + retrieved evidence, return `found`, `missing`, `sufficient`
- [ ] Rewrite node: targets the **missing** facts specifically (see section 8)
- [ ] Conditional edges: insufficient and `retrieval_round < 2` → rewrite → retrieve; else → verify
- [ ] Verifier: LLM proposes status; **deterministic validators override** (a failed validator downgrades `MET`)
- [ ] Log every step to `audit_log` and to `retry_log`

**B: UI against mock API**
- [ ] Case selector page
- [ ] Criteria list with status badges (`MET` / `MISSING` / `AMBIGUOUS` / `CONTRADICTED`)
- [ ] Evidence card: source, quote, date, verified check
- [ ] **Retry timeline component**: Search 1 → gap found → rewrite → Search 2 → verified (this is the demo centerpiece)

**Deliverable:** Workflow runs per criterion on all three cases; UI renders mock data.

**Exit check:** Case B shows a failed first retrieval and a successful second one in `retry_log`.

---

### PHASE 4 — Integration and Human Review (h14–18)

**A**
- [ ] Wire workflow to `/api/v1/cases/{id}/run` and `/api/v1/results`
- [ ] `/review` endpoint: accept human-added info (re-verified by validators) or "accept gap"
- [ ] `/approve` endpoint: approve / edit / reject
- [ ] Packet Author: input is verified structured evidence only; prompt forbids new facts; run `evidence.py` over the output to flag any claim not backed by evidence

**B**
- [ ] Swap mock API for real API
- [ ] Evidence Gap Review screen: `[Add Information] [Accept Gap] [Continue]`
- [ ] Final Review screen: counts of verified / ambiguous / missing; `[Approve] [Edit] [Reject]`
- [ ] Packet view with clickable citations (source + quote)
- [ ] Persistent disclaimer: "Administrative evidence preparation. Not a medical or insurance decision."

**Deliverable:** All three cases run through the browser end to end.

**Exit check:** Case A → packet generated. Case B → retry visible, then packet. Case C → human review required, no fabricated evidence.

---

### PHASE 5 — Evaluation and Proof (h18–21)

**B**
- [ ] `dataset.json`: about 10 criteria with gold policy chunks, gold evidence spans, gold status, and `trap_type`
- [ ] `evaluate.py`: context recall, context precision, MRR, status accuracy, citation correctness, **false-MET rate**
- [ ] `ablation.py`: run configurations A, B, C, E (see section 9) and write results to a table

**A**
- [ ] Config flags so each retrieval feature can be toggled
- [ ] Fix bugs found by eval runs
- [ ] Bounded-loop test: confirm max 2 retries

**Deliverable:** Real measured ablation table (even if small).

**Exit check:** Results are reproducible from one command. **Code freeze at h21.**

---

### PHASE 6 — Demo and Submission (h21–24)

- [ ] Rehearse the demo (section 10) at least twice
- [ ] Record a backup screen capture
- [ ] README: pitch, architecture diagram, safety boundary, **real** ablation numbers
- [ ] Reset DB and verify a clean `docker-compose up` works from scratch
- [ ] Prepare judge Q&A (section 11)

**Exit check:** A teammate who hasn't touched the code can run the demo from the README.

---

## 8. Corrective Retrieval Specification

```text
for each criterion:
    facts = decompose(criterion)            # treatment_type, start_date, end_date
    query = build_query(criterion, facts)
    round = 0
    loop:
        hits   = hybrid_search(query, patient_id)
        suff   = sufficiency(criterion, facts, hits)
        log(round, query, suff)
        if suff.sufficient or round == 2:
            break
        query = rewrite(criterion, suff.missing, hits)
        round += 1
    verify(criterion, hits)                  # validators have final say
```

**Rewrite rules**
- Target `suff.missing`, not the whole criterion
- Add synonyms and document-type hints (PT evaluation, discharge, follow-up)
- Add date-oriented terms when dates are missing
- Never repeat a previous query
- Hard cap: 2 retries; then `MISSING` / `AMBIGUOUS` → human review

**Verifier rules (deterministic overrides LLM)**

| Check | Failure result |
|---|---|
| Source document not found | Evidence dropped |
| Quote not verbatim in source | Evidence dropped |
| Patient ID mismatch | Evidence dropped, flagged |
| Duration below policy minimum | Status ≠ `MET` |
| LLM-claimed duration ≠ computed | Claim rejected |
| Contradiction found | `CONTRADICTED` |
| No surviving evidence | `MISSING` |

---

## 9. RAG Ablation Configurations

| ID | Configuration | Phase |
|---|---|---|
| A | Dense only | 5 |
| B | Dense + FTS | 5 |
| C | Dense + FTS + RRF | 5 |
| D | C + parent expansion | 8 |
| E | C + corrective loop | 5 |
| F | E + reranker | 7 |

**Results table (fill with measured values only)**

| Config | Recall | Precision | MRR | Status Acc. | False-MET |
|---|---:|---:|---:|---:|---:|
| A | — | — | — | — | — |
| B | — | — | — | — | — |
| C | — | — | — | — | — |
| E | — | — | — | — | — |

Add a baseline row: **whole chart in context, no retrieval**. Judges will ask about it. Report where it wins and where it fails (auditability, scale, false-MET).

---

## 10. Demo Script (5 minutes)

1. **Problem (30s):** PA teams manually connect policy, chart, dates, and citations.
2. **Case A (45s):** Happy path. Criteria extracted → evidence → packet.
3. **Case B (90s), centerpiece:** Show retry timeline. Search 1 finds treatment but no duration → system names the gap → rewrite → Search 2 finds PT start/end → verified at 7 weeks.
4. **Validator rejection (45s):** Show the LLM claiming "8 weeks"; validator computes 7; claim rejected. *This is the false-MET prevention moment.*
5. **Case C (45s):** Evidence genuinely missing; two failed searches; system refuses to fabricate; human review.
6. **Numbers (30s):** Ablation table with real measurements.
7. **Close (15s):** "AuthOS prepares the packet. The human makes the decision."

---

## 11. Judge Q&A Prep

| Question | Answer |
|---|---|
| Why not stuff the whole chart in context? | Baseline row in ablation; real charts are far larger; retrieval gives auditable per-criterion evidence trails. |
| How do you stop hallucinated evidence? | Extractive quotes, verbatim-match validator, patient ID check, packet author sees verified evidence only. |
| What stops infinite agent loops? | Hard cap of 2 retries, then human escalation. |
| Is it making medical decisions? | No. Administrative preparation only; final decision is the human's. |
| Real patient data? | No. Fully synthetic. |
| Why LangGraph? | Explicit state, bounded loops, conditional edges, inspectable runs. |
| What would production need? | Secure EHR integration, access control, audit logging, privacy and compliance. |

---

## 12. Extensions (Only After Phase 6 Works)

### PHASE 7 — Reranker
- [ ] Cross-encoder rerank over top-k after RRF
- [ ] Toggle flag; add ablation row F
- [ ] Report whether it helped; keep it only if it does

### PHASE 8 — Parent-Document Expansion
- [ ] Retrieve small chunks; expand to surrounding section or full note
- [ ] Ablation row D
- [ ] Watch for noise from over-expansion

### PHASE 9 — MCP Layer
- [ ] Tools: `get_patient_record`, `search_policy`, `retrieve_document`, `generate_report`
- [ ] Explicit input/output schemas
- [ ] Retrieval tools read-only; report tool write-only
- [ ] Agents call tools through MCP rather than direct imports
- [ ] Test each tool in isolation

### PHASE 10 — Cross-Reference Following
- [ ] Detect "see Section X" patterns in policy chunks
- [ ] Retrieve referenced section; merge definitions/criteria
- [ ] Cap depth at 2 to prevent cycles

### PHASE 11 — Workflow Robustness
- [ ] LangGraph checkpointing (Postgres)
- [ ] Interrupt/resume for the human-review step
- [ ] Streaming execution status to UI (SSE)

### PHASE 12 — Evaluation Dashboard
- [ ] Metrics page: recall, precision, MRR, status accuracy, false-MET
- [ ] Ablation table generated from stored runs
- [ ] Per-`trap_type` breakdown

### PHASE 13 — Data Scale-Out
- [ ] Add POL-RA-BIO-001, POL-KNEE-001, POL-CT-001
- [ ] Grow to 5–6 patients, 10–15 documents each
- [ ] Add traps from section 6.3
- [ ] Expand gold dataset accordingly

### PHASE 14 — Hardening
- [ ] Contradiction detection validator
- [ ] Final status constraint validator (e.g., `MET` requires ≥1 verified evidence)
- [ ] Complete audit log view in UI
- [ ] Broader pytest coverage and CI

---

## 13. Working With AI Coding Tools

1. **Spec first.** Give the tool this plan and the README as context.
2. **Contracts first.** Generate code against `contracts/schemas.py`, not against vibes.
3. **Tests first for validators.** Validator tests are your ground truth for generated code.
4. **Separate directories** per person so parallel agents don't collide.
5. **Small, scoped prompts** ("implement `hybrid_search.py` with RRF, signature X") beat large ones.
6. **Verify library calls.** Check LangGraph, pgvector, and MCP API usage against current docs; models often use outdated signatures.
7. **Commit after every working step.** Roll back freely.
8. **Hand-verify data.** AI writes plausible but wrong dates.
9. **No new features after h21.**

---

## 14. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Policy extraction flaky | Medium | Hardcoded fallback criteria; show extraction as bonus |
| Malformed LLM JSON | High | Pydantic validation, one retry, then fallback |
| Case B doesn't fail naturally on Search 1 | Medium | Tune data vocabulary, not the code; log real queries |
| Embedding dimension mismatch | Medium | Pin in config; set once in Phase 0 |
| Integration breaks at the seams | High | Contract-first; mock API; integrate by h14 |
| Run out of time | High | Cut line below; protect demo over metrics |
| LLM latency / rate limits on demo day | Medium | Cache results for demo cases; backup video |
| Scope creep from AI-speed | High | Hard freeze at h21 |

---

## 15. Cut Line (If Behind)

| Behind at… | Cut |
|---|---|
| h9 | Reranker, MCP, parent expansion, extra policies (already extensions) |
| h14 | Eval dashboard; reduce eval to 5 criteria |
| h18 | Ablation to 2 rows (Dense vs. Hybrid + Loop); freeze UI polish |
| h21 | Everything but bug fixes and demo prep |

**Never cut:** the Case B retry timeline, the validator rejection, Case C refusal, the safety disclaimer, the backup video.

---

## 16. Definition of Done

**Core (must pass)**
- [ ] Select synthetic patient and requested service
- [ ] Retrieve applicable policy; extract structured criteria
- [ ] Hybrid retrieval scoped to the right patient
- [ ] Detect insufficient evidence, rewrite, retrieve again (max 2 retries)
- [ ] Deterministic validators run and can override the LLM
- [ ] `MET` / `MISSING` / `AMBIGUOUS` / `CONTRADICTED` produced per criterion
- [ ] Uncertain cases escalate to human review
- [ ] Final packet generated from verified evidence only, with citations
- [ ] All three demo cases run end to end in the UI
- [ ] Real ablation numbers (even if few)
- [ ] README and backup video ready

**Stretch**
- [ ] Reranker, parent expansion, MCP
- [ ] Cross-reference following
- [ ] Checkpointing, streaming, dashboard

---

## 17. Roadmap Beyond the Hackathon

- Secure healthcare integrations and fine-grained access control
- Enterprise audit logging, compliance and privacy controls
- Larger policy corpora and richer evaluation
- Production deployment

These are future considerations, not part of the MVP.

---

## 18. Core Principle

> Build the smallest system where every architectural decision can be demonstrated.

```text
RETRIEVE → REASON → CHECK → RETRY → VERIFY → ESCALATE → APPROVE
```
