import type { CaseStatus } from './cases'
import type { PolicyCriterionResult } from './criteria'

export interface AuditEvent {
  id?: number
  case_id: string
  timestamp?: string
  created_at?: string
  actor: string
  action: string
  criterion_id?: string
  note?: string
  status_before?: string
  status_after?: string
}

export interface ReviewPacket {
  case_id: string
  patient_id: string
  service: string
  policy_id: string
  status: CaseStatus
  criteria: PolicyCriterionResult[]
  reviewer_note?: string
  finalized: boolean
  finalized_at?: string
  audit_events?: AuditEvent[]
}
