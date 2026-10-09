# AuthOS — Security and Privacy Baseline

**Status:** Baseline for synthetic hackathon MVP. This is not a compliance certification or legal opinion.

## Data classification and scope

MVP input must be fully synthetic. Do not paste, upload, log or send real patient information, production screenshots, identifiers or actual clinical documents to the repository, model APIs, issue trackers or demo recordings. Synthetic data must be reviewed for accidental real identifiers before publication.

A future pilot with real patient data is a separate security and privacy project and is not authorized by this document. It requires a documented jurisdiction/role assessment, legal/privacy review, data-processing/vendor review, access control, audit controls, retention/deletion rules, incident response and deployment approval before any real data is loaded.

## Threats and baseline controls

| Threat | MVP control | Future deployment gate |
|---|---|---|
| Cross-patient evidence leakage | Filter by case/patient in the database query; verify source patient again in deterministic code. | Authorization checks at every endpoint and tenant boundary tests. |
| Fabricated or mismatched citation | Exact quote/source verification; reject evidence that fails validation. | Continuous adversarial evaluation and audit sampling. |
| Prompt injection in retrieved text | Treat source text as untrusted data, never as system instructions; isolate tool permissions. | Red-team test suite and provider/tool hardening. |
| Secrets committed to Git | `.env.example` contains placeholders only; `.env` ignored; rotate exposed credentials. | Secret scanning and managed secret storage. |
| Sensitive text in logs | Synthetic-only input; log IDs, status, timings and validator codes rather than full source content where possible. | Approved logging policy, access controls and retention limits. |
| Unauthorized review/finalization | Local demo boundary and explicit server-side state transition checks. | Authentication, role-based authorization, reviewer identity and auditability. |
| Dependency/model supply chain | Pin dependencies and record model/provider configuration. | Vulnerability scanning, vendor review and change management. |
| Unsafe packet finalization | Finalization requires explicit human action; no insurer approval language. | Verified identity, durable audit record and operational procedure. |

## Secure implementation requirements

- Validate every request and model output; reject unknown enum values and unexpected state transitions.
- Never use an LLM output as SQL, a filesystem path, a shell command, or authorization logic.
- Use parameterized database queries and least-privilege database credentials.
- Keep tool inputs/outputs narrowly scoped; read tools by default. Any write/finalization tool must require explicit human workflow state.
- Avoid logging API keys, prompts containing sensitive data, full chart text, or environment variables.
- Pin and update dependencies deliberately; do not rely on remembered APIs from coding assistants.
- Provide safe error responses without stack traces or secrets.
- Keep audit events append-only at the application layer; record run, reviewer action and packet finalization events.
- Include a persistent disclaimer that AuthOS prepares evidence and does not decide medical necessity or insurance approval.

## Real-data release blockers

Before any real patient data is used, owners must determine applicable law and contractual obligations, data controller/processor roles, model-provider data handling and retention, data residency, encryption, access/identity management, audit retention, breach response, deletion/export, backup protection and security testing. Do not claim HIPAA or other compliance merely because a checklist exists.

## Incident handling for MVP

If real or sensitive data is accidentally introduced: stop sharing/running the affected workflow, restrict access, remove it from tracked artifacts and logs where possible, rotate any exposed credentials, notify the project owner, and document what was exposed and what remediation occurred. For a real deployment, replace this lightweight procedure with an approved incident-response process.
