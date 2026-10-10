# AuthOS Phase 10: Retrieval Quality Evaluation, Evidence Recall, Failure Analysis & Architecture Decisions Report

**Document Version:** 1.0  
**Status:** Approved & Formally Documented  
**Lead Evaluator:** Principal AI Systems Architect, Senior RAG Engineer & Safety Evaluation Lead  
**Evaluation Date:** October 10, 2026  
**Git Commit:** `caf39402e168313cd834bc40eb6facf0255b5b3c` (Branch: `main`)  
**Environment:** Windows 11, Python 3.13.1, PostgreSQL 18, fastembed 0.7.4 (local CPU ONNX runtime)

---

## 1. Executive Summary

Phase 10 conducted an exhaustive, skeptical, and mathematically disciplined investigation of clinical evidence retrieval in **AuthOS**, evaluating retrieval quality independently from downstream criterion verification and clinician adjudication.

### Core Discoveries:
1. **Lexical BM25 Strength & Precision**: The deterministic BM25Okapi implementation achieves near-zero latency (0.85 ms) and 100% clean abstention on negative controls and off-domain queries. However, it suffers from vocabulary mismatch when clinical terminology variants (e.g. *"ambulation assistance and non operative rehabilitation regimen"*) share zero lexical tokens with the chart (*"supervised physical therapy"*), yielding 0.8571 recall.
2. **Bounded Corrective Retrieval Efficacy**: Rule-based, bounded query reformulations (maximum 2 retries) bridge clinical synonym gaps deterministically, achieving **1.0000 recall** and **0.9048 MRR** while preserving **100% clean abstention** on off-domain and negative control queries with minimal latency overhead (0.88 ms).
3. **The Uncalibrated Dense Retrieval Pitfall**: Local dense semantic embeddings (`BAAI/bge-small-en-v1.5`) without score thresholding achieve 1.0000 recall on positive queries, but **completely fail safety gates** on negative controls: cosine similarities for unmentioned or off-domain queries (e.g. coronary artery bypass graft queries evaluated on lumbar records) hover between 0.55 and 0.68. Raw dense search returns 3 irrelevant candidates on 100% of negative control queries (0% empty-result rate).
4. **Calibrated Threshold Limitations**: Setting a static global cosine cutoff `min_score = 0.70` restores 100% abstention on negative controls, but drops recall back to 0.8571 because true semantic synonym matches (`RET-04`) score `0.6519`. No single static cosine threshold separates domain-proximate true negatives from subtle semantic matches.
5. **Calibrated Hybrid RRF Stability**: When Reciprocal Rank Fusion (RRF) is combined with a calibrated dense threshold (`min_dense_score = 0.70`), Hybrid RRF passes 100% of safety checks without foreign candidate leakage.
6. **Retrieval Relevance != Criterion Verification**: Across all tested strategies, retrieving a highly relevant passage (e.g. patient declining physical therapy or negative neurological exam) does not mutate criterion state to `MET`. Downstream deterministic verification rigorously rejects or marks contradictory evidence as `CONTRADICTED` and sub-duration evidence as `AMBIGUOUS`.

---

## 2. Current Retrieval Architecture & Call Paths

AuthOS maintains strict boundaries between source ingestion, chunking, retrieval, verification, and human review:

