# AuthOS — Evidence-Grounded Prior-Authorization Linter

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org)
[![React 19](https://img.shields.io/badge/React-19.2-61DAFB.svg)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6.svg)](https://www.typescriptlang.org)
[![Pytest Tests](https://img.shields.io/badge/pytest-335%20passed-brightgreen.svg)](https://pytest.org)
[![Vitest Tests](https://img.shields.io/badge/vitest-19%20passed-brightgreen.svg)](https://vitest.dev)
[![Model Context Protocol](https://img.shields.io/badge/MCP-2.3.0-purple.svg)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **AuthOS** is an evidence-linting engine for healthcare prior authorization. It programmatically validates whether clinical criteria in a payer policy are substantiated by supplied medical chart records. Every claim requires exact source text provenance with character-level offsets or is classified as `MISSING`, `AMBIGUOUS`, or `CONTRADICTED`.
>
> **Notice**: AuthOS is an administrative evidence linter that prepares structured review packets for human clinical adjudication. **It does not make coverage decisions, issue claim denials, or provide medical advice.**

---

## Table of Contents

- [Executive Overview](#executive-overview)
- [Core Architectural Invariants](#core-architectural-invariants)
- [System Architecture](#system-architecture)
  - [End-to-End Linting & Adjudication Flow](#end-to-end-linting--adjudication-flow)
  - [Advisory LLM vs. Deterministic Gate Decoupling](#advisory-llm-vs-deterministic-gate-decoupling)
- [Technology Stack](#technology-stack)
- [Repository Layout](#repository-layout)
- [Prerequisites & Environment Configuration](#prerequisites--environment-configuration)
- [Quickstart & Installation](#quickstart--installation)
  - [Option 1: Docker Compose (Recommended)](#option-1-docker-compose-recommended)
  - [Option 2: Native Host Development](#option-2-native-host-development)
- [Interactive Clinical Reviewer Walkthrough](#interactive-clinical-reviewer-walkthrough)
- [REST API Specification](#rest-api-specification)
- [Model Context Protocol (MCP) Server](#model-context-protocol-mcp-server)
- [Testing & Evaluation Benchmarks](#testing--evaluation-benchmarks)
- [Safety, Ethics & Non-Goal Disclosures](#safety-ethics--non-goal-disclosures)
- [Operational FAQ & Troubleshooting](#operational-faq--troubleshooting)

---

## Executive Overview

### The Prior-Authorization Problem
In United States healthcare, prior authorization (PA) creates severe administrative friction between healthcare providers and health insurance payers:
1. **Administrative Overhead**: Clinicians spend hours manually combing through electronic health records (EHRs) to locate notes, lab values, and conservative therapy timelines required by complex payer policies.
2. **High Initial Denial Rates**: A significant portion of initial denials stem from administrative documentation omissions—such as failing to cite the duration of physical therapy or missing an imaging report—rather than medical necessity.
3. **Black-Box AI Risks**: Deploying unconstrained large language models (LLMs) to automate approvals or denials risks dangerous hallucinations, cross-patient chart leaks, fabricated clinical citations, and regulatory violations.

### How AuthOS Solves It
AuthOS acts as a **pre-submission clinical linter**. Before a prior authorization packet is transmitted to an insurer:
* It parses the clinical criteria of the payer policy (e.g., Lumbar Spine MRI under `POL-LMRI-001`).
* It searches the patient's longitudinal record to extract supporting evidence.
* It submits proposed citations to an **authoritative deterministic verification engine** that enforces verbatim character-level quote matching, date/timeline duration verification, and negation detection.
* It packages the substantiated evidence, missing documentation gaps, and full audit provenance into an interactive workstation for a **licensed clinician reviewer to inspect, annotate, and sign**.

---

## Core Architectural Invariants

AuthOS is designed around strict safety principles that prevent automated errors and ensure auditable clinical governance:

| Invariant | Implementation Mechanism | Enforced By |
| :--- | :--- | :--- |
| **Deterministic Status Authority** | Only deterministic verification logic can assign criterion statuses (`MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`). Advisory AI output is strictly isolated. | `backend.verification.engine.verify_criterion_evidence` |
| **Verbatim Quote Provenance** | Every citation must match document text character-for-character: `doc.text[char_start:char_end] == quote`. Substring approximations and fabricated quotes are rejected. | `backend.verification.engine` |
| **Patient Boundary Isolation** | Documents and citations belonging to patient $A$ can never be retrieved or attached to a case for patient $B$. Cross-patient citation attempts trigger an access violation. | `backend.db.repository.PostgresCaseRepository` |
| **Clinical Duration Arithmetic** | Conservative therapy duration (e.g., "minimum 6 weeks of physical therapy") is computed using explicit clinical start/end dates or encounter timestamps, rejecting synthetic date shifts. | `backend.verification.temporal` |
| **Temporal Negation Logic** | Distinguishes between historical rule-outs and active symptoms. A documented current positive symptom cannot be negated by an unrelated historical denial clause. | `backend.verification.negation` |
| **Explicit Non-Met Semantics** | `MISSING` denotes an absence of documentation in the supplied chart—not proof of clinical non-occurrence. `CONTRADICTED` requires explicit documentation of therapy refusal or medical contraindication. | `contracts.schemas.CriterionStatus` |
| **Mandatory Human Finalization** | Cases cannot be finalized or transmitted to payers by background automation or AI. The approve endpoint requires an authenticated clinician JWT (`clinician_reviewer` or `admin`). | `backend.auth.dependencies.require_reviewer_role` |

---

## System Architecture

### End-to-End Linting & Adjudication Flow

```mermaid
flowchart TD
    subgraph Client["Clinical Reviewer Interface"]
        UI["React 19 Workstation\n(Case Queue, Inspector, Adjudication)"]
        MCP_Client["External AI Copilot\n(Claude Desktop / Cursor via MCP)"]
    end

    subgraph API["FastAPI Application Layer"]
        Auth["JWT Security & Scoped RBAC\n(/api/v1/auth)"]
        CasesRouter["Case & Document Endpoints\n(/api/v1/cases)"]
        HealthRouter["Liveness & Readiness Probes\n(/health/live, /health/ready)"]
        MCP_Server["MCP stdio Server\n(4 Read-Only Linting Tools)"]
    end

    subgraph AdvisoryLayer["Advisory AI Layer (Non-Authoritative)"]
        Agent["Multi-Agent Workflow / Orchestrator"]
        LLM["Google Gemini 3.5 Flash-Lite / Offline Stub<br/>(Default: offline stub)"]
        Proposal["Advisory Proposal Model\n(Never writes final criterion status)"]
    end

    subgraph VerificationEngine["Authoritative Deterministic Gate"]
        Engine["Verification Engine\nbackend.verification.engine"]
        Offsets["Verbatim Slice Check\ntext[start:end] == quote"]
        Isolation["Patient Isolation Guard\ndoc.patient_id == case.patient_id"]
        Duration["Clinical Duration & Negation Analyzer"]
        StatusResult["Authoritative Criterion Result\n(MET | MISSING | AMBIGUOUS | CONTRADICTED)"]
    end

    subgraph Storage["PostgreSQL 16 Relational Store"]
        DB_Cases[("Cases & Policies")]
        DB_Docs[("Documents & Chunks (Relational / BM25)")]
        DB_Audit[("Append-Only Audit Logs & Review Packets")]
    end

    UI -->|REST + Bearer JWT| Auth
    MCP_Client -->|JSON-RPC via stdio| MCP_Server
    MCP_Server -->|Read-Only Scoped Access| Engine
    Auth --> CasesRouter
    CasesRouter -->|1. Request Advisory Extraction| Agent
    Agent --> LLM
    LLM --> Proposal
    Proposal -->|2. Submit Proposed Citations| Engine
    CasesRouter -->|Or Direct Verification Run| Engine
    Engine --> Offsets
    Engine --> Isolation
    Engine --> Duration
    Duration --> StatusResult
    StatusResult --> DB_Cases
    CasesRouter --> DB_Docs
    CasesRouter --> DB_Audit
```

### Advisory LLM vs. Deterministic Gate Decoupling

The advisory LLM and the deterministic verification gate are strictly separated. The LLM can suggest candidate citations and extract potential facts, but it cannot persist a final determination.

```mermaid
sequenceDiagram
    autonumber
    actor Clinician as Clinician Reviewer
    participant Workstation as React Workstation
    participant API as FastAPI Router
    participant Orchestrator as Agent Orchestrator
    participant LLM as Advisory LLM (Gemini / Stub)
    participant Verifier as Deterministic Verifier Gate
    participant DB as PostgreSQL Database

    Clinician->>Workstation: Select Case CASE-SYN-001 & Click "Run Agent Workflow"
    Workstation->>API: POST /api/v1/cases/CASE-SYN-001/agent-workflow
    API->>Orchestrator: run_case_workflow(case_id)
    Orchestrator->>LLM: Analyze clinical notes & propose citations
    LLM-->>Orchestrator: Return AgentProposalModel (Advisory Status: MET)
    Orchestrator->>Verifier: verify_criterion_evidence(case, proposal.citations)

    rect rgb(240, 248, 255)
        Note over Verifier: Deterministic Boundary Check
        Verifier->>Verifier: Check 1: doc.patient_id == case.patient_id
        Verifier->>Verifier: Check 2: doc.text[start:end] == quote (verbatim)
        Verifier->>Verifier: Check 3: Check duration >= 6 weeks & negation
    end

    alt Quote Mismatch or Missing Fact
        Verifier-->>Orchestrator: Override proposal -> DOWNGRADE to MISSING / CONTRADICTED
    else Verbatim Provenance Valid
        Verifier-->>Orchestrator: Validated -> Authoritative Status: MET
    end

    Orchestrator->>DB: Persist CriterionResultModel + Audit Trail
    Orchestrator-->>API: Return AgentWorkflowResponse
    API-->>Workstation: Render side-by-side Advisory vs. Authoritative Diff
    Clinician->>Workstation: Review provenance & submit clinical determination
    Workstation->>API: POST /api/v1/cases/CASE-SYN-001/approve (Authenticated Clinician Sign-off)
    API->>DB: Finalize ReviewPacket with timestamp and actor attribution
    API-->>Workstation: 200 OK (Packet Finalized)
```

---

## Technology Stack

| Layer | Component | Version | Description |
| :--- | :--- | :--- | :--- |
| **Backend Core** | Python | 3.13 | High-performance modern Python runtime |
| **API Framework** | FastAPI | 0.115+ | Asynchronous REST API framework with automatic OpenAPI docs |
| **Data Validation** | Pydantic | v2.10+ | Strict type validation, serialization, and input sanitization |
| **Database** | PostgreSQL | 16 | Relational persistence with ACID transactions for cases, criteria, documents, and append-only audit entries |
| **Document Retrieval** | BM25 / FastEmbed | Custom / 0.9+ | Lexical BM25 chunk scoring with in-memory dense vector experiments |
| **ORM & Migrations** | SQLAlchemy / Alembic | 2.0+ / 1.14+ | Relational object mapper and declarative schema migrations |
| **Authentication** | Joserfc | 1.0+ | Modern cryptographic JSON Web Token (JWT) handling with HMAC-SHA256 |
| **Protocol Integration** | Model Context Protocol | 2.3.0 | Official Python MCP SDK for desktop AI assistant integration |
| **Advisory LLM** | Google GenAI SDK | `google-genai` | Integration with Gemini 3.5 Flash-Lite (defaults to offline stub) |
| **Frontend Framework**| React | 19.2 | Modern concurrent React UI |
| **Language & Build** | TypeScript / Vite | 5.8 / 6.2 | Strict type-checked frontend with fast Rollup bundling |
| **Styling & Icons** | Tailwind CSS / Lucide | 4.0 / 0.475 | Utility-first responsive design and accessible clinical iconography |
| **Testing** | Pytest / Vitest | 8.3 / 3.0 | 335 Python backend tests and 19 TypeScript UI component tests |
| **Browser Testing** | Playwright | 1.50+ | Automated end-to-end browser verification of clinical workflows |

---

## Repository Layout

```text
authos/
├── backend/                        # Python backend application
│   ├── agent/                      # Advisory multi-agent workflow & orchestrator
│   ├── analysis/                   # Advisory claim analysis service
│   ├── api/v1/                     # FastAPI versioned routes (auth, cases, health)
│   ├── auth/                       # JWT security, synthetic personas, RBAC dependencies
│   ├── config.py                   # Pydantic BaseSettings configuration
│   ├── db/                         # SQLAlchemy models, migrations, and PostgreSQL repo
│   ├── evaluation/                 # Benchmark runners, metrics, and adversarial datasets
│   ├── ingest/                     # Patient document ingestion and text chunking
│   ├── main.py                     # FastAPI application factory and error handlers
│   ├── mcp/                        # Model Context Protocol stdio server adapter
│   ├── retrieval/                  # Hybrid BM25 & dense retrieval algorithms
│   └── verification/               # Authoritative deterministic verification engine
├── contracts/                      # Shared Pydantic data schemas and contract types
├── fixtures/                       # Deterministic synthetic clinical policies and cases
├── frontend/                       # React 19 + TypeScript + Vite clinical workstation
│   ├── src/
│   │   ├── components/             # Reusable UI components (header, modal, badges)
│   │   ├── screens/                # Clinical screens (queue, inspector, criteria, review)
│   │   ├── test/                   # Vitest unit and integration test suites
│   │   └── types/                  # TypeScript interface definitions
│   └── vite.config.ts              # Vite bundler configuration with backend proxy
├── scripts/                        # Database initialization, migration, and seed scripts
├── tests/                          # Pytest test suites (335 tests across 31 files)
├── docker-compose.yml              # Multi-container orchestration (PostgreSQL + Backend)
├── Dockerfile                      # Multi-stage production container build
├── requirements.txt                # Production backend dependencies
└── requirements-dev.txt            # Development, testing, and evaluation dependencies
```

---

## Prerequisites & Environment Configuration

### Prerequisites
* **Python**: `3.13` (recommended) or `3.11+`
* **Node.js**: `20.x` or `22.x LTS` (with `npm 10+`)
* **Docker & Docker Compose**: (Optional, for containerized execution)
* **PostgreSQL**: `16` (if running natively without Docker)

### Environment Configuration Reference (`.env`)

Copy the template to initialize your local environment:
```bash
cp .env.example .env
```

| Environment Variable | Default Value | Allowed Values | Description & Security Policy |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | `development` | `development`, `staging`, `production` | Operational environment. Production enforces non-default secrets and disables synthetic login shortcuts. |
| `API_PREFIX` | `/api/v1` | String path | Base URL prefix for versioned REST endpoints. |
| `DATABASE_URL` | `postgresql+psycopg2://authos:authos@localhost:5432/authos` | Valid SQLAlchemy DB URL | PostgreSQL connection string. (Use port `5433` for Windows native dev when Docker Compose is active). |
| `AUTH_SECRET_KEY` | `dev-insecure-secret-key-change-in-production-authos-2026` | String ($\ge 32$ chars) | Cryptographic HMAC secret for signing JWTs. In production, must be generated randomly (`openssl rand -hex 32`). |
| `AUTH_ALGORITHM` | `HS256` | `HS256` | JWT signature algorithm. |
| `AUTH_TOKEN_EXPIRE_MINUTES` | `120` | Integer | Token expiration window in minutes. |
| `AUTH_ISSUER` | `authos` | String | JWT issuer identifier validated during token verification. |
| `AUTH_AUDIENCE` | `authos-api` | String | JWT audience identifier validated during token verification. |
| `LLM_PROVIDER` | `stub` | `stub`, `gemini` | Advisory provider. `stub` operates fully offline deterministically. `gemini` connects to Google GenAI. |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Valid Gemini model ID | Model identifier used when `LLM_PROVIDER=gemini`. |
| `GEMINI_API_KEY` | *(empty)* | Google GenAI API Key | Required only if `LLM_PROVIDER=gemini`. Never commit to Git. |
| `LLM_TIMEOUT_SECONDS` | `15.0` | Float | Maximum HTTP client timeout for advisory model calls. |
| `LLM_MAX_RETRIES` | `2` | Integer | Maximum retry attempts for transient advisory API failures. |
| `ENABLE_CORRECTIVE_RETRIEVAL` | `false` | `true`, `false` | Activates multi-hop iterative retrieval expansion. |

---

## Quickstart & Installation

### Option 1: Docker Compose (Recommended)

Docker Compose provisions an isolated PostgreSQL database, compiles the React 19 frontend into static assets, and boots the FastAPI backend service.

1. **Clone Repository & Prepare Environment**:
   ```bash
   git clone https://github.com/sanskarchourasiya445/AuthOS.git
   cd authos
   cp .env.example .env
   ```

2. **Build & Start Services**:
   ```bash
   docker compose up --build -d
   ```

3. **Run Migrations & Seed Synthetic Demo Cases**:
   ```bash
   docker compose run --rm seed
   ```

4. **Verify Application Health**:
   ```bash
   curl http://localhost:8000/health/ready
   ```
   *Expected response:* `{"status":"ready","database":"connected","advisory_provider":{"name":"stub","status":"ready","mode":"offline_deterministic","role":"advisory_only"}}`

5. **Access the Reviewer Workstation**:
   Open your browser to `http://localhost:8000/app`.

---

### Option 2: Native Host Development

If developing directly on your host machine (Windows PowerShell or Linux/macOS):

1. **Create & Activate Python Virtual Environment**:
   ```bash
   # Windows PowerShell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install Python Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements-dev.txt
   ```

3. **Build Frontend Static Assets**:
   ```bash
   cd frontend
   npm ci
   npm run build
   cd ..
   ```

4. **Initialize Database & Seed Synthetic Data**:
   Ensure PostgreSQL is running locally, then execute:
   ```bash
   python scripts/init_and_seed.py
   ```

5. **Start API Server**:
   ```bash
   uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```

6. **Start Frontend Dev Server (Optional for Hot-Reloading)**:
   In a separate terminal:
   ```bash
   cd frontend
   npm run dev
   ```
   Navigate to `http://localhost:5173` (Vite proxies backend requests to port `8000`).

---

## Interactive Clinical Reviewer Walkthrough

AuthOS comes pre-seeded with synthetic prior authorization cases. Follow this walkthrough to evaluate the clinical workflow:

### Pre-Configured Synthetic Personas
For rapid local demonstration, AuthOS includes authenticated synthetic personas (disabled in production):

| Persona | Sub / ID | Role | Access Scope | Password |
| :--- | :--- | :--- | :--- | :--- |
| **Dr. Sarah Chen, MD** | `REV-001` | `clinician_reviewer` | `CASE-SYN-001`, `CASE-SYN-002`, `CASE-SYN-003` | `synthetic-demo-pass-dr-chen` |
| **Dr. Allison Ross, MD** | `REV-002` | `clinician_reviewer` | `CASE-SYN-001` | `synthetic-demo-pass-dr-ross` |
| **Jane Doe (Auditor)** | `AUD-001` | `auditor` | `CASE-SYN-001`, `CASE-SYN-002`, `CASE-SYN-003` | `synthetic-demo-pass-auditor-jane` |
| **Alex Rivera (Admin)** | `ADM-001` | `admin` | Full Global Access (`*`) | `synthetic-demo-pass-admin-alex` |

### Step-by-Step Demo Guide (`CASE-SYN-001`)

```text
Queue Selection ──► Criteria Review ──► Source Inspector ──► Advisory Diff ──► Adjudication & Packet
```

1. **Sign In**: Navigate to `http://localhost:8000/app`. By default, the workstation signs in as **Dr. Sarah Chen, MD** (`clinician_reviewer`).
2. **Case Queue**: In the queue table, select case **`CASE-SYN-001`** (Lumbar Spine MRI request under policy `POL-LMRI-001` for patient `SYN-P001`).
3. **Criteria Review Tab**:
   - **Criterion 1 (Low Back Pain $\ge$ 6 Weeks)**: Marked `MET`. Notice the exact quote citation and document date.
   - **Criterion 2 (Conservative Therapy)**: Marked `MET`. Verified 8 weeks of physical therapy completed.
   - **Criterion 3 (Prior Imaging / Red Flags)**: Marked `MISSING`. The patient's chart contains no prior plain radiographs.
4. **Document Inspector**: Click the **🔍 Inspect in Source** button on Criterion 1. The workstation switches to the raw document view, scrolling to and highlighting the exact character offsets in the clinic note.
5. **Advisory vs. Authoritative Comparison**: Switch to the **Advisory vs. Authoritative** tab and click **Run Agent Workflow**. Observe:
   - The advisory agent extracts candidate citations.
   - The deterministic verification engine checks each citation against the chart text.
   - Any hallucinated or unsupported proposal is intercepted and downgraded.
6. **Clinical Adjudication**: Navigate to **Adjudicate & Finalize**.
   - Review the criteria checklist.
   - Enter a clinical rationale (e.g., *"Patient meets conservative therapy requirements; documentation lacks required preliminary lumbar radiographs."*).
   - Select determination: **REQUEST_EDITS** or **REJECT**. (Clinicians can also approve if all criteria are satisfied).
7. **Audit Trail & Review Packet**: Open **Review Packet & Audit Trail** to inspect the finalized review packet, including UTC timestamps, clinician reviewer attribution (`REV-001`), and append-only audit event history.
8. **Role-Based Access Control Test**: Click **Switch Persona** in the top navigation and select **Jane Doe (Auditor)**. Notice that the adjudication form controls are immediately disabled—auditors can inspect evidence and view audit packets, but cannot finalize clinical determinations.

---

## REST API Specification

AuthOS exposes versioned, strictly typed REST endpoints documented interactively at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### Health & Operations
* `GET /health/live`: Fast process liveness check (`{"status": "alive", "service": "authos-api"}`).
* `GET /health/ready`: Deep dependency readiness probe verifying PostgreSQL connection and reporting advisory provider status.

### Authentication (`/api/v1/auth`)
* `POST /api/v1/auth/token`: Exchanges username/password for a signed HMAC-SHA256 JWT access token.
* `GET /api/v1/auth/me`: Returns identity, role, and authorized case scopes for the currently authenticated bearer token.

### Cases & Evidence (`/api/v1/cases`)
* `GET /api/v1/cases`: Returns all prior authorization cases accessible to the authenticated actor.
* `GET /api/v1/cases/{case_id}`: Retrieves comprehensive case details, patient demographics, and policy identifier.
* `GET /api/v1/cases/{case_id}/results`: Retrieves authoritative criterion determinations, verified evidence offsets, missing documentation gaps, and retry audit logs.
* `POST /api/v1/cases/{case_id}/evaluate`: Triggers deterministic retrieval and authoritative evidence verification.
* `POST /api/v1/cases/{case_id}/claim-analysis`: Executes advisory claim analysis (`mode=deterministic` or `mode=agent`).
* `POST /api/v1/cases/{case_id}/agent-workflow`: Runs the multi-agent evidence retrieval and candidate extraction workflow.
* `GET /api/v1/cases/{case_id}/documents`: Lists all chart documents associated with the case's patient.
* `GET /api/v1/cases/{case_id}/documents/{source_id}`: Retrieves raw chart document text and character count. Strictly enforces patient chart boundary isolation (returns `403 Forbidden` on cross-patient document queries).
* `POST /api/v1/cases/{case_id}/documents`: Ingests a new clinical chart document, validating patient boundaries and generating text chunks.
* `POST /api/v1/cases/{case_id}/review`: Records clinician reviewer notes, gap dispositions, and criterion annotations.
* `POST /api/v1/cases/{case_id}/approve`: Finalizes clinical adjudication (`APPROVE`, `REJECT`, `REQUEST_EDITS`). Restricted to `clinician_reviewer` and `admin` roles.
* `GET /api/v1/cases/{case_id}/packet`: Retrieves the finalized review packet. Requires `?preview=true` if inspecting an unfinalized draft.

---

## Model Context Protocol (MCP) Server

AuthOS includes an outward-facing **Model Context Protocol (MCP)** server adapter (`backend.mcp.server`) built with the official Python `mcp==2.3.0` SDK. It allows external desktop AI assistants (such as Anthropic Claude Desktop, Cursor, or clinical copilots) to query AuthOS evidence.

### Architectural Boundaries & Security
1. **Strictly Read-Only**: The MCP server exposes zero packet approval, record deletion, database mutation, or arbitrary SQL execution tools.
2. **Deterministic Output**: Evidence statuses returned through MCP are computed exclusively by AuthOS's deterministic verification engine. The external assistant cannot override statuses.
3. **Patient Chart Isolation**: All tool calls enforce case and patient boundaries. Cross-patient document access returns `CROSS_PATIENT_ACCESS_DENIED`.
4. **Clean stdio Transport**: All diagnostic and error logging is routed to `sys.stderr` via a dedicated handler (`_StderrStreamHandler`), preventing protocol corruption on `sys.stdout`.

### Exposed MCP Tools

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `authos_list_cases` | `auth_token?: str` | Lists available synthetic prior authorization cases. |
| `authos_get_case` | `case_id: str, auth_token?: str` | Retrieves case summary, status, policy ID, and criterion results. |
| `authos_lint_evidence` | `case_id: str, auth_token?: str` | Performs deterministic evidence linting, returning substantiated criteria, exact offsets, and missing documentation gaps. |
| `authos_get_document_excerpt` | `case_id: str, source_id: str, char_start?: int, char_end?: int, auth_token?: str` | Retrieves verbatim text excerpt from patient chart, verifying slice boundaries and patient isolation. |

### Claude Desktop Configuration Example
Add the following configuration to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "authos-linter": {
      "command": "python",
      "args": ["-m", "backend.mcp.server"],
      "cwd": "/path/to/authos",
      "env": {
        "AUTHOS_MCP_DEFAULT_ACTOR": "dr_chen",
        "DATABASE_URL": "postgresql+psycopg2://authos:authos@localhost:5432/authos"
      }
    }
  }
}
```

*Note: In production environments, `AUTHOS_MCP_DEFAULT_ACTOR` fails closed; clients must provide a signed JWT token via `AUTHOS_MCP_TOKEN` or the tool-level `auth_token` parameter.*

---

## Testing & Evaluation Benchmarks

AuthOS maintains an exhaustive, multi-tier testing and verification framework:

### Test Suite Summary

| Test Tier | Framework | Command | Tests | Scope |
| :--- | :--- | :--- | :--- | :--- |
| **Backend Unit & Integration** | Pytest | `pytest -v --ignore=frontend` | **335 tests** | API routes, verifier, schemas, temporal logic, patient boundary guards, MCP server |
| **Frontend Component Tests** | Vitest | `cd frontend && npm test -- --run` | **19 tests** | React screens, modal sign-in, queue filtering, inspector, adjudication state |
| **End-to-End Browser Tests** | Playwright | `pytest tests/test_phase7_browser_e2e.py tests/test_phase9_react_browser_e2e.py -v` | **7 tests** | Full browser automation of clinical review, annotation, role gating, and persistence |
| **Gold Verification Benchmark** | Python Runner | `python -m backend.evaluation.runner` | **34 cases** | Deterministic verification precision, recall, and exact quote offset validity |
| **Adversarial Safety Evaluation**| Python Runner | `python -m backend.evaluation.agent_eval` | **64 cases** | 12 adversarial safety categories, prompt injection defense, and budget limits |

### Adversarial Safety Benchmark Coverage
AuthOS's deterministic verification engine and multi-agent workflow are evaluated against 12 adversarial stress categories:
1. **Direct Prompt Injection**: Injection payloads embedded in physician notes attempting to force `MET` status.
2. **Indirect Prompt Injection**: External instructions hidden in chart text instructing the model to ignore payer rules.
3. **Cross-Patient Citation Leaks**: Submitting valid citations from patient $A$ to substantiate criteria for patient $B$.
4. **Hallucinated Quotes**: Non-existent clinical statements with plausible medical terminology.
5. **Subtle Date Shift Fabrications**: Altering encounter dates in citations to falsely satisfy conservative therapy duration rules.
6. **Temporal Negation Overrides**: Attempting to use historical symptom resolutions to negate active diagnoses.
7. **Duration Arithmetic Edge Cases**: Evaluating therapy completed 41 days prior against a 42-day (6-week) requirement.
8. **Malformed JSON & Schema Attacks**: Injecting invalid enums or extra fields into agent outputs.
9. **Citation Boundary Truncation**: Intentionally shifting start/end character offsets by $\pm 1$ character.
10. **Treatment Refusal Contradictions**: Detecting explicit patient refusals of conservative therapy (`CONTRADICTED`).
11. **Empty Document & Zero-Evidence Guard**: Ensuring proper abstention (`MISSING`) when charts contain no relevant data.
12. **Agent Timeout & Budget Enforcers**: Halting multi-step agent reasoning when execution budgets are exceeded.

---

## Safety, Ethics & Non-Goal Disclosures

> [!IMPORTANT]
> ### Clinical Safety & Ethical Disclosures
> 1. **Synthetic Data Only**: All patient records (`SYN-P001` through `SYN-P006`), physician encounter notes, and payer policy criteria (`POL-LMRI-001`) are entirely synthetic demonstration fixtures. No real Protected Health Information (PHI) is present or stored.
> 2. **Not a Medical Device**: AuthOS is an administrative documentation linter. It does not provide medical diagnoses, treatment recommendations, or coverage guarantees.
> 3. **Mandatory Human-in-the-Loop**: AuthOS cannot approve, reject, or submit prior authorization requests autonomously. A licensed human clinician must review all citations and execute determinations.
> 4. **No Claim of Regulatory Clearance**: AuthOS is an engineering prototype. It has not been reviewed by the FDA, cleared under HIPAA compliance audits, or certified by commercial health plans.
> 5. **Offline Deterministic Verification**: The core verification engine requires no external AI connectivity. When running in default configuration (`LLM_PROVIDER=stub`), all evidence linting is 100% deterministic, offline, and reproducible.

### Non-Goals
* **Not an Automated Claim Approver/Denier**: AuthOS does not replace payer adjudication engines or make financial coverage decisions.
* **Not an Electronic Health Record (EHR)**: AuthOS is not a permanent medical record system. It operates on read-only chart snapshots provided for pre-submission review.
* **Not a Free-Form Diagnostic Chatbot**: The system does not converse with patients or offer unstructured medical opinions.

---

## Operational FAQ & Troubleshooting

### Why is PostgreSQL mapped to port 5433 instead of 5432 in Docker Compose?
To prevent port collisions on host workstations (especially Windows) that already run a local PostgreSQL service on `localhost:5432`, the Docker Compose configuration maps the container database to host port `5433` (`127.0.0.1:5433:5432`). Inside the Docker network, backend containers connect to `db:5432`. If running native Python backend code against the Docker database, set `DATABASE_URL=postgresql+psycopg2://authos:authos@localhost:5433/authos` in your `.env`.

### Can I run AuthOS without a Google Gemini API Key?
Yes. AuthOS defaults to `LLM_PROVIDER=stub`. The offline deterministic stub provides pre-calculated, verified candidate proposals for all synthetic test cases. The authoritative verification engine is completely deterministic and never requires an LLM. To use hosted Gemini models for advisory analysis, set `LLM_PROVIDER=gemini` and configure `GEMINI_API_KEY` in `.env`.

### Why does the MCP server log diagnostic messages to `sys.stderr`?
The Model Context Protocol uses `sys.stdout` for JSON-RPC message framing. Standard logging to stdout corrupts JSON-RPC payloads, causing desktop clients (like Claude Desktop) to disconnect. AuthOS routes all internal MCP logger events through `_StderrStreamHandler` with `propagate=False`.

### How do I re-seed or reset the database?
To reset and re-seed the PostgreSQL database with clean synthetic fixtures:
```bash
# Docker Compose:
docker compose run --rm seed

# Native Host:
python scripts/init_and_seed.py
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
