# AuthOS — Hackathon Build Readiness

**Mode:** lightweight prototype gate for a 24-hour, two-person hackathon. This replaces production-style approval theater; it does not waive safety boundaries.

## Build now — minimum controls
- [x] Narrow MVP: synthetic patient charts, one explicitly synthetic lumbar-MRI policy, pre-submission evidence gap detection.
- [x] Product boundary: AuthOS prepares evidence; it does not diagnose, decide medical necessity, predict approval, submit claims, or make insurer decisions.
- [x] Core statuses documented: `MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`.
- [x] API prefix selected: `/api/v1`.
- [x] Deterministic source/quote/patient verifier implemented with unit tests.
- [x] Three synthetic patient scenarios prepared.
- [x] Packet rendering is template-based; no LLM is needed to author final packet prose.
- [ ] Team reviews the scenarios and confirms that all data is synthetic and clearly labeled.
- [ ] Run the full-chart-in-context baseline on the same cases as the retrieval pipeline before making comparative claims.
- [ ] Have a teammate who did not author the cases create or review 3–5 additional held-out cases if time permits.
- [ ] Demo labels the planted vocabulary trap as a deliberately constructed test, not independent evidence of real-world performance.

## Defer until after the core demo
- Production authentication and authorization, real EHR/payer integrations, real patient data, deployment hardening, MCP, A2A, reranking, and complex multi-agent deployment.
- Numeric performance claims beyond the observed results of a reproducible test run. A tiny synthetic set demonstrates behavior; it does not establish population-level accuracy.
- Market-demand claims until at least one relevant user conversation or other credible evidence exists.

## Demo acceptance checks
1. Exact source quote and source ID pass provenance checks for the correct synthetic patient.
2. Fabricated/non-verbatim quote is rejected with a visible reason.
3. Wrong-patient source is rejected.
4. Missing or ambiguous evidence remains unresolved and is surfaced for human review.
5. Packet is rendered deterministically from verified structured results and is marked not finalized until a human review action.
6. UI and pitch state that all cases and policy text are synthetic.

## Honest limitations
- Exact-quote validation proves that the quoted text exists in the referenced source; it does not prove that the text semantically supports the claim. Semantic entailment still requires separate evaluation and human oversight.
- Three hand-authored cases are demo fixtures, not a statistically meaningful benchmark.
- Market research is not complete; supplied competitor notes remain unverified until checked against primary sources.
