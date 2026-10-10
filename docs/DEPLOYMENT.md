# AuthOS Deployment and Operations Guide

**System**: AuthOS Prior Authorization Evidence Linter  
**Phase**: 14 (Reproducible Deployment and Operations)  
**Target Environment**: Containerized (Docker Compose) or Native (Local Python / PostgreSQL / Node.js)  

---

## 1. Overview & Operational Model

AuthOS is an evidence-linting prototype for prior authorization requests. Its sole purpose is to evaluate whether clinical criteria are substantiated by supplied medical chart records, requiring exact verbatim quote provenance and deterministic duration verification.

### Core Operational Principles
- **Authoritative Gate**: The deterministic verification engine (`backend.verification.engine.verify_criterion_evidence`) is the sole authority for assigning final criterion status (`MET`, `MISSING`, `AMBIGUOUS`, `CONTRADICTED`).
- **Advisory LLM Decoupling**: External LLMs (e.g. Google Gemini) are strictly advisory. Unavailability or absence of LLM credentials does not take down the system or block deterministic verification.
- **Fail-Closed Security**: In the absence of verifiable evidence or when credentials/permissions are invalid, the system fails closed (`MISSING`, `AMBIGUOUS`, or `403 Forbidden`).

---

## 2. Prerequisites

### Option A: Docker Deployment (Recommended for Reproducibility)
- **Docker Engine**: `>= 24.0`
- **Docker Compose**: `>= v2.20`

### Option B: Native Host Deployment
- **Python**: `3.13` or `3.12`
- **Node.js**: `>= 20.x` & `npm`
- **PostgreSQL**: `>= 16.x` (running locally or network-accessible)

---

## 3. Environment Configuration

Copy the template configuration file:
```bash
cp .env.example .env
```

### Environment Variable Reference

| Variable | Required | Default | Scope | Description |
| :--- | :---: | :---: | :---: | :--- |
| `APP_ENV` | Yes | `development` | System | Environment mode: `development`, `staging`, or `production`. |
| `API_PREFIX` | No | `/api/v1` | System | Base URL prefix for all REST endpoints. |
| `DATABASE_URL` | Yes | *See below* | Backend | SQLAlchemy PostgreSQL connection string with driver. |
| `ENABLE_CORRECTIVE_RETRIEVAL` | No | `false` | RAG | Enables bounded 2-stage corrective query rewriting. |
| `MAX_RETRIEVAL_RETRIES` | No | `2` | RAG | Maximum number of retrieval retries (0–5). |
| `AUTH_SECRET_KEY` | Yes | *Dev default* | Security | Symmetric JWT signing key. **Must be $\ge 32$ bytes in production**. |
| `AUTH_ALGORITHM` | No | `HS256` | Security | JWT signing algorithm. |
| `AUTH_TOKEN_EXPIRE_MINUTES` | No | `120` | Security | Expiration duration for bearer access tokens. |
| `LLM_PROVIDER` | No | `stub` | Agent | Advisory provider: `stub` (offline deterministic) or `gemini`. |
| `LLM_MODEL` | No | `gemini-2.5-flash-lite` | Agent | LLM model identifier. |
| `GEMINI_API_KEY` | Conditional | `""` | Agent | Required only if `LLM_PROVIDER=gemini`. |
| `LLM_TIMEOUT_SECONDS` | No | `15.0` | Agent | Per-call HTTP timeout for external provider. |
| `LLM_MAX_RETRIES` | No | `2` | Agent | Maximum retry attempts for transient API errors. |

> [!WARNING] Production Security Invariants
> When `APP_ENV=production`, the application strictly enforces:
> 1. `AUTH_SECRET_KEY` cannot match the default development key and must be at least 32 bytes (`openssl rand -hex 32`).
> 2. `DATABASE_URL` must be set and cannot point to an empty or default unauthenticated target.
> 3. `GEMINI_API_KEY` is required if `LLM_PROVIDER=gemini`.
> 4. Synthetic development login (`POST /api/v1/auth/token`) is automatically blocked with `403 Forbidden`.

---

## 4. Quickstart: Docker Compose

### 1. Build and Start Services
```bash
docker compose up --build -d
```
This builds the multi-stage container (compiling the React frontend, installing Python dependencies, applying non-root user permissions), starts PostgreSQL on an internal isolated network with health checks, applies Alembic migrations automatically on startup, and launches the Uvicorn application server on port `8000`.

