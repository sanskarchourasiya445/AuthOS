import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CriteriaReviewScreen } from '../features/evidence/CriteriaReviewScreen'
import { ToastProvider } from '../components/common/Toast'
import { api } from '../lib/api/endpoints'
import type { PolicyCriterionResult } from '../types/criteria'

const mockCriteria: PolicyCriterionResult[] = [
  {
    criterion_id: 'CRIT-001',
    criterion: 'Trial of conservative physical therapy >= 6 weeks',
    status: 'MET',
    verified: true,
    reason: 'Documented 8 weeks of supervised physical therapy with no relief.',
    evidence: [
      {
        source_id: 'SYN-P001-PT-01',
        quote: 'Patient completed 8 weeks of formal physical therapy with minimal improvement.',
        char_start: 120,
        char_end: 201,
        polarity: 'SUPPORTING',
      },
    ],
    missing_facts: [],
  },
  {
    criterion_id: 'CRIT-002',
    criterion: 'Persistent radicular pain for >= 6 weeks',
    status: 'CONTRADICTED',
    verified: false,
    reason: 'Chart indicates symptom onset was only 10 days ago.',
    evidence: [],
    conflicting_evidence: [
      {
        source_id: 'SYN-P001-NOTE-01',
        quote: 'Pain began abruptly 10 days ago after lifting heavy boxes.',
        char_start: 45,
        char_end: 104,
        polarity: 'CONTRADICTING',
      },
    ],
    missing_facts: ['Documentation of persistent symptoms >= 6 weeks'],
  },
]

describe('CriteriaReviewScreen', () => {
  it('renders criteria cards with correct status, evidence, and offsets', () => {
    const onInspect = vi.fn()

    render(
      <ToastProvider>
        <CriteriaReviewScreen
          caseId="CASE-SYN-001"
          criteria={mockCriteria}
          onInspectEvidence={onInspect}
          onRefreshWorkspace={vi.fn()}
          onTriggerEvaluation={vi.fn()}
        />
      </ToastProvider>
    )

    // Check criterion 1
    expect(screen.getByText('CRIT-001')).toBeInTheDocument()
    expect(screen.getByText('Trial of conservative physical therapy >= 6 weeks')).toBeInTheDocument()
    expect(screen.getByText('Verified: YES')).toBeInTheDocument()
    expect(screen.getByText('MET')).toBeInTheDocument()
    expect(screen.getByText(/8 weeks of formal physical therapy/i)).toBeInTheDocument()
    expect(screen.getByText('Offsets: [120:201]')).toBeInTheDocument()

    // Check criterion 2
    expect(screen.getByText('CRIT-002')).toBeInTheDocument()
    expect(screen.getByText('CONTRADICTED')).toBeInTheDocument()
    expect(screen.getByText(/Conflicting \/ Refusal Evidence/i)).toBeInTheDocument()
    expect(screen.getByText(/Pain began abruptly 10 days ago/i)).toBeInTheDocument()
    expect(screen.getByText('Documentation of persistent symptoms >= 6 weeks')).toBeInTheDocument()
  })

  it('triggers onInspectEvidence with sourceId and exact offsets when inspect button is clicked', async () => {
    const user = userEvent.setup()
    const onInspect = vi.fn()

    render(
      <ToastProvider>
        <CriteriaReviewScreen
          caseId="CASE-SYN-001"
          criteria={mockCriteria}
          onInspectEvidence={onInspect}
          onRefreshWorkspace={vi.fn()}
          onTriggerEvaluation={vi.fn()}
        />
      </ToastProvider>
    )

    const inspectBtns = screen.getAllByRole('button', { name: /Inspect in Source/i })
    await user.click(inspectBtns[0])

    expect(onInspect).toHaveBeenCalledWith('SYN-P001-PT-01', 120, 201)
  })

  it('submits reviewer annotation to API when clinical note is provided', async () => {
    const user = userEvent.setup()
    const reviewMock = vi.spyOn(api.cases, 'review').mockResolvedValue({
      case_id: 'CASE-SYN-001',
      criterion_id: 'CRIT-001',
      action: 'accept_gap',
      note: 'Verified with outpatient PT clinic records.',
      timestamp: new Date().toISOString(),
    })
    const refreshMock = vi.fn()

    render(
      <ToastProvider>
        <CriteriaReviewScreen
          caseId="CASE-SYN-001"
          criteria={mockCriteria}
          onInspectEvidence={vi.fn()}
          onRefreshWorkspace={refreshMock}
          onTriggerEvaluation={vi.fn()}
        />
      </ToastProvider>
    )

    const noteInputs = screen.getAllByPlaceholderText(/mandatory reviewer rationale/i)
    await user.type(noteInputs[0], 'Verified with outpatient PT clinic records.')

    const actionSelects = screen.getAllByLabelText(/reviewer action/i)
    await user.selectOptions(actionSelects[0], 'accept_gap')

    const saveBtns = screen.getAllByRole('button', { name: /save annotation/i })
    await user.click(saveBtns[0])

    expect(reviewMock).toHaveBeenCalledWith('CASE-SYN-001', {
      criterion_id: 'CRIT-001',
      action: 'accept_gap',
      note: 'Verified with outpatient PT clinic records.',
    })
    expect(refreshMock).toHaveBeenCalled()
  })
})
