import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { AuthProvider, useAuth } from '../features/auth/AuthContext'
import { ToastProvider } from '../components/common/Toast'
import { AppShell } from '../components/layout/AppShell'
import { CaseQueueScreen } from '../features/cases/CaseQueueScreen'
import { CaseWorkspaceScreen } from '../features/workspace/CaseWorkspaceScreen'
import { LoadingState } from '../components/common/LoadingState'

// Wrapper to pass activeCaseId to AppShell
const WorkspaceRoute: React.FC = () => {
  const { caseId } = useParams<{ caseId: string }>()
  return (
    <AppShell activeCaseId={caseId}>
      <CaseWorkspaceScreen />
    </AppShell>
  )
}

const QueueRoute: React.FC = () => {
  return (
    <AppShell activeCaseId={null}>
      <CaseQueueScreen />
    </AppShell>
  )
}

const InitialAuthBootstrap: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, loginAsPersona } = useAuth()
  const [bootstrapping, setBootstrapping] = useState(!isAuthenticated)
  const bootstrappedRef = React.useRef(false)

  useEffect(() => {
    if (!bootstrappedRef.current) {
      bootstrappedRef.current = true
      if (!isAuthenticated) {
        loginAsPersona('dr_chen')
          .catch(() => {})
          .finally(() => setBootstrapping(false))
        return
      }
    }
    setBootstrapping(false)
  }, [isAuthenticated, loginAsPersona])

  if (bootstrapping) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <LoadingState message="Initializing clinical session..." />
      </div>
    )
  }

  return <>{children}</>
}

export const App: React.FC = () => {
  const basename =
    typeof window !== 'undefined' && window.location.pathname.startsWith('/app') ? '/app' : '/'

  return (
    <BrowserRouter basename={basename}>
      <AuthProvider>
        <ToastProvider>
          <InitialAuthBootstrap>
            <Routes>
              <Route path="/" element={<Navigate to="/cases" replace />} />
              <Route path="/cases" element={<QueueRoute />} />
              <Route path="/cases/:caseId" element={<WorkspaceRoute />} />
              <Route path="*" element={<Navigate to="/cases" replace />} />
            </Routes>
          </InitialAuthBootstrap>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
