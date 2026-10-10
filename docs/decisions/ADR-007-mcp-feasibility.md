# ADR-007: Model Context Protocol (MCP) Feasibility, Security Review & Prototype Implementation

**Status:** IMPLEMENTED (Minimal Read-Only Prototype)
**Date:** 2026-10-10
**Authors:** Senior Backend Architect & Security Reviewer
**Scope:** Phase 15

---

## 1. Context and Problem Statement

Clinicians and prior-authorization reviewers increasingly interact with external AI workstations and desktop assistants (e.g., Anthropic Claude Desktop, Cursor, and clinical copilot interfaces). Without standardized integration, interacting with AuthOS's deterministic verification capabilities from external environments requires either custom UI embedding, manual copy-pasting of patient records, or brittle ad-hoc API wrappers.

The **Model Context Protocol (MCP)** provides an open JSON-RPC standard over `stdio` and `SSE` for models to discover tools, inspect resources, and query external systems.

This ADR records the feasibility assessment, security boundaries, and controlled implementation of an outward-facing MCP server adapter for AuthOS.

---

## 2. Options Considered & Trade-offs

| Option | Description | Utility & Architectural Impact | Decision |
| :--- | :--- | :--- | :--- |
| **Option A: Outward MCP Server** | Expose carefully scoped, read-only AuthOS capabilities to external AI clients over standard MCP `stdio`. | **High Utility / Low Risk.** Enables external AI assistants to invoke deterministic evidence linting, fetch case summaries, and verify citation offsets without building proprietary plugins. Reuses existing service layers. | **IMPLEMENTED (Minimal Read-Only Prototype)** |
| **Option B: Internal MCP Bus** | Replace internal orchestrator and agent communication (`Orchestrator` ↔ `EvidenceRetrievalAgent` ↔ `CriterionAnalysisAgent`) with MCP client/server processes. | **Negative Utility (Anti-Pattern).** AuthOS's internal multi-agent pipeline runs in-process with strongly typed Pydantic v2 schemas (`contracts/schemas.py`) and sub-millisecond execution. Replacing this with JSON-RPC over pipes adds 10–50ms IPC overhead, process failure modes, and serialization complexity with zero architectural gain. | **REJECTED** |
| **Option C: Inward MCP Client** | Connect AuthOS as an MCP client to consume patient charts from third-party EHR MCP servers. | **Low Utility / Premature.** In clinical healthcare technology, health data exchange is legally and technically standardized around **HL7 FHIR Release 4** (mandated under the 21st Century Cures Act). Certified commercial EHRs (Epic, Cerner) expose SMART-on-FHIR REST endpoints, not MCP servers. | **DEFERRED in favor of standard FHIR/REST ingestion** |

---

## 3. Decision & Rationale

**Decision:** Implement a minimal, strictly read-only outward MCP server adapter (`backend/mcp/server.py`) using the official `mcp==2.3.0` Python SDK.

### Architectural Rationale:
1. **Decoupled Adapter Pattern:** The MCP server is cleanly separated in `backend/mcp/` and acts as a facade over existing domain services (`evaluate_case`, `PostgresCaseRepository`, `verify_criterion_evidence`). The core REST API and internal agent pipelines remain completely untouched.
2. **Authoritative Determinism Invariant:** External LLMs cannot alter or override criterion statuses. The MCP server runs AuthOS's deterministic rules engine; the output is authoritative and purely deterministic.
3. **Strict Read-Only Boundary:** The prototype exposes zero approval, packet finalization, record deletion, SQL execution, or filesystem access tools.

---

## 4. Authentication & Authorization Model

MCP over `stdio` operates as a local subprocess spawned by the host client (e.g. Claude Desktop). To ensure security and case scoping:

1. **Token Precedence:**
   - **Explicit Argument:** Tools accept an optional `auth_token: str | None` argument (Bearer JWT). If explicitly supplied but empty or whitespace, fails closed immediately.
   - **Environment Fallback:** If omitted, the server checks `AUTHOS_MCP_TOKEN`.
   - **Local Dev / Testing Fallback:** If neither is set and running in supported local environments (`settings.app_env in ('development', 'dev', 'test', 'testing', 'local')`), the server checks `AUTHOS_MCP_DEFAULT_ACTOR` against synthetic test personas (e.g. `dr_chen`, `dr_ross`). In staging/production, this fallback is disabled and fails closed.
   - **Fail-Closed:** If no valid credentials are provided or if the JWT is invalid/expired, the server immediately returns a structured `AUTHENTICATION_REQUIRED` error.
2. **Case Scoping (`verify_actor_case_access`):**
   - The actor's assigned cases are extracted from token claims (`cases: list[str]`).
   - Admins (`role="admin"`) possess wildcard access.
   - Clinician reviewers and auditors can only query cases explicitly assigned to them.
   - Any attempt to access an unauthorized case fails closed with `ACCESS_DENIED`.

---

## 5. Read-Only Tool Specifications

The MCP server exposes exactly 4 bounded tools:

