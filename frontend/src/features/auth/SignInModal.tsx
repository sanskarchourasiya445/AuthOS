import React, { useState } from 'react'
import { Modal } from '../../components/common/Modal'
import { Button } from '../../components/common/Button'
import { useAuth } from './AuthContext'
import { SYNTHETIC_PERSONAS } from './personas'

interface SignInModalProps {
  isOpen: boolean
  onClose: () => void
}

export const SignInModal: React.FC<SignInModalProps> = ({ isOpen, onClose }) => {
  const { loginAsPersona, loginWithCredentials, isLoading, error, clearError } = useAuth()
  const [showManualForm, setShowManualForm] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const handleSelectPersona = async (personaKey: string) => {
    setLocalError(null)
    clearError()
    try {
      await loginAsPersona(personaKey)
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed'
      setLocalError(msg)
    }
  }

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim()) {
      setLocalError('Username is required')
      return
    }
    setLocalError(null)
    clearError()
    try {
      await loginWithCredentials({ username: username.trim(), password })
      onClose()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed'
      setLocalError(msg)
    }
  }

  const displayError = localError || error

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Clinical Actor Authentication" maxWidth="560px">
      <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
        Select a synthetic clinical reviewer or auditor persona to acquire a signed JWT access token.
      </p>

      {displayError && (
        <div
          role="alert"
          style={{
            background: 'var(--danger-bg)',
            color: 'var(--danger)',
            padding: '10px 14px',
            borderRadius: '6px',
            fontSize: '0.8125rem',
            marginBottom: '16px',
            border: '1px solid #fca5a5',
          }}
        >
          <strong>Authentication Error:</strong> {displayError}
        </div>
      )}

      {!showManualForm ? (
        <>
          <div className="persona-grid" role="group" aria-label="Synthetic Reviewer Personas">
            {Object.values(SYNTHETIC_PERSONAS).map((persona) => {
              const roleClass =
                persona.role === 'clinician_reviewer'
                  ? 'role-reviewer'
                  : persona.role === 'auditor'
                  ? 'role-auditor'
                  : 'role-admin'

              return (
                <div
                  key={persona.key}
                  className="persona-btn"
                  onClick={() => handleSelectPersona(persona.key)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleSelectPersona(persona.key)
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`Sign in as ${persona.name}, ${persona.scope}`}
                >
                  <div>
                    <strong style={{ fontSize: '0.9375rem', display: 'block' }}>{persona.name}</strong>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {persona.scope}
                    </div>
                  </div>
                  <span className={`role-badge ${roleClass}`}>{persona.roleLabel}</span>
                </div>
              )
            })}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '12px' }}>
            <button
              type="button"
              onClick={() => setShowManualForm(true)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--primary)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              Enter credentials manually
            </button>
            <Button variant="secondary" onClick={onClose} disabled={isLoading}>
              Cancel
            </Button>
          </div>
        </>
      ) : (
        <form onSubmit={handleManualSubmit}>
          <div style={{ marginBottom: '12px' }}>
            <label
              htmlFor="authUsername"
              style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
            >
              Username
            </label>
            <input
              id="authUsername"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. dr_chen"
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.875rem',
              }}
              required
            />
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label
              htmlFor="authPassword"
              style={{ display: 'block', fontSize: '0.8125rem', fontWeight: 600, marginBottom: '4px' }}
            >
              Password
            </label>
            <input
              id="authPassword"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password..."
              style={{
                width: '100%',
                padding: '8px 12px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                fontSize: '0.875rem',
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              type="button"
              onClick={() => setShowManualForm(false)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--primary)',
                fontSize: '0.75rem',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              ← Back to Persona Selection
            </button>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" isLoading={isLoading}>
                Sign In
              </Button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  )
}
