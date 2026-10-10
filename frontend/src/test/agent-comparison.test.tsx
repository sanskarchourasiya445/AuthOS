import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AgentComparisonScreen } from '../features/workflow/AgentComparisonScreen'
import { ToastProvider } from '../components/common/Toast'
import { api } from '../lib/api/endpoints'
import type { PolicyCriterionResult } from '../types/criteria'
import type { ClaimAnalysisResponse } from '../types/workflow'

const mockCriteria: PolicyCriterionResult[] = [
  {
    criterion_id: 'CRIT-001',
    criterion: 'Trial of conservative physical therapy >= 6 weeks',
    status: 'MET',
    verified: true,
    reason: 'Documented 8 weeks of supervised physical therapy.',
    evidence: [],
  },
]

const mockAnalysisResp: ClaimAnalysisResponse = {
  case_id: 'CASE-SYN-001',
  patient_id: 'SYN-P001',
  policy_id: 'POL-LUMBAR-001',
  analyzer_provider: 'MULTI_AGENT_WORKFLOW (DETERMINISTIC_AGENT_STUB)',
  generated_at: '2026-10-10T11:00:00Z',
  disclaimer: 'Advisory draft suggestion only.',
  proposals: [
    {
      criterion_id: 'CRIT-001',
      proposed_status: 'MET',
      confidence: 0.95,
      evidence_quotes: ['8 weeks formal PT documented.'],
      missing_facts: [],
      detected_gaps: [],
      uncertainty_rationale: 'Chart note strongly substantiates conservative care.',
      is_ai_generated: true,
      flags: ['AGENT_ORCHESTRATED', 'VERIFIED_BY_GATE:true'],
    },
  ],
}

describe('AgentComparisonScreen', () => {
  it('displays advisory disclaimer and allows running workflow comparison', async () => {
    const user = userEvent.setup()
    vi.spyOn(api.cases, 'claimAnalysis').mockResolvedValue(mockAnalysisResp)

    render(
      <ToastProvider>
        <AgentComparisonScreen caseId="CASE-SYN-001" criteria={mockCriteria} />
      </ToastProvider>
    )

    expect(screen.getByText(/Advisory AI Analysis Disclaimer/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run Multi-Agent Workflow/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Single-Pass Baseline/i })).toBeInTheDocument()

    // Trigger workflow
    await user.click(screen.getByRole('button', { name: /Run Multi-Agent Workflow/i }))

    await waitFor(() => {
      expect(screen.getByText(/DETERMINISTIC_AGENT_STUB/i)).toBeInTheDocument()
      expect(screen.getByText(/Status Agreement/i)).toBeInTheDocument()
      expect(screen.getByText(/Authoritative Verification/i)).toBeInTheDocument()
      expect(screen.getByText(/Advisory Proposal/i)).toBeInTheDocument()
      expect(screen.getByText('95.0%')).toBeInTheDocument()
      expect(screen.getByText('AGENT_ORCHESTRATED')).toBeInTheDocument()
    })
  })
})
