import React, { useState, useEffect, useRef } from 'react'
import type { PatientDocumentSummary, PatientDocumentDetail } from '../../types/documents'
import { api } from '../../lib/api/endpoints'
import { Button } from '../../components/common/Button'
import { Modal } from '../../components/common/Modal'
import { useToast } from '../../components/common/Toast'

interface DocumentInspectorScreenProps {
  caseId: string
  patientId: string
  documents: PatientDocumentSummary[]
  selectedDocId: string | null
  highlightOffsets: { start: number; end: number } | null
  onSelectDoc: (sourceId: string) => void
  onRefreshDocuments: () => Promise<void>
}

export const DocumentInspectorScreen: React.FC<DocumentInspectorScreenProps> = ({
  caseId,
  patientId,
  documents,
  selectedDocId,
  highlightOffsets,
  onSelectDoc,
  onRefreshDocuments,
}) => {
  const { showToast } = useToast()
  const highlightRef = useRef<HTMLElement>(null)

  const [activeDocDetail, setActiveDocDetail] = useState<PatientDocumentDetail | null>(null)
  const [isLoadingDoc, setIsLoadingDoc] = useState<boolean>(false)
  const [docError, setDocError] = useState<string | null>(null)

  // Ingestion Modal State
  const [isIngestOpen, setIsIngestOpen] = useState<boolean>(false)
  const [ingestSourceId, setIngestSourceId] = useState<string>('')
  const [ingestDocDate, setIngestDocDate] = useState<string>(
    new Date().toISOString().split('T')[0]
  )
  const [ingestMimeType, setIngestMimeType] = useState<string>('text/plain')
  const [ingestText, setIngestText] = useState<string>('')
  const [isSubmittingIngest, setIsSubmittingIngest] = useState<boolean>(false)

  // Load document content whenever selectedDocId changes
  useEffect(() => {
    if (!selectedDocId) {
      if (documents.length > 0) {
        onSelectDoc(documents[0].source_id)
      } else {
        setActiveDocDetail(null)
      }
      return
    }

    let isMounted = true
    setIsLoadingDoc(true)
    setDocError(null)

    api.cases
      .getDocument(caseId, selectedDocId)
      .then((detail) => {
        if (isMounted) {
          setActiveDocDetail(detail)
          setIsLoadingDoc(false)
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          const msg = err instanceof Error ? err.message : 'Failed to load document'
          setDocError(msg)
          setIsLoadingDoc(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [caseId, selectedDocId, documents, onSelectDoc])

  // Scroll to active highlight
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [activeDocDetail, highlightOffsets])

  const handleIngestSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ingestSourceId.trim() || !ingestText.trim()) {
      showToast('Source ID and Document Text are required.', 'error')
      return
    }

    // Max size check: 2MB limit
    if (ingestText.length > 2 * 1024 * 1024) {
      showToast('Document text exceeds maximum allowed size (2MB).', 'error')
      return
    }

    setIsSubmittingIngest(true)
    try {
      const resp = await api.cases.ingestDocument(caseId, {
        source_id: ingestSourceId.trim(),
        patient_id: patientId,
        doc_date: ingestDocDate,
        mime_type: ingestMimeType,
        text: ingestText,
      })
      showToast(
        `Document ${resp.source_id} ingested successfully (${resp.chunks_created} chunks).`,
        'success'
      )
      setIsIngestOpen(false)
      setIngestSourceId('')
      setIngestText('')
      await onRefreshDocuments()
      onSelectDoc(resp.source_id)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Ingestion failed'
      showToast(msg, 'error')
    } finally {
      setIsSubmittingIngest(false)
    }
  }

  // Render raw document with or without highlight
  const renderDocumentContent = () => {
    if (isLoadingDoc) {
      return <div style={{ color: 'var(--text-muted)' }}>Loading raw document from server...</div>
    }
    if (docError) {
      return <div style={{ color: 'var(--danger)' }}>Error loading document: {docError}</div>
    }
    if (!activeDocDetail) {
      return (
        <div style={{ color: 'var(--text-muted)' }}>
          Select a document or evidence citation to inspect verbatim source text.
        </div>
      )
    }

    const rawText = activeDocDetail.text
    if (highlightOffsets) {
      const { start, end } = highlightOffsets
      const isValid = start >= 0 && end > start && end <= rawText.length

      if (!isValid) {
        return (
          <div>
            <div
              style={{
                color: 'var(--danger)',
                background: 'var(--danger-bg)',
                padding: '8px 12px',
                borderRadius: '4px',
                marginBottom: '12px',
              }}
            >
              ⚠️ Verification Error: Specified character offsets [{start}:{end}] are invalid for document length ({rawText.length} chars).
            </div>
            <span>{rawText}</span>
          </div>
        )
      }

      const before = rawText.substring(0, start)
      const target = rawText.substring(start, end)
      const after = rawText.substring(end)

      return (
        <span>
          {before}
          <mark
            className="evidence-highlight"
            id="activeHighlightSpan"
            ref={highlightRef}
          >
            {target}
          </mark>
          {after}
        </span>
      )
    }

    return <span>{rawText}</span>
  }

  return (
    <div id="wsInspectorView" className="ws-sub-view">
      <div className="inspector-layout">
        {/* Left: Document Navigation List */}
        <div className="doc-nav-card">
          <div
            style={{
              fontWeight: 600,
              fontSize: '0.875rem',
              marginBottom: '12px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>Chart Documents</span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIsIngestOpen(true)}
              style={{ padding: '2px 8px', fontSize: '0.75rem' }}
            >
              + Ingest Note
            </Button>
          </div>

          <div className="doc-list" id="docListContainer">
            {documents.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>No chart documents found.</p>
            ) : (
              documents.map((d) => {
                const isActive = d.source_id === selectedDocId
                return (
                  <button
                    key={d.source_id}
                    id={`navDoc_${d.source_id}`}
                    type="button"
                    className={`doc-list-item ${isActive ? 'active' : ''}`}
                    onClick={() => onSelectDoc(d.source_id)}
                  >
                    <strong className="mono" style={{ fontSize: '0.8125rem' }}>
                      {d.source_id}
                    </strong>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                      {d.doc_date || 'No date'} ({d.character_count} chars)
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* Right: Verbatim Source Viewer */}
        <div className="viewer-card">
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '14px',
              borderBottom: '1px solid var(--border)',
              paddingBottom: '10px',
              flexWrap: 'wrap',
              gap: '8px',
            }}
          >
            <div>
              <h3 id="docViewerTitle" style={{ fontSize: '1rem', fontWeight: 700 }}>
                {activeDocDetail ? activeDocDetail.source_id : 'Select a document'}
              </h3>
              <div id="docViewerMeta" className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {activeDocDetail
                  ? `Patient: ${activeDocDetail.patient_id} | Date: ${activeDocDetail.doc_date || 'N/A'} | Length: ${activeDocDetail.character_count} chars | Chunks: ${activeDocDetail.chunks_count}`
                  : ''}
              </div>
            </div>

            <div id="docVerificationStatus">
              {highlightOffsets && activeDocDetail ? (
                <span className="badge badge-MET" style={{ fontSize: '0.6875rem' }}>
                  Offsets [{highlightOffsets.start}:{highlightOffsets.end}] Verified
                </span>
              ) : (
                <span className="tag">Verbatim Ground Truth</span>
              )}
            </div>
          </div>

          <div className="doc-raw-container" id="docRawContent">
            {renderDocumentContent()}
          </div>
        </div>
      </div>

      {/* Ingest Document Modal */}
      <Modal
        isOpen={isIngestOpen}
        onClose={() => setIsIngestOpen(false)}
        title="Ingest Clinical Chart Record"
        maxWidth="600px"
      >
        <form onSubmit={handleIngestSubmit} id="modalIngest">
          <div style={{ marginBottom: '12px' }}>
            <label
              htmlFor="ingestSourceId"
              style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
            >
              Document Source ID (e.g. SYN-P001-PT-03)
            </label>
            <input
              id="ingestSourceId"
              type="text"
              value={ingestSourceId}
              onChange={(e) => setIngestSourceId(e.target.value)}
              placeholder="Unique clinical source identifier..."
              required
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.875rem',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div>
              <label
                htmlFor="ingestDocDate"
                style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
              >
                Document Date
              </label>
              <input
                id="ingestDocDate"
                type="date"
                value={ingestDocDate}
                onChange={(e) => setIngestDocDate(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  fontSize: '0.875rem',
                }}
              />
            </div>

            <div>
              <label
                htmlFor="ingestMimeType"
                style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
              >
                MIME Format
              </label>
              <select
                id="ingestMimeType"
                value={ingestMimeType}
                onChange={(e) => setIngestMimeType(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                  fontSize: '0.875rem',
                  background: 'white',
                }}
              >
                <option value="text/plain">Plain Text (text/plain)</option>
                <option value="text/markdown">Markdown (text/markdown)</option>
                <option value="application/json">Structured JSON (application/json)</option>
              </select>
            </div>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label
              htmlFor="ingestText"
              style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
            >
              Raw Document Text Content
            </label>
            <textarea
              id="ingestText"
              rows={8}
              value={ingestText}
              onChange={(e) => setIngestText(e.target.value)}
              placeholder="Paste clinical progress note, physical therapy summary, or radiology narrative..."
              required
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8125rem',
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIsIngestOpen(false)}
              disabled={isSubmittingIngest}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" isLoading={isSubmittingIngest}>
              Ingest Document
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
