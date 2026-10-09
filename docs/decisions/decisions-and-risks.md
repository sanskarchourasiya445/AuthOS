# AuthOS — Decisions and Risks

---

## 1. Architecture Decision Records (ADRs)

### ADR-001: Few agents, bounded loops

| | |
|---|---|
| **Decision** | Use 4 agents plus a human step; sufficiency and rewrite live inside the Evidence Agent |
| **Why** | More agents add latency, failure points, and integration cost without improving reliability |
| **Alternatives** | One agent per RAG step; a single monolithic agent |
| **Trade-off** | Less modularity in exchange for simplicity and a clearer demo |
| **Revisit if** | A step needs independent scaling or distinct permissions |

### ADR-002: Deterministic validators override the LLM

| | |
|---|---|
| **Decision** | Dates, durations, patient IDs, quote existence, and thresholds are checked by code; validator failure beats LLM judgment |
| **Why** | LLMs make date-math and citation errors; these checks are cheap and exact in code |
| **Alternatives** | LLM-as-judge for everything |
| **Trade-off** | More code to write; far lower false-`MET` risk |

### ADR-003: Hybrid retrieval (dense + FTS + RRF)

| | |
|---|---|
| **Decision** | Combine pgvector dense search and Postgres FTS with Reciprocal Rank Fusion |
| **Why** | Dense handles vocabulary mismatch; FTS handles exact terms, dates, drug names; RRF needs no score calibration |
| **Alternatives** | Dense only; separate vector DB |
| **Trade-off** | Slightly more tuning; one database, no extra infra |

### ADR-004: Postgres for everything

| | |
|---|---|
| **Decision** | PostgreSQL + pgvector + built-in FTS for vectors, text search, cases, and audit |
| **Why** | One service, one `docker-compose`, joins and metadata filters are trivial |
| **Alternatives** | Qdrant, Pinecone, Elasticsearch |
| **Trade-off** | Not tuned for huge scale; irrelevant at demo scale |

### ADR-005: LangGraph for orchestration

| | |
|---|---|
| **Decision** | Use LangGraph with explicit state and conditional edges |
| **Why** | Retry loops, caps, and human checkpoints are first-class; runs are inspectable |
| **Alternatives** | Hand-rolled state machine; free-form agent frameworks |
| **Trade-off** | Library learning curve; API may differ from model memory, so verify against docs |

### ADR-006: Human approval is mandatory

| | |
|---|---|
| **Decision** | No packet is finalized without explicit human approval; gaps require a human decision |
| **Why** | Safety boundary: AuthOS prepares evidence, it does not decide |
| **Alternatives** | Auto-finalize when all criteria are `MET` |
| **Trade-off** | An extra step; non-negotiable for the safety story |

### ADR-007: Extractive evidence only

| | |
|---|---|
| **Decision** | Evidence must be verbatim quotes with source IDs; paraphrases are not evidence |
| **Why** | Enables exact-match validation and auditability |
| **Trade-off** | Some useful evidence is awkward to quote; the validator would rather drop it than trust it |

### ADR-008: Maximum 2 retrieval retries

| | |
|---|---|
| **Decision** | Corrective loop caps at 2 retries, then escalates |
| **Why** | Bounds cost and latency; prevents infinite loops; mirrors how a human would give up and ask |
| **Trade-off** | Some retrievable evidence may be missed; acceptable because misses escalate rather than fail silently |

### ADR-009: Synthetic data only

| | |
|---|---|
| **Decision** | All patients and policies are fictional |
| **Why** | No PHI risk; full control over traps and gold labels |
| **Trade-off** | Less realistic noise; mitigated by designed traps |

### ADR-010: Add `CONTRADICTED` status

| | |
|---|---|
| **Decision** | Four statuses: `MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED` |
| **Why** | "Patient declined PT" is not the same as "no PT documented"; conflating them risks false-`MET` or misleading gaps |
| **Trade-off** | Slightly more UI and eval complexity |

### ADR-011: Measure, don't claim

| | |
|---|---|
| **Decision** | Every RAG technique is evaluated against the gold set; the README reports only measured numbers |
| **Why** | Adding techniques does not automatically improve quality; credibility with judges |
| **Trade-off** | Time spent on eval; mitigated by a mini eval in P0 |

### ADR-012: Include a "whole chart in context" baseline

| | |
|---|---|
| **Decision** | Ablation includes a no-retrieval baseline |
| **Why** | At 5–15 docs per patient, judges will ask why RAG is needed; an honest comparison is the best answer |
| **Trade-off** | One more eval row; may show the baseline is competitive on small charts, in which case argue auditability and scale |

### ADR-013: MCP is an extension

