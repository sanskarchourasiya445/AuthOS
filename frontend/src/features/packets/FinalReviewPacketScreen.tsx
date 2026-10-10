import React from 'react'
import type { ReviewPacket } from '../../types/packets'
import type { Case } from '../../types/cases'
import { Badge } from '../../components/common/Badge'

interface FinalReviewPacketScreenProps {
  caseData: Case | null
  packetData: ReviewPacket | null
}

export const FinalReviewPacketScreen: React.FC<FinalReviewPacketScreenProps> = ({
  caseData,
  packetData,
}) => {
  const isFinalized = packetData?.finalized
  const audits = packetData?.audit_events || []

  return (
    <div id="wsAuditView" className="ws-sub-view">
      {/* Screen 8: Review Packet Summary */}
      <div className="card" style={{ marginBottom: '24px', padding: '20px' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px' }}>
          Final Prior-Authorization Review Packet View
        </h3>
        <div
          id="packetSummaryBox"
          style={{
            background: '#f8fafc',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '16px',
            fontSize: '0.8125rem',
          }}
        >
          {packetData ? (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: '16px',
              }}
            >
              <div>
                <strong style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Packet Disposition:
                </strong>
                {isFinalized ? (
                  <Badge status="FINALIZED">FINALIZED</Badge>
                ) : (
                  <Badge status="DRAFT">UNFINALIZED DRAFT</Badge>
                )}
              </div>

              <div>
                <strong style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Case Lifecycle State:
                </strong>
                <Badge status={caseData?.status || 'UNKNOWN'} />
              </div>

              <div>
                <strong style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Criteria Evaluated:
                </strong>
                <span className="mono" style={{ fontWeight: 600 }}>
                  {(packetData.criteria || []).length} criteria
                </span>
              </div>

              <div>
                <strong style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Clinician Signature / Timestamp:
                </strong>
                <span className="mono" style={{ fontSize: '0.75rem' }}>
                  {packetData.finalized_at || 'Pending Clinician Signature'}
                </span>
              </div>

              {packetData.reviewer_note && (
                <div style={{ gridColumn: '1 / -1', marginTop: '4px' }}>
                  <strong style={{ display: 'block', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Reviewer Note:
                  </strong>
                  <div
                    style={{
                      background: 'white',
                      padding: '8px 12px',
                      borderRadius: '4px',
                      border: '1px solid var(--border)',
                      fontStyle: 'italic',
                    }}
                  >
                    "{packetData.reviewer_note}"
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div>Loading packet details...</div>
          )}
        </div>
      </div>

      {/* Screen 9: Chronological Audit Trail */}
      <div className="card">
        <div
          style={{
            padding: '14px 18px',
            background: '#f8fafc',
            borderBottom: '1px solid var(--border)',
            fontWeight: 700,
            fontSize: '0.875rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>📜 Chronological Audit Trail (Immutable)</span>
          <span className="tag mono">{audits.length} events logged</span>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" aria-label="Immutable Audit Trail">
            <thead>
              <tr>
                <th scope="col">Timestamp (UTC)</th>
                <th scope="col">Authenticated Actor</th>
                <th scope="col">Action</th>
                <th scope="col">Criterion</th>
                <th scope="col">Clinical Note / Rationale</th>
              </tr>
            </thead>
            <tbody id="auditTrailBody">
              {audits.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '24px' }}
                  >
                    No audit records logged for this case.
                  </td>
                </tr>
              ) : (
                audits.map((a, i) => (
                  <tr key={i}>
                    <td className="mono" style={{ fontSize: '0.75rem' }}>
                      {a.created_at || a.timestamp || '-'}
                    </td>
                    <td>
                      <strong>{a.actor || 'SYSTEM'}</strong>
                    </td>
                    <td>
                      <span className="mono tag">{a.action}</span>
                    </td>
                    <td className="mono">{a.criterion_id || 'ALL'}</td>
                    <td style={{ fontSize: '0.8125rem' }}>{a.note || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
