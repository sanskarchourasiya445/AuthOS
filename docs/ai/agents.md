# AuthOS — Agents

> Principle: **use the minimum number of agents required to solve the problem reliably.**
> LLMs handle language problems. Code handles anything that must be exactly right.

---

## 1. Overview

| # | Component | LLM? | Type | Reads | Writes |
|---|---|---|---|---|---|
| 1 | Case Router | No | Deterministic | Case config | Initial state |
| 2 | Policy Analyst | Yes | Agent | Policy chunks | Criteria |
| 3 | Chart Evidence Agent | Yes + retrieval | Agent (agentic RAG) | Chart chunks | Evidence, retry log |
| 4 | Verifier | LLM + code | Agent + validators | Evidence | Criterion status |
| 5 | Human Reviewer | n/a | Person | Results | Decisions |
| 6 | Packet Author | Yes | Agent | Verified evidence | Packet |

Sufficiency checking and query rewriting are **steps inside** the Chart Evidence Agent, not separate agents.

---

## 2. Shared Rules (All Agents)

1. Output **structured JSON** validated by Pydantic. On malformed output, retry once, then fall back.
2. Never invent facts, sources, quotes, or dates.
3. Never decide medical necessity or approval.
4. Only use tools allowed for that agent (least privilege).
5. Log inputs, outputs, and decisions to the audit log.
6. Respect loop caps. No agent may exceed 2 retrieval retries.

---

## 3. Case Router

**Purpose:** Initialize the workflow for one case.

| Item | Detail |
|---|---|
| Input | `case_id` |
| Logic | Look up patient, requested service, applicable policy (service → policy map) |
| Output | `AuthState` with `patient_id`, `service`, `policy_id`, empty results, `retrieval_round = 0` |
| LLM | None. Pure code |

**Failure modes:** unknown service or policy → stop with a clear error.

---

## 4. Policy Analyst

**Purpose:** Convert policy text into structured, checkable criteria.

| Item | Detail |
|---|---|
| Input | `policy_id`, service |
| Tools | `search_policy` (read-only) |
| Output | `list[Criterion]`, exceptions, definitions, cross-references |
| Constraint | Must not read patient data |

**Responsibilities**

- Retrieve the relevant policy sections.
- Extract each criterion with `id`, `text`, `evidence_type`, `required_facts`, and `min_duration_days` where applicable.
- Link exceptions to the criteria they waive (e.g., E1 red flags waive C1/C2).
- Record cross-references (e.g., "see Section 4.2").

**Example output**

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

**Failure modes and mitigations**

| Failure | Mitigation |
|---|---|
| Misses a criterion | Compare against hand-written gold criteria in eval |
| Malformed JSON | Retry once, then use fallback criteria file |
| Merges two criteria | Prompt requires one criterion per object; schema validates |

---

## 5. Chart Evidence Agent

**Purpose:** Find evidence for each criterion and recover when the first search fails. This is the primary agentic RAG component.

| Item | Detail |
|---|---|
| Input | One `Criterion`, `patient_id` |
| Tools | `hybrid_search` (read-only, patient-scoped), `retrieve_document` |
| Output | `list[EvidenceItem]`, `retry_log` |
| Loop cap | 2 retries |

### 5.1 Internal Steps

```text
Decompose → Expand vocabulary → Search → Sufficiency check
                                    ↑            │
                                    └─ Rewrite ←─┘ (if insufficient and round < 2)
```

1. **Decompose.** Criterion → required facts (e.g., `treatment_type`, `start_date`, `end_date`).
2. **Expand vocabulary.** "Conservative treatment" → PT, physiotherapy, rehab, NSAIDs, home exercise.
3. **Search.** Hybrid (dense + FTS + RRF) with patient metadata filter.
4. **Sufficiency check.** Compare required facts to found facts; return `found`, `missing`, `sufficient`.
5. **Rewrite.** Target the **missing** facts; add document-type hints; never repeat a prior query.
6. **Aggregate.** Combine evidence across documents (treatment in one note, dates in another).

### 5.2 Sufficiency Output

```json
{
  "criterion_id": "C2",
  "required": ["treatment_type", "start_date", "end_date"],
  "found": ["treatment_type"],
  "missing": ["start_date", "end_date"],
  "sufficient": false
}
```

