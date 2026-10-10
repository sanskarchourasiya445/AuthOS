import React from 'react'

interface LoadingStateProps {
  message?: string
}

export const LoadingState: React.FC<LoadingStateProps> = ({ message = 'Loading records...' }) => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 24px',
        color: 'var(--text-muted)',
        gap: '12px',
      }}
      role="status"
    >
      <div
        style={{
          width: '24px',
          height: '24px',
          border: '3px solid var(--border-dark)',
          borderTopColor: 'var(--primary)',
          borderRadius: '50%',
          animation: 'spin 0.8s linear infinite',
        }}
      />
      <span style={{ fontSize: '0.875rem' }}>{message}</span>
    </div>
  )
}
