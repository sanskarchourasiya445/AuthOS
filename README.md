# AuthOS — Evidence-Grounded Prior-Authorization Linter

AuthOS is an evidence-linting system for healthcare prior authorization. It evaluates whether clinical criteria in a payer policy are substantiated by supplied medical chart records. Every claim must be grounded in exact source text provenance with character-level offsets or explicitly classified as `MISSING`, `AMBIGUOUS`, or `CONTRADICTED`.

AuthOS is an administrative evidence linter that prepares structured review packets for human clinical adjudication. **It does not make coverage decisions or clinical recommendations.**

---

## Key Capabilities & Architectural Model

* **Authoritative Deterministic Gate**: Final criterion determinations (`MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`) are governed exclusively by a deterministic verification engine (`backend.verification.engine.verify_criterion_evidence`).
* **Advisory LLM Separation**: Agent proposals (`AgentProposalModel`) from local stubs or hosted models (Google Gemini) are strictly advisory. Unsupported agent proposals are intercepted and safely downgraded by the deterministic gate.
* **Exact Character-Level Provenance**: Every cited fact requires verbatim quotation matching (`text[char_start:char_end] == quote`) and patient boundary isolation.
* **Clinical Duration & Negation Logic**: Reconciles conservative therapy durations (e.g., 6-week conservative physical therapy requirements) and preserves current positive symptoms over historical negations.
* **Modern Reviewer Workstation**: React 19 + TypeScript + Vite clinical workstation (`/app`) with side-by-side evidence inspection, advisory vs. authoritative diffing, reviewer annotations, and an immutable audit trail.
* **Adversarial Safety Benchmarks**: Verified against 12 adversarial safety categories including indirect prompt injection, cross-patient citation leaks, hallucinated quotes, and duration arithmetic edge cases.

---

## System Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                 React Reviewer Workstation                  │
│       Queue ── Document Inspector ── Advisory Diff ── Packet │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST / JSON (JWT Authenticated)
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Backend Router                   │
│   /health/live  /health/ready  /api/v1/auth  /api/v1/cases  │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
┌──────────────▼─────────────┐ ┌──────────────▼───────────────┐
│     Advisory LLM Agent     │ │    Authoritative Deterministic│
│ (Gemini or Offline Stub)   │ │      Verification Engine      │
│  - Candidate extraction    │ │  - Verbatim text provenance   │
│  - Advisory status proposal│ │  - Character offset matching  │
│  - Never writes final state│ │  - Clinical duration checks   │
└──────────────┬─────────────┘ │  - Contradiction detection    │
               │               │  - Sole status authority      │
               └───────────────►──────────────┬────────────────┘
                                              │
                               ┌──────────────▼───────────────┐
                               │     PostgreSQL Database      │
                               │  - Cases & Criteria Results  │
                               │  - Documents & Text Chunks   │
                               │  - Immutable Audit History   │
                               └──────────────────────────────┘
```

---

## Quickstart

### Option 1: Docker Compose (Recommended)

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   ```
2. **Start Services (Database + Backend + Frontend)**:
   ```bash
   docker compose up --build -d
   ```
3. **Seed Synthetic Data (One-Shot Task)**:
   ```bash
   docker compose run --rm seed
   ```
4. **Open in Browser**:
   - Workstation UI: `http://localhost:8000/app`
   - API Documentation: `http://localhost:8000/docs`
   - Readiness Probe: `http://localhost:8000/health/ready`

### Option 2: Native Host Development

1. **Install Python & Node Dependencies**:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1  # Windows PowerShell (or source .venv/bin/activate on Linux)
   pip install -r requirements-dev.txt

   cd frontend && npm ci && npm run build && cd ..
   ```
2. **Run Migrations & Seed Database**:
   ```bash
   python scripts/init_and_seed.py
   ```
3. **Launch API Server**:
   ```bash
   uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```

---

## Testing & Evaluation

AuthOS includes a complete suite of unit, integration, browser E2E, and adversarial evaluation benchmarks:

```bash
# Backend pytest suite (313 passed)
pytest -v --ignore=frontend

# Frontend Vitest suite (19 passed)
cd frontend && npm test && cd ..

# Browser E2E Playwright suites (7 passed)
pytest tests/test_phase7_browser_e2e.py -v
pytest tests/test_phase9_react_browser_e2e.py -v

# Core verification & retrieval evaluation benchmark (34 cases)
python -m backend.evaluation.runner