```
[Raw Clinical Documents (JSON/Text)]
               │
               ▼
[Ingestion Engine: backend/rag/ingest.py]
  - Paragraph/Sentence Boundary Preservation
  - Exact Character Offset Tracking: text[char_start:char_end] == chunk_text
  - Version Scoping: chunk_version='v1'
               │
               ▼
[PostgreSQL: DocumentChunkModel]
  - Indexed by (patient_id, chunk_version, source_id, chunk_index)
  - Zero cross-patient or policy mixing
               │
               ▼
[Retrieval Router: backend/rag/retrieval.py]
  - Strictly patient-scoped SQL filter: patient_id == case.patient_id
  - Defensive cross-patient assertion
               │
  ┌────────────┴────────────────────────────────────────┐
  │                                                     │
  ▼ (Default Strategy)                                  ▼ (Configurable Option)
[Pure Lexical BM25Okapi]                      [Bounded Corrective BM25: corrective.py]
  - Stopword filtering                          - Maximum 2 retries
  - Term Frequency / Lucene IDF                 - Deterministic synonym substitution
  - Deterministic tie-breaking                  - Substantive keyword fallback
  │                                             │
  └────────────┬────────────────────────────────┘
               │
               ▼
[Ranked Evidence Candidates (Top-k)]
  - Carries exact quote, source_id, char_start, char_end, doc_date
               │
               ▼
[Deterministic Verifier: backend/verification/engine.py]
  - Verbatim text slice assertion
  - Negation pattern detection
  - Temporal & duration threshold arithmetic (>= 42 days)
  - Polarity assignment: SUPPORTING vs CONTRADICTING
  - State assignment: MET, MISSING, AMBIGUOUS, CONTRADICTED
               │
               ▼
[Immutable Audit Trail & React Reviewer Workstation (/app)]
  - Human clinician adjudication desk
  - Advisory AI proposals rendered with explicit non-authoritative disclaimers
```

---

## 3. Implemented vs. Enabled Retrieval Strategies

| Strategy | Module Location | Implementation Status | Default Configuration | Evaluation Verdict |
|---|---|---|---|---|
| **BM25Okapi Baseline** | `backend/rag/retrieval.py` | Fully Implemented & Unit Tested | **ENABLED BY DEFAULT** | **KEEP** |
| **Bounded Corrective BM25** | `backend/rag/corrective.py` | Fully Implemented & Unit Tested | Optional (`enable_corrective_retrieval=False`) | **ADOPT (Recommended)** |
| **Dense Embeddings (bge-small-en-v1.5)** | `backend/rag/dense_experiment.py` | Local ONNX Runtime Implemented | Experimental / Inactive in Production | **EXPERIMENTAL (Calibrated only)** |
| **Raw Cosine Dense (min_score=0.0)** | `backend/rag/dense_experiment.py` | Implemented | Inactive | **REJECT (Safety failure)** |
| **Hybrid BM25 + Dense RRF (Raw)** | `backend/rag/dense_experiment.py` | Implemented | Inactive | **REJECT (Safety failure)** |
| **Hybrid BM25 + Dense RRF (Calibrated 0.70)** | `backend/rag/dense_experiment.py` | Implemented | Inactive | **EXPERIMENTAL** |
| **Cross-Encoder Neural Reranking** | N/A | Not Implemented | Inactive | **DEFER** |
| **PostgreSQL pgvector / HNSW** | N/A | Not Implemented (Alembic preserved) | Inactive | **DEFER** |

---

## 4. Reproducible Baseline & Evaluation Protocol

- **Dataset**: `eval-dataset-v1.0` (frozen synthetic benchmark, 34 verification cases, 10 retrieval queries)
- **Execution Command**: `python -m backend.evaluation.runner`
- **Safety Gates**:
  - Zero false-positive MET results on adversarial cases (`0 observed / 0 threshold`)
  - Zero cross-patient leakage across all retrieval methods (`0 observed / 0 threshold`)
  - Strict provenance integrity (`raw_text[char_start:char_end] == chunk_text`)
  - 100% determinism across repeat executions

---

## 5. Metric Definitions & Formulas

1. **Precision@k**: $\frac{|\text{Retrieved Sources at } k \cap \text{Expected Sources}|}{|\text{Retrieved Sources at } k|}$
   - *Denominator*: Total sources returned at cutoff $k$. If no candidates returned, reported as $0.0$.
