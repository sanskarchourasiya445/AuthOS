# AuthOS — Reliability Baseline & Adversarial Evaluation Report

> **CRITICAL SAFETY NOTICE:**
> This report reflects empirical verification over frozen synthetic fixtures (`SYN-P001`, `SYN-P002`, `SYN-P003`).
> It establishes software engineering regression guarantees and evidence-linter invariants,
> **NOT** clinical efficacy, medical necessity decisions, or real-world prior-authorization approval accuracy.

- **Dataset Version:** `eval-dataset-v1.0`
- **Execution Timestamp:** `2026-10-10T07:02:08.480942+00:00`
- **Git Commit:** `25b2da4007a13b4af5febd71ec263c4f71c01d05` (Branch: `main`, Dirty: `true`)
- **Environment:** `Windows-11-10.0.26300-SP0`, Python `3.13.1`

## 1. Executive Summary & Mandatory Safety Gates

**Overall Safety Verdict:** `PASSED`

| Safety Gate | Status | Observed | Threshold | Description |
|---|---|---|---|---|
| `zero_false_positive_met` | ✅ PASS | `0` | `0` | Zero false-positive MET results permitted across all adversarial non-MET cases. |
| `zero_cross_patient_leakage` | ✅ PASS | `0` | `0` | Zero cross-patient evidence leakage permitted across verification and retrieval. |
| `exact_provenance_integrity` | ✅ PASS | `5 tampered/missing instances detected` | `> 0 detections` | Exact quote offsets and source existence enforced without fabrication. |
| `determinism_verified` | ✅ PASS | `True` | `True` | 100% deterministic output across repeated executions on identical inputs. |

## 2. Evidence Verifier Evaluation

- **Total Verification Cases:** `34` (`34` synthetic benchmark cases)
  - Development Subset (Disclosed Non-Holdout): `12` cases
  - Adversarial Holdout Subset: `22` cases
- **Overall Status Accuracy:** `100.00%` (34/34)
- **False-Positive MET Count:** `0` (Rate: `0.0`)
- **False-Negative MET Count:** `0` (Rate: `0.0`)
- **Undefined Metrics (Zero Denominators):** `0` (truthfully reported as `null` / `N/A`)
- **Determinism:** `True` (reproducible across repeated runs)

### 2.1 4x4 Confusion Matrix (Predicted vs Expected)

| Expected \ Predicted | MET | AMBIGUOUS | CONTRADICTED | MISSING |
|---|---|---|---|---|
| **MET** | 5 | 0 | 0 | 0 |
| **AMBIGUOUS** | 0 | 12 | 0 | 0 |
| **CONTRADICTED** | 0 | 0 | 7 | 0 |
| **MISSING** | 0 | 0 | 0 | 10 |

### 2.2 Per-Class Performance

| Status Class | True Positives | False Positives | False Negatives | Precision | Recall | F1 Score |
|---|---|---|---|---|---|---|
| **MET** | 5 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| **AMBIGUOUS** | 12 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| **CONTRADICTED** | 7 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |
| **MISSING** | 10 | 0 | 0 | 1.0000 | 1.0000 | 1.0000 |

### 2.3 Performance by Adversarial Category

| Adversarial Category | Total Cases | Correct | False Positive MET | Accuracy |
|---|---|---|---|---|
| `ambiguous_evidence` | 8 | 8 | 0 | 100.0% |
| `conflicting_evidence_across_documents` | 3 | 3 | 0 | 100.0% |
| `correctly_supported_claims` | 4 | 4 | 0 | 100.0% |
| `cross_patient_evidence_attempts` | 2 | 2 | 0 | 100.0% |
| `explicitly_contradicted_evidence` | 3 | 3 | 0 | 100.0% |
| `malformed_or_invalid_provenance_offsets` | 3 | 3 | 0 | 100.0% |
| `minimum_duration_and_multi_fact_requirements` | 3 | 3 | 0 | 100.0% |
| `missing_evidence` | 3 | 3 | 0 | 100.0% |
| `negation_and_temporal_ambiguity` | 1 | 1 | 0 | 100.0% |
| `prompt_injection_in_documents` | 1 | 1 | 0 | 100.0% |
| `unsupported_claims_with_keyword_overlap` | 3 | 3 | 0 | 100.0% |

## 3. Retrieval Baseline & Comparative Evaluation

