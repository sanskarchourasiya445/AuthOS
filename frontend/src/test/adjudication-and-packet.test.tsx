import React, { useEffect } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { ClinicianAdjudicationScreen } from '../features/adjudication/ClinicianAdjudicationScreen'
import { FinalReviewPacketScreen } from '../features/packets/FinalReviewPacketScreen'
import { AuthProvider, useAuth } from '../features/auth/AuthContext'
import { ToastProvider } from '../components/common/Toast'
import { api } from '../lib/api/endpoints'
import type { ReviewPacket } from '../types/packets'
import type { Case } from '../types/cases'

const mockCase: Case = {
  case_id: 'CASE-SYN-001',
  patient_id: 'SYN-P001',
  service: 'Lumbar Spine MRI',
  policy_id: 'POL-LUMBAR-001',
  status: 'IN_HUMAN_REVIEW',
}

const mockPacket: ReviewPacket = {
  case_id: 'CASE-SYN-001',
  patient_id: 'SYN-P001',
  service: 'Lumbar Spine MRI',
  policy_id: 'POL-LUMBAR-001',
  status: 'FINALIZED',
  criteria: [
    {
      criterion_id: 'C1',
      criterion: 'Physical therapy trial',
      status: 'MET',
      verified: true,
      evidence: [],
    },
  ],
  finalized: true,
  finalized_at: '2026-10-10T12:00:00Z',
  reviewer_note: 'Approved based on documented conservative therapy failure.',
  audit_events: [
    {
      case_id: 'CASE-SYN-001',
      created_at: '2026-10-10T12:00:00Z',
      actor: 'Dr. Sarah Chen, MD (REV-001)',
      action: 'APPROVE_PACKET',
      criterion_id: 'ALL',
      note: 'Approved based on documented conservative therapy failure.',
    },
  ],
}

const AuditorTestWrapper: React.FC = () => {
  const { loginAsPersona } = useAuth()
  useEffect(() => {
    loginAsPersona('auditor_jane').catch(() => {})
  }, [loginAsPersona])

  return (
    <ClinicianAdjudicationScreen
      caseId="CASE-SYN-001"
      criteria={mockPacket.criteria}
      onSuccess={vi.fn()}
    />
  )
}

describe('Adjudication & Final Packet Views', () => {
  it('disables determination submission for auditor persona', async () => {
    vi.spyOn(api.auth, 'login').mockResolvedValue({
      access_token: 'auditor-token',
      token_type: 'bearer',
      expires_in: 7200,
      user: {
        sub: 'AUD-001',
        name: 'Jane Doe',
        role: 'auditor',
        cases: ['CASE-SYN-001'],
      },
    })

    render(
      <AuthProvider>
        <ToastProvider>
          <AuditorTestWrapper />
        </ToastProvider>
      </AuthProvider>
    )

    await waitFor(() => {
      const commitBtn = screen.getByRole('button', { name: /Commit Determination/i })
      expect(commitBtn).toBeDisabled()
    })
  })

  it('renders packet disposition, summary, and chronological audit history table', () => {
    render(
      <FinalReviewPacketScreen
        caseData={mockCase}
        packetData={mockPacket}
      />
    )

    expect(screen.getByText('Final Prior-Authorization Review Packet View')).toBeInTheDocument()
    expect(screen.getByText('FINALIZED')).toBeInTheDocument()
    const matchingNotes = screen.getAllByText(/Approved based on documented conservative therapy failure/i)
    expect(matchingNotes.length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('📜 Chronological Audit Trail (Immutable)')).toBeInTheDocument()
    expect(screen.getByText('Dr. Sarah Chen, MD (REV-001)')).toBeInTheDocument()
    expect(screen.getByText('APPROVE_PACKET')).toBeInTheDocument()
  })
})