2. **Recall@k**: $\frac{|\text{Retrieved Sources at } k \cap \text{Expected Sources}|}{|\text{Expected Sources}|}$
   - *Denominator*: Number of ground-truth relevant documents in the evaluation case.
3. **Mean Reciprocal Rank (MRR)**: $\frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$, where $\text{rank}_i$ is the rank of the first relevant document.
4. **Empty-Result Rate (Safety)**: $\frac{\text{Safety Queries Returning 0 Candidates}}{\text{Total Safety Queries}}$.
   - *Denominator*: 3 safety queries (`RET-08` cross-patient, `RET-09` unmentioned condition, `RET-10` off-domain). Target: **100%**.
5. **Irrelevant Candidate Rate (Safety)**: $\frac{\text{Safety Queries Returning } >0 \text{ Candidates}}{\text{Total Safety Queries}}$. Target: **0%**.
6. **Cross-Patient Violation Count**: Any candidate chunk belonging to a patient other than the scoped query patient. Target: **0**.

---

## 6. Strategy Comparison Table

Evaluated on `eval-dataset-v1.0` with $k = 3$:

| Retrieval Strategy | Precision@k | Recall@k | MRR | Empty Rate (Safety) | Irrelevant Cand. Rate | Mean Latency | Median Latency | Safety Status |
|---|---|---|---|---|---|---|---|---|
| **BM25 (Baseline)** | 0.5476 | 0.8571 | 0.7619 | 3/3 (100.0%) | 0.0% | 0.85 ms | 0.69 ms | ✅ **PASS** |
| **BM25 (Bounded Corrective)** | **0.6190** | **1.0000** | **0.9048** | **3/3 (100.0%)** | **0.0%** | **0.88 ms** | **0.72 ms** | ✅ **PASS** |
| **Dense (Raw Cosine, min_score=0.0)** | 0.3809 | 1.0000 | 1.0000 | 0/3 (0.0%) | 100.0% | 51.78 ms | 35.01 ms | ❌ **FAIL** |
| **Dense (Calibrated min_score=0.70)** | 0.7619 | 0.8571 | 0.8571 | 3/3 (100.0%) | 0.0% | 32.32 ms | 32.31 ms | ✅ **PASS** |
| **Hybrid RRF (Raw BM25 + Raw Dense)** | 0.3809 | 1.0000 | 0.9286 | 0/3 (0.0%) | 100.0% | 34.52 ms | 34.55 ms | ❌ **FAIL** |
| **Hybrid RRF (Calibrated BM25 + Dense 0.70)**| 0.5476 | 0.8571 | 0.7857 | 3/3 (100.0%) | 0.0% | 33.42 ms | 32.59 ms | ✅ **PASS** |

---

## 7. Systematic Failure Taxonomy Analysis (12 Categories)