Evaluated across `10` synthetic queries at `k=3`:
- **Quality-Oriented Queries:** 7 queries with positive clinical ground truth.
- **Safety Invariant Queries:** 3 queries (cross-patient isolation, negative controls, zero-match).

### 3.1 Aggregate Performance Across Candidate Methods

| Retrieval Method | Precision@k | Recall@k | MRR | Empty-Result Rate (Safety) | Irrelevant Cand. Rate | Mean Latency | Median Latency | Safety Verdict |
|---|---|---|---|---|---|---|---|---|
| **BM25 (Baseline)** | 0.5476 | 0.8571 | 0.7619 | 3/3 (100.0%) | 0.0% | 0.89 ms | 0.73 ms | ✅ PASS |
| **BM25 (Bounded Corrective)** | 0.6190 | 1.0000 | 0.9048 | 3/3 (100.0%) | 0.0% | 1.0 ms | 0.94 ms | ✅ PASS |
| **Dense (Raw Cosine)** | 0.3809 | 1.0000 | 1.0000 | 0/3 (0.0%) | 100.0% | 52.36 ms | 33.9 ms | ❌ FAIL |
| **Dense (Calibrated min_score=0.70)** | 0.7619 | 0.8571 | 0.8571 | 3/3 (100.0%) | 0.0% | 34.51 ms | 33.73 ms | ✅ PASS |
| **Hybrid (BM25 + Dense RRF)** | 0.3809 | 1.0000 | 0.9286 | 0/3 (0.0%) | 100.0% | 35.71 ms | 35.44 ms | ❌ FAIL |
| **Hybrid (Calibrated BM25 + Dense RRF)** | 0.5476 | 0.8571 | 0.7857 | 3/3 (100.0%) | 0.0% | 34.87 ms | 34.51 ms | ✅ PASS |

### 3.2 Per-Query Breakdown (BM25 vs Bounded Corrective vs Dense)

| Case ID | Category | Expected Sources | BM25 Baseline | BM25 Bounded Corrective | Dense (Calibrated 0.70) | Dense (Raw Cosine) |
|---|---|---|---|---|---|---|
| `RET-01-RELEVANT` | `correctly_supported_claims` | `SYN-P001-PT-02` | SYN-P001-PT-02, SYN-P001-ORDER-03, SYN-P001-NOTE-01 | SYN-P001-PT-02, SYN-P001-ORDER-03, SYN-P001-NOTE-01 | SYN-P001-PT-02 | SYN-P001-PT-02, SYN-P001-NOTE-01, SYN-P001-ORDER-03 |
| `RET-02-KEYWORD-OVERLAP` | `unsupported_claims_with_keyword_overlap` | `SYN-P001-NOTE-01` | SYN-P001-ORDER-03, SYN-P001-PT-02, SYN-P001-NOTE-01 | SYN-P001-ORDER-03, SYN-P001-PT-02, SYN-P001-NOTE-01 | SYN-P001-NOTE-01, SYN-P001-ORDER-03, SYN-P001-PT-02 | SYN-P001-NOTE-01, SYN-P001-ORDER-03, SYN-P001-PT-02 |
| `RET-03-CONTRADICTORY` | `explicitly_contradicted_evidence` | `SYN-P003-PT-02` | SYN-P003-PT-02, SYN-P003-ORDER-03 | SYN-P003-PT-02, SYN-P003-ORDER-03 | SYN-P003-PT-02 | SYN-P003-PT-02, SYN-P003-ORDER-03, SYN-P003-NOTE-01 |
| `RET-04-SYNONYM-MISMATCH` | `correctly_supported_claims` | `SYN-P001-PT-02` | *(empty)* | SYN-P001-PT-02, SYN-P001-ORDER-03 | *(empty)* | SYN-P001-PT-02, SYN-P001-ORDER-03, SYN-P001-NOTE-01 |
| `RET-05-MULTIPLE-RELEVANT` | `minimum_duration_and_multi_fact_requirements` | `SYN-P001-NOTE-01, SYN-P001-ORDER-03` | SYN-P001-ORDER-03, SYN-P001-PT-02, SYN-P001-NOTE-01 | SYN-P001-ORDER-03, SYN-P001-PT-02, SYN-P001-NOTE-01 | SYN-P001-ORDER-03, SYN-P001-NOTE-01 | SYN-P001-ORDER-03, SYN-P001-NOTE-01, SYN-P001-PT-02 |
| `RET-06-ORDER-VS-EXAM` | `correctly_supported_claims` | `SYN-P002-ORDER-03` | SYN-P002-ORDER-03 | SYN-P002-ORDER-03 | SYN-P002-ORDER-03 | SYN-P002-ORDER-03, SYN-P002-NOTE-01, SYN-P002-PT-02 |
| `RET-07-EXPLICIT-NEGATION` | `negation_and_temporal_ambiguity` | `SYN-P001-NOTE-01` | SYN-P001-NOTE-01 | SYN-P001-NOTE-01 | SYN-P001-NOTE-01 | SYN-P001-NOTE-01, SYN-P001-ORDER-03, SYN-P001-PT-02 |
| `RET-08-CROSS-PATIENT-ISOLATION` | `cross_patient_evidence_attempts` | `*(none: negative control)*` | *(empty)* | *(empty)* | *(empty)* | SYN-P001-PT-02, SYN-P001-NOTE-01, SYN-P001-ORDER-03 |
| `RET-09-UNSUPPORTED-CRITERION` | `empty_or_irrelevant_retrieval` | `*(none: negative control)*` | *(empty)* | *(empty)* | *(empty)* | SYN-P001-NOTE-01, SYN-P001-ORDER-03, SYN-P001-PT-02 |
| `RET-10-ZERO-MATCH-DOMAIN` | `empty_or_irrelevant_retrieval` | `*(none: negative control)*` | *(empty)* | *(empty)* | *(empty)* | SYN-P001-NOTE-01, SYN-P001-ORDER-03, SYN-P001-PT-02 |

