# AuthOS — AI/RAG Evaluation Framework & Reliability Baseline

**Status:** Authoritative Phase 5A Evaluation Baseline. All metrics are produced by reproducible benchmark runs against synthetic dataset `eval-dataset-v1.0`.

> **MANDATORY NOTICE:**
> All evaluations are conducted exclusively on synthetic patient fixtures (`SYN-P001`, `SYN-P002`, `SYN-P003`) and synthetic policy `POL-LMRI-001`.
> This framework measures software engineering correctness and safety invariants (zero false-positive `MET` results, zero cross-patient leakage, exact quote offset verification).
> It does **NOT** establish clinical validity, predict insurer authorization, or make medical necessity determinations.

---

## 1. Evaluation Architecture & Dataset Versioning

The evaluation framework is codified under `backend/evaluation/` and operates on frozen dataset `eval-dataset-v1.0` (persisted at `data/evaluation/eval_dataset_v1.json`).

### 1.1 Dataset Splits & Provenance Disclosure
To prevent overfitting and test contamination, the verification suite explicitly separates development calibration cases from independent holdouts:

1. **Development Calibration Subset (`DEV-GOLD-01` to `DEV-GOLD-12`):**
   - 12 synthetic cases calibrated during initial Phase 2C verifier development.
   - Disclosed as **non-independent holdouts**.
2. **Adversarial Holdout Subset (`HOLDOUT-ADV-01` to `HOLDOUT-ADV-22`):**
   - 22 synthetic adversarial cases constructed independently in Phase 2C.1 and Phase 5A.
   - Designed to test edge conditions: criterion-relative polarities, planned vs completed care, discussed vs performed therapy, inadequate durations, prompt injection in clinical notes, and offset tampering.
3. **Retrieval Benchmark Suite (`RET-01` to `RET-10`):**
   - 7 IR quality queries targeting specific clinical criteria.
   - 3 safety invariant queries (cross-patient isolation, negative controls for unmentioned conditions, and off-domain surgical queries).

### 1.2 Mandatory 12 Evaluation Categories
Every case in `eval-dataset-v1.0` maps to one of the 12 canonical evaluation categories:
- `correctly_supported_claims`
- `missing_evidence`
- `ambiguous_evidence`
- `explicitly_contradicted_evidence`
- `cross_patient_evidence_attempts`
- `unsupported_claims_with_keyword_overlap`
- `negation_and_temporal_ambiguity`
- `minimum_duration_and_multi_fact_requirements`
- `conflicting_evidence_across_documents`
- `prompt_injection_in_documents`
- `empty_or_irrelevant_retrieval`
- `malformed_or_invalid_provenance_offsets`

---

## 2. Evaluation Commands & CLI Usage

### Running the Evaluation Pipeline
```powershell
# Run the complete evaluation pipeline (verification + BM25 + Dense + Hybrid)
python -m backend.evaluation.runner

# Run with custom output paths or retrieval depth
python -m backend.evaluation.runner --json reports/eval_results.json --md reports/EVAL_BASELINE.md --k 3

# Skip dense embeddings for lightweight smoke runs
python -m backend.evaluation.runner --no-dense
```

### Running Automated Evaluation Regression Tests
```powershell
# Run pytest safety gates
python -m pytest tests/test_evaluation_gates.py -v

# Run the full regression test suite
python -m pytest tests/
```

The runner exits with code `0` if all mandatory safety gates pass, and `1` if any gate fails.

---

## 3. Metric Definitions & Denominators

All metrics enforce mathematically exact denominators. Undefined metrics (e.g. division by zero) are explicitly returned as `None` / `null`, never artificially masked as `0.0` or `1.0`.

### 3.1 Verifier Safety Metrics
- **False-Positive `MET` Rate:**
  $$\text{FPR}_{\text{MET}} = \frac{\text{FP}_{\text{MET}}}{\text{Total True Non-MET Cases}}$$
  *Safety Requirement: Must be 0. Insufficiently supported claims must never be marked `MET`.*
- **False-Negative `MET` Rate:**
  $$\text{FNR}_{\text{MET}} = \frac{\text{FN}_{\text{MET}}}{\text{Total True MET Cases}}$$
- **Per-Class Precision, Recall, and F1:**
  - $\text{Precision}_s = \frac{\text{TP}_s}{\text{TP}_s + \text{FP}_s}$ (undefined if $\text{TP}_s + \text{FP}_s = 0$)
  - $\text{Recall}_s = \frac{\text{TP}_s}{\text{TP}_s + \text{FN}_s}$ (undefined if $\text{TP}_s + \text{FN}_s = 0$)
  - $\text{F1}_s = \frac{2 \cdot P_s \cdot R_s}{P_s + R_s}$ (undefined if $P_s$ or $R_s$ undefined or $P_s + R_s = 0$)
- **Provenance Integrity:** Fraction of valid source quotations where `raw_text[char_start:char_end] == quote`.
- **Cross-Patient Evidence Acceptance:** Count of foreign patient evidence items accepted as verified (Must be 0).

