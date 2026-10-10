import { apiFetch } from './client'
import type { LoginCredentials, TokenResponse, AuthenticatedUser } from '../../types/auth'
import type { Case, CaseResultsResponse } from '../../types/cases'
import type {
  ReviewActionRequest,
  ReviewActionResponse,
  FinalizationActionRequest,
} from '../../types/criteria'
import type {
  PatientDocumentSummary,
  PatientDocumentDetail,
  DocumentIngestRequest,
  DocumentIngestResponse,
} from '../../types/documents'
import type { ClaimAnalysisResponse, AgentWorkflowResponse } from '../../types/workflow'
import type { ReviewPacket } from '../../types/packets'

export const api = {
  auth: {
    login: (credentials: LoginCredentials) =>
      apiFetch<TokenResponse>('/api/v1/auth/token', {
        method: 'POST',
        body: JSON.stringify(credentials),
      }),
    me: () => apiFetch<AuthenticatedUser>('/api/v1/auth/me'),
  },

  cases: {
    list: () => apiFetch<Case[]>('/api/v1/cases'),
    get: (caseId: string) => apiFetch<Case>(`/api/v1/cases/${caseId}`),
    getResults: (caseId: string) => apiFetch<CaseResultsResponse>(`/api/v1/cases/${caseId}/results`),
    getPacket: (caseId: string, preview = true) =>
      apiFetch<ReviewPacket>(`/api/v1/cases/${caseId}/packet?preview=${preview}`),
    getDocuments: (caseId: string) =>
      apiFetch<PatientDocumentSummary[]>(`/api/v1/cases/${caseId}/documents`),
    getDocument: (caseId: string, sourceId: string) =>
      apiFetch<PatientDocumentDetail>(`/api/v1/cases/${caseId}/documents/${sourceId}`),
    ingestDocument: (caseId: string, payload: DocumentIngestRequest) =>
      apiFetch<DocumentIngestResponse>(`/api/v1/cases/${caseId}/documents`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    evaluate: (caseId: string) =>
      apiFetch<ReviewPacket>(`/api/v1/cases/${caseId}/evaluate`, {
        method: 'POST',
      }),
    claimAnalysis: (caseId: string, mode: 'deterministic' | 'agent' = 'deterministic') =>
      apiFetch<ClaimAnalysisResponse>(`/api/v1/cases/${caseId}/claim-analysis?mode=${mode}`, {
        method: 'POST',
      }),
    agentWorkflow: (caseId: string) =>
      apiFetch<AgentWorkflowResponse>(`/api/v1/cases/${caseId}/agent-workflow`, {
        method: 'POST',
      }),
    review: (caseId: string, payload: ReviewActionRequest) =>
      apiFetch<ReviewActionResponse>(`/api/v1/cases/${caseId}/review`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    approve: (caseId: string, payload: FinalizationActionRequest) =>
      apiFetch<ReviewPacket>(`/api/v1/cases/${caseId}/approve`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
  },
}
