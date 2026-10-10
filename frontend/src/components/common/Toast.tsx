import React, { createContext, useContext, useState, useCallback, useMemo } from 'react'

export interface ToastMessage {
  id: string
  message: string
  type: 'info' | 'success' | 'error'
}

interface ToastContextType {
  showToast: (message: string, type?: 'info' | 'success' | 'error') => void
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (message: string, type: 'info' | 'success' | 'error' = 'info') => {
      const id = Math.random().toString(36).substring(2, 9)
      setToasts((prev) => [...prev, { id, message, type }])
      setTimeout(() => {
        removeToast(id)
      }, 4500)
    },
    [removeToast]
  )

  const value = useMemo(() => ({ showToast, removeToast }), [showToast, removeToast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-container" aria-live="polite" aria-atomic="true">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast ${t.type === 'error' ? 'toast-error' : t.type === 'success' ? 'toast-success' : ''}`}
            role="status"
          >
            <span>{t.message}</span>
            <button
              onClick={() => removeToast(t.id)}
              aria-label="Dismiss notification"
              style={{
                background: 'none',
                border: 'none',
                color: 'white',
                cursor: 'pointer',
                opacity: 0.8,
                padding: '2px',
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextType {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
