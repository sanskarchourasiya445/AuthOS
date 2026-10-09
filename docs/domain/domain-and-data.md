# AuthOS — Domain and Data

---

## 1. Domain Primer

**Prior authorization (PA):** Before certain services are covered, a payer requires proof that the patient meets the payer's policy criteria. Staff assemble that proof from the patient's records.

**AuthOS's role:** assemble and verify the evidence packet. It does **not** decide medical necessity or approval.

### 1.1 Glossary

| Term | Meaning |
|---|---|
| **Payer** | Insurance company that decides coverage |
| **Policy** | Payer document listing criteria for coverage of a service |
| **Criterion** | One checkable requirement in a policy (e.g., C2) |
| **Exception** | Condition that waives or changes a criterion (e.g., red flags) |
| **Evidence** | A verbatim quote from a chart document supporting a criterion |
| **Chart** | A patient's collection of clinical documents |
| **Conservative treatment** | Non-surgical care such as PT, NSAIDs, home exercise |
| **PT** | Physical therapy |
| **LBP** | Low back pain |
| **Red flags** | Findings (e.g., cauda equina signs) that may waive normal criteria |
| **Sufficiency** | Whether retrieved evidence covers every fact a criterion requires |
| **Verification** | Deterministic and semantic checks that evidence is real, correct, and aligned |
| **Review packet** | Final cited document for human sign-off |

### 1.2 Criterion Statuses

| Status | Meaning | Human action |
|---|---|---|
| `MET` | Verified evidence supports the criterion | Confirm at final review |
| `MISSING` | No supporting evidence was found in the supplied records after the defined bounded search | Add information or accept gap |
| `AMBIGUOUS` | Partial, indirect, or unresolved-conflict evidence | Review and decide |
| `CONTRADICTED` | Chart contradicts the criterion | Review; do not override silently |

---

## 2. Domain Model

```text
Case ──── Patient
  │          └── Documents ── Chunks
  ├── Service (e.g., Lumbar MRI)
  └── Policy ── Sections ── Criteria ── Required Facts
                    └── Exceptions

Criterion ──▶ Evidence[] ──▶ CriterionResult ──▶ Packet
                                  │
                                  └── RetryLog[]
```

### 2.1 Entities

| Entity | Key fields |
|---|---|
| **Patient** | `patient_id` (e.g., P-104), synthetic demographics |
| **Document** | `id`, `patient_id`, `doc_type`, `doc_date`, `title`, `full_text` |
| **Chunk** | `id`, `document_id`, `patient_id`, `text`, `doc_date`, embedding, tsvector |
| **Policy** | `policy_id`, `service`, `title`, `version` |
| **PolicyChunk** | `id`, `policy_id`, `section`, `text`, embedding, tsvector |
| **Criterion** | `id`, `text`, `evidence_type`, `required_facts[]`, `min_duration_days?`, `exception_ids[]`, `source_chunk` |
| **EvidenceItem** | `source_id`, `patient_id`, `quote`, `date`, `retrieval_round` |
| **CriterionResult** | `criterion_id`, `status`, `verified`, `evidence[]`, `missing_facts[]`, `retry_log[]`, `validator_flags[]` |
| **Case** | `id`, `patient_id`, `service`, `policy_id`, `status` |
| **Packet** | Summary, criteria table, cited evidence, gaps, reviewer decisions, disclaimer |

### 2.2 Document Types

`primary_care_note`, `specialist_note`, `pt_evaluation`, `pt_followup`, `pt_discharge`, `imaging_report`, `medication_history`, `procedure_history`, `discharge_note`

### 2.3 Evidence Types (policy side)

`diagnosis`, `treatment_history`, `symptom_duration`, `imaging_history`, `neuro_findings`, `medication_history`, `red_flags`

---

## 3. Synthetic Policy: POL-LMRI-001 (Lumbar MRI)

| ID | Criterion | Required facts |
|---|---|---|
| C1 | Low back pain documented for at least 6 weeks | `symptom_onset_date`, `symptom_duration` |
| C2 | Conservative treatment for at least 6 weeks | `treatment_type`, `start_date`, `end_date` |
| C3 | Persistent symptoms despite treatment | `symptom_status_after_treatment` |
| C4 | Neurological deficit or radicular symptoms documented | `neuro_finding` or `radicular_symptom` |
| C5 | No lumbar MRI in the prior 12 months | `prior_imaging_dates` |
| E1 | **Exception:** documented red-flag findings waive C1 and C2 | `red_flag_finding` |

**Policy structure to include:** eligibility section, exclusions, one exception, a definitions section ("conservative treatment means…"), and one cross-reference ("see Section 4.2").

