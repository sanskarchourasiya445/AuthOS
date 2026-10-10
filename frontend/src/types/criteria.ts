export type CriterionStatus = 'MET' | 'MISSING' | 'AMBIGUOUS' | 'CONTRADICTED'

export type EvidencePolarity = 'SUPPORTING' | 'CONTRADICTING' | 'INCONCLUSIVE'

export interface EvidenceItem {
  source_id: string
  patient_id?: string
  quote: string
  document_date?: string
  chunk_id?: string
  char_start: number
  char_end: number
  polarity: EvidencePolarity | string
}

export interface PolicyCriterionResult {
  criterion_id: string
  criterion: string
  status: CriterionStatus
  verified: boolean
  reason?: string
  evidence: EvidenceItem[]
  conflicting_evidence?: EvidenceItem[]
  missing_facts?: string[]
  retry_log?: unknown[]
  validator_flags?: string[]
}

export type ReviewActionType =
  | 'request_information'
  | 'accept_gap'
  | 'flag_contradiction'
  | 'custom_note'

export interface ReviewActionRequest {
  criterion_id: string
  action: ReviewActionType
  note: string
}

export interface ReviewActionResponse {
  case_id: string
  criterion_id: string
  action: string
  note: string
  timestamp: string
}

export type FinalActionType = 'approve_packet' | 'request_edits' | 'reject_packet'

export interface FinalizationActionRequest {
  action: FinalActionType
  reviewer_note: string
}