### 2. Seed Synthetic Clinical Data (One-Shot Task)
```bash
docker compose run --rm seed
```
This runs the idempotent data seeding script, populating synthetic policies, patients (`SYN-P001` through `SYN-P006`), demo cases, and document text chunks.

### 3. Verify Health Probes
```bash
# Liveness
curl http://localhost:8000/health/live
# Expected: {"status": "alive", "service": "authos-api"}

# Readiness (verifies DB connection)
curl http://localhost:8000/health/ready
# Expected: {"status": "ready", "database": "connected", "advisory_provider": {"name": "stub", "status": "ready", ...}}
```

### 4. Access the Reviewer Workstation
Open your browser to:
- **Modern React Reviewer Workstation**: `http://localhost:8000/app`
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`

### 5. Tear Down
```bash
docker compose down -v  # Removes containers and local volume
```

---

## 5. Native Host Deployment (Development Workflow)

### 1. Python Virtual Environment Setup
```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
```

### 2. Frontend Build
```bash
cd frontend
npm ci
npm run build
cd ..
```

### 3. Database Initialization & Seeding
Ensure PostgreSQL is active. Run the consolidated migration and idempotent seeding utility:
```bash
python scripts/init_and_seed.py
```
This runs `alembic upgrade head`, validates all tables, and seeds initial synthetic data.

### 4. Start Application Server
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 6. Health, Readiness, and Observability Endpoints

AuthOS provides three distinct health check endpoints:

### `GET /health/live`
- **Purpose**: Fast process liveness probe for container engines and load balancers.
- **Behavior**: Returns `200 OK` immediately without performing network or database I/O.
- **Response**:
  ```json
  {"status": "alive", "service": "authos-api"}
  ```

### `GET /health/ready`
- **Purpose**: Dependency readiness probe.
- **Behavior**: Executes a lightweight `SELECT 1` database query. Checks optional advisory LLM configuration.
- **Response (Healthy - 200 OK)**:
  ```json
  {
    "status": "ready",
    "database": "connected",
    "advisory_provider": {
      "name": "stub",
      "status": "ready",
      "mode": "offline_deterministic",
      "role": "advisory_only"
    }
  }
  ```
- **Response (Degraded - 503 Service Unavailable)**:
  ```json
  {
    "status": "not_ready",
    "database": "unavailable",
    "advisory_provider": { ... }
  }
  ```
  *Note: Connection passwords, SQL statements, and internal server stack traces are never exposed in health probe responses.*

### `GET /api/v1/health`
- Backwards-compatible legacy probe returning `{"status": "ok", "version": "v1"}`.

---

## 7. Running Tests and Evaluations

### Complete Backend Pytest Suite
```bash
pytest -v --ignore=frontend
```
*Current baseline: 313 passed.*

### Frontend Vitest Suite
```bash
cd frontend && npm test && cd ..
```
*Current baseline: 19 passed across 7 test files.*

### Browser End-to-End Suites (Playwright)
```bash
# Vanilla review UI suite (6 tests)
pytest tests/test_phase7_browser_e2e.py -v

# Modern React Workstation suite (1 comprehensive workflow test)
pytest tests/test_phase9_react_browser_e2e.py -v
```

### Full Evaluation Benchmarks
```bash
# Benchmark 1: Core Verifier Fixtures & RAG Metrics
python -m backend.evaluation.runner

# Benchmark 2–5: Multi-Agent Adjudication & Adversarial Suite
python -m backend.evaluation.agent_eval
```

---

## 8. Operational & Security Limitations

1. **Synthetic Clinical Data Only**: AuthOS is tested exclusively against synthetic patient charts and synthetic policy models. It contains no real protected health information (PHI).
2. **Not a Clinical Device**: AuthOS is an evidence-linting prototype. It does not provide medical advice, diagnosis, treatment recommendations, or coverage determinations.
3. **External LLM Provider**: Live Google Gemini integration requires outbound HTTPS access and a valid `GEMINI_API_KEY`. When unconfigured, the system operates in offline deterministic mode.
4. **Environment Configuration**: Environment variables alone do not constitute comprehensive production security; production deployment requires encrypted secrets management (e.g., HashiCorp Vault, AWS Secrets Manager), TLS termination, and network firewalls.
