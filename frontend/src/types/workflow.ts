import type { CriterionStatus } from './criteria'

export interface AIClaimProposal {
  criterion_id: string
  proposed_status: CriterionStatus
  confidence: number
  evidence_quotes: string[]
  missing_facts: string[]
  detected_gaps: string[]
  uncertainty_rationale: string
  is_ai_generated: boolean
  flags: string[]
}

export interface ClaimAnalysisResponse {
  case_id: string
  patient_id: string
  policy_id: string
  analyzer_provider: string
  proposals: AIClaimProposal[]
  disclaimer: string
  generated_at: string
}

export interface AgentExecutionMetadata {
  latency_ms: number
  steps_executed: string[]
  provider: string
  is_external_llm: boolean
  prompt_injection_detected: boolean
  circuit_broken: boolean
  iterations: number
}

export interface AgentCriterionProposal {
  criterion_id: string
  proposed_status: CriterionStatus
  confidence: number
  uncertainty_rationale: string
  evidence_quotes: string[]
  missing_facts: string[]
  detected_gaps: string[]
  retrieval_rounds: number
  is_verified_by_boundary: boolean
  verification_feedback?: string
  flags: string[]
}

export interface AgentWorkflowResponse {
  case_id: string
  patient_id: string
  policy_id: string
  status: string
  execution_metadata: AgentExecutionMetadata
  proposals: AgentCriterionProposal[]
  disclaimer: string
  created_at: string
}
