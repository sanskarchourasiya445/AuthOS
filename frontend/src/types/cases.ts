export type CaseStatus =
  | 'DRAFT'
  | 'RESULTS_READY'
  | 'IN_HUMAN_REVIEW'
  | 'FINALIZED'
  | 'REJECTED'

export interface Case {
  case_id: string
  patient_id: string
  service: string
  policy_id: string
  status: CaseStatus
  scenario?: string
  created_at?: string
  updated_at?: string
}

export interface CaseResultsResponse {
  case_id: string
  patient_id: string
  policy_id: string
  status: CaseStatus
  criteria_results: unknown[]
}