| # | Category | Description / Clinical Scenario | Observed Engine Behavior | Downstream Verifier Impact |
|---|---|---|---|---|
| **1** | **Lexical Mismatch** | Query uses *"ambulation assistance non operative rehabilitation"* while chart states *"supervised physical therapy"*. | BM25 returns `[]` (Recall: 0.0). Corrective BM25 applies rule `("non operative rehabilitation", "conservative treatment physical therapy")` and recovers target chunk at rank 1. | Verifier correctly receives evidence under Corrective BM25; verifies 50 days duration as `MET`. |
| **2** | **Terminology Mismatch** | Query uses *"ordering clinician requisition for lumbar imaging study"*. | BM25 partially matches on keywords, ranking `ORDER-03` at #1. Corrective BM25 synonyms reinforce target. | Verifier confirms requisition fact. |
| **3** | **Negation & Polarity** | Query for cauda equina / sphincter changes retrieves note *"No bowel or bladder changes reported"*. | Lexical search successfully retrieves `NOTE-01` due to term overlap. | **Verifier Protection**: Negation pattern matches; engine refuses to mark `MET` and assigns `CONTRADICTED`. |
| **4** | **Temporal Mismatch** | Progress note records 10 days of physical therapy (sub-threshold for 6-week policy). | Retrieval correctly finds the note. | **Verifier Protection**: Date arithmetic calculates 10 days (< 42 days required); assigns `AMBIGUOUS`. |
| **5** | **Chunk-Boundary Loss** | Multi-paragraph note with dates in paragraph 2 and diagnosis in paragraph 1. | Ingestion engine preserves paragraph boundaries with exact character slice offsets. | Verbatim slice `text[char_start:char_end]` verified; zero offset drift. |
| **6** | **Multi-Passage Requirements** | Criterion requires proving both symptom persistence and ordering requisition. | Top-3 retrieval returns both `NOTE-01` (symptoms) and `ORDER-03` (requisition). | Verifier aggregates facts across distinct citations to substantiate criterion. |
| **7** | **Duration / Threshold Gap** | Chart states *"attended several sessions; exact start date and duration are not documented"*. | Retrieval returns `PT-02`. | **Verifier Protection**: Identifies conservative ambiguity pattern; assigns `AMBIGUOUS` with `review_required=True`. |
| **8** | **Contradictory Evidence** | Chart states *"Physical therapy was offered. Patient declined physical therapy at this visit"*. | Retrieval returns `PT-02` at Rank 1. | **Verifier Protection**: Detects refusal keyword (`declined`); marks criterion `CONTRADICTED`. |
| **9** | **Irrelevant High-Rank Passages** | Order note mentions *"low back pain"* but lacks clinical duration detail found in clinic note. | Both notes retrieved. `ORDER-03` ranks #1 in BM25; `NOTE-01` ranks #3. | Verifier examines both; extracts duration from `NOTE-01`. |
| **10** | **Source-Offset Mismatch** | Corrupted or out-of-bounds character offsets in evidence citation. | Detected immediately by `validate_evidence_provenance`. | **Fail-Closed**: Citation marked invalid (`INVALID_OFFSETS`), rejected from criterion support. |
| **11** | **Metadata Filtering Failure** | Query scoped to non-existent chunk version (e.g. `v99`). | Returns empty candidate list cleanly without database error or cross-contamination. | Verifier cleanly assigns `MISSING`. |
| **12** | **Patient Isolation Failure** | Query containing exact verbatim text from Patient SYN-P002 executed under Patient SYN-P001. | SQL filter `DocumentChunkModel.patient_id == patient_id` strictly confines search; zero foreign chunks returned. | Verifier evaluates only isolated patient documents; 0 cross-patient violations. |

---

## 8. Implemented Changes & Regression Test Results

### Code Changes:
1. `backend/rag/dense_experiment.py`:
   - Enhanced `retrieve_hybrid_chart_candidates` with an optional `min_dense_score: float = 0.0` parameter.
   - Added early termination guard when both BM25 and thresholded dense pools are empty, enabling safe Calibrated Hybrid RRF evaluation.
2. `backend/evaluation/runner.py`:
   - Added `Hybrid (Calibrated BM25 + Dense RRF)` to the automated evaluation pipeline to report both raw and calibrated RRF metrics side-by-side.
3. `tests/test_phase10_retrieval_taxonomy.py`:
   - Implemented 13 unit and integration tests systematically verifying each of the 12 failure taxonomy categories and calibrated hybrid safety.

### Test Execution Verification:
- **Pytest Full Suite**: `python -m pytest tests/` -> **246 passed, 1 warning in 34.57s** (233 original + 13 new Phase 10 taxonomy tests).
- **Vitest Suite**: `npm test` (in `frontend/`) -> **19/19 passed in 6.82s**.
- **Playwright Browser E2E**: `python -m pytest tests/test_phase9_react_browser_e2e.py` -> **1 passed in 6.17s**.
- **Evaluation Runner**: `python -m backend.evaluation.runner` -> **PASSED, 100% verifier accuracy, 0 false-positive METs**.