| | |
|---|---|
| **Decision** | MCP is built only after the core works |
| **Why** | Core demo does not depend on it; MCP adds integration risk in a 24-hour window |
| **Trade-off** | The "MCP" claim is weaker if skipped; present it as designed-for rather than built |

---

## 2. Risk Register

**Scale:** Likelihood and Impact are Low / Medium / High.

| ID | Risk | L | I | Mitigation | Owner |
|---|---|:-:|:-:|---|:-:|
| R1 | Scope too large for 24 hours | H | H | P0/P1 split; cut line; hour-21 freeze | Both |
| R2 | Policy extraction is flaky | M | M | Fallback criteria file; show extraction as a bonus | A |
| R3 | LLM returns malformed JSON | H | M | Pydantic validation; one retry; fallback | A |
| R4 | Case B doesn't fail naturally on round 1 | M | H | Tune data vocabulary, not code; log real queries | B |
| R5 | Integration breaks at the seams | H | H | Contract-first; mock API; integrate by hour 14 | Both |
| R6 | Embedding dimension mismatch | M | M | Pin dimension in config in Phase 0 | A |
| R7 | LLM latency or rate limits on demo day | M | H | Cache demo-case results; backup video | A |
| R8 | AI-generated dates or durations wrong | H | H | Hand-verify all data; validator tests first | B |
| R9 | Outdated library APIs from AI tools | H | M | Check LangGraph, pgvector, MCP against current docs | A |
| R10 | Quote validator too strict (whitespace, punctuation) | M | M | Normalize whitespace; test edge cases | B |
| R11 | Sufficiency judge too lenient or strict | M | H | Required-facts checklist; eval on trap cases | A |
| R12 | Ablation shows RAG adds little on small charts | M | M | Report honestly; emphasize auditability, scale, false-`MET` | B |
| R13 | Safety boundary eroded by feature creep (e.g., readiness score) | M | H | No approval prediction; persistent disclaimer | Both |
| R14 | Wrong-patient evidence leaks into results | L | H | Metadata filter at query level plus identity validator | A |
| R15 | Live demo fails | M | H | Backup recording; cached runs; rehearse twice | B |
| R16 | Merge conflicts from parallel AI agents | M | M | Separate directories; commit often | Both |
| R17 | Crowded market: idea looks generic | M | M | Lead pitch with false-`MET` prevention and the validator demo | B |
| R18 | Team member unavailable or blocked | L | H | Shared contracts and docs; commit notes | Both |

---

## 3. Assumptions

| # | Assumption | If wrong |
|---|---|---|
| A1 | LLM and embedding APIs are available all 24 hours | Use cached results; smaller local embedding model |
| A2 | One policy is enough to show the architecture | Add a second policy in Phase 13 |
| A3 | Judges value visible control loops | Lead with the metrics and safety story instead |
| A4 | 3 patients suffice for the demo | Add patients only after Phase 6 |
| A5 | AI coding tools speed boilerplate, not data or tuning | Plan time accordingly |

---

## 4. Known Limitations (State Honestly)

- Synthetic data is cleaner than real charts.
- Small charts mean retrieval gains may be modest; the main value is auditability and verification.
- Policy extraction is evaluated on one policy.
- No real EHR, payer, or PHI integration.
- Verification catches unsupported claims but cannot judge clinical appropriateness.
- Metrics come from a small gold set and are indicative, not statistically strong.

---

## 5. Safety and Ethics

| Concern | Control |
|---|---|
| System appears to make medical or insurance decisions | Persistent disclaimer; no approval prediction; human sign-off |
| Fabricated evidence | Extractive quotes, validators, packet post-check, refusal on missing evidence |
| Wrong patient's data used | Patient-scoped retrieval; identity validator |
| Over-reliance on automation | Gaps escalate; reviewer can edit or reject |
| Privacy | Synthetic data only; production privacy and compliance are future work |

---

## 6. Open Decisions

| # | Decision needed | Needed by | Default |
|---|---|---|---|
| D1 | Embedding model and dimension | Hour 1 | Pin and move on |
| D2 | Which LLM for judgments vs. extraction | Hour 4 | One model, low temperature |
| D3 | Cache demo runs? | Hour 18 | Yes, with live-run flag |
| D4 | Include MCP? | After Phase 6 | Skip unless ahead of schedule |
| D5 | Show `CONTRADICTED` in the live demo? | Hour 18 | Only if time allows |

---

## 7. Cut Decisions (If Behind)

| Behind at | Cut |
|---|---|
| Hour 9 | Reranker, MCP, parent expansion |
| Hour 14 | Eval dashboard; shrink eval to 5 criteria |
| Hour 18 | Ablation to 2 rows; stop UI polish |
| Hour 21 | Everything except bug fixes and demo prep |

**Never cut:** the Case B retry timeline, the validator rejection, the Case C refusal, the safety disclaimer, the backup video.
