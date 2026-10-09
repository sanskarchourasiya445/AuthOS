# AuthOS — Market Research and Differentiation

**Status:** Research plan; external market research has not been completed or independently verified in this documentation package.

## Research question

Is there a meaningful, demonstrable need for a workflow that maps payer-policy criteria to chart evidence, performs bounded corrective retrieval, verifies citations deterministically, and explicitly surfaces missing, ambiguous, or contradictory evidence for a human reviewer?

## Hypothesis to test

AuthOS may differentiate through evidence traceability and controlled failure handling rather than by claiming to automate authorization decisions. This is a hypothesis, not a verified market finding.

## Alternatives to investigate

Research current offerings and workflows across these categories; do not infer product capabilities from category labels alone:

1. Prior-authorization automation platforms.
2. Clinical documentation and utilization-management tools.
3. Payer policy search and medical policy portals.
4. General-purpose enterprise search and RAG systems.
5. Manual workflows using EHR exports, checklists, and document templates.

## Comparison framework

For each product/workflow, record vendor/source, date accessed, intended user, supported services/payers, input data, criterion-level evidence mapping, citation/source-span behavior, missing-evidence handling, human review, integrations, deployment/privacy claims, pricing if public, and evidence confidence. Distinguish vendor claims from independently verified capabilities.

## Validation activities

- Interview or obtain structured feedback from at least one person familiar with prior-authorization preparation, if accessible.
- Test whether the problem is evidence retrieval, policy interpretation, workflow coordination, or a combination.
- Compare the proposed workflow with a simple keyword-search/manual-review baseline.
- Identify the narrowest service/policy scope that still demonstrates the product's value.

## Decision rule

Retain the differentiation claim only if evidence supports it. Otherwise revise the product brief and demo story. Do not claim that AuthOS is unique, faster, more accurate, compliant, or superior without a defined comparison and recorded results.

## Open questions

- Which user performs the initial work and who signs off?
- Which payer/service scope is most painful and feasible to demonstrate?
- Which competing tools already provide criterion-level provenance and gap handling?
- What workflow outcome matters: time saved, fewer missing documents, reviewer confidence, or auditability?
- Is the hackathon demo intended only as a synthetic prototype, or is a future pilot anticipated?