---

## 9. Architecture Decision Record (ADR)

| Component / Proposal | Decision | Technical Rationale |
|---|---|---|
| **Deterministic BM25 Baseline** | **KEEP** | Essential foundation. Sub-millisecond latency (0.85 ms), zero hallucination risk, 100% clean abstention on negative controls, zero dependency footprint. |
| **Bounded Corrective Retrieval** | **ADOPT** | Proven to boost recall from 0.8571 to **1.0000** and MRR from 0.7619 to **0.9048** on clinical synonym mismatch while preserving **100% clean abstention** on negative controls with negligible overhead (+0.03 ms). Recommended as default production configuration. |
| **Raw Dense Embeddings (min_score=0.0)** | **REJECT** | Severe safety failure. 100% false-positive candidate return rate on negative controls, generating plausible-sounding but completely irrelevant evidence for unmentioned conditions. |
| **Calibrated Dense Embeddings (min_score=0.70)** | **EXPERIMENTAL** | Safely restores 100% negative abstention, but static global thresholding drops recall back to 0.8571 on subtle synonyms. High latency (32 ms vs 0.85 ms). Retain for offline experimentation. |
| **Raw Hybrid RRF** | **REJECT** | Inherits raw dense failure mode: reciprocal rank fusion rewards irrelevant dense matches even when BM25 correctly yields 0 hits. |
| **Calibrated Hybrid RRF** | **EXPERIMENTAL** | Safe (100% empty-result rate on negative controls), but does not outperform Bounded Corrective BM25 in recall (0.8571 vs 1.0000) and incurs 38x latency overhead. |
| **Cross-Encoder Neural Rerankers** | **DEFER** | Unjustified resource and latency overhead for small patient document sets (<50 chunks). |
| **PostgreSQL pgvector / Cloud Vector DB** | **DEFER** | Over-engineering for patient-isolated charts. Standard relational indexing with in-memory BM25/ONNX execution is faster, simpler, and guarantees strict patient isolation. |

---

## 10. Recommendations & Readiness for Phase 11 (LLM Criterion Analysis)

Phase 10 provides solid ground for connecting the first real LLM provider in Phase 11:

### Invariants for Phase 11 LLM Criterion Analysis:
1. **Input Contract**: The LLM Criterion Analysis Agent must consume ONLY retrieved candidate chunks that have passed patient boundary checks, accompanied by policy criterion text.
2. **Output Contract**: The agent must emit structured JSON containing `status` (`MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`), `rationale`, and `quoted_evidence` (with exact source IDs).
3. **Advisory Boundary**: Agent proposals must remain strictly **advisory**. They must be persisted into the `agent_proposals` table and rendered in the React workstation's comparison screen.
4. **Authority Invariant**: The deterministic verification engine (`verify_criterion_evidence`) remains the **sole authoritative gate** for whether a criterion is accepted as verified. An LLM proposal must NEVER directly mutate `criterion_results.verified` or `criterion_results.status`.
5. **Human Primacy**: Only an authorized human clinical reviewer can commit final determinations (`APPROVE_PACKET` / `REJECT_PACKET`).

---

## 11. Exact Commands to Reproduce Phase 10 Results

```bash
# 1. Run Complete Pytest Suite (246 tests)
python -m pytest tests/

# 2. Run Phase 10 Taxonomy Tests Specifically
python -m pytest tests/test_phase10_retrieval_taxonomy.py -v

# 3. Run Deterministic Baseline & Retrieval Comparative Benchmark
python -m backend.evaluation.runner

# 4. Run Multi-Agent Workflow Benchmark
python -m backend.evaluation.agent_eval

# 5. Run Frontend Vitest Component Suite
cd frontend && npm test

# 6. Run Playwright React Workstation Browser E2E
python -m pytest tests/test_phase9_react_browser_e2e.py -v
```
