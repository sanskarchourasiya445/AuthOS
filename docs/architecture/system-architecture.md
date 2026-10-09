# AuthOS — Architecture

---

## 1. System Context

```text
┌──────────────┐        ┌─────────────────────────────┐
│ PA Specialist │ ─────▶ │          AuthOS             │
│  / Reviewer   │ ◀───── │  (web app, synthetic data)  │
└──────────────┘        └──────────┬──────────────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
               LLM API       Embedding model     PostgreSQL
              (extraction,    (dense vectors)   (+ pgvector, FTS)
               judgments)
```

External dependencies: an LLM API and an embedding model. No EHR, no payer API, no real PHI.

---

## 2. Layered Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                      React UI                           │
│  Cases │ Evidence Review │ Human Review │ Final Packet  │
└──────────────────────────┬──────────────────────────────┘
                           │ REST (JSON)
┌──────────────────────────▼──────────────────────────────┐
│                       FastAPI                           │
│  Case API │ Workflow API │ Evidence API │ Packet API    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                      LangGraph                          │
│  Router → Policy Analyst → Evidence Agent →             │
│  Sufficiency → (Rewrite loop) → Verifier →              │
│  Human Review → Packet Author                           │
└───────┬──────────────────┬──────────────────┬───────────┘
        │                  │                  │
        ▼                  ▼                  ▼
   PostgreSQL          RAG Layer         Validators
  (cases, audit)  (dense · FTS · RRF)   (citations, dates,
                   rerank · parent)        evidence)
                          │
                          ▼
                    MCP Tools (extension)
```

---

## 3. Components

| Component | Responsibility | Tech |
|---|---|---|
| **React UI** | Case selection, evidence cards, retry timeline, human review, packet view | React, TypeScript, Vite, Tailwind |
| **FastAPI** | HTTP API, request validation, workflow invocation | FastAPI, Pydantic |
| **LangGraph workflow** | Explicit state machine with bounded loops and conditional edges | LangGraph |
| **RAG layer** | Ingestion, hybrid search, RRF, optional rerank and parent expansion | Python, pgvector, Postgres FTS |
| **Validators** | Deterministic checks the LLM cannot override | Pure Python |
| **PostgreSQL** | Policies, chart chunks, cases, results, audit log | Postgres + pgvector |
| **MCP server** (extension) | Tool boundary for record, policy, document, report access | MCP |
| **Evaluation** | Gold dataset, metrics, ablation runner | Python, pytest |

---

## 4. Workflow Graph

```text
START
  │
  ▼
case_router
  │
  ▼
policy_analyst ──▶ criteria[]
  │
  ▼
┌─────────── for each criterion ───────────┐
│                                          │
│   retrieve                               │
│      │                                   │
│      ▼                                   │
│   sufficiency_check                      │
│      │                                   │
│   ┌──┴────────────┐                      │
│   │ sufficient    │ insufficient         │
│   │               │ and round < 2        │
│   │               ▼                      │
│   │          rewrite_query ──▶ retrieve  │
│   ▼                                      │
│   verify                                 │
│      │                                   │
│      ▼                                   │
│   assign_status                          │
└──────────────────┬───────────────────────┘
                   ▼
            human_review
                   │
                   ▼
            packet_author
                   │
                   ▼
                  END
```

### 4.1 Loop Control

| Rule | Value |
|---|---|
| Max retrieval retries per criterion | 2 |
| After cap reached | Go to `verify`; result likely `MISSING` / `AMBIGUOUS`; escalate |
| Duplicate query | Rejected; must differ from prior rounds |
| LLM output malformed | One retry, then fallback |

### 4.2 State (summary)

`case_id`, `patient_id`, `service`, `policy_id`, `criteria`, `current_index`, `retrieval_round`, `retrieved`, `sufficiency`, `results`, `human_decisions`, `packet`. Full definition in `PLAN.md` section 4.4.

---

## 5. RAG Pipeline

```text
Criterion
   │
   ▼
Query decomposition        (criterion → required facts)
   │
   ▼
Vocabulary expansion       (policy terms → chart terms)
   │
   ▼
Metadata filter            (patient_id, doc type, date range)
   │
   ▼
┌───────────────────────────────┐
│ Dense (pgvector) │ FTS (tsv)  │
└───────────────┬───────────────┘
                ▼
        RRF fusion (k = 60)
                │
                ▼
     Parent expansion (optional)
                │
                ▼
        Reranker (optional)
                │
                ▼
        Sufficiency judge