### 3.2 Retrieval Metrics
- **Precision@k:** $\frac{|\text{Retrieved@k} \cap \text{Expected}|}{k}$ (computed strictly over queries with non-empty ground truth).
- **Recall@k:** $\frac{|\text{Retrieved@k} \cap \text{Expected}|}{|\text{Expected}|}$ (computed strictly over queries with non-empty ground truth).
- **MRR (Mean Reciprocal Rank):** $\frac{1}{\text{rank of first relevant source}}$ ($0$ if no relevant source in top $k$).
- **Cross-Patient Leakage:** Number of candidates belonging to prohibited patients (Must be 0).
- **Negative Control Pass Rate:** Zero candidates returned for ungrounded or off-domain queries.

---

## 4. Phase 5A Baseline Results

### 4.1 Mandatory Safety Gates
| Gate Name | Status | Observed | Threshold | Description |
|---|---|---|---|---|
| `zero_false_positive_met` | ✅ PASS | `0` | `0` | Zero false-positive `MET` results across all non-MET cases. |
| `zero_cross_patient_leakage` | ✅ PASS | `0` | `0` | Zero cross-patient leakage across verification and retrieval. |
| `exact_provenance_integrity` | ✅ PASS | `5 instances detected` | `> 0 detections` | All tampered/stale offsets correctly rejected. |
| `determinism_verified` | ✅ PASS | `True` | `True` | 100% reproducible across repeat executions. |

### 4.2 Verifier Performance (34 Cases)
- **Overall Accuracy:** `100.00%` (34/34)
- **False-Positive `MET` Rate:** `0.0%` (0 / 29 non-MET cases)
- **False-Negative `MET` Rate:** `0.0%` (0 / 5 true MET cases)

#### Confusion Matrix
| Expected \ Predicted | MET | AMBIGUOUS | CONTRADICTED | MISSING |
|---|---|---|---|---|
| **MET** | 5 | 0 | 0 | 0 |
| **AMBIGUOUS** | 0 | 12 | 0 | 0 |
| **CONTRADICTED** | 0 | 0 | 7 | 0 |
| **MISSING** | 0 | 0 | 0 | 10 |

### 4.3 Phase 5B Retrieval Method Comparison ($k=3$)
| Method | Precision@k | Recall@k | MRR | Empty-Result Rate (Safety) | Irrelevant Cand. Rate | Mean Latency | Median Latency | Safety Verdict |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **BM25 (Baseline)** | 0.5476 | 0.8571 | 0.7619 | **3/3 (100.0%)** | **0.0%** | **0.80 ms** | 0.0 ms | **✅ PASS** |
| **BM25 (Bounded Corrective)** | **0.6190** | **1.0000** | **0.9048** | **3/3 (100.0%)** | **0.0%** | **0.77 ms** | 0.0 ms | **✅ PASS** |
| **Dense (Raw Cosine)** | 0.3809 | **1.0000** | **1.0000** | 0/3 (0.0%) | 100.0% | 55.50 ms | 0.0 ms | ❌ FAIL (negative controls) |
| **Dense (Calibrated min_score=0.70)** | **0.7619** | 0.8571 | 0.8571 | **3/3 (100.0%)** | **0.0%** | 34.78 ms | 0.0 ms | **✅ PASS** |
| **Hybrid (BM25 + Dense RRF)**| 0.3809 | **1.0000** | 0.9286 | 0/3 (0.0%) | 100.0% | 36.12 ms | 0.0 ms | ❌ FAIL (negative controls) |

#### Key Information Retrieval & Safety Findings:
1. **BM25 Baseline Preserved as Production Default:** BM25 achieves sub-millisecond latency (0.80 ms), 100% empty-result abstention on negative controls, and 0 cross-patient leakage. It remains the default baseline.
2. **Bounded Corrective Retrieval as Measured Improvement:** For queries exhibiting synonym vocabulary mismatches (e.g. `RET-04`), deterministic bounded query expansion (maximum 2 retries, zero external LLMs, hard candidate capping) increases Recall@3 to 1.0000 (+14.3%) and Precision@3 to 0.6190 (+7.1%) while strictly maintaining 100% negative control abstention and 0 cross-patient leaks.
3. **Dense Threshold Calibration Trade-Off:**
   - Raw dense embeddings assign cosine similarity scores between `0.55` and `0.68` to clinical notes even for off-domain queries, causing 100% irrelevant candidate retrieval on negative controls.
   - Calibrating `min_score = 0.70` restores 100% negative control abstention, but filters out semantic synonym matches (`RET-04` score `0.6519`), dropping recall back to `0.8571` at 45x higher latency than BM25.
   - There is no single global static cosine threshold that simultaneously captures low-similarity true positives and rejects high-similarity true negatives.

---

## 5. Adding New Adversarial Cases

To expand the evaluation suite without risking test-set contamination:

1. **Define the Case in `backend/evaluation/dataset.py`:**
   - Assign a new ID (`HOLDOUT-ADV-<N>`).
   - Mark `is_holdout = True`.
   - Specify expected status and rationale.
   - Map to one of the 12 `MANDATORY_CATEGORIES`.
2. **Update the Frozen JSON Dataset:**
   - Re-serialize to `data/evaluation/eval_dataset_v1.json` or increment version (`eval-dataset-v1.1`).
3. **Execute the Gates:**
   - Run `python -m backend.evaluation.runner`.
   - Ensure the new case does not cause regressions or trigger false-positive `MET` results.
