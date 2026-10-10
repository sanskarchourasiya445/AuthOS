-- AuthOS Relational Schema (PostgreSQL DDL Reference)
-- Created in Phase 1A. Managed by Alembic migrations.

-- Payer Policies
CREATE TABLE IF NOT EXISTS policies (
    policy_id VARCHAR(64) PRIMARY KEY,
    service VARCHAR(128) NOT NULL,
    version VARCHAR(32) NOT NULL,
    notice TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Policy Criteria
CREATE TABLE IF NOT EXISTS policy_criteria (
    id SERIAL PRIMARY KEY,
    policy_id VARCHAR(64) NOT NULL REFERENCES policies(policy_id) ON DELETE CASCADE,
    criterion_id VARCHAR(32) NOT NULL,
    text TEXT NOT NULL,
    evidence_expectation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_policy_criterion UNIQUE (policy_id, criterion_id)
);
CREATE INDEX IF NOT EXISTS ix_policy_criteria_policy_id ON policy_criteria(policy_id);

-- Synthetic Chart Source Documents
CREATE TABLE IF NOT EXISTS documents (
    source_id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    doc_date VARCHAR(32),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_documents_patient_id ON documents(patient_id);

-- Prior Authorization Review Cases
CREATE TABLE IF NOT EXISTS cases (
    case_id VARCHAR(64) PRIMARY KEY,
    patient_id VARCHAR(64) NOT NULL,
    service VARCHAR(128) NOT NULL,
    policy_id VARCHAR(64) NOT NULL REFERENCES policies(policy_id),
    status VARCHAR(32) NOT NULL DEFAULT 'RESULTS_READY',
    scenario VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalized_at TIMESTAMPTZ,
    reviewer_note TEXT
);
CREATE INDEX IF NOT EXISTS ix_cases_patient_id ON cases(patient_id);
CREATE INDEX IF NOT EXISTS ix_cases_policy_id ON cases(policy_id);

-- Criterion Evaluation Results per Case
CREATE TABLE IF NOT EXISTS criterion_results (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    criterion_id VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    retry_log JSONB NOT NULL DEFAULT '[]'::jsonb,
    validator_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_case_criterion UNIQUE (case_id, criterion_id)
);
CREATE INDEX IF NOT EXISTS ix_criterion_results_case_id ON criterion_results(case_id);

-- Append-Only Review and Finalization Audit Trail
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    criterion_id VARCHAR(32),
    action VARCHAR(64) NOT NULL,
    note TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL DEFAULT 'HUMAN_REVIEWER (UNAUTHENTICATED_DEV)',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_case_id ON audit_log(case_id);

-- Advisory Multi-Agent Workflow Proposals (Phase 8)
CREATE TABLE IF NOT EXISTS agent_proposals (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(64) NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL,
    criterion_id VARCHAR(32) NOT NULL,
    proposed_status VARCHAR(32) NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.0,
    uncertainty_rationale TEXT NOT NULL,
    evidence_quotes JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    detected_gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieval_rounds INT NOT NULL DEFAULT 1,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    verification_feedback JSONB,
    flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_case_run_criterion UNIQUE (case_id, run_id, criterion_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_proposals_case_id ON agent_proposals(case_id);
CREATE INDEX IF NOT EXISTS ix_agent_proposals_run_id ON agent_proposals(run_id);