```

| Technique | Why it exists |
|---|---|
| Dense retrieval | Semantic matching ("rehab sessions" ≈ PT) |
| Full-text search | Exact terms, codes, dates, drug names |
| RRF | Merge rankings without score calibration |
| Metadata filtering | Patient isolation; scope to correct policy |
| Query decomposition | Complex criteria → searchable facts |
| Vocabulary expansion | Bridge policy and chart language |
| Parent expansion | Restore context around small chunks |
| Query rewrite | Recover from insufficient retrieval |
| Sufficiency check | Decide whether evidence is actually enough |

**Chunking**

| Source | Strategy |
|---|---|
| Policy | By section, preserve section IDs and cross-references |
| Chart | By paragraph (about 200–400 tokens); keep `document_id`, `patient_id`, `doc_date`, `doc_type` |

---

## 6. Data Architecture

```text
policy_chunks     (id, policy_id, section, text, embedding, tsv)
documents         (id, patient_id, doc_type, doc_date, title, full_text)
chart_chunks      (id, document_id, patient_id, text, doc_date, embedding, tsv)
cases             (id, patient_id, service, policy_id, status)
criterion_results (case_id, criterion_id, status, verified, payload jsonb)
audit_log         (id, case_id, step, payload jsonb, created_at)
```

Indexes: HNSW or IVFFlat on embeddings, GIN on `tsv`, btree on `patient_id`.
Details in [`../domain/domain-and-data.md`](../domain/domain-and-data.md).

---

## 7. API Surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/cases` | List demo cases |
| POST | `/api/v1/cases/{id}/run` | Run workflow |
| GET | `/api/v1/cases/{id}/results` | Criteria results with retry logs |
| POST | `/api/v1/cases/{id}/review` | Human decisions |
| POST | `/api/v1/cases/{id}/approve` | Approve / edit / reject; generate packet |
| GET | `/api/v1/cases/{id}/packet` | Final packet |
| GET | `/eval/ablation` | Ablation results (extension) |

All request and response bodies are Pydantic models in `contracts/schemas.py`. All MVP paths use the `/api/v1` prefix, consistent with `docs/api/api-contract.md`.

---

## 8. Validation Architecture

```text
LLM (probabilistic)  ──▶  Candidate evidence / status
                                │
                                ▼
                     Deterministic validators
                                │
                  ┌─────────────┴─────────────┐
                  ▼                           ▼
               Pass                      Fail → override / drop evidence
```

| Validator | Checks |
|---|---|
| `citations.py` | Source exists; quote verbatim |
| `evidence.py` | Patient identity; evidence ↔ criterion mapping; status constraints |
| `dates.py` | Parse dates; compute duration; compare to threshold |

Packet post-check: every claim must map to a verified evidence item.

---

## 9. MCP Tool Boundaries (Extension)

| Server / Tool | Access | Used by |
|---|---|---|
| Patient Records: `get_patient_record` | Read | Verifier |
| Policy Search: `search_policy` | Read | Policy Analyst |
| Document: `retrieve_document` | Read | Evidence Agent, Verifier |
| Report: `generate_report` | Write | Packet Author |

Each tool has explicit input/output schemas. Agents call tools through MCP instead of direct imports.

---

## 10. Deployment (Hackathon)

```text
docker-compose
 ├── postgres (pgvector)
 ├── backend  (FastAPI + LangGraph)
 └── frontend (Vite dev or static build)
```

No Kubernetes, Redis, or microservices. One command to start; one seed command to load synthetic data.

---

## 11. Observability

| What | Where |
|---|---|
| Every workflow step with input/output | `audit_log` |
| Per-criterion retrieval rounds | `retry_log` in results; shown in UI timeline |
| Validator flags | Stored on each `CriterionResult` |
| LLM calls | Request/response logging in dev; cache for demo cases |

---

## 12. Security and Privacy

- Synthetic data only; no PHI.
- Secrets in `.env`, never committed.
- Retrieval tools are read-only; the report tool is write-only.
- Patient-scoped queries enforced at the data layer, not just in prompts.
- Production concerns (access control, enterprise audit, compliance) are future work.

---

## 13. Quality Attributes

| Attribute | How the architecture supports it |
|---|---|
| Reliability | Bounded loops, fallbacks, deterministic validators |
| Explainability | Retry log, per-claim citations, audit log |
| Testability | Validators unit-tested; gold dataset for retrieval; ablation flags |
| Simplicity | Minimum agents; no extra infrastructure |
| Extensibility | Feature flags for rerank, parent expansion, MCP |
