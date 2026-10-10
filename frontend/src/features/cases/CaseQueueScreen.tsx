import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api/endpoints'
import type { Case, CaseStatus } from '../../types/cases'
import { Badge } from '../../components/common/Badge'
import { Button } from '../../components/common/Button'
import { LoadingState } from '../../components/common/LoadingState'
import { useAuth } from '../auth/AuthContext'
import { useToast } from '../../components/common/Toast'

export const CaseQueueScreen: React.FC = () => {
  const navigate = useNavigate()
  const { user, token } = useAuth()
  const { showToast } = useToast()

  const [cases, setCases] = useState<Case[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState<string>('')

  const fetchCases = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await api.cases.list()
      setCases(data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load case queue'
      setError(msg)
      showToast(msg, 'error')
    } finally {
      setIsLoading(false)
    }
  }, [showToast])

  useEffect(() => {
    fetchCases()
  }, [token, fetchCases])

  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      const matchStatus = statusFilter === 'ALL' || c.status === statusFilter
      const query = searchQuery.toLowerCase().trim()
      const matchSearch =
        !query ||
        c.case_id.toLowerCase().includes(query) ||
        c.patient_id.toLowerCase().includes(query) ||
        (c.service || '').toLowerCase().includes(query)
      return matchStatus && matchSearch
    })
  }, [cases, statusFilter, searchQuery])

  return (
    <section id="screenQueue" className="screen-view active">
      <div className="card" style={{ padding: '20px' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '16px',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <label htmlFor="queueStatusFilter" style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
              Filter Status:
            </label>
            <select
              id="queueStatusFilter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.8125rem',
                background: 'white',
              }}
            >
              <option value="ALL">All Statuses</option>
              <option value="DRAFT">DRAFT</option>
              <option value="RESULTS_READY">RESULTS_READY</option>
              <option value="IN_HUMAN_REVIEW">IN_HUMAN_REVIEW</option>
              <option value="FINALIZED">FINALIZED</option>
              <option value="REJECTED">REJECTED</option>
            </select>

            <input
              type="text"
              id="queueSearch"
              placeholder="Search case, patient, or service..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '240px',
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.8125rem',
              }}
            />
          </div>

          <Button variant="secondary" size="sm" onClick={fetchCases} disabled={isLoading}>
            🔄 Refresh Cases
          </Button>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              background: 'var(--danger-bg)',
              color: 'var(--danger)',
              padding: '12px 16px',
              borderRadius: '6px',
              marginBottom: '16px',
              fontSize: '0.875rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>Error loading case queue: {error}</span>
            <Button variant="danger" size="sm" onClick={fetchCases}>
              Retry
            </Button>
          </div>
        )}

        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" aria-label="Prior Authorization Cases Queue">
            <thead>
              <tr>
                <th scope="col">Case ID</th>
                <th scope="col">Patient ID</th>
                <th scope="col">Requested Service</th>
                <th scope="col">Payer Policy</th>
                <th scope="col">Workflow Status</th>
                <th scope="col">Scenario / Notes</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody id="caseQueueBody">
              {isLoading ? (
                <tr>
                  <td colSpan={7}>
                    <LoadingState message="Fetching active cases from server..." />
                  </td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    style={{
                      textAlign: 'center',
                      color: 'var(--text-muted)',
                      padding: '32px',
                    }}
                  >
                    No prior-authorization cases found matching the criteria.
                    {user?.cases && user.cases.length > 0 && user.role !== 'admin' && (
                      <div style={{ fontSize: '0.75rem', marginTop: '6px' }}>
                        (Signed-in user authorized cases: {user.cases.join(', ')})
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => (
                  <tr key={c.case_id}>
                    <td className="mono" style={{ fontWeight: 700 }}>
                      {c.case_id}
                    </td>
                    <td className="mono">{c.patient_id}</td>
                    <td>{c.service}</td>
                    <td className="mono">{c.policy_id}</td>
                    <td>
                      <Badge status={c.status as CaseStatus} />
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                      {c.scenario || '-'}
                    </td>
                    <td>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => navigate(`/cases/${c.case_id}`)}
                      >
                        Open Workspace
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
