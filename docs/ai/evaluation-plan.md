# AuthOS — AI/RAG Evaluation Plan

**Status:** Required design before AI implementation. No metrics are claimed here; all thresholds and results must be filled from reproducible runs.

## Evaluation objective

Test whether AuthOS retrieves relevant source evidence, maps it to the correct criterion, detects insufficient or contradictory evidence, validates citations, and avoids unsupported `MET` statuses. A successful demo alone is not evidence of general reliability.

## Synthetic case suite

Use the existing domain document's three baseline cases:

- **P-101 / happy path:** evidence is available in the first retrieval.
- **P-104 / corrective retrieval:** initial search misses a required fact; a bounded query rewrite retrieves it on a later round.
- **P-107 / missing evidence:** evidence remains absent after the retry budget and is escalated without fabrication.

Add adversarial tests for wrong-patient evidence, quote mismatch, date arithmetic, negation (`declined PT`), contradictory notes, outdated policy version, exception/cross-reference handling, malformed model output, prompt injection inside retrieved text, empty retrieval, duplicate evidence and database/provider failure.

## Gold-label format

Each case should contain: synthetic case/patient/policy IDs, policy version, criterion IDs, required facts, relevant source IDs/spans, expected status, expected missing facts, expected retry behavior, prohibited evidence, and rationale. Keep labels separate from the prompts/configuration being tuned. Do not put evaluation labels in retrievable chart content.

## Baselines and ablations

Run the same cases and model settings across:

1. Keyword/full-text retrieval only.
2. Dense vector retrieval only.
3. Hybrid retrieval using RRF.
4. Hybrid + corrective query rewriting.
5. Optional reranker/parent expansion only after the core baseline works.
6. Whole-chart-in-context baseline on small charts, when feasible, to test whether retrieval adds value at this scale.

Record the exact corpus version, embedding model, LLM/model version, prompt version, retrieval settings, seed where supported, run date, latency and cost. Do not attribute improvements to a component unless the comparison isolates it reasonably.

## Metrics

| Metric | Definition / interpretation |
|---|---|
| Retrieval recall@k | Fraction of labeled relevant evidence chunks found in top k. |
| Retrieval precision@k | Fraction of top-k chunks labeled relevant. |
| MRR | Ranking quality of the first relevant result. |
| Citation exactness | Share of emitted quotes that exactly match the identified source/span. |
| Source attribution accuracy | Share of evidence items with correct source and patient. |
| Criterion status accuracy | Match between predicted and gold status; report per class, not only aggregate. |
| Missing-evidence detection | Recall on cases where evidence is truly absent from the supplied corpus. |
| False-`MET` rate | Share of gold non-`MET` criteria incorrectly marked `MET`; critical safety metric. |
| Retry utility | Fraction of initially insufficient cases where bounded corrective retrieval finds valid missing facts. |
| Latency/cost | End-to-end and per-run latency plus model/embedding usage cost where measurable. |

## Release gates

Before coding, agree numeric thresholds for citation exactness, source attribution and false-`MET` on the synthetic suite. Thresholds are currently **TBD**; the team must not invent passing numbers. If a critical safety metric fails, fix the cause or narrow the supported scope rather than hiding it in an aggregate score.

## Evaluation reporting template

- Commit/hash or package version:
- Dataset version and case count:
- Model/provider and model version:
- Embedding model/dimension:
- Prompt and retrieval configuration versions:
- Baseline and ablation configuration:
- Metrics with denominators and confidence/limitations:
- False-`MET` examples and root causes:
- Citation/source mismatch examples:
- Known failure modes:
- Decision: pass / revise / narrow scope:

## Anti-leakage rules

- Keep held-out cases out of prompt iteration where practical.
- Do not manually fix output labels after viewing model responses without recording the change.
- Version the gold set and preserve previous results for comparisons.
- Publish only measured values; synthetic performance does not establish clinical or production performance.
