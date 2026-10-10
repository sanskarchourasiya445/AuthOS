import React, { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../../lib/api/endpoints'
import type { Case } from '../../types/cases'
import type { ReviewPacket } from '../../types/packets'
import type { PatientDocumentSummary } from '../../types/documents'
import { Badge } from '../../components/common/Badge'
import { Button } from '../../components/common/Button'
import { LoadingState } from '../../components/common/LoadingState'
import { useToast } from '../../components/common/Toast'
import { useAuth } from '../auth/AuthContext'

import { CriteriaReviewScreen } from '../evidence/CriteriaReviewScreen'
import { DocumentInspectorScreen } from '../documents/DocumentInspectorScreen'
import { AgentComparisonScreen } from '../workflow/AgentComparisonScreen'
import { ClinicianAdjudicationScreen } from '../adjudication/ClinicianAdjudicationScreen'
import { FinalReviewPacketScreen } from '../packets/FinalReviewPacketScreen'

type WorkspaceSubTab =
  | 'wsCriteriaView'
  | 'wsInspectorView'
  | 'wsAdvisoryView'
  | 'wsAdjudicateView'
  | 'wsAuditView'

interface CaseWorkspaceScreenProps {
  onCaseLoaded?: (caseId: string) => void
}

export const CaseWorkspaceScreen: React.FC<CaseWorkspaceScreenProps> = ({ onCaseLoaded }) => {
  const { caseId } = useParams<{ caseId: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()
  const { isAuthenticated } = useAuth()

  const [activeTab, setActiveTab] = useState<WorkspaceSubTab>('wsCriteriaView')
  const [caseData, setCaseData] = useState<Case | null>(null)
  const [packetData, setPacketData] = useState<ReviewPacket | null>(null)
  const [documents, setDocuments] = useState<PatientDocumentSummary[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [isEvaluating, setIsEvaluating] = useState<boolean>(false)

  // Document Inspector State
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [highlightOffsets, setHighlightOffsets] = useState<{ start: number; end: number } | null>(
    null
  )

  const loadCaseData = useCallback(async () => {
    if (!caseId || !isAuthenticated) return
    setIsLoading(true)
    setError(null)

    try {
      const [caseResp, packetResp, docsResp] = await Promise.all([
        api.cases.get(caseId),
        api.cases.getPacket(caseId, true),
        api.cases.getDocuments(caseId),
      ])

      setCaseData(caseResp)
      setPacketData(packetResp)
      setDocuments(docsResp)
      if (docsResp.length > 0 && !selectedDocId) {
        setSelectedDocId(docsResp[0].source_id)
      }
      if (onCaseLoaded) onCaseLoaded(caseId)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : `Failed to load case ${caseId}`
      setError(msg)
      showToast(msg, 'error')
    } finally {
      setIsLoading(false)
    }
  }, [caseId, isAuthenticated, selectedDocId, onCaseLoaded, showToast])

  useEffect(() => {
    loadCaseData()
  }, [loadCaseData])

  const handleTriggerEvaluation = async () => {
    if (!caseId) return
    setIsEvaluating(true)
    showToast('Running deterministic retrieval and evaluation...', 'info')
    try {
      const updatedPacket = await api.cases.evaluate(caseId)
      setPacketData(updatedPacket)
      const updatedCase = await api.cases.get(caseId)
      setCaseData(updatedCase)
      showToast('Deterministic evaluation completed.', 'success')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Evaluation failed'
      showToast(msg, 'error')
    } finally {
      setIsEvaluating(false)
    }
  }

  const handleInspectEvidence = (sourceId: string, charStart: number, charEnd: number) => {
    setSelectedDocId(sourceId)
    setHighlightOffsets({ start: charStart, end: charEnd })
    setActiveTab('wsInspectorView')
  }

  const handleSelectDoc = (sourceId: string) => {
    setSelectedDocId(sourceId)
    setHighlightOffsets(null)
  }

  if (isLoading) {
    return (
      <section id="screenWorkspace" className="screen-view active">
        <LoadingState message={`Loading workspace records for case ${caseId}...`} />
      </section>
    )
  }

  if (error || !caseData) {
    return (
      <section id="screenWorkspace" className="screen-view active">
        <div
          role="alert"
          style={{
            background: 'var(--danger-bg)',
            color: 'var(--danger)',
            padding: '24px',
            borderRadius: 'var(--radius)',
            border: '1px solid #fca5a5',
            textAlign: 'center',
          }}
        >
          <h3 style={{ marginBottom: '8px', fontSize: '1.125rem' }}>Failed to Load Case Workspace</h3>
          <p style={{ marginBottom: '16px', fontSize: '0.875rem' }}>{error || 'Case not found or unauthorized.'}</p>
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
            <Button variant="secondary" onClick={() => navigate('/cases')}>
              ← Back to Case Queue
            </Button>
            <Button variant="primary" onClick={loadCaseData}>
              Retry Loading
            </Button>
          </div>
        </div>
      </section>
    )
  }

  const isFinalized = packetData?.finalized

  return (
    <section id="screenWorkspace" className="screen-view active">
      {/* Workspace Header */}
      <div className="workspace-header">
        <div className="workspace-meta">
          <div className="meta-box">
            <div className="label">Case ID</div>
            <div className="value mono" id="wsCaseId">
              {caseData.case_id}
            </div>
          </div>
          <div className="meta-box">
            <div className="label">Patient</div>
            <div className="value mono" id="wsPatientId">
              {caseData.patient_id}
            </div>
          </div>
          <div className="meta-box">
            <div className="label">Requested Service</div>
            <div className="value" id="wsService">
              {caseData.service}
            </div>
          </div>
          <div className="meta-box">
            <div className="label">Policy ID</div>
            <div className="value mono" id="wsPolicy">
              {caseData.policy_id}
            </div>
          </div>
          <div className="meta-box">
            <div className="label">Workflow State</div>
            <div className="value" id="wsStatusBadge">
              <Badge status={caseData.status} />
            </div>
          </div>
          <div className="meta-box">
            <div className="label">Packet State</div>
            <div className="value" id="wsPacketBadge">
              {isFinalized ? (
                <Badge status="FINALIZED">FINALIZED</Badge>
              ) : (
                <Badge status="DRAFT">DRAFT / IN REVIEW</Badge>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <Button
            variant="primary"
            size="sm"
            onClick={handleTriggerEvaluation}
            isLoading={isEvaluating}
          >
            ⚡ Run Evaluation
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setActiveTab('wsAdvisoryView')}
          >
            🤖 Advisory AI Analysis
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadCaseData}
          >
            🔄 Refresh
          </Button>
        </div>
      </div>

      {/* Sub-Tabs Navigation */}
      <div className="workspace-tabs" role="tablist" aria-label="Case Workspace Subtabs">
        <button
          type="button"
          id="wsTabCriteria"
          role="tab"
          aria-selected={activeTab === 'wsCriteriaView'}
          aria-controls="wsCriteriaView"
          className={`ws-tab ${activeTab === 'wsCriteriaView' ? 'active' : ''}`}
          onClick={() => setActiveTab('wsCriteriaView')}
        >
          📋 Criteria & Evidence
        </button>
        <button
          type="button"
          id="wsTabInspector"
          role="tab"
          aria-selected={activeTab === 'wsInspectorView'}
          aria-controls="wsInspectorView"
          className={`ws-tab ${activeTab === 'wsInspectorView' ? 'active' : ''}`}
          onClick={() => setActiveTab('wsInspectorView')}
        >
          📄 Source Document Inspector
        </button>
        <button
          type="button"
          id="wsTabAdvisory"
          role="tab"
          aria-selected={activeTab === 'wsAdvisoryView'}
          aria-controls="wsAdvisoryView"
          className={`ws-tab ${activeTab === 'wsAdvisoryView' ? 'active' : ''}`}
          onClick={() => setActiveTab('wsAdvisoryView')}
        >
          ⚖️ Advisory vs Authoritative Diff
        </button>
        <button
          type="button"
          id="wsTabAdjudicate"
          role="tab"
          aria-selected={activeTab === 'wsAdjudicateView'}
          aria-controls="wsAdjudicateView"
          className={`ws-tab ${activeTab === 'wsAdjudicateView' ? 'active' : ''}`}
          onClick={() => setActiveTab('wsAdjudicateView')}
        >
          ✍️ Clinician Adjudication
        </button>
        <button
          type="button"
          id="wsTabAudit"
          role="tab"
          aria-selected={activeTab === 'wsAuditView'}
          aria-controls="wsAuditView"
          className={`ws-tab ${activeTab === 'wsAuditView' ? 'active' : ''}`}
          onClick={() => setActiveTab('wsAuditView')}
        >
          📜 Packet & Audit Trail
        </button>
      </div>

      {/* Active Sub-Tab View */}
      {activeTab === 'wsCriteriaView' && (
        <CriteriaReviewScreen
          caseId={caseData.case_id}
          criteria={packetData?.criteria || []}
          onInspectEvidence={handleInspectEvidence}
          onRefreshWorkspace={loadCaseData}
          onTriggerEvaluation={handleTriggerEvaluation}
        />
      )}

      {activeTab === 'wsInspectorView' && (
        <DocumentInspectorScreen
          caseId={caseData.case_id}
          patientId={caseData.patient_id}
          documents={documents}
          selectedDocId={selectedDocId}
          highlightOffsets={highlightOffsets}
          onSelectDoc={handleSelectDoc}
          onRefreshDocuments={loadCaseData}
        />
      )}

      {activeTab === 'wsAdvisoryView' && (
        <AgentComparisonScreen
          caseId={caseData.case_id}
          criteria={packetData?.criteria || []}
        />
      )}

      {activeTab === 'wsAdjudicateView' && (
        <ClinicianAdjudicationScreen
          caseId={caseData.case_id}
          criteria={packetData?.criteria || []}
          onSuccess={loadCaseData}
        />
      )}

      {activeTab === 'wsAuditView' && (
        <FinalReviewPacketScreen
          caseData={caseData}
          packetData={packetData}
        />
      )}
    </section>
  )
}