Later policies (extension): POL-RA-BIO-001, POL-KNEE-001, POL-CT-001.

---

## 4. Synthetic Patients

| Case | Patient | Purpose |
|---|---|---|
| **A** | P-101 | Happy path |
| **B** | P-104 | Corrective retrieval (vocabulary mismatch) |
| **C** | P-107 | Missing evidence |

Each patient: 5–10 documents, 2026 dates, fully fictional.

### 4.1 P-101 (Happy Path)

| Document | Key content |
|---|---|
| Primary care note | LBP since January; conservative plan started |
| PT discharge | PT completed, with clear start/end dates over 6+ weeks |
| Specialist note | Persistent pain; radicular symptoms |
| Medication history | NSAID course |
| Imaging history | No prior lumbar MRI |

**Expected:** C1–C5 `MET`; no retry needed.

### 4.2 P-104 (Corrective Retrieval)

| Document | Key content |
|---|---|
| Primary care note | "Patient referred for rehab sessions and NSAID trial" (no dates) |
| PT evaluation | PT started March 4 |
| PT follow-up | Ongoing symptoms; notes "about 8 weeks of therapy so far" (**planted unsupported claim**) |
| PT discharge | "Patient completed PT from March 4 through April 22." |
| Specialist note | Persistent symptoms despite therapy |

**Anchor facts:** March 4 → April 22 = **49 days = 7 weeks**. The "about 8 weeks" note is deliberately wrong so the validator has something to reject.

**Expected flow for C2**

| Round | Query | Found | Missing | Sufficient |
|---|---|---|---|---|
| 1 | "conservative treatment 6 weeks" | treatment type | duration / dates | No |
| 2 | "physical therapy treatment start date end date duration persistent symptoms" | treatment type, start, end | none | Yes |

**Expected:** C2 `MET` at 7 weeks; any 8-week claim rejected.

### 4.3 P-107 (Missing Evidence)

| Document | Key content |
|---|---|
| Primary care note | Mentions "tried some exercises"; no dates, no duration |
| Specialist note | Pain complaint; no statement on persistence after treatment |
| Imaging history | No prior lumbar MRI |

**Expected:** C2 and C3 `MISSING` or `AMBIGUOUS` after the initial retrieval and up to two corrective retries; escalate to human; nothing fabricated.

---

## 5. Gold Dataset (Evaluation)

### 5.1 Record Format

```json
{
  "case_id": "CASE-B",
  "patient_id": "P-104",
  "criterion_id": "C2",
  "gold_policy_chunks": ["POL-LMRI-001-S4"],
  "gold_evidence_spans": ["PT_NOTE_004"],
  "gold_status": "MET",
  "trap_type": "vocabulary_mismatch"
}
```

### 5.2 Trap Types

| `trap_type` | Description | Tests |
|---|---|---|
| `none` | Straightforward | Baseline |
| `vocabulary_mismatch` | Policy and chart terms differ | Vocabulary expansion, dense search |
| `split_evidence` | Facts spread across documents | Aggregation |
| `duration_error` | Note states wrong duration | Date validator |
| `missing_evidence` | No support exists | Refusal to fabricate |
| `negation` | "Declined PT" | `CONTRADICTED` handling |
| `wrong_patient_doc` | Another patient's note in corpus | Metadata filter, identity validator |
| `relative_date` | "6 weeks ago" | Date handling |

### 5.3 Metrics

| Group | Metric |
|---|---|
| Retrieval | Context recall, context precision, MRR, retrieval relevance |
| Evidence | Citation correctness, evidence sufficiency, status accuracy, missing-evidence detection, **false-`MET` rate** |
| Generation | Groundedness / faithfulness, answer relevance |

Target size: about 10 criterion records for the core build; grow with Phase 13.

---

## 6. Data Rules

1. **Synthetic only.** No real PHI.
2. **Hand-verify** every date and duration. Do not trust AI-generated date math.
3. **IDs are stable** (`PT_NOTE_004`, `POL-LMRI-001-S4`) so gold labels remain valid.
4. **Quotes are verbatim.** Gold evidence spans must exist in the source text exactly.
5. **Patient isolation.** Every chunk carries `patient_id`; every query filters on it.
6. **Dates in ISO format** in structured fields (`2026-04-22`); free text may vary.
7. **Seed script is idempotent.** Re-running it resets to a known state.

---

## 7. Data Lifecycle

```text
Author synthetic files (policies/, patients/)
        │
        ▼
Seed script: chunk → embed → load (documents, chunks, tsv)
        │
        ▼
Run case: results + retry logs + audit log
        │
        ▼
Eval: compare results to gold dataset → metrics, ablation
```

Reset between demos: truncate `cases`, `criterion_results`, `audit_log`; keep ingested content.
