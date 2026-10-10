import React, { useState } from 'react'
import type { PolicyCriterionResult, ReviewActionType } from '../../types/criteria'
import { Badge } from '../../components/common/Badge'
import { Button } from '../../components/common/Button'
import { api } from '../../lib/api/endpoints'
import { useToast } from '../../components/common/Toast'

interface CriteriaReviewScreenProps {
  caseId: string
  criteria: PolicyCriterionResult[]
  onInspectEvidence: (sourceId: string, charStart: number, charEnd: number) => void
  onRefreshWorkspace: () => Promise<void>
  onTriggerEvaluation: () => Promise<void>
}

export const CriteriaReviewScreen: React.FC<CriteriaReviewScreenProps> = ({
  caseId,
  criteria,
  onInspectEvidence,
  onRefreshWorkspace,
  onTriggerEvaluation,
}) => {
  const { showToast } = useToast()
  const [actionTypes, setActionTypes] = useState<Record<string, ReviewActionType>>({})
  const [actionNotes, setActionNotes] = useState<Record<string, string>>({})
  const [submittingCritId, setSubmittingCritId] = useState<string | null>(null)

  const handleActionChange = (critId: string, action: ReviewActionType) => {
    setActionTypes((prev) => ({ ...prev, [critId]: action }))
  }

  const handleNoteChange = (critId: string, note: string) => {
    setActionNotes((prev) => ({ ...prev, [critId]: note }))
  }

  const handleSubmitAnnotation = async (critId: string) => {
    const action = actionTypes[critId] || 'request_information'
    const note = (actionNotes[critId] || '').trim()

    if (!note) {
      showToast('Reviewer clinical note is mandatory for audit logging.', 'error')
      return
    }

    setSubmittingCritId(critId)
    try {
      await api.cases.review(caseId, {
        criterion_id: critId,
        action,
        note,
      })
      showToast('Criterion annotation committed to immutable audit trail.', 'success')
      setActionNotes((prev) => ({ ...prev, [critId]: '' }))
      await onRefreshWorkspace()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to record review action'
      showToast(msg, 'error')
    } finally {
      setSubmittingCritId(null)
    }
  }

  if (!criteria || criteria.length === 0) {
    return (
      <div id="wsCriteriaView" className="ws-sub-view">
        <div id="criteriaListContainer">
          <div
            style={{
              background: 'white',
              padding: '32px',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              textAlign: 'center',
            }}
          >
            <p style={{ color: 'var(--text-muted)', marginBottom: '16px' }}>
              No evaluated criterion records found for this case.
            </p>
            <Button variant="primary" onClick={onTriggerEvaluation}>
              ⚡ Run Deterministic Evaluation
            </Button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div id="wsCriteriaView" className="ws-sub-view">
      <div id="criteriaListContainer">
        {criteria.map((c) => {
          const action = actionTypes[c.criterion_id] || 'request_information'
          const note = actionNotes[c.criterion_id] || ''

          return (
            <div key={c.criterion_id} className="criterion-card">
              <div className="crit-header">
                <div className="crit-title-area">
                  <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {c.criterion_id}
                  </span>
                  <span className="crit-text">{c.criterion}</span>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span
                    className="tag"
                    style={{
                      background: c.verified ? '#dcfce7' : '#fee2e2',
                      color: c.verified ? '#15803d' : '#b91c1c',
                      fontWeight: 600,
                    }}
                  >
                    Verified: {c.verified ? 'YES' : 'NO'}
                  </span>
                  <Badge status={c.status} />
                </div>
              </div>

              <div className="crit-eval-box">
                <strong>Assessment Reason:</strong> {c.reason || 'No clinical reasoning documented.'}
              </div>

              {c.missing_facts && c.missing_facts.length > 0 && (
                <div className="gaps-box">
                  <strong>Clinical Documentation Gaps:</strong>
                  <ul style={{ marginLeft: '20px', marginTop: '4px' }}>
                    {c.missing_facts.map((gap, i) => (
                      <li key={i}>{gap}</li>
                    ))}
                  </ul>
                </div>
              )}

              {c.conflicting_evidence && c.conflicting_evidence.length > 0 && (
                <div style={{ marginBottom: '14px' }}>
                  <h4
                    style={{
                      fontSize: '0.75rem',
                      textTransform: 'uppercase',
                      color: 'var(--danger)',
                      marginBottom: '6px',
                    }}
                  >
                    ⚠️ Conflicting / Refusal Evidence ({c.conflicting_evidence.length})
                  </h4>
                  {c.conflicting_evidence.map((ev, i) => (
                    <div key={i} className="evidence-item contradicting">
                      <div style={{ fontWeight: 600, color: 'var(--danger)', marginBottom: '4px' }}>
                        Contradictory Chart Record:
                      </div>
                      <div>
                        <em>"{ev.quote}"</em>
                      </div>
                      <div className="evidence-meta-row">
                        <span className="tag mono">Source: {ev.source_id}</span>
                        <span className="tag mono">
                          Offsets: [{ev.char_start}:{ev.char_end}]
                        </span>
                        <span className="tag mono">Date: {ev.document_date || 'N/A'}</span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => onInspectEvidence(ev.source_id, ev.char_start, ev.char_end)}
                          style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                        >
                          🔍 Inspect in Source
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ marginBottom: '16px' }}>
                <h4
                  style={{
                    fontSize: '0.75rem',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted)',
                    marginBottom: '6px',
                  }}
                >
                  Supporting Evidence Citations ({(c.evidence || []).length})
                </h4>
                {c.evidence && c.evidence.length > 0 ? (
                  c.evidence.map((ev, i) => (
                    <div key={i} className="evidence-item">
                      <div style={{ marginBottom: '4px' }}>
                        <em>"{ev.quote}"</em>
                      </div>
                      <div className="evidence-meta-row">
                        <span className="tag mono">Source: {ev.source_id}</span>
                        <span className="tag mono">
                          Offsets: [{ev.char_start}:{ev.char_end}]
                        </span>
                        <span className="tag mono">Date: {ev.document_date || 'N/A'}</span>
                        <span className="tag">Polarity: {ev.polarity}</span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => onInspectEvidence(ev.source_id, ev.char_start, ev.char_end)}
                          style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                        >
                          🔍 Inspect in Source
                        </Button>
                      </div>
                    </div>
                  ))
                ) : (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                    No grounded supporting evidence found.
                  </p>
                )}
              </div>

              {/* Reviewer Annotation Control */}
              <div
                style={{
                  borderTop: '1px dashed var(--border)',
                  paddingTop: '12px',
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                }}
              >
                <label
                  htmlFor={`action_${c.criterion_id}`}
                  style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}
                >
                  Reviewer Action:
                </label>
                <select
                  id={`action_${c.criterion_id}`}
                  value={action}
                  onChange={(e) => handleActionChange(c.criterion_id, e.target.value as ReviewActionType)}
                  style={{
                    fontSize: '0.75rem',
                    padding: '6px 10px',
                    borderRadius: '4px',
                    border: '1px solid var(--border)',
                    background: 'white',
                  }}
                >
                  <option value="request_information">
                    Request Additional Records (REQUEST_INFORMATION)
                  </option>
                  <option value="accept_gap">Accept Documentation Gap (ACCEPT_GAP)</option>
                  <option value="flag_contradiction">Flag Contradiction (FLAG_CONTRADICTION)</option>
                  <option value="custom_note">Reviewer Note (CUSTOM_NOTE)</option>
                </select>

                <input
                  type="text"
                  id={`note_${c.criterion_id}`}
                  placeholder="Mandatory reviewer rationale for audit trail..."
                  value={note}
                  onChange={(e) => handleNoteChange(c.criterion_id, e.target.value)}
                  style={{
                    flex: 1,
                    minWidth: '220px',
                    fontSize: '0.75rem',
                    padding: '6px 10px',
                    borderRadius: '4px',
                    border: '1px solid var(--border)',
                  }}
                />

                <Button
                  id={`submitCriterionAnnotation_${c.criterion_id}`}
                  variant="secondary"
                  size="sm"
                  onClick={() => handleSubmitAnnotation(c.criterion_id)}
                  isLoading={submittingCritId === c.criterion_id}
                >
                  Save Annotation
                </Button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