```
┌────────────────────────────────────────────────────────────────────────┐
│                      AuthOS MCP Server Interface                       │
│                                                                        │
│   1. authos_list_cases(auth_token?)                                    │
│      └─ Returns: list of cases authorized for calling actor            │
│                                                                        │
│   2. authos_get_case(case_id, auth_token?)                             │
│      └─ Returns: clinical metadata, service, payer policy              │
│                                                                        │
│   3. authos_lint_evidence(case_id, auth_token?)                        │
│      └─ Returns: deterministic criterion statuses (MET, MISSING,      │
│                  AMBIGUOUS, CONTRADICTED), missing facts, citations    │
│                                                                        │
│   4. authos_get_document_excerpt(case_id, source_id, start?, end?)     │
│      └─ Returns: verbatim text slice, verified character bounds        │
│                                                                        │
│   [ Prohibited & Non-Existent Tools ]                                  │
│   ✖ No authos_approve_packet / finalize                                │
│   ✖ No arbitrary SQL query / file reading                              │
│   ✖ No external LLM invocations during tool execution                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Patient-Isolation & Evidence Provenance Guarantees

1. **Cross-Patient Chart Isolation:**
   - In `authos_get_document_excerpt`, the server queries the database for `case = repo.get_case(case_id)` and verifies that `doc.patient_id == case.patient_id`.
   - If a caller supplies a valid case ID but references a document belonging to a different patient, the request is immediately aborted with `CROSS_PATIENT_ACCESS_DENIED`.
2. **Verbatim Provenance & Offsets:**
   - Evidence citations return exact `char_start` and `char_end` bounds.
   - Slicing validates `0 <= char_start < char_end <= len(raw_text)`. Out-of-bounds offsets are rejected with `INVALID_OFFSETS`.
3. **Contract Status Integrity:**
   - Criterion statuses strictly adhere to `contracts.schemas.CriterionStatus`: `MET`, `MISSING`, `AMBIGUOUS`, and `CONTRADICTED`.
   - `MISSING` denotes that documentation is unproven in the submitted chart; it does not assert that the real-world treatment never occurred.
4. **Transport Stream Hygiene:**
   - Diagnostic logging in `authos.mcp` is directed exclusively to `sys.stderr` with `propagate = False`, ensuring zero log leakage into `sys.stdout` (reserved for JSON-RPC framing).

---

## 7. Testing Performed & Verification Evidence

A comprehensive automated test suite was implemented in [`tests/test_phase15_mcp_server.py`](file:///d:/authos/tests/test_phase15_mcp_server.py):

| Test Case | Scenario Verified | Result |
| :--- | :--- | :--- |
| `test_01_tool_registry_read_only_boundary` | Confirms exactly 4 tools registered; zero mutation/SQL tools | **PASSED** |
| `test_02_missing_auth_fails_closed` | Requests without credentials fail closed with `AUTHENTICATION_REQUIRED` | **PASSED** |
| `test_03_invalid_or_malformed_token_rejected` | Malformed JWT strings return `AUTHENTICATION_REQUIRED` | **PASSED** |
| `test_04_actor_scoped_case_listing` | Restricted user (`Dr. Ross`) sees only `CASE-SYN-001`; full reviewer sees all | **PASSED** |
| `test_05_cross_case_access_denied_for_restricted_user` | Restricted user denied access to `CASE-SYN-002` with `ACCESS_DENIED` | **PASSED** |
| `test_06_cross_patient_document_access_denied` | Attempting to fetch `SYN-P002-NOTE-01` via `CASE-SYN-001` returns `CROSS_PATIENT_ACCESS_DENIED` | **PASSED** |
| `test_07_deterministic_evidence_linting_output` | Verifies deterministic evaluation, valid statuses, and verbatim citations | **PASSED** |
| `test_08_document_excerpt_exact_slice_verification` | Verifies verbatim offset extraction and rejection of out-of-bounds offsets | **PASSED** |
| `test_09_default_actor_blocked_in_production_mode` | Confirms default actor fallback is strictly disabled in production mode | **PASSED** |
| `test_10_explicit_empty_token_fails_closed` | Confirms explicit empty/whitespace token fails closed immediately | **PASSED** |
| `test_11_expired_token_rejected_in_mcp` | Confirms expired JWT tokens return `AUTHENTICATION_REQUIRED` | **PASSED** |
| `test_12_stdio_logging_isolated_to_stderr` | Confirms diagnostic logging routes strictly to stderr, protecting JSON-RPC | **PASSED** |

**Execution Result:** `12 passed in 4.02s` (100% green).

---

## 8. Known Limitations & Deferred Scope

1. **Experimental Prototype:** Designed for local evaluation with synthetic prior-authorization datasets.
2. **Transport Scope:** Configured for `stdio` transport (standard for Claude Desktop and local LLM clients). Networked `SSE` transport is intentionally omitted to avoid exposing unauthenticated public network listeners.
3. **Read-Only Finalization Boundary:** Human clinicians must finalize cases through the authenticated web UI or REST API (`/approve`). The MCP server cannot commit clinical adjudications.
