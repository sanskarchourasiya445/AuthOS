import React, { useState } from 'react'
import type { PolicyCriterionResult, FinalActionType } from '../../types/criteria'
import { Button } from '../../components/common/Button'
import { api } from '../../lib/api/endpoints'
import { useAuth } from '../auth/AuthContext'
import { useToast } from '../../components/common/Toast'

interface ClinicianAdjudicationScreenProps {
  caseId: string
  criteria: PolicyCriterionResult[]
  onSuccess: () => Promise<void>
}

export const ClinicianAdjudicationScreen: React.FC<ClinicianAdjudicationScreenProps> = ({
  caseId,
  criteria,
  onSuccess,
}) => {
  const { user, isAuditor } = useAuth()
  const { showToast } = useToast()

  const [action, setAction] = useState<FinalActionType>('approve_packet')
  const [note, setNote] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false)

  const hasUnmet = criteria.some((c) => c.status !== 'MET')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!note.trim()) {
      showToast('Clinical rationale is mandatory when finalizing an authorization packet.', 'error')
      return
    }

    if (isAuditor) {
      showToast('Auditor role is read-only. Clinician reviewer credentials required.', 'error')
      return
    }

    setIsSubmitting(true)
    try {
      await api.cases.approve(caseId, {
        action,
        reviewer_note: note.trim(),
      })
      showToast('Final determination recorded and packet updated.', 'success')
      setNote('')
      await onSuccess()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Finalization failed'
      showToast(msg, 'error')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div id="wsAdjudicateView" className="ws-sub-view">
      <div className="card" style={{ padding: '24px', maxWidth: '780px' }}>
        <h3 style={{ fontSize: '1.125rem', fontWeight: 700, marginBottom: '8px' }}>
          Formal Clinician Determination Desk
        </h3>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
          Commit an authoritative clinical adjudication on the review packet. Approval confirms evidence criteria are met or clinically justified.
        </p>

        <div id="adjudicationWarning" style={{ marginBottom: '16px' }}>
          {hasUnmet ? (
            <div className="gaps-box" style={{ marginBottom: 0 }}>
              ⚠️ <strong>Clinical Notice:</strong> One or more policy criteria are currently MISSING, AMBIGUOUS, or CONTRADICTED. Approval requires documented clinician justification or accepted gap annotations.
            </div>
          ) : (
            <div
              style={{
                background: 'var(--success-bg)',
                border: '1px solid #86efac',
                color: '#166534',
                padding: '10px 14px',
                borderRadius: '6px',
                fontSize: '0.8125rem',
              }}
            >
              ✅ <strong>All Criteria MET:</strong> All required clinical facts are substantiated in the patient chart.
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '16px' }}>
            <label
              htmlFor="finalActionSelect"
              style={{ display: 'block', fontWeight: 600, fontSize: '0.8125rem', marginBottom: '6px' }}
            >
              Adjudication Action:
            </label>
            <select
              id="finalActionSelect"
              value={action}
              onChange={(e) => setAction(e.target.value as FinalActionType)}
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.875rem',
                background: 'white',
              }}
            >
              <option value="approve_packet">
                Approve Internal Packet for Submission (APPROVE_PACKET)
              </option>
              <option value="request_edits">Request Additional Clinical Records (REQUEST_EDITS)</option>
              <option value="reject_packet">Reject Authorization Packet (REJECT_PACKET)</option>
            </select>
            <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              Note: Packet approval signifies provider-side internal validation for submission, not a payer coverage decision.
            </div>
          </div>

          <div style={{ marginBottom: '20px' }}>
            <label
              htmlFor="finalActionNote"
              style={{ display: 'block', fontWeight: 600, fontSize: '0.8125rem', marginBottom: '6px' }}
            >
              Reviewer Clinical Rationale / Note (Mandatory):
            </label>
            <textarea
              id="finalActionNote"
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Detail clinical documentation findings, rationale for disposition, or specific record requests..."
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

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
            }}
          >
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Acting Clinician:{' '}
              <strong id="adjudicationActorLabel">
                {user ? `${user.name} (${user.role})` : 'Unauthenticated'}
              </strong>
            </div>

            <Button
              type="submit"
              variant="success"
              id="btnSubmitFinal"
              isLoading={isSubmitting}
              disabled={isAuditor || isSubmitting}
              title={
                isAuditor
                  ? 'Auditor role has read-only access. Clinician reviewer role required to adjudicate.'
                  : ''
              }
            >
              💾 Commit Determination
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