# Multi-agent adjudication & adversarial evaluation benchmark (64 cases)
python -m backend.evaluation.agent_eval
```

---

## How to Run the Demo Workflow

1. Navigate to `http://localhost:8000/app`.
2. The application automatically initializes as **Dr. Sarah Chen, MD** (synthetic clinician reviewer).
3. In the **Case Queue**, select `CASE-SYN-001` (Lumbar Spine MRI prior authorization request).
4. Review the three policy criteria cards:
   - **C1: Low Back Pain**: Substantiated by clinic note with exact character highlight. Click **🔍 Inspect in Source** to view the document passage.
   - **C2: Conservative Therapy**: Verified 8-week physical therapy duration.
   - **C3: Prior Imaging / Red Flags**: Correctly flagged as `MISSING` (absent from chart).
5. Switch to the **Advisory vs. Authoritative** tab and click **Run Agent Workflow** to observe the multi-agent proposal vs. deterministic verifier gate comparison.
6. Under **Adjudicate & Finalize**, enter a clinical reviewer note and record the determination.
7. Open **Review Packet & Audit Trail** to view the signed packet and cryptographic audit history.
8. Click **Switch Actor** to test role-based access control with **Jane Doe (Auditor)** or **Dr. Allison Ross, MD**.

---

## Model Context Protocol (MCP) Integration (Experimental)

AuthOS includes an experimental outward-facing MCP server adapter (`backend.mcp.server`) for desktop AI assistants (e.g. Anthropic Claude Desktop, Cursor):

* **Protocol**: Model Context Protocol (JSON-RPC over `stdio`) via official `mcp` SDK.
* **Scope**: Strictly read-only evidence linting, case inspection, and verbatim citation offset verification on synthetic cases.
* **Security & Invariants**: Enforces JWT token authorization or local synthetic actor scoping, strict patient chart isolation, and deterministic verification. Exposes zero approval, mutation, or SQL query tools.
* **Usage (Local Synthetic-Data Development Only)**:
  ```cmd
  :: For local development and testing only (fails closed in staging/production):
  set AUTHOS_MCP_DEFAULT_ACTOR=dr_chen
  python -m backend.mcp.server
  ```
  In production environments, a cryptographically signed JWT token must be provided via `AUTHOS_MCP_TOKEN` or tool-level `auth_token`.
* **Architectural Boundaries**:
  - Exposes 4 read-only tools: `authos_list_cases`, `authos_get_case`, `authos_lint_evidence`, and `authos_get_document_excerpt`.
  - Zero approval, packet mutation, deletion, or arbitrary SQL execution tools.
  - Diagnostic logging streams exclusively to `sys.stderr` to prevent JSON-RPC protocol corruption on `sys.stdout`.
  - Cross-patient document access is strictly rejected (`CROSS_PATIENT_ACCESS_DENIED`).

---

## Safety & Compliance Disclosures

> [!IMPORTANT]
> 1. **Synthetic Data Only**: All patient records (`SYN-P001` through `SYN-P006`), physician notes, and policy criteria (`POL-LMRI-001`) are synthetic fixtures created exclusively for software demonstration and testing. No real Protected Health Information (PHI) is used.
> 2. **Not a Medical Device**: AuthOS is an administrative evidence linter. It does not provide medical diagnoses, treatment advice, or coverage guarantees.
> 3. **Human-in-the-Loop Required**: Prior authorization determinations cannot be submitted without authenticated clinician review and sign-off.
> 4. **No Claim of Regulatory Clearance**: AuthOS is an engineering prototype. It has not been submitted for FDA clearance, HIPAA compliance audit, or insurer production approval.
> 5. **Advisory LLM Decoupling**: External LLM evaluations (Google Gemini) remain decoupled; the core verification engine is completely deterministic and operates offline.

---

## Operational Notes & Health Probes

* **Health Endpoints**:
  - `GET /health/live`: Basic process liveness probe (returns `{"status": "alive"}`).
  - `GET /health/ready`: Deep dependency readiness probe verifying PostgreSQL connectivity and advisory LLM provider status.
* **Database Port Mapping**: In Docker Compose, the PostgreSQL service is exposed on host port `5433` (`127.0.0.1:5433:5432`) to prevent conflicts with local host PostgreSQL installations, while internal container networking uses port `5432`.
* **Advisory LLM Decoupling**: Defaults to `LLM_PROVIDER=stub` (offline deterministic). To optionally enable live Google Gemini advisory analysis, configure `LLM_PROVIDER=gemini` and set `GEMINI_API_KEY` in `.env`.
