import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../features/auth/AuthContext'
import { ToastProvider } from '../components/common/Toast'
import { CaseQueueScreen } from '../features/cases/CaseQueueScreen'
import { api } from '../lib/api/endpoints'
import type { Case } from '../types/cases'

const mockCases: Case[] = [
  {
    case_id: 'CASE-SYN-001',
    patient_id: 'SYN-P001',
    service: 'Lumbar Spine MRI',
    policy_id: 'POL-LUMBAR-001',
    status: 'RESULTS_READY',
    scenario: 'Conservative therapy failure documented',
  },
  {
    case_id: 'CASE-SYN-002',
    patient_id: 'SYN-P002',
    service: 'Lumbar Spine MRI',
    policy_id: 'POL-LUMBAR-001',
    status: 'IN_HUMAN_REVIEW',
    scenario: 'Contradiction flagged',
  },
]

describe('CaseQueueScreen', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api.auth, 'login').mockResolvedValue({
      access_token: 'valid-token',
      token_type: 'bearer',
      expires_in: 7200,
      user: {
        sub: 'REV-001',
        name: 'Dr. Sarah Chen, MD',
        role: 'clinician_reviewer',
        cases: ['CASE-SYN-001', 'CASE-SYN-002'],
      },
    })
  })

  it('renders case queue table and filters by text and status', async () => {
    vi.spyOn(api.cases, 'list').mockResolvedValue(mockCases)
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <AuthProvider>
          <ToastProvider>
            <CaseQueueScreen />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    )

    // Wait for data load
    await waitFor(() => {
      expect(screen.getByText('CASE-SYN-001')).toBeInTheDocument()
      expect(screen.getByText('CASE-SYN-002')).toBeInTheDocument()
    })

    // Search filter test
    const searchInput = screen.getByPlaceholderText(/search case/i)
    await user.type(searchInput, 'CASE-SYN-001')
    expect(screen.getByText('CASE-SYN-001')).toBeInTheDocument()
    expect(screen.queryByText('CASE-SYN-002')).not.toBeInTheDocument()

    // Clear search and status filter test
    await user.clear(searchInput)
    const statusSelect = screen.getByLabelText(/filter status/i)
    await user.selectOptions(statusSelect, 'IN_HUMAN_REVIEW')

    expect(screen.queryByText('CASE-SYN-001')).not.toBeInTheDocument()
    expect(screen.getByText('CASE-SYN-002')).toBeInTheDocument()
  })

  it('displays empty state when no cases match', async () => {
    vi.spyOn(api.cases, 'list').mockResolvedValue([])

    render(
      <MemoryRouter>
        <AuthProvider>
          <ToastProvider>
            <CaseQueueScreen />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/no prior-authorization cases found/i)).toBeInTheDocument()
    })
  })
})