### 5.3 Must Not

- Assign a final status (that is the Verifier's job).
- Paraphrase quotes. Evidence must be **extractive**.
- Search outside the case patient's documents.

### 5.4 Failure Modes

| Failure | Mitigation |
|---|---|
| Sufficiency judge too lenient | Required-facts checklist makes it a coverage test, not a vibe |
| Rewrite repeats the same query | Reject duplicates; force different terms |
| Infinite loop | Hard cap at 2 retries |
| Wrong-patient document retrieved | Metadata filter plus identity validator |

---

## 6. Verifier

**Purpose:** Challenge the evidence instead of trusting it, then assign a status.

| Item | Detail |
|---|---|
| Input | Criterion + candidate evidence |
| Tools | Validators (code), optional LLM for alignment judgment |
| Output | `CriterionResult` with `status`, `verified`, `validator_flags` |

### 6.1 Two Layers

| Layer | Who | Checks |
|---|---|---|
| Deterministic | Code | Source exists; quote verbatim; patient ID; date parsing; duration math; threshold comparison; evidence-to-criterion mapping |
| Semantic | LLM | Does this quote actually satisfy the criterion? Any contradiction? |

**Rule:** deterministic failures always override semantic judgments.

### 6.2 Status Decision Table

| Condition | Status |
|---|---|
| All required facts verified and thresholds satisfied | `MET` |
| No surviving evidence after verification | `MISSING` |
| Partial, indirect, or conflicting-but-unresolved evidence | `AMBIGUOUS` |
| Evidence contradicts the criterion (e.g., declined PT) | `CONTRADICTED` |

### 6.3 Example: Validator Override

```text
LLM claim:    "Treatment lasted 8 weeks."
Dates found:  March 4 → April 22
Computed:     49 days = 7 weeks
Result:       Claim rejected; evidence kept with computed duration
```

---

## 7. Human Reviewer

**Purpose:** Keep a person in control of every final decision.

| Step | Actions |
|---|---|
| **Gap review** (per non-`MET` criterion) | Add Information (re-verified), Accept Gap, Continue |
| **Final approval** | Approve, Edit, Reject |

Human-added information passes through the same validators as retrieved evidence.

---

## 8. Packet Author

**Purpose:** Produce the final review packet.

| Item | Detail |
|---|---|
| Input | Verified structured results only, plus human decisions |
| Tools | `generate_report` (write-only) |
| Output | Packet: case summary, criteria table, evidence with citations, gaps, reviewer decisions |

**Rules**

- Must not introduce new facts, dates, or sources.
- Every sentence about a criterion must cite an evidence item.
- Post-generation check: any claim without matching evidence is flagged and the packet is blocked.
- Includes the disclaimer: administrative preparation only.

---

## 9. Orchestration Summary

```text
Case Router
   ↓
Policy Analyst → criteria
   ↓
for each criterion:
    Chart Evidence Agent  (retrieve → sufficiency → rewrite ≤ 2)
         ↓
    Verifier              (validators + semantic check → status)
   ↓
Human Reviewer            (gap review → final approval)
   ↓
Packet Author             (verified evidence only)
```

---

## 10. Tool Permissions

| Tool | Policy Analyst | Evidence Agent | Verifier | Packet Author |
|---|:-:|:-:|:-:|:-:|
| `search_policy` | ✅ | ❌ | ❌ | ❌ |
| `hybrid_search` (chart) | ❌ | ✅ | ❌ | ❌ |
| `retrieve_document` | ❌ | ✅ | ✅ | ❌ |
| `get_patient_record` | ❌ | ❌ | ✅ | ❌ |
| `generate_report` | ❌ | ❌ | ❌ | ✅ |
| Validators | ❌ | ❌ | ✅ | ✅ (post-check) |

---

## 11. Prompting Guidelines

- One job per prompt; state what the agent must **not** do.
- Provide the JSON schema and one example in the prompt.
- Require extractive quotes with source IDs.
- Instruct "if evidence is absent, return empty; do not infer."
- Keep temperature low for extraction, verification, and sufficiency steps.
