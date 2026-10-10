import React, { useState } from 'react'
import type { PolicyCriterionResult } from '../../types/criteria'
import type { ClaimAnalysisResponse } from '../../types/workflow'
import { Badge } from '../../components/common/Badge'
import { Button } from '../../components/common/Button'
import { api } from '../../lib/api/endpoints'
import { useToast } from '../../components/common/Toast'

interface AgentComparisonScreenProps {
  caseId: string
  criteria: PolicyCriterionResult[]
}

export const AgentComparisonScreen: React.FC<AgentComparisonScreenProps> = ({ caseId, criteria }) => {
  const { showToast } = useToast()
  const [analysis, setAnalysis] = useState<ClaimAnalysisResponse | null>(null)
  const [isRunning, setIsRunning] = useState<boolean>(false)
  const [runningMode, setRunningMode] = useState<string | null>(null)

  const handleRunAnalysis = async (mode: 'agent' | 'deterministic') => {
    setIsRunning(true)
    setRunningMode(mode)
    const modeLabel = mode === 'agent' ? 'multi-agent workflow' : 'single-pass analyzer'
    showToast(`Running ${modeLabel}...`, 'info')

    try {
      const data = await api.cases.claimAnalysis(caseId, mode)
      setAnalysis(data)
      showToast(`Advisory analysis completed (${modeLabel}).`, 'success')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Claim analysis failed'
      showToast(msg, 'error')
    } finally {
      setIsRunning(false)
      setRunningMode(null)
    }
  }

  const authoritativeMap = React.useMemo(() => {
    const map: Record<string, PolicyCriterionResult> = {}
    criteria.forEach((c) => {
      map[c.criterion_id] = c
    })
    return map
  }, [criteria])

  return (
    <div id="wsAdvisoryView" className="ws-sub-view">
      <div
        className="disclaimer-banner"
        style={{
          background: '#fffbeb',
          borderColor: '#fde68a',
          borderLeftColor: '#d97706',
          color: '#92400e',
        }}
        role="note"
      >
        <div style={{ fontSize: '1.25rem' }} aria-hidden="true">
          ⚠️
        </div>
        <div>
          <strong>Advisory AI Analysis Disclaimer:</strong> AI proposals are non-authoritative clinical draft suggestions. They do NOT mutate authoritative database criterion records. All decisions require human reviewer validation.
        </div>
      </div>

      <div
        style={{
          marginBottom: '16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <span style={{ fontSize: '0.875rem', fontWeight: 600 }} id="advisoryProviderLabel">
          Provider:{' '}
          {analysis
            ? `${analysis.analyzer_provider} (Generated: ${analysis.generated_at})`
            : 'Not yet executed for this session'}
        </span>

        <div style={{ display: 'flex', gap: '8px' }}>
          <Button
            id="btnRunAgentWorkflow"
            variant="primary"
            size="sm"
            onClick={() => handleRunAnalysis('agent')}
            isLoading={isRunning && runningMode === 'agent'}
            disabled={isRunning}
          >
            🤖 Run Multi-Agent Workflow
          </Button>
          <Button
            id="btnRunSinglePass"
            variant="secondary"
            size="sm"
            onClick={() => handleRunAnalysis('deterministic')}
            isLoading={isRunning && runningMode === 'deterministic'}
            disabled={isRunning}
          >
            ⚡ Single-Pass Baseline
          </Button>
        </div>
      </div>

      <div id="comparisonContainer">
        {!analysis ? (
          <div
            style={{
              background: 'white',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              padding: '32px',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.875rem',
            }}
          >
            Click "Run Multi-Agent Workflow" or "Single-Pass Baseline" to execute bounded advisory analysis.
          </div>
        ) : (
          analysis.proposals.map((p) => {
            const authCrit = authoritativeMap[p.criterion_id]
            const authStatus = authCrit ? authCrit.status : 'NOT_EVALUATED'
            const isAgreement = authStatus === p.proposed_status

            return (
              <div
                key={p.criterion_id}
                className="card"
                style={{ marginBottom: '16px', padding: '16px' }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    fontSize: '0.9375rem',
                    marginBottom: '12px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <span className="mono">Criterion {p.criterion_id}</span>
                  <span
                    className={`badge ${isAgreement ? 'badge-MET' : 'badge-AMBIGUOUS'}`}
                    style={{ fontSize: '0.75rem' }}
                  >
                    {isAgreement ? 'Status Agreement' : 'Status Divergence'}
                  </span>
                </div>

                <div className="comparison-grid">
                  {/* Left Column: Authoritative Deterministic Ground Truth */}
                  <div className="comp-col">
                    <div className="comp-header">
                      <strong>Authoritative Verification</strong>
                      <Badge status={authStatus} />
                    </div>
                    <div style={{ fontSize: '0.8125rem', color: '#334155' }}>
                      <div>
                        <strong>Verified by Rules:</strong> {authCrit?.verified ? 'YES' : 'NO'}
                      </div>
                      <div style={{ marginTop: '6px' }}>
                        <strong>Assessment Reason:</strong>{' '}
                        {authCrit?.reason || 'No deterministic verification reason.'}
                      </div>
                    </div>
                  </div>

                  {/* Right Column: Advisory AI Suggestion */}
                  <div
                    className="comp-col"
                    style={{ background: '#faf5ff', borderColor: '#e9d5ff' }}
                  >
                    <div className="comp-header">
                      <strong>Advisory Proposal</strong>
                      <Badge status={p.proposed_status} />
                    </div>
                    <div style={{ fontSize: '0.8125rem', color: '#334155' }}>
                      <div>
                        <strong>Confidence:</strong> {(p.confidence * 100).toFixed(1)}%
                      </div>
                      <div style={{ marginTop: '6px' }}>
                        <strong>Uncertainty Rationale:</strong> {p.uncertainty_rationale}
                      </div>
                      {p.flags && p.flags.length > 0 && (
                        <div
                          style={{
                            marginTop: '8px',
                            display: 'flex',
                            gap: '4px',
                            flexWrap: 'wrap',
                          }}
                        >
                          {p.flags.map((flag, idx) => (
                            <span
                              key={idx}
                              className="tag"
                              style={{ background: '#f3e8ff', color: '#6b21a8' }}
                            >
                              {flag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