### 3.3 Investigation of Dense Failure on Negative Controls & Threshold Trade-off
1. **Raw Dense Failure:** Dense embeddings (`bge-small-en-v1.5`) without a threshold assign similarity scores between `0.55` and `0.68` to clinical notes even for off-domain queries (e.g. coronary artery bypass surgery on lumbar records). This caused raw dense retrieval to return 3 irrelevant candidates for every negative control (0% empty-result rate).
2. **Empirical Threshold Sweep:**
   - `min_score = 0.60`: Empty-result rate `66.7%` (passes `RET-08`, `RET-10`, but fails `RET-09` score `0.6823`). Quality recall = `1.0000`.
   - `min_score = 0.70`: Empty-result rate `100.0%` (passes all negative controls), but Quality recall drops to `0.8571` because true synonym match (`RET-04`) scores `0.6519`.
   - **Conclusion:** No single global static cosine threshold separates domain-proximate true negatives (`RET-09`) from semantic synonym matches (`RET-04`).
3. **Bounded Corrective Retrieval Advantage:** Bounded corrective BM25 solves `RET-04` (+14.3% recall, 1.0000 MRR) using deterministic clinical synonyms, while abstaining cleanly on all negative controls (`RET-08`, `RET-09`, `RET-10`) with 0.85 ms latency.

## 4. Dataset Transparency & Methodology

### 4.1 Development vs Holdout Disclosure
- **Development Subset (`DEV-GOLD-*`):** 12 synthetic cases used during Phase 2C to calibrate verifier rules. Disclosed as non-independent holdouts.
- **Adversarial Holdout Subset (`HOLDOUT-ADV-*`):** 22 synthetic adversarial cases constructed independently in Phase 2C.1 / 5A.
- **Retrieval Suite (`RET-*`):** 10 synthetic queries spanning positive clinical criteria, keyword traps, explicit negations, and cross-patient isolation.

### 4.2 Known Blind Spots & Engineering Limitations
1. **Synthetic Fixtures Only:** Evaluation was conducted entirely on 3 synthetic patients (`SYN-P001`, `SYN-P002`, `SYN-P003`) and 1 synthetic lumbar MRI policy (`POL-LMRI-001`).
2. **No OCR / Scanned PDF Noise:** Passages assume digital text with exact character indexing; noisy OCR artifacts and handwriting are not modeled.
3. **Lexical Keyword Dependency:** While dense embedding bridges synonym mismatches, clinical ambiguity still requires human-in-the-loop review.
4. **Lack of Clinical Determination:** AuthOS is strictly an administrative evidence linter. A `MET` verification only asserts evidence traceability, never medical necessity.
