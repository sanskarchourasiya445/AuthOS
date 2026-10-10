import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DocumentInspectorScreen } from '../features/documents/DocumentInspectorScreen'
import { ToastProvider } from '../components/common/Toast'
import { api } from '../lib/api/endpoints'
import type { PatientDocumentSummary, PatientDocumentDetail } from '../types/documents'

const mockDocSummaries: PatientDocumentSummary[] = [
  {
    source_id: 'SYN-P001-PT-01',
    patient_id: 'SYN-P001',
    doc_date: '2026-08-15',
    character_count: 145,
    chunks_count: 2,
    created_at: '2026-08-15T10:00:00Z',
  },
]

const mockDocDetail: PatientDocumentDetail = {
  source_id: 'SYN-P001-PT-01',
  patient_id: 'SYN-P001',
  doc_date: '2026-08-15',
  text: 'CLINICAL NOTE: Patient reports 8 weeks of supervised physical therapy with no significant low back pain relief.',
  character_count: 111,
  chunks_count: 2,
  created_at: '2026-08-15T10:00:00Z',
}

describe('DocumentInspectorScreen', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  it('renders document list and raw text verbatim', async () => {
    vi.spyOn(api.cases, 'getDocument').mockResolvedValue(mockDocDetail)

    render(
      <ToastProvider>
        <DocumentInspectorScreen
          caseId="CASE-SYN-001"
          patientId="SYN-P001"
          documents={mockDocSummaries}
          selectedDocId="SYN-P001-PT-01"
          highlightOffsets={null}
          onSelectDoc={vi.fn()}
          onRefreshDocuments={vi.fn()}
        />
      </ToastProvider>
    )

    await waitFor(() => {
      expect(screen.getAllByText('SYN-P001-PT-01').length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText(/Patient reports 8 weeks of supervised physical therapy/i)).toBeInTheDocument()
      expect(screen.getByText('Verbatim Ground Truth')).toBeInTheDocument()
    })
  })

  it('highlights exact character offsets using a <mark> element when offsets are valid', async () => {
    vi.spyOn(api.cases, 'getDocument').mockResolvedValue(mockDocDetail)

    // Highlight "8 weeks of supervised physical therapy"
    // "CLINICAL NOTE: Patient reports " is 31 chars
    // "8 weeks of supervised physical therapy" is 38 chars
    const start = 31
    const end = 69

    render(
      <ToastProvider>
        <DocumentInspectorScreen
          caseId="CASE-SYN-001"
          patientId="SYN-P001"
          documents={mockDocSummaries}
          selectedDocId="SYN-P001-PT-01"
          highlightOffsets={{ start, end }}
          onSelectDoc={vi.fn()}
          onRefreshDocuments={vi.fn()}
        />
      </ToastProvider>
    )

    await waitFor(() => {
      const mark = screen.getByText('8 weeks of supervised physical therapy')
      expect(mark.tagName.toLowerCase()).toBe('mark')
      expect(mark).toHaveClass('evidence-highlight')
      expect(screen.getByText(/Offsets \[31:69\] Verified/i)).toBeInTheDocument()
    })
  })

  it('displays verification error message when offsets exceed document bounds', async () => {
    vi.spyOn(api.cases, 'getDocument').mockResolvedValue(mockDocDetail)

    render(
      <ToastProvider>
        <DocumentInspectorScreen
          caseId="CASE-SYN-001"
          patientId="SYN-P001"
          documents={mockDocSummaries}
          selectedDocId="SYN-P001-PT-01"
          highlightOffsets={{ start: 50, end: 9999 }}
          onSelectDoc={vi.fn()}
          onRefreshDocuments={vi.fn()}
        />
      </ToastProvider>
    )

    await waitFor(() => {
      expect(screen.getByText(/Verification Error: Specified character offsets/i)).toBeInTheDocument()
    })
  })

  it('validates document ingestion inputs before submission', async () => {
    const user = userEvent.setup()
    vi.spyOn(api.cases, 'getDocument').mockResolvedValue(mockDocDetail)

    render(
      <ToastProvider>
        <DocumentInspectorScreen
          caseId="CASE-SYN-001"
          patientId="SYN-P001"
          documents={mockDocSummaries}
          selectedDocId="SYN-P001-PT-01"
          highlightOffsets={null}
          onSelectDoc={vi.fn()}
          onRefreshDocuments={vi.fn()}
        />
      </ToastProvider>
    )

    // Open ingestion modal
    const ingestBtn = screen.getByRole('button', { name: /\+ Ingest Note/i })
    await user.click(ingestBtn)

    expect(screen.getByText('Ingest Clinical Chart Record')).toBeInTheDocument()
    expect(screen.getByLabelText(/Document Source ID/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Raw Document Text Content/i)).toBeInTheDocument()
  })
})
